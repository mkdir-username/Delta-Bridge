"""Tests for do_browser_search() and extract action href support."""

import sys
import os
import types

_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "server"))
sys.path.insert(0, os.path.dirname(__file__))

for _mod in [
    "truststore",
    "imapclient",
    "readability",
    "PIL",
    "PIL.Image",
    "requests",
    "trafilatura",
]:
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)
sys.modules["truststore"].inject_into_ssl = lambda: None
sys.modules["imapclient"].IMAPClient = type("IMAPClient", (), {})


class _MockDoc:
    def __init__(self, html=""):
        self._html = html

    def title(self):
        return "Mock Title"

    def summary(self):
        return "<p>Mock content</p>"


sys.modules["readability"].Document = _MockDoc
sys.modules["PIL.Image"] = sys.modules["PIL"]
sys.modules["PIL"].Image = sys.modules["PIL"]
sys.modules["requests"].get = lambda *a, **kw: None
sys.modules["trafilatura"].extract = lambda *a, **kw: None

os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "pass")
os.environ.setdefault("IOE_SECRET", "secret123")

from unittest.mock import patch

from server import do_browser_search


class TestDoBrowserSearch:
    def test_parses_extract_elements_into_results(self):
        mock_resp = {
            "status": 200,
            "results": [
                {"action": "goto", "title": "DuckDuckGo"},
                {
                    "action": "extract",
                    "selector": ".result__a",
                    "elements": [
                        {"text": "Python Tutorial", "href": "https://python.org"},
                        {"text": "Learn Python", "href": "https://learnpython.org"},
                    ],
                    "texts": ["Python Tutorial", "Learn Python"],
                },
            ],
        }
        with patch("server.handle_browser_request", return_value=mock_resp):
            results = do_browser_search("python")
        assert len(results) == 2
        assert results[0]["title"] == "Python Tutorial"
        assert results[0]["href"] == "https://python.org"
        assert results[1]["title"] == "Learn Python"

    def test_error_status_returns_error_result(self):
        mock_resp = {"status": 500, "error": "browser crashed"}
        with patch("server.handle_browser_request", return_value=mock_resp):
            results = do_browser_search("fail")
        assert len(results) == 1
        assert "error" in results[0]["title"].lower()
        assert "browser crashed" in results[0]["snippet"]

    def test_playwright_unavailable(self):
        mock_resp = {"status": 503, "error": "playwright not installed"}
        with patch("server.handle_browser_request", return_value=mock_resp):
            results = do_browser_search("no pw")
        assert len(results) == 1
        assert "playwright" in results[0]["snippet"]

    def test_no_results_returns_fallback(self):
        mock_resp = {
            "status": 200,
            "results": [
                {"action": "goto", "title": "DuckDuckGo"},
                {"action": "extract", "selector": ".result__a", "elements": [], "texts": []},
            ],
        }
        with patch("server.handle_browser_request", return_value=mock_resp):
            results = do_browser_search("xyznonexistent")
        assert len(results) == 1
        assert "no results" in results[0]["title"].lower()

    def test_max_10_results(self):
        elements = [{"text": f"Result {i}", "href": f"https://example.com/{i}"} for i in range(20)]
        mock_resp = {
            "status": 200,
            "results": [
                {"action": "goto", "title": "DuckDuckGo"},
                {
                    "action": "extract",
                    "selector": ".result__a",
                    "elements": elements,
                    "texts": [e["text"] for e in elements],
                },
            ],
        }
        with patch("server.handle_browser_request", return_value=mock_resp):
            results = do_browser_search("many")
        assert len(results) == 10

    def test_exception_returns_error(self):
        with patch("server.handle_browser_request", side_effect=RuntimeError("boom")):
            results = do_browser_search("error")
        assert len(results) == 1
        assert "boom" in results[0]["snippet"]
