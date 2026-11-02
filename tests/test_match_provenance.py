"""Offline scoring failures and provenance persistence; all model calls are mocked."""

import json
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dls.config import Config
from dls.engine import DeepSearchEngine
from dls.llm import HeuristicLLM, OpenAIChatLLM
from dls.models import Paper
from dls.scoring import heuristic_match
from dls.store import SCHEMA, Store


class TestMatchProvenance(unittest.TestCase):
    def setUp(self):
        self.llm = OpenAIChatLLM(Config(llm_api_key="offline-test"))
        self.papers = [Paper("a", "Dataset descriptions"), Paper("b", "Quantum codes")]
        self.criteria = ["dataset descriptions"]
        # Any accidental transport call fails locally instead of reaching the network.
        self.transport = mock.patch.object(self.llm.session, "post", side_effect=AssertionError("network forbidden"))
        self.transport.start()
        self.addCleanup(self.transport.stop)
        self.addCleanup(self.llm.session.close)

    def score(self, entries):
        with mock.patch.object(self.llm, "_chat", return_value=json.dumps({"scores": entries})):
            return self.llm.score_matches(self.criteria, self.papers)

    def assert_fallback(self, result, paper, reason):
        self.assertEqual(result.source, "heuristic")
        self.assertEqual(result.fallback, reason)
        self.assertEqual((result.score, result.reason), heuristic_match(self.criteria, paper))
        self.assertTrue(math.isfinite(result.score))
        self.assertTrue(0 <= result.score <= 100)

    def test_model_success_and_boundaries(self):
        scores = self.score([{"index": 1, "score": 0}, {"index": 0, "score": 100, "reason": "direct"}])
        self.assertEqual(len(scores), 2)
        self.assertEqual(scores[0], (100.0, "direct", "llm", None))
        self.assertEqual(scores[1], (0.0, "", "llm", None))

    def test_missing_index_only_degrades_missing_paper(self):
        scores = self.score([{"index": 0, "score": 87, "reason": "direct"}])
        self.assertEqual(scores[0].source, "llm")
        self.assert_fallback(scores[1], self.papers[1], "missing_index")

    def test_batch_failure(self):
        with mock.patch.object(self.llm, "_chat", side_effect=RuntimeError("offline failure")):
            scores = self.llm.score_matches(self.criteria, self.papers)
        self.assertEqual(len(scores), len(self.papers))
        for result, paper in zip(scores, self.papers):
            self.assert_fallback(result, paper, "batch_error")

    def test_invalid_score_only_degrades_invalid_paper(self):
        for value in (170, -1, float("nan"), float("inf"), None, "bad", True, "87"):
            with self.subTest(value=value):
                scores = self.score([{"index": 0, "score": value}, {"index": 1, "score": 65}])
                self.assert_fallback(scores[0], self.papers[0], "invalid_score")
                self.assertEqual(scores[1].source, "llm")
                self.assertEqual(scores[1].score, 65)

    def test_malformed_batch(self):
        for payload in ("invalid json", "[]", '{"scores": {}}'):
            with self.subTest(payload=payload), mock.patch.object(self.llm, "_chat", return_value=payload):
                scores = self.llm.score_matches(self.criteria, self.papers)
                for result, paper in zip(scores, self.papers):
                    self.assert_fallback(result, paper, "batch_error")

    def test_failure_in_one_batch_preserves_later_batch(self):
        papers = [Paper(str(i), f"Paper {i}") for i in range(11)]
        with mock.patch.object(self.llm, "_chat", side_effect=[RuntimeError("failed"), '{"scores":[{"index":0,"score":92}]}']):
            scores = self.llm.score_matches(self.criteria, papers)
        self.assertEqual(len(scores), 11)
        self.assertTrue(all(s.fallback == "batch_error" for s in scores[:10]))
        self.assertEqual(scores[10].source, "llm")

    def test_duplicate_and_invalid_indexes_are_not_model_judgments(self):
        scores = self.score([{"index": 0, "score": 80}, {"index": 0, "score": 90}, {"index": 1.5, "score": 100}])
        self.assert_fallback(scores[0], self.papers[0], "duplicate_index")
        self.assert_fallback(scores[1], self.papers[1], "missing_index")

    def test_explicit_heuristic_is_not_a_fallback(self):
        scores = HeuristicLLM().score_matches(self.criteria, self.papers)
        self.assertTrue(all(s.source == "heuristic" and s.fallback is None for s in scores))

    def test_engine_store_roundtrip_includes_excluded_fallbacks(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "library.db"
            store = Store(path)
            s2 = mock.Mock()
            s2.search.return_value = self.papers
            engine = DeepSearchEngine(s2, None, self.llm, store, include_threshold=90)
            with mock.patch.object(self.llm, "_chat", return_value='{"scores":[{"index":0,"score":95}]}'):
                outcome = engine.run(self.criteria[0], self.criteria, max_rounds=0)
            self.assertEqual(outcome.found, 1)
            self.assertEqual(len(outcome.warnings), 1)
            self.assertIn("missing_index", outcome.warnings[0])
            self.assertEqual(store.get_search(outcome.search_id)["counts"]["match_fallbacks"], {"missing_index": 1})
            # A second search has different provenance for the same paper.
            engine.llm = HeuristicLLM()
            second = engine.run(self.criteria[0], self.criteria, max_rounds=0)
            self.assertEqual(second.warnings, [])
            store.conn.close()
            store = Store(path)
            self.addCleanup(store.conn.close)
            first = {p.paper_id: p for p in store.search_papers(outcome.search_id, included_only=False)}
            self.assertEqual((first["a"].match_source, first["a"].match_fallback), ("llm", None))
            self.assertEqual((first["b"].match_source, first["b"].match_fallback), ("heuristic", "missing_index"))
            self.assertTrue(all(p.match_source == "heuristic" and p.match_fallback is None for p in store.search_papers(second.search_id, included_only=False)))

    def test_trace_reports_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(Path(td) / "library.db")
            self.addCleanup(store.conn.close)
            s2 = mock.Mock()
            s2.citations.return_value = self.papers
            s2.references.return_value = []
            engine = DeepSearchEngine(s2, None, self.llm, store)
            with mock.patch.object(self.llm, "_chat", side_effect=RuntimeError("failed")):
                outcome = engine.trace(Paper("seed", "Seed paper"), hops=1)
            self.assertIn("batch_error: 2", outcome.warnings[0])
            self.assertEqual(store.get_search(outcome.search_id)["counts"]["match_fallbacks"], {"batch_error": 2})

    def test_old_database_migration_preserves_unknown_source(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = sqlite3.connect(path)
            conn.executescript(SCHEMA.replace("    match_source TEXT,\n", "").replace("    match_fallback TEXT,\n", ""))
            conn.close()
            store = Store(path)
            sid = store.create_search("default", "q", ["q"], {})
            pid = store.upsert_paper(self.papers[0])
            store.conn.execute("INSERT INTO search_results (search_id, paper_id, match, included) VALUES (?, ?, 80, 1)", (sid, pid))
            store.conn.commit()
            store.conn.close()
            store = Store(path)  # Migration remains safe on repeated opens.
            self.addCleanup(store.conn.close)
            paper = store.search_papers(sid)[0]
            self.assertIsNone(paper.match_source)
            self.assertIsNone(paper.match_fallback)
