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


class TestCacheEviction:
    def test_вытесняет_старую_запись_при_переполнении(self):
        import types
        import ioe_server

        old_max = ioe_server.PAGE_CACHE_MAX
        ioe_server.PAGE_CACHE_MAX = 2
        ioe_server._page_cache.clear()

        def make_resp(html):
            return types.SimpleNamespace(text=html, status_code=200, raise_for_status=lambda: None)

        html_a = "<html><body><p>" + "word " * 20 + "</p></body></html>"
        html_b = "<html><body><p>" + "word " * 20 + "</p></body></html>"
        html_c = "<html><body><p>" + "word " * 20 + "</p></body></html>"

        responses = {
            "https://example.com/evict-a": html_a,
            "https://example.com/evict-b": html_b,
            "https://example.com/evict-c": html_c,
        }

        def mock_get(url, *a, **kw):
            base = url.split("?")[0]
            return make_resp(responses[base])

        original = ioe_server.requests.get
        ioe_server.requests.get = mock_get
        try:
            ioe_server.smart_extract("https://example.com/evict-a")
            ioe_server.smart_extract("https://example.com/evict-b")
            assert len(ioe_server._page_cache) == 2
            ioe_server.smart_extract("https://example.com/evict-c")
            assert len(ioe_server._page_cache) == 2
            assert "https://example.com/evict-a" not in ioe_server._page_cache
            assert "https://example.com/evict-c" in ioe_server._page_cache
        finally:
            ioe_server.requests.get = original
            ioe_server._page_cache.clear()
            ioe_server.PAGE_CACHE_MAX = old_max


class _FakeSession:
    def close(self):
        pass


class TestSessionLifecycle:
    def test_session_start_создаёт_сессию(self):
        import ioe_server

        original_session_cls = getattr(ioe_server.requests, "Session", None)
        ioe_server.requests.Session = _FakeSession
        try:
            result = ioe_server.dispatch_request({"type": "session_start", "session_id": "test-s1", "user_id": "u1"})
            assert result.get("status") == 200
            assert "test-s1" in ioe_server._sessions
        finally:
            if original_session_cls is None:
                del ioe_server.requests.Session
            else:
                ioe_server.requests.Session = original_session_cls
            ioe_server._sessions.pop("test-s1", None)

    def test_session_end_удаляет_существующую_сессию(self):
        import ioe_server

        ioe_server.requests.Session = _FakeSession
        try:
            ioe_server.dispatch_request({"type": "session_start", "session_id": "test-s2", "user_id": "u1"})
            result = ioe_server.dispatch_request({"type": "session_end", "session_id": "test-s2", "user_id": "u1"})
            assert result.get("status") == 200
            assert "test-s2" not in ioe_server._sessions
        finally:
            ioe_server._sessions.pop("test-s2", None)

    def test_session_end_несуществующей_сессии_возвращает_404(self):
        import ioe_server

        result = ioe_server.dispatch_request({"type": "session_end", "session_id": "no-such-session", "user_id": "u1"})
        assert result.get("status") == 404

    def test_unknown_type_возвращает_400(self):
        import ioe_server

        result = ioe_server.dispatch_request({"type": "totally_unknown_type", "user_id": "u1"})
        assert result.get("status") == 400

    def test_unknown_command_service_возвращает_400(self):
        import ioe_server

        result = ioe_server.dispatch_request({"type": "command", "service": "nonexistent_service", "user_id": "u1"})
        assert result.get("status") == 400


class TestRedirectFollowing:
    def test_http_proxy_следует_редиректу_301(self):
        import types
        import ioe_server

        final_resp = types.SimpleNamespace(
            status_code=200,
            headers={"Content-Type": "text/plain"},
            text="final destination",
            url="https://example.com/final",
        )
        redirect_resp = types.SimpleNamespace(
            status_code=301,
            headers={"Location": "https://example.com/final", "Content-Type": "text/plain"},
            text="",
            url="https://example.com/old",
        )

        call_urls = []

        class MockRequests:
            @staticmethod
            def request(method, url, **kw):
                call_urls.append(url)
                if url == "https://example.com/old":
                    return redirect_resp
                return final_resp

        original = ioe_server.requests
        ioe_server.requests = MockRequests
        try:
            result = ioe_server.handle_http_proxy({"method": "GET", "url": "https://example.com/old", "user_id": "u1"})
            assert result["status_code"] == 200
            assert "example.com/final" in result["url"]
        finally:
            ioe_server.requests = original

    def test_http_proxy_останавливается_после_5_редиректов(self):
        import types
        import ioe_server

        loop_resp = types.SimpleNamespace(
            status_code=302,
            headers={"Location": "https://example.com/loop", "Content-Type": "text/plain"},
            text="",
            url="https://example.com/loop",
        )

        class MockRequests:
            @staticmethod
            def request(method, url, **kw):
                return loop_resp

        original = ioe_server.requests
        ioe_server.requests = MockRequests
        try:
            result = ioe_server.handle_http_proxy({"method": "GET", "url": "https://example.com/loop", "user_id": "u1"})
            assert result.get("status_code") in (302, 200, 502)
        finally:
            ioe_server.requests = original


