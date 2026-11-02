"""Deterministic helpers: citation keys, deduplication, heuristic MATCH."""

from __future__ import annotations

import math
import re

from .models import Paper

_STOPWORDS = {
    "a", "an", "the", "of", "for", "and", "or", "to", "in", "on", "with",
    "using", "via", "based", "toward", "towards", "from", "by", "at", "as",
    "is", "are", "be", "we", "our", "this", "that", "it", "its", "into",
    "including", "include", "includes", "between", "among", "within",
    "study", "studies", "paper", "approach", "approaches", "method",
    "methods", "analysis", "research",
}


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2]


def content_tokens(text: str) -> set[str]:
    return {t for t in tokenize(text) if t not in _STOPWORDS}


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def make_key(paper: Paper, taken: set[str]) -> str:
    """Author-year citation key in Undermind's style: Zha25, Cai26, Cai26b."""
    surname = paper.first_author_surname()
    base_name = surname[:12]
    year2 = f"{paper.year % 100:02d}" if paper.year else "nd"
    base = f"{base_name}{year2}"
    if base not in taken:
        taken.add(base)
        return base
    # Undermind style: first collision gets 'b', then 'c', ...
    for suffix_ord in range(ord("b"), ord("z") + 1):
        candidate = base + chr(suffix_ord)
        if candidate not in taken:
            taken.add(candidate)
            return candidate
    n = 2
    while f"{base}x{n}" in taken:
        n += 1
    candidate = f"{base}x{n}"
    taken.add(candidate)
    return candidate


def _merge_into(dst: Paper, src: Paper) -> None:
    for s in src.sources:
        if s not in dst.sources:
            dst.sources.append(s)
    if not dst.abstract and src.abstract:
        dst.abstract = src.abstract
    if not dst.open_access_pdf and src.open_access_pdf:
        dst.open_access_pdf = src.open_access_pdf
    if not dst.doi and src.doi:
        dst.doi = src.doi
    if not dst.arxiv_id and src.arxiv_id:
        dst.arxiv_id = src.arxiv_id
    if not dst.tldr and src.tldr:
        dst.tldr = src.tldr
    if not dst.venue and src.venue:
        dst.venue = src.venue
    if not dst.year and src.year:
        dst.year = src.year
    if src.citation_count > dst.citation_count:
        dst.citation_count = src.citation_count
    if not dst.authors and src.authors:
        dst.authors = src.authors
    if not dst.url and src.url:
        dst.url = src.url


def dedupe(papers: list[Paper]) -> list[Paper]:
    """Merge duplicates by DOI, else canonical id, else normalized title."""
    by_doi: dict[str, Paper] = {}
    by_id: dict[str, Paper] = {}
    by_title: dict[str, Paper] = {}
    out: list[Paper] = []
    for p in papers:
        found: Paper | None = None
        if p.doi and p.doi.lower() in by_doi:
            found = by_doi[p.doi.lower()]
        elif p.paper_id in by_id:
            found = by_id[p.paper_id]
        elif normalize_title(p.title) in by_title:
            found = by_title[normalize_title(p.title)]
        if found is None:
            out.append(p)
            found = p
        else:
            _merge_into(found, p)
        if found.doi:
            by_doi[found.doi.lower()] = found
        by_id[found.paper_id] = found
        by_title[normalize_title(found.title)] = found
    return out


def lexical_relevance(query_text: str, paper: Paper) -> float:
    """0..1 overlap of query content tokens with title (boosted) and abstract."""
    q = content_tokens(query_text)
    if not q:
        return 0.0
    title_tokens = content_tokens(paper.title)
    abstract_tokens = content_tokens(paper.abstract or "")
    title_hits = len(q & title_tokens)
    abstract_hits = len(q & abstract_tokens)
    coverage = (abstract_hits + 1.6 * title_hits) / (len(q) * 1.6)
    return max(0.0, min(1.0, coverage))


def heuristic_match(criteria: list[str], paper: Paper, current_year: int = 2026) -> tuple[float, str]:
    """Offline MATCH score (0..100) + a short human-readable reason.

    Combines lexical relevance to the search criteria (dominant), citation
    velocity (mild), and recency (mild). Deterministic and testable.
    """
    joined = " ".join(criteria)
    rel = max(lexical_relevance(c, paper) for c in criteria) if criteria else lexical_relevance(joined, paper)
    avg_rel = (
        sum(lexical_relevance(c, paper) for c in criteria) / len(criteria) if criteria else rel
    )
    relevance = 0.75 * rel + 0.25 * avg_rel

    velocity = paper.citations_per_year(current_year)
    citation_component = min(1.0, math.log10(1 + velocity) / 2.0)  # 100/yr -> 1.0

    if paper.year:
        age = current_year - paper.year
        recency_component = 1.0 if age <= 2 else max(0.0, 1.0 - (age - 2) / 12.0)
    else:
        recency_component = 0.3

    score = 100.0 * (0.78 * relevance + 0.12 * citation_component + 0.10 * recency_component)
    score = round(max(0.0, min(100.0, score)), 1)

    matched = sorted(content_tokens(joined) & content_tokens(paper.title + " " + (paper.abstract or "")))
    reason_bits = []
    if matched:
        reason_bits.append("matched terms: " + ", ".join(matched[:6]))
    if paper.citation_count:
        reason_bits.append(f"{paper.citation_count} citations")
    if paper.year:
        reason_bits.append(f"year {paper.year}")
    return score, "; ".join(reason_bits) or "weak lexical overlap"
