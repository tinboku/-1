"""SQLite-backed project library: papers, searches, reports, updates."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .models import Paper
from .scoring import make_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_uid TEXT UNIQUE NOT NULL,
    key TEXT UNIQUE,
    title TEXT NOT NULL,
    abstract TEXT,
    year INTEGER,
    authors TEXT NOT NULL DEFAULT '[]',
    venue TEXT,
    citation_count INTEGER NOT NULL DEFAULT 0,
    reference_count INTEGER NOT NULL DEFAULT 0,
    doi TEXT,
    arxiv_id TEXT,
    oa_pdf TEXT,
    url TEXT,
    tldr TEXT,
    source TEXT,
    starred INTEGER NOT NULL DEFAULT 0,
    folder TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    question TEXT NOT NULL,
    criteria TEXT NOT NULL DEFAULT '[]',
    answers TEXT NOT NULL DEFAULT '{}',
    counts TEXT NOT NULL DEFAULT '{}',
    coverage TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS search_results (
    search_id INTEGER NOT NULL REFERENCES searches(id),
    paper_id INTEGER NOT NULL REFERENCES papers(id),
    match REAL,
    reason TEXT,
    included INTEGER NOT NULL DEFAULT 0,
    rank INTEGER,
    PRIMARY KEY (search_id, paper_id)
);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER NOT NULL REFERENCES searches(id),
    paper_id INTEGER NOT NULL REFERENCES papers(id),
    found_at REAL NOT NULL,
    seen INTEGER NOT NULL DEFAULT 0
);
"""


