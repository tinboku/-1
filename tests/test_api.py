"""Offline tests for the HTTP API layer (dls.api).

Uses a fake engine/LLM context so no network or API key is needed.
Skipped automatically when fastapi is not installed (it is an optional
extra); run with the project venv:  .venv/bin/python -m unittest tests.test_api
"""

from __future__ import annotations

import tempfile
import time
import types
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    raise unittest.SkipTest("fastapi not installed (pip install -e .[api])")

from dls.api import create_app, paper_dict
from dls.models import Paper, SearchOutcome
from dls.store import Store


def _paper() -> Paper:
    p = Paper(
        paper_id="s2:abc",
        title="AutoDDG: Automated Dataset Description Generation",
        abstract="We generate descriptions of tabular datasets.",
        year=2025,
        authors=["Wei Zhang"],
        venue="ACM TODS",
        citation_count=12,
        doi="10.1145/3786626",
    )
    return p


def _fake_ctx(tmp: Path):
    store = Store(tmp / "library.db")
    paper = _paper()
    paper.match = 92.0
    paper.match_reason = "directly on topic"
    paper.found_via = "search"

    def fake_run(question, criteria, answers=None, project="default",
                 per_query=40, max_rounds=2, progress=None):
        sid = store.create_search(project, question, criteria, answers or {})
        if progress:
            progress("Searching for the most promising papers", "fake channel")
            progress("Identifying the best candidate papers", "1 candidates")
        db_id = store.upsert_paper(paper)
        paper.db_id = db_id
        store.save_results(sid, [paper], {db_id}, {"found": 1, "excluded": 0}, None)
        if progress:
            progress("Done", "1 papers")
        return SearchOutcome(
            search_id=sid, question=question, criteria=criteria, included=[paper],
            excluded_count=0, with_full_text=0, rounds=1, converged=True,
            coverage=None, warnings=[],
        )

    engine = types.SimpleNamespace(
        brainstorm=lambda q: ["Scope?", "Methods only?"],
        build_criteria=lambda q, answers=None: [q, "narrow scope"],
        run=fake_run,
        trace=None,
    )
    llm = types.SimpleNamespace(answer=lambda q, papers: f"answer over {len(papers)} papers")
    config = types.SimpleNamespace(
        llm_model="test-model",
        db_path=tmp / "library.db",
        files_dir=tmp / "files",
        ensure_dirs=lambda: (tmp / "files").mkdir(parents=True, exist_ok=True),
    )
    return types.SimpleNamespace(
        config=config, store=store, engine=engine, llm=llm, s2=None, crossref=None
    )


