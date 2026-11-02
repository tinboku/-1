"""HTTP API + job runner for the deep-literature-search engine.

This is the backend layer that turns the CLI/library into a service:

- **Jobs**: searches, traces, reports, extractions and update checks run
  in a background thread pool (they take minutes), each with a live
  progress event stream — the engine already reports
  (stage, detail) pairs through its `progress` callback.
- **Progress streaming**: `GET /api/jobs/{id}/events` is a
  Server-Sent-Events stream; `GET /api/jobs/{id}` returns a snapshot.
- **Data endpoints**: searches, papers, files (reports/tables), library
  import/export — thin wrappers over `Store` and the existing helpers
  in `report.py` / `extract.py` / `importers.py` / `updates.py`.

The store uses a single SQLite connection shared across threads, so all
store access is serialized through one re-entrant lock. That is fine for
a local, single-user service and keeps the core package untouched.

Run it with:  dls api --port 8000      (requires the `api` extra:
                                        pip install fastapi uvicorn)
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .models import Paper

WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"


# ----------------------------------------------------------------------
# Job management
# ----------------------------------------------------------------------

@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"  # queued | running | done | error
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    events: list[dict] = field(default_factory=list)
    result: dict | None = None
    error: str | None = None
    _cond: threading.Condition = field(default_factory=threading.Condition, repr=False)

    def emit(self, stage: str, detail: str) -> None:
        with self._cond:
            self.events.append({"ts": time.time(), "stage": stage, "detail": detail})
            self._cond.notify_all()

    def finish(self, status: str, result: dict | None = None, error: str | None = None) -> None:
        with self._cond:
            self.status = status
            self.result = result
            self.error = error
            self.finished_at = time.time()
            self._cond.notify_all()

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "events": list(self.events),
            "result": self.result,
            "error": self.error,
        }


class JobManager:
    def __init__(self, max_workers: int = 2):
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="dls-job")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, fn: Callable[[Job], dict]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.id] = job

        def _run() -> None:
            job.status = "running"
            try:
                result = fn(job)
                job.finish("done", result=result)
            except Exception as exc:  # surfaced to the client via the job
                job.finish("error", error=f"{type(exc).__name__}: {exc}")

        self._pool.submit(_run)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: -j.created_at)


# ----------------------------------------------------------------------
# Request bodies
# ----------------------------------------------------------------------

class PlanIn(BaseModel):
    question: str
    answers: dict[str, str] = Field(default_factory=dict)


class SearchIn(BaseModel):
    question: str
    criteria: list[str] | None = None
    answers: dict[str, str] = Field(default_factory=dict)
    project: str = "default"
    per_query: int = 40
    rounds: int = 2


class TraceIn(BaseModel):
    identifier: str
    question: str | None = None
    hops: int = 1


class ReportIn(BaseModel):
    focus: str | None = None


class ExtractIn(BaseModel):
    columns: list[str]
    top: int = 10


class AskIn(BaseModel):
    question: str


class StarIn(BaseModel):
    starred: bool = True


class FolderIn(BaseModel):
    folder: str | None = None


class ImportDoiIn(BaseModel):
    doi: str


class ImportBibtexIn(BaseModel):
    content: str


# ----------------------------------------------------------------------
# Serialization helpers
# ----------------------------------------------------------------------

def paper_dict(p: Paper) -> dict:
    return {
        "db_id": getattr(p, "db_id", None),
        "paper_id": p.paper_id,
        "key": p.key,
        "title": p.title,
        "abstract": p.abstract,
        "tldr": p.tldr,
        "year": p.year,
        "authors": p.authors,
        "venue": p.venue,
        "citation_count": p.citation_count,
        "reference_count": p.reference_count,
        "citations_per_year": round(p.citations_per_year(), 1),
        "doi": p.doi,
        "arxiv_id": p.arxiv_id,
        "url": p.url,
        "open_access_pdf": p.open_access_pdf,
        "has_full_text": p.has_full_text,
        "source": p.source,
        "match": p.match,
        "match_reason": p.match_reason,
        "found_via": p.found_via,
        "starred": bool(getattr(p, "starred", False)),
        "folder": getattr(p, "folder", None),
    }


def _resolve_seed(ctx, identifier: str) -> Paper | None:
    """Same resolution order as the CLI's `trace` command."""
    stored = ctx.store.find_paper(identifier)
    if stored is not None:
        if stored.paper_id.startswith("doi:"):
            try:
                seed = ctx.s2.paper(f"DOI:{stored.doi}") if stored.doi else None
            except Exception:
                seed = None
            if seed is not None:
                return seed
        else:
            return stored
    if identifier.startswith("10."):
        try:
            return ctx.s2.paper(f"DOI:{identifier}")
        except Exception:
            pass
    try:
        results = ctx.s2.search(identifier, limit=1)
        return results[0] if results else None
    except Exception:
        return None


# ----------------------------------------------------------------------
# App factory
# ----------------------------------------------------------------------

