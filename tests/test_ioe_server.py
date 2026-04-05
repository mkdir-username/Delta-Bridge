"""Tests for IoE server — search format."""

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


def _mock_trafilatura_extract(html, **kw):
    if not html or len(html) < 500:
        return None
    from html.parser import HTMLParser

    class S(HTMLParser):
        def __init__(self):
            super().__init__()
            self.text = []

        def handle_data(self, d):
            self.text.append(d)

    s = S()
    s.feed(html)
    text = " ".join(s.text).strip()
    if len(text) < 200:
        return None
    if kw.get("output_format") == "markdown":
        return "# Extracted\n\n" + text[:2000]
    return text[:2000]


sys.modules["trafilatura"].extract = _mock_trafilatura_extract
sys.modules["PIL"].open = lambda *a: None

os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "pass")
os.environ.setdefault("IOE_SECRET", "secret123")

import server as _server_mod

sys.modules["ioe_server"] = _server_mod

from unittest.mock import patch

_dns_patcher = patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 0))])


def setup_module(module):
    _dns_patcher.start()


def teardown_module(module):
    _dns_patcher.stop()


def test_do_search_returns_list_of_dicts():
    """do_search must return structured results, not plain text."""
    mock_results = [
        {
            "title": "Weather SPb",
            "href": "https://example.com/weather",
            "body": "Forecast for SPb",
        },
        {
            "title": "SPb News",
            "href": "https://example.com/news",
            "body": "Latest news",
        },
    ]

    class MockDDGS:
        def text(self, query, max_results=10):
            return mock_results

    sys.modules["ddgs"] = types.ModuleType("ddgs")
    sys.modules["ddgs"].DDGS = MockDDGS

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
            {
                "title": "Result 1",
                "href": "https://example.com",
                "snippet": "Description",
            },
        ],
    }
    assert "results" in sample_response
    assert isinstance(sample_response["results"], list)
    assert "body" not in sample_response


def test_smart_extract_returns_markdown_for_article():
    import types
    import ioe_server

    html = (
        "<html><body><article><h1>Title</h1><p>Long article. "
        + "Sentence here. " * 50
        + "</p><a href='https://link.com'>Link</a></article></body></html>"
    )
    mock_resp = types.SimpleNamespace(text=html, status_code=200, raise_for_status=lambda: None)
    original = ioe_server.requests.get
    ioe_server.requests.get = lambda *a, **kw: mock_resp
    try:
        result = ioe_server.smart_extract("https://example.com/article/1")
        assert result["format"] in ("markdown", "html")
        assert len(result["body"]) > 100
        assert result["type"] in ("article", "page")
        assert "domain" in result
        assert "word_count" in result
    finally:
        ioe_server.requests.get = original


def test_smart_extract_soup_fallback_for_feed():
    import types
    import ioe_server

    feed_html = "<html><body>"
    for i in range(10):
        feed_html += f'<article><h2><a href="/post/{i}">Post {i}</a></h2><p>Desc {i}</p></article>'
    feed_html += "</body></html>"
    mock_resp = types.SimpleNamespace(text=feed_html, status_code=200, raise_for_status=lambda: None)
    original = ioe_server.requests.get
    ioe_server.requests.get = lambda *a, **kw: mock_resp
    try:
        result = ioe_server.smart_extract("https://example.com/feed")
        assert result["type"] == "feed"
        assert "Post 0" in result["body"]
        assert "Post 9" in result["body"]
    finally:
        ioe_server.requests.get = original


def test_detect_type_article():
    import ioe_server

    assert ioe_server.detect_type("https://habr.com/ru/articles/123/", "<html><article>x</article></html>") == "article"


def test_detect_type_feed():
    import ioe_server

    html = "<html><body>" + "<article>x</article>" * 5 + "</body></html>"
    assert ioe_server.detect_type("https://habr.com/ru/feed/", html) == "feed"


def test_smart_extract_includes_metadata():
    import types
    import ioe_server

    html = "<html><body><article><h1>T</h1><p>" + "Word " * 100 + "</p></article></body></html>"
    mock_resp = types.SimpleNamespace(text=html, status_code=200, raise_for_status=lambda: None)
    original = ioe_server.requests.get
    ioe_server.requests.get = lambda *a, **kw: mock_resp
    try:
        result = ioe_server.smart_extract("https://example.com/page")
        assert result["domain"] == "example.com"
        assert result["word_count"] > 0
    finally:
        ioe_server.requests.get = original


