"""Mocked provider tests; no OpenAI key, Ollama server, or network required."""
import io
import json
import os
import unittest
from unittest.mock import patch

from jobbot import llm
from jobbot.cli import _llm, build_parser


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class ProviderTests(unittest.TestCase):
    def test_ollama_remains_default(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "unused"}):
            with patch.object(llm.LLM, "available", return_value=True):
                model = llm.LLM(provider="ollama")
        self.assertEqual((model.provider, model.model), ("ollama", llm.DEFAULT_MODEL))

    def test_openai_requires_key_and_does_not_fallback(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            model = llm.LLM(provider="openai")
            self.assertFalse(model.enabled)
            with self.assertRaises(RuntimeError):
                model.chat("system", "user")
        self.assertEqual(model.provider, "openai")

    def test_openai_json_request_and_response(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["timeout"] = timeout
            captured["headers"] = dict(req.header_items())
            captured["payload"] = json.loads(req.data)
            return Response(json.dumps({"choices": [{"message": {"content": '{"approved": true, "reviewed_field_ids": ["f1"], "issues": []}'}}]}).encode())

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-secret-not-real"}):
            with patch.object(llm.urllib.request, "urlopen", side_effect=fake_urlopen):
                model = llm.LLM(provider="openai", model="gpt-4.1-mini")
                result = model.chat("Review form fields", "private resume data", as_json=True, temperature=0, timeout=9)
        self.assertEqual(captured["url"], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(captured["timeout"], 9)
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-secret-not-real")
        self.assertEqual(captured["payload"]["response_format"], {"type": "json_object"})
        self.assertEqual(captured["payload"]["messages"][1]["content"], "private resume data")
        self.assertEqual(result["reviewed_field_ids"], ["f1"])

    def test_same_field_context_reaches_both_providers(self):
        context = {"instructions": "Describe the most recent gap.",
                   "parent": {"question": "Did you have an employment gap?", "answer": "Yes"}}
        response = json.dumps({"basis": "fact", "answer": "I took time off to study."})
        for provider in ("ollama", "openai"):
            with self.subTest(provider=provider), patch.dict(os.environ, {"OPENAI_API_KEY": "placeholder"}):
                payload = {}
                def respond(req, timeout):
                    payload.update(json.loads(req.data))
                    body = {"choices": [{"message": {"content": response}}]} if provider == "openai" else {
                        "message": {"content": response}}
                    return Response(json.dumps(body).encode())
                with patch.object(llm.LLM, "available", return_value=True), patch.object(
                        llm.urllib.request, "urlopen", side_effect=respond):
                    result = llm.LLM(provider=provider).answer(
                        "If yes, please explain", "textarea", [], {}, "", context=context)
                self.assertEqual(result["answer"], "I took time off to study.")
                self.assertIn(json.dumps(context), payload["messages"][1]["content"])

    def test_openai_text_response(self):
        def fake_urlopen(req, timeout):
            return Response(json.dumps({"choices": [{"message": {"content": "  A grounded answer  "}}]}).encode())
        with patch.dict(os.environ, {"OPENAI_API_KEY": "placeholder"}):
            with patch.object(llm.urllib.request, "urlopen", side_effect=fake_urlopen):
                self.assertEqual(llm.LLM(provider="openai").chat("s", "u"), "A grounded answer")

    def test_openai_invalid_json_fails_closed(self):
        def fake_urlopen(req, timeout):
            return Response(json.dumps({"choices": [{"message": {"content": "not json"}}]}).encode())
        with patch.dict(os.environ, {"OPENAI_API_KEY": "placeholder"}):
            with patch.object(llm.urllib.request, "urlopen", side_effect=fake_urlopen):
                with self.assertRaises(json.JSONDecodeError):
                    llm.LLM(provider="openai").chat("s", "u", as_json=True)

    def test_cli_openai_override_without_ollama(self):
        args = build_parser().parse_args(["rank", "--llm", "openai"])
        with patch.dict(os.environ, {"OPENAI_API_KEY": "placeholder"}):
            model = _llm(args)
        self.assertTrue(model.enabled)
        self.assertEqual(model.provider, "openai")
        self.assertEqual(model.model, llm.OPENAI_MODEL)

    def test_cli_none_disables_model_even_with_key(self):
        args = build_parser().parse_args(["rank", "--llm", "none"])
        with patch.dict(os.environ, {"OPENAI_API_KEY": "placeholder"}):
            self.assertFalse(_llm(args).enabled)


if __name__ == "__main__":
    unittest.main()
