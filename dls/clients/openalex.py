"""OpenAlex API client (secondary source + forward snowballing).

Docs: https://docs.openalex.org
OpenAlex moved to keyed, credit-based access in 2026; without a key the
trial budget is tiny, so failures surface as RateLimited and the engine
falls back to single-source mode.
"""

from __future__ import annotations

import time

import requests

from ..models import Paper
from .semantic_scholar import RateLimited

BASE = "https://api.openalex.org"


class OpenAlexClient:
    name = "openalex"

    def __init__(self, api_key: str | None = None, email: str | None = None, max_retries: int = 3):
        self.api_key = api_key
        self.email = email
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def _params(self, extra: dict) -> dict:
        params = dict(extra)
        if self.api_key:
            params["api_key"] = self.api_key
        elif self.email:
            params["mailto"] = self.email
        return params

    def _get(self, path: str, params: dict) -> dict:
        delay = 1.5
        last_status = None
        for _ in range(self.max_retries):
            resp = self.session.get(f"{BASE}{path}", params=self._params(params), timeout=30)
            last_status = resp.status_code
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (409, 429, 500, 502, 503, 504):
                time.sleep(delay)
                delay *= 2
                continue
            resp.raise_for_status()
        raise RateLimited(f"OpenAlex unavailable after retries (status {last_status})")

    # -- mapping ---------------------------------------------------------
    @staticmethod
    def _decode_abstract(inverted: dict | None) -> str | None:
        if not inverted:
            return None
        positions: list[tuple[int, str]] = []
        for word, idxs in inverted.items():
            for i in idxs:
                positions.append((i, word))
        positions.sort()
        return " ".join(w for _, w in positions)

    @classmethod
    def _to_paper(cls, w: dict) -> Paper | None:
        if not w or not w.get("id") or not w.get("title"):
            return None
        authors = []
        for a in w.get("authorships") or []:
            name = (a.get("author") or {}).get("display_name")
            if name:
                authors.append(name)
        source = ((w.get("primary_location") or {}).get("source") or {}).get("display_name")
        oa = w.get("open_access") or {}
        best_oa = w.get("best_oa_location") or {}
        doi = w.get("doi")
        if doi and doi.startswith("https://doi.org/"):
            doi = doi[len("https://doi.org/"):]
        return Paper(
            paper_id=w["id"].rsplit("/", 1)[-1],  # e.g. W2741809807
            title=w["title"],
            abstract=cls._decode_abstract(w.get("abstract_inverted_index")),
            year=w.get("publication_year"),
            authors=authors,
            venue=source,
            citation_count=w.get("cited_by_count") or 0,
            reference_count=len(w.get("referenced_works") or []),
            doi=doi,
            open_access_pdf=best_oa.get("pdf_url") if oa.get("is_oa") else None,
            url=w.get("id"),
            source="openalex",
        )

    # -- API -------------------------------------------------------------
    def search(self, query: str, per_page: int = 25) -> list[Paper]:
        data = self._get("/works", {"search": query, "per_page": min(per_page, 100)})
        return [p for p in (self._to_paper(w) for w in data.get("results") or []) if p]

    def work_id_for_doi(self, doi: str) -> str | None:
        data = self._get(f"/works/doi:{doi}", {})
        wid = data.get("id")
        return wid.rsplit("/", 1)[-1] if wid else None

    def citing(self, openalex_id: str, per_page: int = 25) -> list[Paper]:
        """Papers that cite the given work (forward snowballing)."""
        data = self._get("/works", {"filter": f"cites:{openalex_id}", "per_page": min(per_page, 100)})
        return [p for p in (self._to_paper(w) for w in data.get("results") or []) if p]
