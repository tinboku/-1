"""Core data types shared across clients, the engine and the store."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Paper:
    paper_id: str  # canonical id: S2 id, "W..." OpenAlex id, or "doi:..."
    title: str
    abstract: str | None = None
    year: int | None = None
    authors: list[str] = field(default_factory=list)
    venue: str | None = None
    citation_count: int = 0
    reference_count: int = 0
    doi: str | None = None
    arxiv_id: str | None = None
    open_access_pdf: str | None = None
    url: str | None = None
    tldr: str | None = None
    source: str = "semantic_scholar"
    sources: list[str] = field(default_factory=list)  # every channel that found it

    # Filled in by scoring / storage layers
    key: str | None = None        # citation key, e.g. "Zha25"
    match: float | None = None    # 0..100 relevance to a search's criteria
    match_reason: str | None = None
    found_via: str | None = None  # provenance: "search", "citations of [Key]", ...

    def __post_init__(self) -> None:
        if self.source and self.source not in self.sources:
            self.sources.append(self.source)

    @property
    def has_full_text(self) -> bool:
        return bool(self.open_access_pdf)

    def citations_per_year(self, current_year: int = 2026) -> float:
        if not self.year:
            return float(self.citation_count)
        age = max(1, current_year - self.year + 1)
        return self.citation_count / age

    def first_author_surname(self) -> str:
        if not self.authors:
            return "Anon"
        name = self.authors[0].strip()
        if not name:
            return "Anon"
        # "First Last" -> "Last"; keep only letters for a compact key.
        last = name.split()[-1]
        cleaned = "".join(ch for ch in last if ch.isalpha())
        return cleaned or "Anon"


@dataclass
class SearchOutcome:
    search_id: int
    question: str
    criteria: list[str]
    included: list[Paper]
    excluded_count: int
    with_full_text: int
    rounds: int
    converged: bool
    coverage: dict | None  # discovery-curve estimate, see engine.estimate_coverage
    warnings: list[str] = field(default_factory=list)
    degraded: bool = False

    @property
    def found(self) -> int:
        return len(self.included)
