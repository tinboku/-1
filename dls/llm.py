"""Pluggable LLM backends.

Two implementations of the same interface:

- ``OpenAIChatLLM``: any OpenAI-compatible chat endpoint (set LLM_API_KEY,
  LLM_BASE_URL, LLM_MODEL). Used for brainstorming, criteria writing,
  MATCH judging, report writing, table extraction and follow-up Q&A.
- ``HeuristicLLM``: deterministic offline fallback (lexical scoring,
  extractive report assembly). Lets the whole pipeline run — and be
  tested — with no API key at all.

Every method degrades to the heuristic behavior on API errors, so a flaky
endpoint never kills a search run.
"""

from __future__ import annotations

import json
import re

import requests

from .config import Config
from .models import Paper
from .scoring import content_tokens, heuristic_match


# ---------------------------------------------------------------------------
# Heuristic backend
# ---------------------------------------------------------------------------

class HeuristicLLM:
    name = "heuristic"

    # -- brainstorming ----------------------------------------------------
    def brainstorm(self, question: str) -> list[str]:
        return [
            "Scope: should the search focus narrowly on the core approach named in "
            "your question, or also include earlier and adjacent approaches as "
            "comparison points?",
            "Purpose: is the goal mainly discovery and cataloguing of what exists, "
            "or should evaluation of quality and usefulness be a priority as well?",
        ]

    # -- criteria -----------------------------------------------------------
    def make_criteria(self, question: str, answers: dict[str, str] | None = None) -> list[str]:
        criteria = [question.strip()]
        focus_terms: list[str] = []
        if answers:
            joined_answers = " ".join(answers.values())
            focus_terms = [t for t in content_tokens(joined_answers) if len(t) > 4][:6]
        if focus_terms:
            criteria.append(question.strip() + " — focus: " + ", ".join(focus_terms))
        # A third, term-based criterion built from the question's content words.
        terms = [t for t in content_tokens(question) if len(t) > 4][:8]
        if terms:
            criteria.append("Papers about: " + " ".join(terms))
        return criteria

    # -- scoring ------------------------------------------------------------
    def score_matches(self, criteria: list[str], papers: list[Paper]) -> list[tuple[float, str]]:
        return [heuristic_match(criteria, p) for p in papers]

    # -- reflection (adapting stage) -----------------------------------------
    def reflect(self, criteria: list[str], top_papers: list[Paper], round_no: int) -> dict:
        seen = content_tokens(" ".join(criteria))
        fresh: list[str] = []
        for p in top_papers:
            for t in content_tokens(p.title):
                if t not in seen and len(t) > 4 and t not in fresh:
                    fresh.append(t)
        new_queries = []
        if fresh:
            new_queries.append(" ".join(fresh[:6]))
        return {"new_queries": new_queries, "stop": round_no >= 2}

    # -- report ---------------------------------------------------------------
    _FAMILY_KEYWORDS = [
        ("LLM / generative methods", ["llm", "language model", "generative", "gpt", "prompt"]),
        ("Profiling-driven methods", ["profiling", "profile", "statistics", "schema"]),
        ("Retrieval & embedding methods", ["retrieval", "embedding", "semantic search", "indexing"]),
        ("Template / rule-based methods", ["template", "rule", "ontology", "knowledge graph"]),
        ("Evaluation & benchmarking", ["evaluation", "benchmark", "quality", "assessment"]),
    ]

    def _family(self, paper: Paper) -> str:
        text = (paper.title + " " + (paper.abstract or "")).lower()
        best, best_hits = "Other approaches", 0
        for name, kws in self._FAMILY_KEYWORDS:
            hits = sum(1 for k in kws if k in text)
            if hits > best_hits:
                best, best_hits = name, hits
        return best

    @staticmethod
    def _first_sentence(text: str | None) -> str:
        if not text:
            return ""
        parts = re.split(r"(?<=[.!?])\s+", text.strip())
        return parts[0] if parts else ""

    def write_report(self, question: str, criteria: list[str], papers: list[Paper], focus: str | None = None) -> str:
        papers = sorted(papers, key=lambda p: (p.match or 0), reverse=True)
        lines: list[str] = []
        lines.append(f"# Literature search report")
        lines.append("")
        lines.append(f"**Research question.** {question}")
        lines.append("")
        lines.append("**Search criteria.**")
        for c in criteria:
            lines.append(f"- {c}")
        lines.append("")
        lines.append("## Executive summary")
        lines.append("")
        lines.append(
            f"This search retained {len(papers)} papers after relevance scoring and "
            f"citation snowballing. The strongest matches are "
            + ", ".join(f"[{p.key}]" for p in papers[:5])
            + ". The sections below group the retained papers by method family and "
            "summarize what each contributes, using the papers' own abstracts."
        )
        lines.append("")
        families: dict[str, list[Paper]] = {}
        for p in papers:
            families.setdefault(self._family(p), []).append(p)
        lines.append("## Method families")
        for fam, members in sorted(families.items(), key=lambda kv: -len(kv[1])):
            lines.append("")
            lines.append(f"### {fam}")
            lines.append("")
            for p in members[:6]:
                sentence = self._first_sentence(p.abstract) or (p.tldr or "")
                lines.append(f"- [{p.key}] {p.title} ({p.year or 'n.d.'}). {sentence}")
        lines.append("")
        lines.append("## Evaluation and limitations")
        lines.append("")
        lines.append(
            "Scores (MATCH) combine lexical relevance to the criteria with citation "
            "velocity and recency in offline mode; treat the ordering as a screening "
            "aid, not a quality judgement. Papers without abstracts could only be "
            "scored on titles, and citation counts favour older work."
        )
        lines.append("")
        lines.append("## References")
        lines.append("")
        lines.append("| KEY | Year | Cit/yr | Title |")
        lines.append("|---|---|---|---|")
        for p in papers:
            cpy = p.citations_per_year()
            lines.append(f"| {p.key} | {p.year or ''} | {cpy:.1f} | {p.title} |")
        lines.append("")
        return "\n".join(lines)

    # -- table extraction ------------------------------------------------------
    def extract_row(self, paper: Paper, columns: list[str]) -> dict[str, str]:
        row: dict[str, str] = {}
        abstract = paper.abstract or ""
        for col in columns:
            c = col.lower()
            if "paper" in c or "title" in c:
                row[col] = f"[{paper.key}] {paper.title}"
            elif "year" in c:
                row[col] = str(paper.year or "")
            elif "author" in c:
                row[col] = ", ".join(paper.authors[:3])
            elif "venue" in c:
                row[col] = paper.venue or ""
            elif "citation" in c:
                row[col] = str(paper.citation_count)
            elif "method" in c or "approach" in c:
                row[col] = self._family(paper)
            else:
                # Find the abstract sentence mentioning the column's key term.
                term = c.split()[0] if c.split() else c
                sentence = next(
                    (s for s in re.split(r"(?<=[.!?])\s+", abstract) if term in s.lower()),
                    "",
                )
                row[col] = sentence[:200] if sentence else "—"
        return row

    # -- follow-up Q&A -----------------------------------------------------------
    def answer(self, question: str, papers: list[Paper]) -> str:
        ranked = sorted(papers, key=lambda p: (p.match or 0), reverse=True)[:5]
        bits = [f"Based on the {len(papers)} papers in this search, the most relevant sources are:"]
        for p in ranked:
            sentence = self._first_sentence(p.abstract) or (p.tldr or "")
            bits.append(f"- [{p.key}] {p.title}: {sentence}")
        bits.append("(Offline mode: connect an LLM via LLM_API_KEY for a synthesized answer.)")
        return "\n".join(bits)


