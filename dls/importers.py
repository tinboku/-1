"""Importers: DOI, BibTeX files, and PDF files into the library."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from .clients.crossref import CrossrefClient
from .clients.semantic_scholar import SemanticScholarClient
from .models import Paper
from .store import Store


def import_doi(store: Store, doi: str, crossref: CrossrefClient, s2: SemanticScholarClient | None = None) -> Paper:
    paper = None
    if s2 is not None:
        try:
            paper = s2.paper(f"DOI:{doi}")
        except Exception:
            paper = None
    if paper is None:
        paper = crossref.by_doi(doi)
    if paper is None:
        raise ValueError(f"DOI not found: {doi}")
    store.upsert_paper(paper)
    stored = store.find_paper(doi)
    return stored or paper


# -- BibTeX -------------------------------------------------------------------

_ENTRY_RE = re.compile(r"@\w+\s*\{\s*([^,]+),(.*?)\n\}", re.S)
_FIELD_RE = re.compile(r"(\w+)\s*=\s*\{((?:[^{}]|\{[^{}]*\})*)\}|(\w+)\s*=\s*\"([^\"]*)\"|(\w+)\s*=\s*(\d+)")


def parse_bibtex(text: str) -> list[Paper]:
    papers: list[Paper] = []
    for _key, body in _ENTRY_RE.findall(text):
        fields: dict[str, str] = {}
        for m in _FIELD_RE.finditer(body):
            if m.group(1):
                fields[m.group(1).lower()] = m.group(2)
            elif m.group(3):
                fields[m.group(3).lower()] = m.group(4)
            elif m.group(5):
                fields[m.group(5).lower()] = m.group(6)
        title = re.sub(r"[{}]", "", fields.get("title", "")).strip()
        if not title:
            continue
        authors = []
        if fields.get("author"):
            authors = [a.strip() for a in re.split(r"\s+and\s+", fields["author"]) if a.strip()]
        year = None
        if fields.get("year", "").isdigit():
            year = int(fields["year"])
        doi = fields.get("doi")
        papers.append(
            Paper(
                paper_id=f"doi:{doi}" if doi else f"bibtex:{title[:40]}",
                title=title,
                abstract=fields.get("abstract"),
                year=year,
                authors=authors,
                venue=fields.get("journal") or fields.get("booktitle"),
                doi=doi,
                url=fields.get("url"),
                source="bibtex",
            )
        )
    return papers


def import_bibtex(store: Store, path: Path) -> int:
    papers = parse_bibtex(path.read_text(encoding="utf-8", errors="replace"))
    for p in papers:
        store.upsert_paper(p)
    return len(papers)


# -- PDF ------------------------------------------------------------------------

def import_pdf(store: Store, path: Path, files_dir: Path) -> Paper:
    """Register a PDF in the library. Extracts first-page text when a PDF
    library (pypdf/PyPDF2) happens to be installed; otherwise stores the
    file with filename-based metadata for later enrichment."""
    files_dir.mkdir(parents=True, exist_ok=True)
    dest = files_dir / path.name
    if path.resolve() != dest.resolve():
        shutil.copyfile(path, dest)
    title = path.stem.replace("_", " ").replace("-", " ").strip() or path.name
    abstract = None
    try:
        reader = None
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception:
            from PyPDF2 import PdfReader  # type: ignore
        reader = PdfReader(str(dest))
        if reader.pages:
            text = reader.pages[0].extract_text() or ""
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if lines:
                title = lines[0][:200]
            abstract = " ".join(lines)[:1500] or None
    except Exception:
        pass
    paper = Paper(
        paper_id=f"file:{dest.name}",
        title=title,
        abstract=abstract,
        url=str(dest),
        source="upload",
    )
    store.upsert_paper(paper)
    return store.find_paper(paper.paper_id) or paper
