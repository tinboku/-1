import json
import unittest
from unittest import mock

from dls.config import Config
from dls.llm import GeminiConnectorLLM, HeuristicLLM, OpenAIChatLLM, get_llm


class TestFactory(unittest.TestCase):
    def test_gemini_connector_backend(self):
        llm = get_llm(Config(llm_backend="gemini-connector", llm_model="gemini-3.8-flash"))
        self.assertIsInstance(llm, GeminiConnectorLLM)

    def test_heuristic_backend(self):
        llm = get_llm(Config(llm_backend="heuristic"))
        self.assertIs(type(llm), HeuristicLLM)


class TestReflection(unittest.TestCase):
    def setUp(self):
        self.llm = OpenAIChatLLM(Config())
        self.context = {
            "query_history": [{"query": "中文", "result_count": 0}],
            "excluded_papers": [{"title": "排除论文", "reason": "out of scope"}],
            "criteria_coverage": [{"criterion": "中文", "matched_papers": 0}],
        }

    def test_online_prompt_and_stop_reason(self):
        response = {"new_queries": ["新查询"], "stop": True, "reason": "范围已覆盖"}
        with mock.patch.object(self.llm, "_chat", return_value=json.dumps(response)) as chat:
            self.assertEqual(self.llm.reflect(["中文"], [], 1, context=self.context), response)
        prompt = chat.call_args.args[1]
        self.assertEqual(json.loads(prompt.split("Search context:\n")[1]), self.context)
        self.assertIn("required when stopping", chat.call_args.args[0])

    def test_missing_reason_and_malformed_decisions_fall_back(self):
        for response in [
            {"new_queries": [], "stop": True},
            {"new_queries": [], "stop": True, "reason": " "},
            {"new_queries": "bad list", "stop": True, "reason": "done"},
            {"new_queries": [], "stop": "false", "reason": "done"},
        ]:
            with self.subTest(response=response), mock.patch.object(
                self.llm, "_chat", return_value=json.dumps(response)
            ):
                result = self.llm.reflect(["中文"], [], 1, context=self.context)
                self.assertFalse(result["stop"])
                self.assertTrue(result["reason"].strip())

    def test_transport_failure_keeps_offline_interface(self):
        with mock.patch.object(self.llm, "_chat", side_effect=RuntimeError("offline")):
            result = self.llm.reflect(["中文"], [], 2, context=self.context)
        self.assertTrue(result["stop"])
        self.assertTrue(result["reason"])
        self.assertEqual(result, HeuristicLLM().reflect(["中文"], [], 2))


class TestGeminiChatTransport(unittest.TestCase):
    def setUp(self):
        self.llm = GeminiConnectorLLM(
            Config(llm_backend="gemini-connector", llm_model="gemini-3.8-flash")
        )

    def test_chat_parses_helper_output(self):
        fake = mock.Mock(
            returncode=0,
            stdout=json.dumps({"choices": [{"message": {"content": "ready"}}]}),
            stderr="",
        )
        with mock.patch("dls.llm.subprocess.run", return_value=fake) as run:
            out = self.llm._chat("sys", "hi", json_mode=True)
        self.assertEqual(out, "ready")
        payload = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(payload["model"], "gemini-3.8-flash")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["messages"][1]["content"], "hi")

    def test_chat_raises_on_helper_failure(self):
        fake = mock.Mock(returncode=1, stdout="", stderr="boom")
        with mock.patch("dls.llm.subprocess.run", return_value=fake), \
             mock.patch("dls.llm.time.sleep", return_value=None):
            with self.assertRaises(RuntimeError):
                self.llm._chat("sys", "hi")

    def test_chat_retries_then_succeeds(self):
        bad = mock.Mock(returncode=1, stdout="", stderr="stall")
        good = mock.Mock(
            returncode=0,
            stdout=json.dumps({"choices": [{"message": {"content": "ok"}}]}),
            stderr="",
        )
        with mock.patch("dls.llm.subprocess.run", side_effect=[bad, good]) as run, \
             mock.patch("dls.llm.time.sleep", return_value=None):
            out = self.llm._chat("sys", "hi")
        self.assertEqual(out, "ok")
        self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
