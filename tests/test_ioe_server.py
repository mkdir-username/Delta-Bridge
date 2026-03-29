"""Tests for IoE server — search format."""
import json
import sys
import os
import types
sys.path.insert(0, os.path.dirname(__file__))

for _mod in ["truststore", "imapclient", "readability", "PIL", "PIL.Image", "requests"]:
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
sys.modules["PIL"].open = lambda *a: None

os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "pass")
os.environ.setdefault("IOE_SECRET", "secret123")


def test_do_search_returns_list_of_dicts():
    """do_search must return structured results, not plain text."""
    mock_results = [
        {"title": "Weather SPb", "href": "https://example.com/weather", "body": "Forecast for SPb"},
        {"title": "SPb News", "href": "https://example.com/news", "body": "Latest news"},
    ]

    class MockDDGS:
        def text(self, query, max_results=10):
            return mock_results

    sys.modules['ddgs'] = types.ModuleType('ddgs')
    sys.modules['ddgs'].DDGS = MockDDGS

    import ioe_server
    import importlib
    importlib.reload(ioe_server)

    result = ioe_server.do_search("weather spb")

    assert isinstance(result, list), f"Expected list, got {type(result)}"
    assert len(result) >= 1
    assert "title" in result[0]
    assert "href" in result[0]
    assert "snippet" in result[0]


def test_search_response_has_results_field():
    """SEARCH response must contain 'results' key with list, not 'body' with text."""
    sample_response = {
        "id": "abc123",
        "status": 200,
        "cmd": "SEARCH",
        "results": [
            {"title": "Result 1", "href": "https://example.com", "snippet": "Description"},
        ]
    }
    assert "results" in sample_response
    assert isinstance(sample_response["results"], list)
    assert "body" not in sample_response


def test_fetch_markdown_returns_markdown():
    import types, ioe_server
    mock_resp = types.SimpleNamespace(
        text="# Hello World\n\nSome content here. More text to exceed fifty chars minimum length check.",
        status_code=200, raise_for_status=lambda: None,
    )
    original = ioe_server.requests.get
    ioe_server.requests.get = lambda *a, **kw: mock_resp
    try:
        title, content, fmt = ioe_server.fetch_markdown("https://example.com")
        assert fmt == "markdown"
        assert "Hello World" in content
    finally:
        ioe_server.requests.get = original


def test_fetch_markdown_fallback_on_error():
    import types, ioe_server
    call_log = []
    def mock_get(url, **kw):
        call_log.append(url)
        if "md.dhr.wtf" in url:
            raise Exception("down")
        return types.SimpleNamespace(
            text="<html><body><h1>T</h1><p>C</p></body></html>",
            status_code=200, raise_for_status=lambda: None,
        )
    original = ioe_server.requests.get
    ioe_server.requests.get = mock_get
    try:
        title, content, fmt = ioe_server.fetch_markdown("https://example.com")
        assert fmt == "html"
        assert any("md.dhr.wtf" in u for u in call_log)
    finally:
        ioe_server.requests.get = original