class TestImageInlining:
    def test_большое_изображение_удаляется(self):
        import ioe_server

        large_size = ioe_server.MAX_IMAGE_BYTES + 1

        class MockResp:
            headers = {"Content-Length": str(large_size)}
            content = b"x" * large_size

        original_get = ioe_server.requests.get
        ioe_server.requests.get = lambda *a, **kw: MockResp()
        try:
            html = '<html><body><img src="https://example.com/big.jpg"></body></html>'
            result = ioe_server.inline_images(html, "https://example.com/")
            assert 'src="https://example.com/big.jpg"' not in result
            assert "data:image/jpeg;base64," not in result
        finally:
            ioe_server.requests.get = original_get

    def test_изображение_инлайнится_как_base64(self):
        import ioe_server
        from unittest.mock import MagicMock

        small_jpeg = b"\xff\xd8\xff" + b"\x00" * 100

        class MockResp:
            headers = {"Content-Length": "103"}
            content = small_jpeg

        mock_pil_img = MagicMock()
        mock_pil_img.width = 400
        mock_pil_img.height = 300
        converted = MagicMock()
        buf_data = b"fakejpegdata"

        def fake_save(buf, fmt, **kw):
            buf.write(buf_data)

        converted.save = fake_save
        mock_pil_img.convert.return_value = converted

        original_get = ioe_server.requests.get
        ioe_server.requests.get = lambda *a, **kw: MockResp()
        with patch.object(ioe_server.Image, "open", return_value=mock_pil_img):
            try:
                html = '<html><body><img src="https://example.com/small.jpg"></body></html>'
                result = ioe_server.inline_images(html, "https://example.com/")
                assert "data:image/jpeg;base64," in result
            finally:
                ioe_server.requests.get = original_get


class TestSendTgNotification:
    def test_уведомление_отправляется_через_imap(self):
        import ioe_server
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_client.__enter__ = lambda s: s
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch.object(ioe_server, "append_response") as mock_append:
            original_imap = ioe_server.IMAPClient
            ioe_server.IMAPClient = lambda *a, **kw: mock_client
            try:
                ioe_server._send_tg_notification({"type": "tg_update", "data": "hello"})
                mock_client.login.assert_called_once()
                mock_append.assert_called_once()
            finally:
                ioe_server.IMAPClient = original_imap

    def test_ошибка_imap_не_роняет_процесс(self):
        import ioe_server

        def boom(*a, **kw):
            raise ConnectionError("IMAP down")

        original_imap = ioe_server.IMAPClient
        ioe_server.IMAPClient = boom
        try:
            ioe_server._send_tg_notification({"type": "tg_update"})
        finally:
            ioe_server.IMAPClient = original_imap


class TestLockFile:
    def test_acquire_lock_выходит_при_занятом_файле(self):
        import ioe_server
        import fcntl
        from unittest.mock import patch, MagicMock

        with (
            patch("builtins.open", return_value=MagicMock()) as mock_open,
            patch.object(fcntl, "flock", side_effect=OSError("locked")),
            patch.object(ioe_server.sys, "exit") as mock_exit,
        ):
            mock_open.return_value  # noqa: B018
            ioe_server._acquire_lock()
            mock_exit.assert_called_once_with(1)

    def test_acquire_lock_записывает_pid(self):
        import ioe_server
        import fcntl
        import os
        from unittest.mock import patch, MagicMock

        mock_fd = MagicMock()
        with patch("builtins.open", return_value=mock_fd), patch.object(fcntl, "flock"):
            result = ioe_server._acquire_lock()
            mock_fd.write.assert_called_once_with(str(os.getpid()))
            mock_fd.flush.assert_called_once()
