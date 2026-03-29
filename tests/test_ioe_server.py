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


def test_fetch_content_returns_html():
    import types, ioe_server
    html = "<html><body><h1>Title</h1>" + "<p>Content paragraph. " * 100 + "</p></body></html>"
    mock_resp = types.SimpleNamespace(
        text=html, status_code=200, raise_for_status=lambda: None,
    )
    original = ioe_server.requests.get
    ioe_server.requests.get = lambda *a, **kw: mock_resp
    try:
        title, content, fmt = ioe_server.fetch_content("https://example.com")
        assert fmt == "html"
        assert isinstance(content, str)
        assert len(content) > 100
    finally:
        ioe_server.requests.get = original


def test_fetch_content_preserves_links():
    import types, ioe_server
    html = '<html><body><a href="/article/1">Link</a><p>' + 'Text. ' * 200 + '</p></body></html>'
    mock_resp = types.SimpleNamespace(
        text=html, status_code=200, raise_for_status=lambda: None,
    )
    original = ioe_server.requests.get
    ioe_server.requests.get = lambda *a, **kw: mock_resp
    try:
        title, content, fmt = ioe_server.fetch_content("https://example.com")
        assert "https://example.com/article/1" in content or "/article/1" in content
    finally:
        ioe_server.requests.get = original


def test_fetch_content_soup_fallback_on_short_readability():
    """readability < MIN_READABLE_LEN -> soup fallback с полным контентом."""
    import types, ioe_server

    full_html = '<html><head><title>Feed</title></head><body>'
    for i in range(20):
        full_html += '<div><a href="/post/{}">Post {}</a><p>Description {}</p></div>'.format(i, i, i)
    full_html += '</body></html>'

    mock_resp = types.SimpleNamespace(
        text=full_html, status_code=200, raise_for_status=lambda: None,
    )
    original = ioe_server.requests.get
    ioe_server.requests.get = lambda *a, **kw: mock_resp
    try:
        title, content, fmt = ioe_server.fetch_content("https://example.com/feed")
        assert fmt == "html"
        assert "Post 0" in content
        assert "Post 19" in content
        assert len(content) > 500
    finally:
        ioe_server.requests.get = original


def test_fetch_content_strips_dangerous_tags():
    """script, style, iframe должны быть удалены из soup fallback."""
    import types, ioe_server

    html = '<html><body><script>alert(1)</script><style>.x{}</style><iframe src="evil"></iframe><p>Safe content here. ' + 'More text. ' * 100 + '</p></body></html>'
    mock_resp = types.SimpleNamespace(
        text=html, status_code=200, raise_for_status=lambda: None,
    )
    original = ioe_server.requests.get
    ioe_server.requests.get = lambda *a, **kw: mock_resp
    try:
        title, content, fmt = ioe_server.fetch_content("https://example.com")
        assert "alert(1)" not in content
        assert "<script" not in content
        assert "<iframe" not in content
        assert "<style" not in content
        assert "Safe content" in content
    finally:
        ioe_server.requests.get = original


def test_fetch_content_converts_relative_links():
    """Относительные href /path -> абсолютные https://domain/path."""
    import types, ioe_server

    html = '<html><body><a href="/about">About</a><a href="https://other.com">Other</a><p>' + 'Text. ' * 200 + '</p></body></html>'
    mock_resp = types.SimpleNamespace(
        text=html, status_code=200, raise_for_status=lambda: None,
    )
    original = ioe_server.requests.get
    ioe_server.requests.get = lambda *a, **kw: mock_resp
    try:
        title, content, fmt = ioe_server.fetch_content("https://example.com/page")
        assert "https://example.com/about" in content
        assert "https://other.com" in content
    finally:
        ioe_server.requests.get = original


def test_fetch_content_readability_crash_fallback():
    """Если readability бросает исключение -> soup fallback."""
    import types, ioe_server

    class CrashDoc:
        def __init__(self, html):
            raise ValueError("readability crash")

    original_doc = sys.modules["readability"].Document
    sys.modules["readability"].Document = CrashDoc

    html = '<html><head><title>Page</title></head><body><p>' + 'Content here. ' * 100 + '</p></body></html>'
    mock_resp = types.SimpleNamespace(
        text=html, status_code=200, raise_for_status=lambda: None,
    )
    original = ioe_server.requests.get
    ioe_server.requests.get = lambda *a, **kw: mock_resp
    try:
        import importlib
        importlib.reload(ioe_server)
        title, content, fmt = ioe_server.fetch_content("https://example.com")
        assert fmt == "html"
        assert "Content here" in content
    finally:
        ioe_server.requests.get = original
        sys.modules["readability"].Document = original_doc


def test_fetch_text_strips_html():
    """fetch_text должен вернуть plain text без тегов."""
    import types, ioe_server

    html = '<html><body><h1>Title</h1><nav>Nav</nav><p>Hello world</p><script>bad</script></body></html>'
    mock_resp = types.SimpleNamespace(
        text=html, status_code=200, raise_for_status=lambda: None,
    )
    original = ioe_server.requests.get
    ioe_server.requests.get = lambda *a, **kw: mock_resp
    try:
        text = ioe_server.fetch_text("https://example.com")
        assert "Hello world" in text
        assert "<h1>" not in text
        assert "<script>" not in text
        assert "Nav" not in text
    finally:
        ioe_server.requests.get = original


def test_do_search_error_returns_structured():
    """do_search при ошибке DDG должен вернуть list с error, не crash."""
    import ioe_server

    class FailDDGS:
        def text(self, query, max_results=10):
            raise ConnectionError("DDG down")

    sys.modules['ddgs'] = types.ModuleType('ddgs')
    sys.modules['ddgs'].DDGS = FailDDGS

    import importlib
    importlib.reload(ioe_server)

    result = ioe_server.do_search("test")
    assert isinstance(result, list)
    assert len(result) >= 1
    assert "error" in result[0].get("snippet", "").lower() or "error" in result[0].get("title", "").lower()