def create_app(ctx=None) -> FastAPI:
    if ctx is None:
        from .cli import Context

        ctx = Context()

    store_lock = threading.RLock()

    @contextmanager
    def locked() -> Iterator[None]:
        with store_lock:
            yield

    jobs = JobManager()
    app = FastAPI(title="deep-literature-search", version="0.2.0")
    app.state.ctx = ctx
    app.state.jobs = jobs

    # -- meta ------------------------------------------------------------
    @app.get("/api/health")
    def health() -> dict:
        cfg = ctx.config
        return {
            "ok": True,
            "llm_backend": type(ctx.llm).__name__,
            "llm_model": cfg.llm_model,
            "db_path": str(cfg.db_path),
        }

    # -- planning ----------------------------------------------------------
    @app.post("/api/plan")
    def plan(body: PlanIn) -> dict:
        """Brainstorm questions + a criteria draft for a question."""
        with locked():
            questions = ctx.engine.brainstorm(body.question)
            criteria = ctx.engine.build_criteria(body.question, body.answers or None)
        return {"questions": questions, "criteria": criteria}

    # -- searches ------------------------------------------------------------
    @app.get("/api/searches")
    def list_searches() -> list[dict]:
        with locked():
            return ctx.store.list_searches()

    @app.get("/api/searches/{search_id}")
    def get_search(search_id: int, included_only: bool = True) -> dict:
        with locked():
            search = ctx.store.get_search(search_id)
            if search is None:
                raise HTTPException(404, "search not found")
            papers = ctx.store.search_papers(search_id, included_only=included_only)
        search["papers"] = [paper_dict(p) for p in papers]
        return search

    @app.post("/api/searches", status_code=202)
    def launch_search(body: SearchIn) -> dict:
        def work(job: Job) -> dict:
            criteria = body.criteria
            if not criteria:
                with locked():
                    criteria = ctx.engine.build_criteria(body.question, body.answers or None)
            job.emit("Interpreting your search criteria", f"{len(criteria)} criteria")
            with locked():
                outcome = ctx.engine.run(
                    body.question,
                    criteria,
                    answers=body.answers,
                    project=body.project,
                    per_query=body.per_query,
                    max_rounds=body.rounds,
                    progress=job.emit,
                )
            return {
                "search_id": outcome.search_id,
                "found": outcome.found,
                "excluded": outcome.excluded_count,
                "with_full_text": outcome.with_full_text,
                "rounds": outcome.rounds,
                "converged": outcome.converged,
                "coverage": outcome.coverage,
                "warnings": outcome.warnings,
            }

        job = jobs.submit("search", work)
        return {"job_id": job.id}

    @app.post("/api/trace", status_code=202)
    def launch_trace(body: TraceIn) -> dict:
        def work(job: Job) -> dict:
            with locked():
                seed = _resolve_seed(ctx, body.identifier)
            if seed is None:
                raise ValueError(f"could not resolve seed paper: {body.identifier}")
            with locked():
                outcome = ctx.engine.trace(
                    seed, question=body.question, hops=body.hops, progress=job.emit
                )
            return {
                "search_id": outcome.search_id,
                "found": outcome.found,
                "excluded": outcome.excluded_count,
                "warnings": outcome.warnings,
            }

        job = jobs.submit("trace", work)
        return {"job_id": job.id}

    # -- per-search actions ----------------------------------------------------
    @app.post("/api/searches/{search_id}/report", status_code=202)
    def launch_report(search_id: int, body: ReportIn) -> dict:
        from .report import generate_report

        def work(job: Job) -> dict:
            job.emit("Writing report", f"search #{search_id}")
            with locked():
                file_id, _md = generate_report(ctx.store, search_id, ctx.llm, focus=body.focus)
            return {"file_id": file_id}

        job = jobs.submit("report", work)
        return {"job_id": job.id}

    @app.post("/api/searches/{search_id}/extract", status_code=202)
    def launch_extract(search_id: int, body: ExtractIn) -> dict:
        from .extract import extract_table

        columns = [c.strip() for c in body.columns if c.strip()]
        if not columns:
            raise HTTPException(422, "at least one column is required")

        def work(job: Job) -> dict:
            job.emit("Extracting table", ", ".join(columns))
            with locked():
                table = extract_table(ctx.store, search_id, columns, ctx.llm, top_n=body.top)
                file_id = ctx.store.save_file(
                    "default", "table", f"extract-search-{search_id}", table
                )
            return {"file_id": file_id}

        job = jobs.submit("extract", work)
        return {"job_id": job.id}

    @app.post("/api/searches/{search_id}/ask")
    def ask(search_id: int, body: AskIn) -> dict:
        with locked():
            papers = ctx.store.search_papers(search_id, included_only=True)
            if not papers:
                raise HTTPException(404, "no included papers in that search")
            answer = ctx.llm.answer(body.question, papers)
        return {"answer": answer}

    @app.post("/api/searches/{search_id}/updates", status_code=202)
    def launch_updates(search_id: int) -> dict:
        from .updates import check_updates

        def work(job: Job) -> dict:
            job.emit("Checking for new papers", f"search #{search_id}")
            with locked():
                fresh = check_updates(ctx.store, search_id, ctx.s2, ctx.llm)
            return {"new_papers": fresh}

        job = jobs.submit("updates", work)
        return {"job_id": job.id}

    @app.get("/api/searches/{search_id}/export")
    def export_search(
        search_id: int,
        format: str = Query("csv", pattern="^(csv|bibtex|ris)$"),
        all: bool = False,
    ) -> PlainTextResponse:
        from .report import papers_to_bibtex, papers_to_csv, papers_to_ris

        with locked():
            papers = ctx.store.search_papers(search_id, included_only=not all)
        if not papers:
            raise HTTPException(404, "no papers to export")
        if format == "csv":
            content, ext, mime = papers_to_csv(papers), "csv", "text/csv"
        elif format == "bibtex":
            content, ext, mime = papers_to_bibtex(papers), "bib", "application/x-bibtex"
        else:
            content, ext, mime = papers_to_ris(papers), "ris", "application/x-research-info-systems"
        return PlainTextResponse(
            content,
            media_type=mime,
            headers={"Content-Disposition": f'attachment; filename="search-{search_id}.{ext}"'},
        )

    # -- files (reports & tables) ---------------------------------------------
    @app.get("/api/files")
    def list_files() -> list[dict]:
        with locked():
            return ctx.store.list_files()

    @app.get("/api/files/{file_id}")
    def get_file(file_id: int) -> dict:
        with locked():
            f = ctx.store.get_file(file_id)
        if f is None:
            raise HTTPException(404, "file not found")
        return f

    # -- library ---------------------------------------------------------------
    @app.get("/api/papers")
    def list_papers(starred: bool = False, folder: str | None = None) -> list[dict]:
        with locked():
            papers = ctx.store.list_papers(starred_only=starred, folder=folder)
        return [paper_dict(p) for p in papers]

    @app.get("/api/papers/lookup")
    def lookup_paper(identifier: str) -> dict:
        with locked():
            paper = ctx.store.find_paper(identifier)
        if paper is None:
            raise HTTPException(404, "paper not found")
        return paper_dict(paper)

    @app.post("/api/papers/{db_id}/star")
    def star_paper(db_id: int, body: StarIn) -> dict:
        with locked():
            if ctx.store.get_paper(db_id) is None:
                raise HTTPException(404, "paper not found")
            ctx.store.set_star(db_id, body.starred)
        return {"db_id": db_id, "starred": body.starred}

    @app.post("/api/papers/{db_id}/folder")
    def folder_paper(db_id: int, body: FolderIn) -> dict:
        with locked():
            if ctx.store.get_paper(db_id) is None:
                raise HTTPException(404, "paper not found")
            ctx.store.set_folder(db_id, body.folder)
        return {"db_id": db_id, "folder": body.folder}

    @app.post("/api/import/doi")
    def import_doi(body: ImportDoiIn) -> dict:
        from .importers import import_doi as _import_doi

        with locked():
            paper = _import_doi(ctx.store, body.doi, ctx.crossref, ctx.s2)
        return paper_dict(paper)

    @app.post("/api/import/bibtex")
    def import_bibtex(body: ImportBibtexIn) -> dict:
        from .importers import import_bibtex as _import_bibtex

        tmp = ctx.config.files_dir / f"import-{uuid.uuid4().hex[:8]}.bib"
        ctx.config.ensure_dirs()
        tmp.write_text(body.content, encoding="utf-8")
        with locked():
            count = _import_bibtex(ctx.store, tmp)
        return {"imported": count}

    # -- jobs ---------------------------------------------------------------------
    @app.get("/api/jobs")
    def list_jobs() -> list[dict]:
        return [
            {k: v for k, v in j.snapshot().items() if k != "events"} for j in jobs.list()
        ]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        return job.snapshot()

    @app.get("/api/jobs/{job_id}/events")
    def job_events(job_id: str, request: Request) -> StreamingResponse:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")

        def stream() -> Iterator[str]:
            sent = 0
            while True:
                with job._cond:
                    pending = job.events[sent:]
                    done = job.status in ("done", "error") and sent >= len(job.events)
                    if not pending and not done:
                        job._cond.wait(timeout=15)
                        pending = job.events[sent:]
                        done = job.status in ("done", "error") and sent >= len(job.events)
                for ev in pending:
                    sent += 1
                    yield f"data: {json.dumps({'type': 'progress', **ev})}\n\n"
                if done:
                    final = {"type": job.status, "result": job.result, "error": job.error}
                    yield f"data: {json.dumps(final)}\n\n"
                    return
                if not pending:
                    yield ": ping\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    # -- frontend -------------------------------------------------------------------
    if WEBAPP_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(WEBAPP_DIR), html=True), name="webapp")

    return app


def run_api(port: int = 8000, host: str = "127.0.0.1") -> None:
    import uvicorn

    uvicorn.run(create_app(), host=host, port=port)