def _wait_job(client: TestClient, job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = client.get(f"/api/jobs/{job_id}").json()
        if snap["status"] in ("done", "error"):
            return snap
        time.sleep(0.05)
    raise AssertionError("job did not finish in time")


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ctx = _fake_ctx(self.tmp)
        self.client = TestClient(create_app(self.ctx))

    def tearDown(self):
        self.client.app.state.jobs._pool.shutdown(wait=True)
        self.client.close()
        self.ctx.store.conn.close()

    def _search(self, **payload):
        response = self.client.post("/api/searches", json={"question": "q", **payload})
        return _wait_job(self.client, response.json()["job_id"])

    def test_plan_answers_reach_criteria_builder(self):
        received = []
        self.ctx.engine.build_criteria = lambda q, answers: received.append(answers) or [answers["Scope?"]]
        response = self.client.post("/api/plan", json={"question": "q", "answers": {"Scope?": "tabular only"}})
        self.assertEqual(response.json()["criteria"], ["tabular only"])
        self.assertEqual(received, [{"Scope?": "tabular only"}])

    def test_search_preserves_edited_criteria_and_answers(self):
        snap = self._search(criteria=["edited criterion"], answers={"Scope?": "tables"})
        detail = self.client.get(f"/api/searches/{snap['result']['search_id']}").json()
        self.assertEqual(detail["criteria"], ["edited criterion"])
        self.assertEqual(detail["answers"], {"Scope?": "tables"})

    def test_job_list_recovers_running_job_without_store_lock(self):
        import threading
        started, release = threading.Event(), threading.Event()
        def work(job):
            started.set()
            release.wait(3)
            return {"file_id": 7}
        job = self.client.app.state.jobs.submit("report", work, search_id=42)
        try:
            self.assertTrue(started.wait(1))
            with self.ctx.store.conn:
                listing = self.client.get("/api/jobs").json()
            self.assertEqual(listing[0]["id"], job.id)
            self.assertEqual(listing[0]["status"], "running")
            self.assertEqual(listing[0]["search_id"], 42)
            self.assertNotIn("events", listing[0])
        finally:
            release.set()

    def test_job_snapshot_replays_all_events(self):
        snap = self._search()
        again = self.client.get(f"/api/jobs/{snap['id']}").json()
        self.assertEqual(again["events"], snap["events"])
        self.assertTrue(all("stage" in e and "detail" in e for e in again["events"]))

    def test_search_exposes_session_warnings(self):
        run = self.ctx.engine.run
        def warned(*args, **kwargs):
            result = run(*args, **kwargs)
            result.warnings = ["OpenAlex unavailable"]
            return result
        self.ctx.engine.run = warned
        snap = self._search()
        self.assertTrue(snap["result"]["degraded"])
        detail = self.client.get(f"/api/searches/{snap['result']['search_id']}").json()
        self.assertEqual(detail["warnings"], ["OpenAlex unavailable"])
        self.assertTrue(detail["degraded"])

    def test_historical_search_does_not_invent_warnings(self):
        sid = self.ctx.store.create_search("default", "old", [], {})
        detail = self.client.get(f"/api/searches/{sid}").json()
        self.assertEqual(detail["warnings"], [])
        self.assertFalse(detail["degraded"])

    def test_paper_score_source_is_explicit_or_unknown(self):
        paper = _paper()
        self.assertIsNone(paper_dict(paper)["match_source"])
        paper.match_source = "heuristic"
        self.assertEqual(paper_dict(paper)["match_source"], "heuristic")

    def test_lookup_and_paper_detail_provenance(self):
        snap = self._search()
        paper = self.client.get(f"/api/searches/{snap['result']['search_id']}").json()["papers"][0]
        for identifier in [paper["key"], paper["doi"], paper["paper_id"]]:
            result = self.client.get("/api/papers/lookup", params={"identifier": identifier})
            self.assertEqual(result.json()["abstract"], _paper().abstract)
        self.assertEqual(paper["found_via"], "search")
        self.assertEqual(self.client.get("/api/papers/lookup?identifier=missing").status_code, 404)

    def test_folder_filter_and_clear(self):
        self._search()
        pid = self.client.get("/api/papers").json()[0]["db_id"]
        self.client.post(f"/api/papers/{pid}/folder", json={"folder": "综述"})
        self.assertEqual(len(self.client.get("/api/papers", params={"folder": "综述"}).json()), 1)
        self.assertEqual(self.client.get("/api/papers?folder=other").json(), [])
        self.client.post(f"/api/papers/{pid}/folder", json={"folder": None})
        self.assertEqual(self.client.get("/api/papers").json()[0]["folder"], None)

    def test_bibtex_import_from_content(self):
        response = self.client.post("/api/import/bibtex", json={"content": "@article{test,\n title={Imported Paper}, author={Alice Smith}, year={2024}\n}"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["imported"], 1)
        self.assertEqual(self.client.get("/api/papers").json()[0]["title"], "Imported Paper")
        self.assertEqual(list(self.ctx.config.files_dir.glob("import-*.bib")), [])
        invalid = self.client.post("/api/import/bibtex", json={"content": "not bibtex"})
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(list(self.ctx.config.files_dir.glob("import-*.bib")), [])

    def test_report_and_extract_jobs_have_search_context(self):
        sid = self._search()["result"]["search_id"]
        self.ctx.llm.write_report = lambda *args: "# Report\n[Zhang25]"
        self.ctx.llm.extract_row = lambda paper, columns: {"title": paper.title}
        for action, body, expected in [("report", {}, "# Report"), ("extract", {"columns": ["title"]}, "AutoDDG")]:
            response = self.client.post(f"/api/searches/{sid}/{action}", json=body)
            snap = _wait_job(self.client, response.json()["job_id"])
            self.assertEqual(snap["status"], "done", snap)
            self.assertEqual(snap["search_id"], sid)
            artifact = self.client.get(f"/api/files/{snap['result']['file_id']}").json()
            self.assertIn(expected, artifact["content"])

    def test_failed_job_surfaces_real_error(self):
        def fail(*args, **kwargs):
            raise RuntimeError("upstream unavailable")
        self.ctx.engine.run = fail
        snap = self._search(criteria=["criterion"])
        self.assertEqual(snap["status"], "error")
        self.assertIn("upstream unavailable", snap["error"])
        self.assertIsNone(snap["result"])

    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_plan(self):
        r = self.client.post("/api/plan", json={"question": "dataset descriptions with LLMs"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body["questions"]), 2)
        self.assertEqual(len(body["criteria"]), 2)

    def test_search_job_flow(self):
        r = self.client.post("/api/searches", json={"question": "dataset descriptions"})
        self.assertEqual(r.status_code, 202)
        snap = _wait_job(self.client, r.json()["job_id"])
        self.assertEqual(snap["status"], "done", snap)
        self.assertEqual(snap["result"]["found"], 1)
        stages = [e["stage"] for e in snap["events"]]
        self.assertIn("Searching for the most promising papers", stages)

        search_id = snap["result"]["search_id"]
        detail = self.client.get(f"/api/searches/{search_id}").json()
        self.assertEqual(detail["question"], "dataset descriptions")
        self.assertEqual(len(detail["papers"]), 1)
        self.assertEqual(detail["papers"][0]["key"], "Zhang25")
        self.assertEqual(detail["papers"][0]["match"], 92.0)

    def test_search_events_stream(self):
        r = self.client.post("/api/searches", json={"question": "stream test"})
        job_id = r.json()["job_id"]
        _wait_job(self.client, job_id)
        with self.client.stream("GET", f"/api/jobs/{job_id}/events") as stream:
            text = "".join(chunk for chunk in stream.iter_text())
        self.assertIn('"type": "progress"', text)
        self.assertIn('"type": "done"', text)

    def test_ask_and_export_and_star(self):
        r = self.client.post("/api/searches", json={"question": "q"})
        snap = _wait_job(self.client, r.json()["job_id"])
        search_id = snap["result"]["search_id"]

        ans = self.client.post(f"/api/searches/{search_id}/ask", json={"question": "which?"})
        self.assertEqual(ans.json()["answer"], "answer over 1 papers")

        exp = self.client.get(f"/api/searches/{search_id}/export", params={"format": "bibtex"})
        self.assertEqual(exp.status_code, 200)
        self.assertIn("Zhang25", exp.text)

        papers = self.client.get("/api/papers").json()
        self.assertEqual(len(papers), 1)
        db_id = papers[0]["db_id"]
        star = self.client.post(f"/api/papers/{db_id}/star", json={"starred": True})
        self.assertEqual(star.json()["starred"], True)
        starred = self.client.get("/api/papers", params={"starred": True}).json()
        self.assertEqual(len(starred), 1)

    def test_unknown_job_404(self):
        self.assertEqual(self.client.get("/api/jobs/nope").status_code, 404)
        self.assertEqual(self.client.get("/api/searches/999").status_code, 404)


if __name__ == "__main__":
    unittest.main()
