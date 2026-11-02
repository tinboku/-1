"""The deep-search engine: orchestrates retrieval, scoring, snowballing.

Stage names intentionally mirror the reference product's progress UI:
Interpreting → Searching → Identifying → Reflecting → Adapting → Done.
A `progress` callback receives (stage, detail) pairs so CLI, Web UI and
tests can all observe the run.
"""

from __future__ import annotations

from typing import Callable

from .clients.openalex import OpenAlexClient
from .clients.semantic_scholar import RateLimited, SemanticScholarClient
from .llm import HeuristicLLM
from .models import Paper, SearchOutcome
from .scoring import dedupe
from .store import Store

ProgressFn = Callable[[str, str], None]


def _noop(stage: str, detail: str) -> None:
    pass


class DeepSearchEngine:
    def __init__(
        self,
        s2: SemanticScholarClient,
        openalex: OpenAlexClient | None,
        llm: HeuristicLLM,
        store: Store,
        include_threshold: float = 55.0,
        crossref=None,
    ):
        self.s2 = s2
        self.openalex = openalex
        self.llm = llm
        self.store = store
        self.include_threshold = include_threshold
        self.crossref = crossref

    # ------------------------------------------------------------------
    def brainstorm(self, question: str) -> list[str]:
        return self.llm.brainstorm(question)

    def build_criteria(self, question: str, answers: dict[str, str] | None = None) -> list[str]:
        return self.llm.make_criteria(question, answers)

    # ------------------------------------------------------------------
    def _score(self, criteria: list[str], papers: list[Paper]) -> list[Paper]:
        scores = self.llm.score_matches(criteria, papers)
        for paper, (score, reason) in zip(papers, scores):
            paper.match = score
            paper.match_reason = reason
        return papers

    def _snowball(self, seeds: list[Paper], limit_per_seed: int = 30) -> list[Paper]:
        out: list[Paper] = []
        for seed in seeds:
            for fetcher in (self.s2.citations, self.s2.references):
                try:
                    out.extend(fetcher(seed.paper_id, limit=limit_per_seed))
                except Exception:
                    continue
        return out

    # ------------------------------------------------------------------
    @staticmethod
    def estimate_coverage(
        s2_relevant: set[str], oa_relevant: set[str], found_relevant: int
    ) -> dict | None:
        """Lincoln–Petersen / Chapman capture–recapture over two channels.

        Treats Semantic Scholar and OpenAlex as two independent "captures"
        of the same relevant-paper population. Only meaningful when both
        channels returned relevant papers with some overlap.
        """
        n1, n2 = len(s2_relevant), len(oa_relevant)
        m = len(s2_relevant & oa_relevant)
        if n1 < 3 or n2 < 3 or m == 0:
            return None
        total_est = ((n1 + 1) * (n2 + 1) / (m + 1)) - 1
        if total_est <= 0:
            return None
        coverage = max(0.0, min(1.0, found_relevant / total_est))
        return {
            "method": "capture-recapture (Chapman) over Semantic Scholar vs OpenAlex relevant sets",
            "estimated_total_relevant": round(total_est, 1),
            "found_relevant": found_relevant,
            "estimated_coverage": round(coverage, 3),
            "channel_sizes": {"semantic_scholar": n1, "openalex": n2, "overlap": m},
        }

    # ------------------------------------------------------------------
    def run(
        self,
        question: str,
        criteria: list[str],
        answers: dict[str, str] | None = None,
        project: str = "default",
        per_query: int = 40,
        max_rounds: int = 2,
        seed_top: int = 8,
        progress: ProgressFn = _noop,
    ) -> SearchOutcome:
        warnings: list[str] = []
        search_id = self.store.create_search(project, question, criteria, answers or {})
        progress("Interpreting your search criteria", f"{len(criteria)} criteria")

        # -- Searching ---------------------------------------------------
        progress("Searching for the most promising papers", "Semantic Scholar + OpenAlex")
        pool: list[Paper] = []
        queries = list(dict.fromkeys([question, *criteria]))
        for q in queries:
            try:
                pool.extend(self.s2.search(q, limit=per_query))
            except RateLimited:
                warnings.append("Semantic Scholar rate-limited part of the initial search.")
                break
            except Exception as exc:  # network etc.
                warnings.append(f"Semantic Scholar search failed: {exc}")
                break
        try:
            if self.openalex is not None:
                pool.extend(self.openalex.search(question, per_page=25))
        except Exception:
            warnings.append("OpenAlex channel unavailable; running single-source.")
        if self.crossref is not None:
            try:
                pool.extend(self.crossref.search(question, rows=per_query))
            except Exception:
                warnings.append("Crossref channel unavailable.")

        pool = dedupe(pool)

        # -- Identifying ---------------------------------------------------
        progress("Identifying the best candidate papers", f"{len(pool)} candidates")
        scored = self._score(criteria, pool)
        included = [p for p in scored if (p.match or 0) >= self.include_threshold]
        seen_ids = {p.paper_id for p in scored}

        # -- Reflecting / Adapting (snowball rounds) -------------------------
        rounds_done = 0
        converged = False
        for round_no in range(1, max_rounds + 1):
            rounds_done = round_no
            progress("Reflecting on the results", f"round {round_no}")
            reflection = self.llm.reflect(criteria, sorted(included, key=lambda p: -(p.match or 0)), round_no)
            seeds = sorted(included, key=lambda p: -(p.match or 0))[:seed_top]
            progress("Adapting and searching again", f"snowballing from {len(seeds)} seeds")
            candidates = dedupe(self._snowball(seeds))
            # The reflection step may propose fresh queries; run them too.
            for new_q in reflection.get("new_queries") or []:
                try:
                    candidates = dedupe(candidates + self.s2.search(new_q, limit=20))
                except Exception:
                    continue
            candidates = [c for c in candidates if c.paper_id not in seen_ids]
            for c in candidates:
                seen_ids.add(c.paper_id)
            if not candidates:
                converged = True
                break
            new_scored = self._score(criteria, candidates)
            scored.extend(new_scored)
            new_included = [p for p in new_scored if (p.match or 0) >= self.include_threshold]
            included.extend(new_included)
            gain = len(new_included) / max(1, len(included))
            if reflection.get("stop") or gain < 0.03:
                converged = True
                break

        included.sort(key=lambda p: -(p.match or 0))

        # Persist papers and results; capture db ids for coverage sets.
        s2_rel: set[str] = set()
        oa_rel: set[str] = set()
        included_db_ids: set[int] = set()
        for p in scored:
            db_id = self.store.upsert_paper(p)
            p.db_id = db_id  # type: ignore[attr-defined]
            if (p.match or 0) >= self.include_threshold:
                if "semantic_scholar" in p.sources:
                    s2_rel.add(p.paper_id)
                if "openalex" in p.sources:
                    oa_rel.add(p.paper_id)
        for p in included:
            included_db_ids.add(getattr(p, "db_id"))

        coverage = self.estimate_coverage(s2_rel, oa_rel, len(included))
        counts = {
            "found": len(included),
            "with_full_text": sum(1 for p in included if p.has_full_text),
            "excluded": len(scored) - len(included),
            "candidates": len(scored),
        }
        self.store.save_results(search_id, scored, included_db_ids, counts, coverage)
        # save_results upserts again internally for any paper missing db_id; keep ids consistent.
        progress("Done", f"{counts['found']} papers · {counts['with_full_text']} with full text · {counts['excluded']} excluded")

        return SearchOutcome(
            search_id=search_id,
            question=question,
            criteria=criteria,
            included=included,
            excluded_count=counts["excluded"],
            with_full_text=counts["with_full_text"],
            rounds=rounds_done,
            converged=converged,
            coverage=coverage,
            warnings=warnings,
        )
