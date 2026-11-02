import json
import unittest
from unittest import mock

from dls.config import Config
from dls.llm import GeminiConnectorLLM, HeuristicLLM, get_llm


class TestFactory(unittest.TestCase):
    def test_gemini_connector_backend(self):
        llm = get_llm(Config(llm_backend="gemini-connector", llm_model="gemini-3.8-flash"))
        self.assertIsInstance(llm, GeminiConnectorLLM)

    def test_heuristic_backend(self):
        llm = get_llm(Config(llm_backend="heuristic"))
        self.assertIs(type(llm), HeuristicLLM)


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