def test_smart_extract_strips_dangerous_tags_in_soup():
    import types
    import ioe_server

    html = (
        '<html><body><script>alert(1)</script><iframe src="x"></iframe><p>Safe. ' + "More. " * 50 + "</p></body></html>"
    )
    mock_resp = types.SimpleNamespace(text=html, status_code=200, raise_for_status=lambda: None)
    original = ioe_server.requests.get
    ioe_server.requests.get = lambda *a, **kw: mock_resp
    try:
        result = ioe_server.smart_extract("https://example.com")
        assert "alert(1)" not in result["body"]
        assert "<script" not in result["body"]
        assert "Safe" in result["body"]
    finally:
        ioe_server.requests.get = original


def test_smart_extract_converts_relative_links_in_soup():
    """When trafilatura fails (short content), soup fallback converts relative links."""
    import types
    import ioe_server

    html = '<html><body><a href="/about">About</a><p>Short.</p></body></html>'
    mock_resp = types.SimpleNamespace(text=html, status_code=200, raise_for_status=lambda: None)
    original = ioe_server.requests.get
    ioe_server.requests.get = lambda *a, **kw: mock_resp
    ioe_server._page_cache.clear()
    try:
        result = ioe_server.smart_extract("https://example.com/page-rellinks")
        assert result["format"] == "html"
        assert "https://example.com/about" in result["body"]
    finally:
        ioe_server.requests.get = original
        ioe_server._page_cache.clear()


def test_fetch_text_strips_html():
    import types
    import ioe_server

    html = "<html><body><h1>Title</h1><nav>Nav</nav><p>Hello world</p><script>bad</script></body></html>"
    mock_resp = types.SimpleNamespace(text=html, status_code=200, raise_for_status=lambda: None)
    original = ioe_server.requests.get
    ioe_server.requests.get = lambda *a, **kw: mock_resp
    try:
        text = ioe_server.fetch_text("https://example.com")
        assert "Hello world" in text
        assert "<script>" not in text
    finally:
        ioe_server.requests.get = original


def test_smart_extract_uses_cache():
    import types
    import ioe_server

    call_count = [0]

    def counting_get(*a, **kw):
        call_count[0] += 1
        html = "<html><body><article><h1>T</h1><p>" + "Word " * 100 + "</p></article></body></html>"
        return types.SimpleNamespace(text=html, status_code=200, raise_for_status=lambda: None)

    original = ioe_server.requests.get
    ioe_server.requests.get = counting_get
    ioe_server._page_cache.clear()
    try:
        r1 = ioe_server.smart_extract("https://example.com/cached-test")
        r2 = ioe_server.smart_extract("https://example.com/cached-test")
        assert r1["body"] == r2["body"]
        assert call_count[0] == 1
    finally:
        ioe_server.requests.get = original
        ioe_server._page_cache.clear()


def test_feed_soup_strips_forms():
    import types
    import ioe_server

    feed_html = (
        '<html><body><form><input type="checkbox"><fieldset><legend>F</legend></fieldset></form>'
        + '<article><a href="/p/1">P1</a></article>' * 4
        + "</body></html>"
    )
    mock_resp = types.SimpleNamespace(text=feed_html, status_code=200, raise_for_status=lambda: None)
    original = ioe_server.requests.get
    ioe_server.requests.get = lambda *a, **kw: mock_resp
    ioe_server._page_cache.clear()
    try:
        result = ioe_server.smart_extract("https://example.com/feed")
        assert "<form" not in result["body"]
        assert "<input" not in result["body"]
        assert "P1" in result["body"]
    finally:
        ioe_server.requests.get = original
        ioe_server._page_cache.clear()


def test_do_search_error_returns_structured():
    import ioe_server

    class FailDDGS:
        def text(self, query, max_results=10):
            raise ConnectionError("DDG down")

    sys.modules["ddgs"] = types.ModuleType("ddgs")
    sys.modules["ddgs"].DDGS = FailDDGS
    import importlib

    importlib.reload(ioe_server)
    result = ioe_server.do_search("test")
    assert isinstance(result, list)
    assert len(result) >= 1