class Store:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the web UI serves requests from worker
        # threads. SQLite itself serializes writers; our transactions are
        # short, which is fine for this local single-user store.
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # -- projects ---------------------------------------------------------
    def project_id(self, name: str = "default") -> int:
        row = self.conn.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
        if row:
            return int(row["id"])
        cur = self.conn.execute(
            "INSERT INTO projects (name, created_at) VALUES (?, ?)", (name, time.time())
        )
        self.conn.commit()
        return int(cur.lastrowid)

    # -- papers -------------------------------------------------------------
    def _taken_keys(self) -> set[str]:
        return {r["key"] for r in self.conn.execute("SELECT key FROM papers WHERE key IS NOT NULL")}

    def upsert_paper(self, paper: Paper) -> int:
        """Insert or enrich a paper; assigns a citation KEY on first insert."""
        row = self.conn.execute(
            "SELECT id FROM papers WHERE paper_uid = ?", (paper.paper_id,)
        ).fetchone()
        if row is None and paper.doi:
            row = self.conn.execute(
                "SELECT id FROM papers WHERE doi = ?", (paper.doi,)
            ).fetchone()
        if row is not None:
            pid = int(row["id"])
            # Enrich missing fields only.
            cur = self.conn.execute("SELECT * FROM papers WHERE id = ?", (pid,)).fetchone()
            updates: dict[str, object] = {}
            if not cur["abstract"] and paper.abstract:
                updates["abstract"] = paper.abstract
            if not cur["oa_pdf"] and paper.open_access_pdf:
                updates["oa_pdf"] = paper.open_access_pdf
            if not cur["tldr"] and paper.tldr:
                updates["tldr"] = paper.tldr
            if paper.citation_count > (cur["citation_count"] or 0):
                updates["citation_count"] = paper.citation_count
            if updates:
                sets = ", ".join(f"{k} = ?" for k in updates)
                self.conn.execute(
                    f"UPDATE papers SET {sets} WHERE id = ?", (*updates.values(), pid)
                )
                self.conn.commit()
            return pid
        if not paper.key:
            paper.key = make_key(paper, self._taken_keys())
        cur = self.conn.execute(
            """INSERT INTO papers (paper_uid, key, title, abstract, year, authors, venue,
               citation_count, reference_count, doi, arxiv_id, oa_pdf, url, tldr, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                paper.paper_id, paper.key, paper.title, paper.abstract, paper.year,
                json.dumps(paper.authors), paper.venue, paper.citation_count,
                paper.reference_count, paper.doi, paper.arxiv_id,
                paper.open_access_pdf, paper.url, paper.tldr, paper.source, time.time(),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def _row_to_paper(self, row: sqlite3.Row) -> Paper:
        p = Paper(
            paper_id=row["paper_uid"],
            title=row["title"],
            abstract=row["abstract"],
            year=row["year"],
            authors=json.loads(row["authors"] or "[]"),
            venue=row["venue"],
            citation_count=row["citation_count"] or 0,
            reference_count=row["reference_count"] or 0,
            doi=row["doi"],
            arxiv_id=row["arxiv_id"],
            open_access_pdf=row["oa_pdf"],
            url=row["url"],
            tldr=row["tldr"],
            source=row["source"] or "import",
        )
        p.key = row["key"]
        p.db_id = int(row["id"])  # type: ignore[attr-defined]
        p.starred = bool(row["starred"])  # type: ignore[attr-defined]
        p.folder = row["folder"]  # type: ignore[attr-defined]
        return p

    def get_paper(self, db_id: int) -> Paper | None:
        row = self.conn.execute("SELECT * FROM papers WHERE id = ?", (db_id,)).fetchone()
        return self._row_to_paper(row) if row else None

    def find_paper(self, identifier: str) -> Paper | None:
        """Look up by KEY, DOI, arXiv id, or canonical paper_uid."""
        for column in ("key", "doi", "arxiv_id", "paper_uid"):
            row = self.conn.execute(
                f"SELECT * FROM papers WHERE {column} = ?", (identifier,)
            ).fetchone()
            if row:
                return self._row_to_paper(row)
        if identifier.startswith("doi:"):
            return self.find_paper(identifier[4:])
        return None

    def list_papers(self, starred_only: bool = False, folder: str | None = None) -> list[Paper]:
        sql = "SELECT * FROM papers"
        clauses, args = [], []
        if starred_only:
            clauses.append("starred = 1")
        if folder is not None:
            clauses.append("folder = ?")
            args.append(folder)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY year DESC, citation_count DESC"
        return [self._row_to_paper(r) for r in self.conn.execute(sql, args)]

    def set_star(self, db_id: int, starred: bool) -> None:
        self.conn.execute("UPDATE papers SET starred = ? WHERE id = ?", (1 if starred else 0, db_id))
        self.conn.commit()

    def set_folder(self, db_id: int, folder: str | None) -> None:
        self.conn.execute("UPDATE papers SET folder = ? WHERE id = ?", (folder, db_id))
        self.conn.commit()

    # -- searches -------------------------------------------------------------
    def create_search(self, project: str, question: str, criteria: list[str], answers: dict) -> int:
        pid = self.project_id(project)
        cur = self.conn.execute(
            "INSERT INTO searches (project_id, question, criteria, answers, created_at) VALUES (?, ?, ?, ?, ?)",
            (pid, question, json.dumps(criteria), json.dumps(answers), time.time()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def save_results(self, search_id: int, scored: list[Paper], included_ids: set[int], counts: dict, coverage: dict | None) -> None:
        rank = 0
        for paper in scored:
            db_id = getattr(paper, "db_id", None)
            if db_id is None:
                db_id = self.upsert_paper(paper)
                paper.db_id = db_id  # type: ignore[attr-defined]
            is_included = db_id in included_ids
            if is_included:
                rank += 1
            self.conn.execute(
                """INSERT OR REPLACE INTO search_results (search_id, paper_id, match, reason, included, rank)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (search_id, db_id, paper.match, paper.match_reason, 1 if is_included else 0, rank if is_included else None),
            )
        self.conn.execute(
            "UPDATE searches SET counts = ?, coverage = ? WHERE id = ?",
            (json.dumps(counts), json.dumps(coverage) if coverage else None, search_id),
        )
        self.conn.commit()

    def get_search(self, search_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM searches WHERE id = ?", (search_id,)).fetchone()
        if not row:
            return None
        return {
            "id": int(row["id"]),
            "project_id": int(row["project_id"]),
            "question": row["question"],
            "criteria": json.loads(row["criteria"] or "[]"),
            "answers": json.loads(row["answers"] or "{}"),
            "counts": json.loads(row["counts"] or "{}"),
            "coverage": json.loads(row["coverage"]) if row["coverage"] else None,
            "created_at": row["created_at"],
        }

    def list_searches(self) -> list[dict]:
        ids = [int(r["id"]) for r in self.conn.execute("SELECT id FROM searches ORDER BY id DESC")]
        return [self.get_search(i) for i in ids if self.get_search(i)]

    def search_papers(self, search_id: int, included_only: bool = True) -> list[Paper]:
        sql = """
            SELECT p.*, sr.match AS sr_match, sr.reason AS sr_reason, sr.rank AS sr_rank
            FROM search_results sr JOIN papers p ON p.id = sr.paper_id
            WHERE sr.search_id = ?
        """
        if included_only:
            sql += " AND sr.included = 1"
        sql += " ORDER BY sr.match DESC"
        papers = []
        for row in self.conn.execute(sql, (search_id,)):
            p = self._row_to_paper(row)
            p.match = row["sr_match"]
            p.match_reason = row["sr_reason"]
            papers.append(p)
        return papers

    def search_paper_ids(self, search_id: int) -> set[int]:
        return {
            int(r["paper_id"])
            for r in self.conn.execute("SELECT paper_id FROM search_results WHERE search_id = ?", (search_id,))
        }

    # -- files (reports) -------------------------------------------------------
    def save_file(self, project: str, kind: str, name: str, content: str) -> int:
        pid = self.project_id(project)
        cur = self.conn.execute(
            "INSERT INTO files (project_id, kind, name, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (pid, kind, name, content, time.time()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_file(self, file_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        if not row:
            return None
        return {"id": int(row["id"]), "kind": row["kind"], "name": row["name"], "content": row["content"]}

    def list_files(self) -> list[dict]:
        return [
            {"id": int(r["id"]), "kind": r["kind"], "name": r["name"], "created_at": r["created_at"]}
            for r in self.conn.execute("SELECT id, kind, name, created_at FROM files ORDER BY id DESC")
        ]

    # -- updates ------------------------------------------------------------------
    def add_update(self, search_id: int, paper_db_id: int) -> None:
        exists = self.conn.execute(
            "SELECT 1 FROM updates WHERE search_id = ? AND paper_id = ?", (search_id, paper_db_id)
        ).fetchone()
        if not exists:
            self.conn.execute(
                "INSERT INTO updates (search_id, paper_id, found_at) VALUES (?, ?, ?)",
                (search_id, paper_db_id, time.time()),
            )
            self.conn.commit()

    def list_updates(self, search_id: int | None = None) -> list[dict]:
        sql = """
            SELECT u.id, u.search_id, u.found_at, u.seen, p.title, p.key, p.year
            FROM updates u JOIN papers p ON p.id = u.paper_id
        """
        args: tuple = ()
        if search_id is not None:
            sql += " WHERE u.search_id = ?"
            args = (search_id,)
        sql += " ORDER BY u.found_at DESC"
        return [dict(r) for r in self.conn.execute(sql, args)]
