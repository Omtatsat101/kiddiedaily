"""Offline regression tests: all HTTP calls are mocked, no secrets required."""
import base64
import hashlib
import importlib.util
import json
import sys
import types
import unittest
from unittest.mock import Mock, patch

# Allow these isolated tests to run without installing dependencies.
if importlib.util.find_spec("requests") is None:
    sys.modules["requests"] = types.SimpleNamespace(get=Mock(), post=Mock(), put=Mock())
import truth_verify as tv


def response(data=None, content=b"", status=200):
    return Mock(status_code=status, content=content, json=Mock(return_value=data))


def encoded(value):
    return {"encoding": "base64", "content": base64.b64encode(value).decode(), "sha": "sha"}


class VerifierTests(unittest.TestCase):
    def test_small_content_unchanged(self):
        data = encoded(b'{"articles": []}')
        with patch.object(tv.requests, "get", return_value=response(data)) as get:
            self.assertEqual(tv.gh_get("manifest.json"), data)
            self.assertEqual(get.call_count, 1)

    def test_large_manifest_raw_fallback(self):
        content = json.dumps({"articles": [], "padding": "x" * 1_100_000}).encode()
        sha = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        with patch.object(tv.requests, "get", side_effect=[
            response({"encoding": "none", "content": "", "sha": sha}),
            response(content=content),
        ]) as get:
            data = tv.gh_get("manifest.json")
            self.assertEqual(json.loads(base64.b64decode(data["content"]))["articles"], [])
            self.assertEqual(data["sha"], sha)
            self.assertEqual(get.call_args.kwargs["headers"]["Accept"], "application/vnd.github.raw+json")
            self.assertEqual(get.call_args.args[0], get.call_args_list[0].args[0])

    def test_changed_content_rejected(self):
        with patch.object(tv.requests, "get", side_effect=[
            response({"encoding": "none", "sha": "wrong"}), response(content=b"changed"),
        ]):
            with self.assertRaises(ValueError):
                tv.gh_get("manifest.json")

    def test_404_remains_missing(self):
        with patch.object(tv.requests, "get", return_value=response(status=404)):
            self.assertIsNone(tv.gh_get("missing"))

    def test_raw_http_failure_propagates(self):
        failed = response()
        failed.raise_for_status.side_effect = RuntimeError("HTTP error")
        with patch.object(tv.requests, "get", side_effect=[response({"encoding": "none"}), failed]):
            with self.assertRaises(RuntimeError):
                tv.gh_get("manifest.json")

    def test_missing_key_stops_before_io(self):
        for key in ("", "  "):
            with self.subTest(key=key), patch.object(tv, "GITHUB_TOKEN", "test"), patch.object(tv, "ANTHROPIC_API_KEY", key), patch.object(tv, "gh_get") as get, patch.object(tv, "gh_put") as put:
                self.assertEqual(tv.run(), 1)
                self.assertIsNone(tv.claude_analyze("", "", 1, 0))
                get.assert_not_called()
                put.assert_not_called()

    def analyze(self, value):
        with patch.object(tv, "ANTHROPIC_API_KEY", "test"), patch.object(tv.requests, "post", return_value=response({"content": [{"text": value}]})):
            return tv.claude_analyze("title", "text", 1, 0)

    def test_invalid_ai_output_has_no_default(self):
        for text in ("not json", "{}", '{"truth_confidence":65,"kid_safe_rating":"G"}'):
            self.assertIsNone(self.analyze(text))

    def test_valid_ai_output_retained(self):
        result = {"truth_confidence": 75, "kid_safe_rating": "PG", "claims": ["A claim"], "bias_signals": [], "missing_context": None}
        self.assertEqual(self.analyze(json.dumps(result)), result)
        for key, value in (("truth_confidence", True), ("truth_confidence", 999), ("kid_safe_rating", "invalid"), ("claims", []), ("claims", [""]), ("claims", ["  "])):
            self.assertIsNone(self.analyze(json.dumps({**result, key: value})))

    def test_provider_error_returns_unavailable(self):
        with patch.object(tv, "ANTHROPIC_API_KEY", "test"), patch.object(tv.requests, "post", side_effect=RuntimeError("provider down")):
            self.assertIsNone(tv.claude_analyze("", "", 1, 0))

    def test_model_text_is_escaped(self):
        result = {"truth_confidence": 75, "kid_safe_rating": "PG", "claims": ['<img src=x onerror="alert(1)">'], "bias_signals": ["<script>alert(1)</script>"], "missing_context": "<svg onload=alert(1)> & context"}
        html = tv.build_truth_html(result)
        self.assertNotIn("<img", html)
        self.assertNotIn("<script", html)
        self.assertNotIn("<svg", html)
        self.assertIn("&lt;img", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&amp; context", html)

    def test_write_failure_makes_run_fail(self):
        manifest = encoded(json.dumps({"articles": [{"date": tv.TODAY, "slug": "article.html"}]}).encode())
        result = {"truth_confidence": 75, "kid_safe_rating": "PG", "claims": ["A claim"], "bias_signals": [], "missing_context": None}
        for ok in (True, False):
            with self.subTest(ok=ok), patch.object(tv, "GITHUB_TOKEN", "test"), patch.object(tv, "ANTHROPIC_API_KEY", "test"), patch.object(tv, "gh_get", side_effect=[manifest, encoded(b"<body>Article</body>")]), patch.object(tv, "claude_analyze", return_value=result), patch.object(tv, "gh_put", return_value=ok) as put, patch.object(tv.time, "sleep"):
                self.assertEqual(tv.run(), 0 if ok else 1)
                put.assert_called_once()

    def test_existing_badges_remain_untouched(self):
        manifest = encoded(json.dumps({"articles": [{"date": tv.TODAY, "slug": "article.html"}]}).encode())
        html = b"<body><!-- TRUTH_CHECK_START -->Existing<!-- TRUTH_CHECK_END --></body>"
        with patch.object(tv, "GITHUB_TOKEN", "test"), patch.object(tv, "ANTHROPIC_API_KEY", "test"), patch.object(tv, "gh_get", side_effect=[manifest, encoded(html)]), patch.object(tv, "claude_analyze") as analyze, patch.object(tv, "gh_put") as put:
            self.assertEqual(tv.run(), 0)
            analyze.assert_not_called()
            put.assert_not_called()

    def test_failed_analysis_never_writes_badge(self):
        manifest = encoded(json.dumps({"articles": [{"date": tv.TODAY, "slug": "article.html"}]}).encode())
        with patch.object(tv, "GITHUB_TOKEN", "test"), patch.object(tv, "ANTHROPIC_API_KEY", "test"), patch.object(tv, "gh_get", side_effect=[manifest, encoded(b"<body>Article</body>")]), patch.object(tv, "claude_analyze", return_value=None), patch.object(tv, "gh_put") as put, patch.object(tv.time, "sleep"):
            self.assertEqual(tv.run(), 1)
            put.assert_not_called()


if __name__ == "__main__":
    unittest.main()