# ---------------------------------------------------------------------------
# OpenAI-compatible backend
# ---------------------------------------------------------------------------

class OpenAIChatLLM(HeuristicLLM):
    name = "openai-compatible"

    def __init__(self, config: Config):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {config.llm_api_key}",
                "Content-Type": "application/json",
            }
        )

    def _chat(self, system: str, user: str, json_mode: bool = False) -> str:
        body: dict = {
            "model": self.config.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        resp = self.session.post(
            f"{self.config.llm_base_url.rstrip('/')}/chat/completions",
            json=body,
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    @staticmethod
    def _parse_json(text: str) -> dict | list | None:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\n?|```$", "", text, flags=re.M).strip()
        try:
            return json.loads(text)
        except Exception:
            m = re.search(r"(\{.*\}|\[.*\])", text, flags=re.S)
            if m:
                try:
                    return json.loads(m.group(1))
                except Exception:
                    return None
            return None

    def brainstorm(self, question: str) -> list[str]:
        try:
            out = self._chat(
                "You are a research librarian. Before searching, ask exactly two short "
                "clarifying questions that pin down scope and purpose. Return JSON: "
                '{"questions": ["...", "..."]}',
                f"Research question: {question}",
                json_mode=True,
            )
            data = self._parse_json(out)
            if isinstance(data, dict) and data.get("questions"):
                return [str(q) for q in data["questions"]][:3]
        except Exception:
            pass
        return super().brainstorm(question)

    def make_criteria(self, question: str, answers: dict[str, str] | None = None) -> list[str]:
        try:
            answers_txt = "\n".join(f"- {k}: {v}" for k, v in (answers or {}).items()) or "(no answers)"
            out = self._chat(
                "You convert a research question into 2-4 natural-language search "
                "criteria statements that a literature search engine will execute. "
                'Return JSON: {"criteria": ["...", "..."]}',
                f"Question: {question}\nClarifying answers:\n{answers_txt}",
                json_mode=True,
            )
            data = self._parse_json(out)
            if isinstance(data, dict) and data.get("criteria"):
                return [str(c) for c in data["criteria"]][:4]
        except Exception:
            pass
        return super().make_criteria(question, answers)

    def score_matches(self, criteria: list[str], papers: list[Paper]) -> list[tuple[float, str]]:
        results: list[tuple[float, str]] = []
        batch_size = 10
        for i in range(0, len(papers), batch_size):
            batch = papers[i : i + batch_size]
            try:
                listing = "\n".join(
                    f"{j}. TITLE: {p.title}\n   ABSTRACT: {(p.abstract or '')[:600]}"
                    for j, p in enumerate(batch)
                )
                out = self._chat(
                    "You judge how well each paper matches the search criteria. "
                    "Score 0-100 (100 = directly on-topic). Return JSON: "
                    '{"scores": [{"index": 0, "score": 87, "reason": "short reason"}]}',
                    f"Criteria:\n- " + "\n- ".join(criteria) + f"\n\nPapers:\n{listing}",
                    json_mode=True,
                )
                data = self._parse_json(out)
                by_index: dict[int, tuple[float, str]] = {}
                if isinstance(data, dict):
                    for s in data.get("scores") or []:
                        by_index[int(s["index"])] = (float(s["score"]), str(s.get("reason", "")))
                for j, p in enumerate(batch):
                    results.append(by_index.get(j) or heuristic_match(criteria, p))
            except Exception:
                results.extend(heuristic_match(criteria, p) for p in batch)
        return results

    def reflect(self, criteria: list[str], top_papers: list[Paper], round_no: int) -> dict:
        try:
            titles = "\n".join(f"- {p.title}" for p in top_papers[:10])
            out = self._chat(
                    "You are reflecting on a literature search in progress. Given the "
                    "criteria and the best papers so far, propose up to 2 new search "
                    "queries that would find relevant papers the criteria miss, and say "
                    "whether the search looks saturated. Return JSON: "
                    '{"new_queries": ["..."], "stop": false}',
                "Criteria:\n- " + "\n- ".join(criteria) + f"\n\nBest papers so far:\n{titles}",
                json_mode=True,
            )
            data = self._parse_json(out)
            if isinstance(data, dict):
                return {
                    "new_queries": [str(q) for q in data.get("new_queries") or []][:2],
                    "stop": bool(data.get("stop")),
                }
        except Exception:
            pass
        return super().reflect(criteria, top_papers, round_no)

    def write_report(self, question: str, criteria: list[str], papers: list[Paper], focus: str | None = None) -> str:
        try:
            listing = "\n".join(
                f"[{p.key}] {p.title} ({p.year or 'n.d.'}) — {(p.abstract or '')[:800]}"
                for p in papers
            )
            focus_txt = f"\nReport focus requested by the user: {focus}" if focus else ""
            return self._chat(
                "You write structured literature-search reports in Markdown. Use ONLY "
                "the papers provided, cite them inline with their [KEY] tokens, group "
                "methods into families, include sections: Executive summary; What "
                "counts as in-scope; Inputs and evidence used; Output types and method "
                "families; How quality is evaluated; Reliability and limits; Practical "
                "synthesis; Bottom line. End with a references table (KEY | Year | "
                "Cit/yr | Title).",
                f"Research question: {question}{focus_txt}\n\nPapers:\n{listing}",
            )
        except Exception:
            return super().write_report(question, criteria, papers, focus)

    def extract_row(self, paper: Paper, columns: list[str]) -> dict[str, str]:
        try:
            out = self._chat(
                "Extract values for the requested columns from the paper's title and "
                "abstract. If a value is not stated, use '—'. Return JSON with exactly "
                "the requested column names as keys.",
                f"Columns: {columns}\nTitle: {paper.title}\nAbstract: {(paper.abstract or '')[:2000]}",
                json_mode=True,
            )
            data = self._parse_json(out)
            if isinstance(data, dict):
                return {c: str(data.get(c, "—")) for c in columns}
        except Exception:
            pass
        return super().extract_row(paper, columns)

    def answer(self, question: str, papers: list[Paper]) -> str:
        try:
            listing = "\n".join(
                f"[{p.key}] {p.title} ({p.year or 'n.d.'}) — {(p.abstract or '')[:700]}"
                for p in sorted(papers, key=lambda x: (x.match or 0), reverse=True)[:15]
            )
            return self._chat(
                "Answer the user's follow-up question using ONLY the papers provided. "
                "Cite papers inline with their [KEY] tokens. If the papers do not "
                "cover the question, say so.",
                f"Question: {question}\n\nPapers:\n{listing}",
            )
        except Exception:
            return super().answer(question, papers)


def get_llm(config: Config) -> HeuristicLLM:
    if config.llm_api_key:
        return OpenAIChatLLM(config)
    return HeuristicLLM()
