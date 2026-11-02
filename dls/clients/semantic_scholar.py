"""Semantic Scholar Graph API client (primary data source).

Docs: https://api.semanticscholar.org/api-docs/graph
Anonymous calls share a heavily throttled pool; with an API key the
introductory limit is 1 req/s. This client backs off exponentially on
429/5xx and raises RateLimited when the budget of retries is exhausted,
so callers can degrade gracefully instead of crashing.
"""

from __future__ import annotations

import time

import requests

from ..models import Paper

BASE = "https://api.semanticscholar.org/graph/v1"
FIELDS = (
    "title,abstract,year,authors,venue,citationCount,referenceCount,"
    "externalIds,openAccessPdf,url,tldr"
)
# Edge endpoints (citations/references) reject `tldr` on nested papers.
FIELDS_EDGE = (
    "title,abstract,year,authors,venue,citationCount,referenceCount,"
    "externalIds,openAccessPdf,url"
)


class RateLimited(Exception):
    pass


class SemanticScholarClient:
    name = "semantic_scholar"

    def __init__(self, api_key: str | None = None, max_retries: int = 4):
        self.api_key = api_key
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        if api_key:
            self.session.headers.update({"x-api-key": api_key})

    # -- low level ------------------------------------------------------
    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{BASE}{path}"
        delay = 1.0 if self.api_key else 2.0
        last_status = None
        for attempt in range(self.max_retries):
            resp = self.session.get(url, params=params, timeout=30)
            last_status = resp.status_code
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (429, 500, 502, 503, 504):
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
                time.sleep(min(wait, 30.0))
                delay *= 2
                continue
            resp.raise_for_status()
        raise RateLimited(f"Semantic Scholar throttled after retries (status {last_status})")

    # -- mapping ---------------------------------------------------------
    @staticmethod
    def _to_paper(d: dict) -> Paper | None:
        if not d or not d.get("paperId") or not d.get("title"):
            return None
        ext = d.get("externalIds") or {}
        oa = d.get("openAccessPdf") or {}
        return Paper(
            paper_id=d["paperId"],
            title=d["title"],
            abstract=d.get("abstract"),
            year=d.get("year"),
            authors=[a.get("name", "") for a in (d.get("authors") or []) if a.get("name")],
            venue=d.get("venue"),
            citation_count=d.get("citationCount") or 0,
            reference_count=d.get("referenceCount") or 0,
            doi=ext.get("DOI"),
            arxiv_id=ext.get("ArXiv"),
            open_access_pdf=oa.get("url"),
            url=d.get("url"),
            tldr=(d.get("tldr") or {}).get("text"),
            source="semantic_scholar",
        )

    # -- API -------------------------------------------------------------
    def search(self, query: str, limit: int = 50, offset: int = 0, year: str | None = None) -> list[Paper]:
        params: dict = {"query": query, "limit": min(limit, 100), "offset": offset, "fields": FIELDS}
        if year:
            params["year"] = year
        data = self._get("/paper/search", params)
        return [p for p in (self._to_paper(d) for d in data.get("data") or []) if p]

    def paper(self, paper_id: str) -> Paper | None:
        data = self._get(f"/paper/{paper_id}", {"fields": FIELDS})
        return self._to_paper(data)

    def citations(self, paper_id: str, limit: int = 50) -> list[Paper]:
        data = self._get(
            f"/paper/{paper_id}/citations",
            {"limit": min(limit, 1000), "fields": f"citingPaper.{FIELDS_EDGE}".replace(",", ",citingPaper.")},
        )
        out = []
        for edge in data.get("data") or []:
            p = self._to_paper(edge.get("citingPaper") or {})
            if p:
                out.append(p)
        return out

    def references(self, paper_id: str, limit: int = 50) -> list[Paper]:
        data = self._get(
            f"/paper/{paper_id}/references",
            {"limit": min(limit, 1000), "fields": f"citedPaper.{FIELDS_EDGE}".replace(",", ",citedPaper.")},
        )
        out = []
        for edge in data.get("data") or []:
            p = self._to_paper(edge.get("citedPaper") or {})
            if p:
                out.append(p)
        return out
