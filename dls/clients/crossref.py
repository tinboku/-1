"""Crossref API client: DOI metadata lookup and enrichment."""

from __future__ import annotations

import html as _html
import re

import requests

from ..models import Paper

BASE = "https://api.crossref.org"


def _clean_abstract(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = _html.unescape(re.sub(r"\s+", " ", cleaned)).strip()
    return cleaned or None


class CrossrefClient:
    name = "crossref"

    def __init__(self, email: str | None = None):
        self.email = email
        self.session = requests.Session()
        ua = "deep-literature-search/0.1"
        if email:
            ua += f" (mailto:{email})"
        self.session.headers.update({"Accept": "application/json", "User-Agent": ua})

    @staticmethod
    def _to_paper(item: dict) -> Paper | None:
        if not item:
            return None
        title = (item.get("title") or [None])[0]
        doi = item.get("DOI")
        if not title or not doi:
            return None
        authors = []
        for a in item.get("author") or []:
            name = " ".join(x for x in [a.get("given"), a.get("family")] if x)
            if name:
                authors.append(name)
        year = None
        for key in ("published-print", "published-online", "issued", "created"):
            parts = ((item.get(key) or {}).get("date-parts") or [[None]])[0]
            if parts and parts[0]:
                year = parts[0]
                break
        return Paper(
            paper_id=f"doi:{doi}",
            title=title,
            abstract=_clean_abstract(item.get("abstract")),
            year=year,
            authors=authors,
            venue=(item.get("container-title") or [None])[0],
            citation_count=item.get("is-referenced-by-count") or 0,
            reference_count=item.get("reference-count") or 0,
            doi=doi,
            url=item.get("URL"),
            source="crossref",
        )

    def by_doi(self, doi: str) -> Paper | None:
        resp = self.session.get(f"{BASE}/works/{doi}", timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return self._to_paper(resp.json().get("message") or {})

    def search(self, query: str, rows: int = 10) -> list[Paper]:
        resp = self.session.get(
            f"{BASE}/works", params={"query": query, "rows": rows}, timeout=30
        )
        resp.raise_for_status()
        items = (resp.json().get("message") or {}).get("items") or []
        return [p for p in (self._to_paper(i) for i in items) if p]
