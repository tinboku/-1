"""Updates: re-check a saved search's criteria for newly published papers."""

from __future__ import annotations

import datetime

from .clients.semantic_scholar import SemanticScholarClient
from .llm import HeuristicLLM
from .scoring import dedupe
from .store import Store


def check_updates(
    store: Store,
    search_id: int,
    s2: SemanticScholarClient,
    llm: HeuristicLLM,
    threshold: float = 55.0,
) -> list[dict]:
    search = store.get_search(search_id)
    if not search:
        raise ValueError(f"search {search_id} not found")
    since_year = datetime.datetime.fromtimestamp(search["created_at"]).year
    known_ids = store.search_paper_ids(search_id)
    fresh = []
    pool = []
    for criterion in search["criteria"] or [search["question"]]:
        try:
            pool.extend(s2.search(criterion, limit=25, year=f"{since_year}-"))
        except Exception:
            continue
    for paper in dedupe(pool):
        if paper.year and paper.year < since_year:
            continue
        db_id = store.upsert_paper(paper)
        if db_id in known_ids:
            continue
        score, _reason = llm.score_matches(search["criteria"], [paper])[0]
        if score >= threshold:
            store.add_update(search_id, db_id)
            fresh.append({"paper_id": db_id, "key": paper.key, "title": paper.title, "year": paper.year, "match": score})
    return fresh
