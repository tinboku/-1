"""Offline checks of reflection decisions and the state actually supplied to them."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from dls.engine import DeepSearchEngine
from dls.llm import HeuristicLLM
from dls.models import Paper
from dls.store import Store


class TestAdaptiveSearch(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(Path(tmp.name) / "test.db")
        self.addCleanup(self.store.conn.close)
        self.seed = Paper("seed", "中文数据集描述", abstract="中文数据集描述")
        self.excluded = Paper("excluded", "量子纠错", abstract="量子计算")
        self.next = Paper("next", "生成中文数据集描述", abstract="中文数据集描述")
        self.s2 = Mock()
        self.s2.search.return_value = [self.seed, self.excluded]
        self.s2.citations.return_value = []
        self.s2.references.return_value = []
        self.llm = Mock(wraps=HeuristicLLM())
        self.llm.reflect.return_value = {"new_queries": [], "stop": False, "reason": "continue"}
        self.engine = DeepSearchEngine(self.s2, None, self.llm, self.store)

    def test_context_contains_history_exclusions_and_each_criterion(self):
        self.engine.run("中文数据集描述", ["中文数据集描述", "量子实验"])
        context = self.llm.reflect.call_args.kwargs["context"]
        self.assertEqual(len(context["query_history"]), 2)
        self.assertEqual(context["query_history"][0], {
            "query": "中文数据集描述", "source": "semantic_scholar", "round": 0,
            "result_count": 2, "status": "success",
        })
        self.assertEqual(context["excluded_papers"][0]["paper_id"], "excluded")
        self.assertIn("below 55.0", context["excluded_papers"][0]["reason"])
        self.assertIn("matched terms", context["excluded_papers"][0]["reason"])
        self.assertEqual(context["criteria_coverage"], [
            {"criterion": "中文数据集描述", "matched_papers": 1},
            {"criterion": "量子实验", "matched_papers": 0},
        ])

    def test_repeated_queries_are_not_executed_across_rounds(self):
        self.llm.score_matches.side_effect = lambda criteria, papers: [(90, "relevant") for _ in papers]
        self.s2.search.side_effect = [[self.seed], [self.next]]
        self.llm.reflect.return_value = {
            "new_queries": ["  INITIAL   QUERY ", "fresh query", " Fresh   Query "],
            "stop": False, "reason": "explore",
        }
        outcome = self.engine.run("initial query", ["initial query"], max_rounds=3)
        self.assertEqual([c.args[0] for c in self.s2.search.call_args_list],
                         ["initial query", "fresh query"])
        self.assertEqual(outcome.rounds, 2)
        second_context = self.llm.reflect.call_args_list[1].kwargs["context"]
        self.assertEqual(second_context["query_history"][-1]["round"], 1)
        self.assertEqual(second_context["query_history"][-1]["result_count"], 1)
        self.assertEqual(len(self.llm.reflect.call_args_list[0].kwargs["context"]["query_history"]), 1)
        self.assertEqual(len(outcome.query_history), 2)

    def test_stop_reason_in_outcome_with_no_new_candidates(self):
        self.llm.reflect.return_value = {"new_queries": [], "stop": True, "reason": "范围已覆盖"}
        outcome = self.engine.run("中文数据集描述", ["中文数据集描述"])
        self.assertEqual(outcome.stop_reason, "范围已覆盖")
        self.assertTrue(outcome.converged)

    def test_stop_reason_with_new_candidates_and_failure(self):
        self.s2.references.return_value = [self.next]
        self.s2.citations.side_effect = RuntimeError("offline")
        self.llm.reflect.return_value = {"new_queries": [], "stop": True, "reason": "停止扩展"}
        outcome = self.engine.run("中文数据集描述", ["中文数据集描述"])
        self.assertEqual(outcome.stop_reason, "停止扩展")
        self.assertTrue(outcome.degraded)
        self.assertFalse(outcome.converged)
        self.assertEqual(outcome.found, 2)

    def test_failed_query_is_recorded_and_not_retried(self):
        self.s2.search.side_effect = [[self.seed], RuntimeError("offline")]
        self.s2.references.side_effect = [[self.next], []]
        self.llm.reflect.return_value = {"new_queries": ["fresh", " FRESH "],
                                         "stop": False, "reason": "explore"}
        outcome = self.engine.run("中文数据集描述", ["中文数据集描述"], max_rounds=3)
        self.assertEqual(self.s2.search.call_count, 2)
        record = self.llm.reflect.call_args.kwargs["context"]["query_history"][-1]
        self.assertEqual(record["status"], "failed")
        self.assertIsNone(record["result_count"])
        self.assertEqual(record["error"], "offline")
        self.assertTrue(outcome.degraded)
        self.assertFalse(outcome.converged)
        self.assertIn("reflection query search failed", outcome.warnings[0])

    def test_successful_zero_results_differ_from_failure(self):
        self.s2.search.return_value = []
        outcome = self.engine.run("empty", ["empty"])
        self.assertEqual(outcome.query_history[0]["status"], "success")
        self.assertEqual(outcome.query_history[0]["result_count"], 0)
        self.assertFalse(outcome.degraded)

    def test_initial_cross_source_searches_are_preserved(self):
        self.engine.openalex = Mock()
        self.engine.openalex.search.return_value = []
        outcome = self.engine.run("中文数据集描述", ["中文数据集描述"])
        self.assertEqual([r["source"] for r in outcome.query_history],
                         ["semantic_scholar", "openalex"])

