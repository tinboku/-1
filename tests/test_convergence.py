"""Offline regression tests for honest convergence and persisted diagnostics."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from dls.engine import DeepSearchEngine
from dls.models import Paper
from dls.store import SCHEMA, Store


class TestConvergence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "test.db"
        self.store = Store(self.path)
        self.addCleanup(self.store.conn.close)
        self.seed = Paper("seed", "Seed paper", key="Seed25")
        self.s2 = Mock()
        self.s2.search.return_value = [self.seed]
        self.s2.citations.return_value = []
        self.s2.references.return_value = []
        self.llm = Mock()
        self.llm.score_matches.side_effect = lambda criteria, papers: [(90, "relevant") for _ in papers]
        self.llm.reflect.return_value = {"new_queries": [], "stop": False}
        self.engine = DeepSearchEngine(self.s2, None, self.llm, self.store)

    def assert_status(self, outcome, converged, degraded):
        self.assertEqual(outcome.converged, converged)
        self.assertEqual(outcome.degraded, degraded)
        stored = self.store.get_search(outcome.search_id)
        self.assertEqual(stored["converged"], converged)
        self.assertEqual(stored["degraded"], degraded)
        self.assertEqual(stored["warnings"], outcome.warnings)

    def test_snowball_all_failed(self):
        self.s2.citations.side_effect = RuntimeError("citations offline")
        self.s2.references.side_effect = RuntimeError("references offline")
        outcome = self.engine.run("q", ["q"])
        self.assert_status(outcome, False, True)
        self.assertEqual(len(outcome.warnings), 2)
        self.assertIn("citations lookup failed for [Seed25]", outcome.warnings[0])
        self.assertIn("references lookup failed for [Seed25]", outcome.warnings[1])

    def test_initial_all_failed(self):
        self.s2.search.side_effect = RuntimeError("S2 offline")
        self.engine.openalex = Mock()
        self.engine.openalex.search.side_effect = RuntimeError("OA offline")
        self.engine.crossref = Mock()
        self.engine.crossref.search.side_effect = RuntimeError("Crossref offline")
        outcome = self.engine.run("q", ["q"])
        self.assert_status(outcome, False, True)
        self.assertEqual(outcome.found, 0)
        self.assertEqual(len(outcome.warnings), 3)

    def test_initial_failure_without_rounds(self):
        self.s2.search.side_effect = RuntimeError("offline")
        self.assert_status(self.engine.run("q", ["q"], max_rounds=0), False, True)

    def test_normal_no_new_candidates(self):
        outcome = self.engine.run("q", ["q"])
        self.assert_status(outcome, True, False)
        self.assertEqual(outcome.warnings, [])

    def test_successful_empty_initial_search(self):
        self.s2.search.return_value = []
        self.assert_status(self.engine.run("q", ["q"]), True, False)

    def test_reflection_query_failure(self):
        self.llm.reflect.return_value = {"new_queries": ["fresh query"], "stop": False}
        self.s2.search.side_effect = [[self.seed], RuntimeError("reflection offline")]
        outcome = self.engine.run("q", ["q"])
        self.assert_status(outcome, False, True)
        self.assertIn("reflection query", outcome.warnings[0])
        self.assertIn("fresh query", outcome.warnings[0])
        self.assertIn("[Seed25]", outcome.warnings[0])

    def test_previous_round_failure_is_not_forgotten(self):
        self.s2.citations.side_effect = [RuntimeError("offline"), [], []]
        self.s2.references.side_effect = [[Paper("next", "Next paper")], [], []]
        self.assert_status(self.engine.run("q", ["q"]), False, True)

    def test_reflection_stop_with_failed_channel(self):
        self.s2.citations.side_effect = RuntimeError("offline")
        self.s2.references.return_value = [Paper("next", "Next paper")]
        self.llm.reflect.return_value = {"new_queries": [], "stop": True}
        self.assert_status(self.engine.run("q", ["q"]), False, True)

    def test_trace_exhausted(self):
        self.assert_status(self.engine.trace(self.seed), True, False)

    def test_trace_failed(self):
        self.s2.citations.side_effect = RuntimeError("offline")
        outcome = self.engine.trace(self.seed)
        self.assert_status(outcome, False, True)
        self.assertIn("citations lookup failed for [Seed25]", outcome.warnings[0])

    def test_trace_hop_limit_is_not_convergence(self):
        self.s2.citations.return_value = [Paper("next", "Next paper")]
        outcome = self.engine.trace(self.seed, hops=1)
        self.assert_status(outcome, False, False)
        self.assertEqual(outcome.rounds, 1)

    def test_trace_converges_after_frontier_exhausted(self):
        self.s2.citations.side_effect = [[Paper("next", "Next paper")], []]
        outcome = self.engine.trace(self.seed, hops=3)
        self.assert_status(outcome, True, False)
        self.assertEqual(outcome.rounds, 2)

    def test_diagnostics_survive_reopen(self):
        self.s2.citations.side_effect = RuntimeError("offline")
        outcome = self.engine.run("q", ["q"])
        reopened = Store(self.path)
        self.addCleanup(reopened.conn.close)
        stored = reopened.get_search(outcome.search_id)
        self.assertTrue(stored["degraded"])
        self.assertEqual(stored["warnings"], outcome.warnings)

    def test_legacy_database_migration_is_repeatable(self):
        path = Path(self.tmp.name) / "legacy.db"
        with sqlite3.connect(path) as conn:
            conn.executescript(SCHEMA)
            conn.execute("INSERT INTO projects (id, name, created_at) VALUES (1, 'old', 0)")
            conn.execute("INSERT INTO searches (project_id, question, created_at) VALUES (1, 'q', 0)")
        for _ in range(2):
            migrated = Store(path)
            try:
                stored = migrated.get_search(1)
                self.assertFalse(stored["degraded"])
                self.assertFalse(stored["converged"])
                self.assertEqual(stored["warnings"], [])
            finally:
                migrated.conn.close()
