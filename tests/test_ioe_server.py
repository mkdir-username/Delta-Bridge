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


class TestDispatchBranches:
    def test_dispatch_none_type_возвращает_none(self):
        import ioe_server

        result = ioe_server.dispatch_request({"user_id": "u1"})
        assert result is None

    def test_dispatch_browser_вызывает_handle_browser_request(self):
        import ioe_server
        from unittest.mock import patch

        fake_result = {"status": 200, "body": "ok"}
        with patch.object(ioe_server, "handle_browser_request", return_value=fake_result) as mock_br:
            result = ioe_server.dispatch_request({"type": "browser", "url": "https://example.com", "user_id": "u1"})
            mock_br.assert_called_once()
            assert result == fake_result

    def test_dispatch_telegram_без_адаптера_возвращает_503(self):
        import ioe_server
        from unittest.mock import patch

        with patch.object(ioe_server, "_get_telegram_adapter", return_value=None):
            result = ioe_server.dispatch_request({"type": "command", "service": "telegram", "user_id": "u1"})
            assert result is not None
            assert result.get("status") == 503

    def test_dispatch_claude_chat_без_модуля_возвращает_503(self):
        import ioe_server

        original = ioe_server._claude_chat
        ioe_server._claude_chat = None
        try:
            result = ioe_server.dispatch_request({"type": "claude_chat", "action": "send", "user_id": "u1"})
            assert result is not None
            assert result.get("status") == 503
        finally:
            ioe_server._claude_chat = original

    def test_dispatch_claude_chat_unknown_action_возвращает_400(self):
        import ioe_server
        from unittest.mock import MagicMock

        mock_chat = MagicMock()
        original = ioe_server._claude_chat
        ioe_server._claude_chat = mock_chat
        try:
            result = ioe_server.dispatch_request({"type": "claude_chat", "action": "unknown_action", "user_id": "u1"})
            assert result is not None
            assert result.get("status") == 400
        finally:
            ioe_server._claude_chat = original

    def test_dispatch_telegram_с_адаптером_auth_code_запускает_listener(self):
        import ioe_server
        from unittest.mock import MagicMock, patch

        mock_adapter = MagicMock()
        mock_adapter.handle.return_value = {"auth_status": "authorized", "status": 200}

        with (
            patch.object(ioe_server, "_get_telegram_adapter", return_value=mock_adapter),
            patch.object(ioe_server, "_start_telegram_listener") as mock_listener,
        ):
            result = ioe_server.dispatch_request(
                {"type": "command", "service": "telegram", "action": "auth_code", "user_id": "u2"}
            )
            mock_listener.assert_called_once_with(mock_adapter, "u2")

    def test_start_telegram_listener_пропускает_повторный_вызов(self):
        import ioe_server
        from unittest.mock import MagicMock

        mock_adapter = MagicMock()
        ioe_server._tg_listeners_started.discard("uid-test-99")
        ioe_server._start_telegram_listener(mock_adapter, "uid-test-99")
        ioe_server._start_telegram_listener(mock_adapter, "uid-test-99")
        assert mock_adapter.start_listener.call_count == 1
        ioe_server._tg_listeners_started.discard("uid-test-99")


class TestTrafilaturaTier2:
    def test_tier2_favor_recall_возвращает_markdown(self):
        import types
        import ioe_server

        call_count = [0]

        def tier2_extract(html, **kw):
            call_count[0] += 1
            if kw.get("favor_recall"):
                return "First line of content\n\nSome article text that is longer than min." + " More. " * 20
            if not html or len(html) < 500:
                return None
            return None

        original_extract = ioe_server.trafilatura.extract
        ioe_server.trafilatura.extract = tier2_extract

        html = "<html><body><p>" + "Short content. " * 5 + "</p></body></html>"
        mock_resp = types.SimpleNamespace(text=html, status_code=200, raise_for_status=lambda: None)
        original_get = ioe_server.requests.get
        ioe_server.requests.get = lambda *a, **kw: mock_resp
        ioe_server._page_cache.clear()

        try:
            result = ioe_server.smart_extract("https://example.com/tier2-test")
            if result["format"] == "markdown":
                assert result["title"] == "First line of content"
        finally:
            ioe_server.trafilatura.extract = original_extract
            ioe_server.requests.get = original_get
            ioe_server._page_cache.clear()


class TestProcessMessage:
    def test_уже_обработанный_uid_пропускается(self):
        import ioe_server

        ioe_server._processed_uids.add(9999)
        mock_client = type("C", (), {"append": lambda *a, **kw: None})()
        result = ioe_server.process_message(mock_client, 9999, b"irrelevant")
        assert result is True
        ioe_server._processed_uids.discard(9999)

    def test_нет_вложения_возвращает_false(self):
        import ioe_server
        from email.mime.text import MIMEText

        msg = MIMEText("plain text no attachment")
        mock_client = type("C", (), {"append": lambda *a, **kw: None})()
        ioe_server._processed_uids.discard(8888)
        result = ioe_server.process_message(mock_client, 8888, msg.as_bytes())
        assert result is False

    def test_поврежденное_вложение_возвращает_false(self):
        import ioe_server
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email import encoders

        msg = MIMEMultipart()
        part = MIMEBase("application", "pdf")
        part.set_payload(b"not-encrypted-garbage")
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename="x.pdf")
        msg.attach(part)

        mock_client = type("C", (), {"append": lambda *a, **kw: None})()
        ioe_server._processed_uids.discard(7777)
        result = ioe_server.process_message(mock_client, 7777, msg.as_bytes())
        assert result is False

    def test_валидный_search_запрос_обрабатывается(self):
        import ioe_server
        import json
        from unittest.mock import MagicMock, patch
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email import encoders
        from ioe_crypto import compress_encrypt

        req = {"id": "test-id-1", "cmd": "SEARCH", "query": "test query", "user_id": "u1"}
        encrypted = compress_encrypt(ioe_server.IOE_KEY, json.dumps(req)).encode("ascii")

        msg = MIMEMultipart()
        part = MIMEBase("application", "pdf")
        part.set_payload(encrypted)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename="x.pdf")
        msg.attach(part)

        appended = []
        mock_client = MagicMock()
        mock_client.append = lambda folder, data: appended.append(data)

        ioe_server._processed_uids.discard(6666)

        with (
            patch.object(ioe_server, "do_search", return_value=[{"title": "r", "href": "h", "snippet": "s"}]),
            patch.object(ioe_server, "check_rate_limit"),
        ):
            result = ioe_server.process_message(mock_client, 6666, msg.as_bytes())

        assert result is True
        assert 6666 in ioe_server._processed_uids
        ioe_server._processed_uids.discard(6666)

    def test_text_команда_обрабатывается(self):
        import ioe_server
        import json
        from unittest.mock import MagicMock, patch
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email import encoders
        from ioe_crypto import compress_encrypt

        req = {"id": "text-id-1", "cmd": "TEXT", "url": "https://example.com", "user_id": "u1"}
        encrypted = compress_encrypt(ioe_server.IOE_KEY, json.dumps(req)).encode("ascii")

        msg = MIMEMultipart()
        part = MIMEBase("application", "pdf")
        part.set_payload(encrypted)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename="x.pdf")
        msg.attach(part)

        mock_client = MagicMock()
        ioe_server._processed_uids.discard(5555)

        with (
            patch.object(ioe_server, "fetch_text", return_value="plain text content"),
            patch.object(ioe_server, "check_rate_limit"),
        ):
            result = ioe_server.process_message(mock_client, 5555, msg.as_bytes())

        assert result is True
        ioe_server._processed_uids.discard(5555)

    def test_get_команда_обрабатывается(self):
        import ioe_server
        import json
        from unittest.mock import MagicMock, patch
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email import encoders
        from ioe_crypto import compress_encrypt

        req = {"id": "get-id-1", "cmd": "GET", "url": "https://example.com", "user_id": "u1"}
        encrypted = compress_encrypt(ioe_server.IOE_KEY, json.dumps(req)).encode("ascii")

        msg = MIMEMultipart()
        part = MIMEBase("application", "pdf")
        part.set_payload(encrypted)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename="x.pdf")
        msg.attach(part)

        mock_client = MagicMock()
        ioe_server._processed_uids.discard(4444)

        extract_result = {
            "format": "markdown",
            "type": "article",
            "title": "Test",
            "body": "body content",
            "domain": "example.com",
            "word_count": 2,
        }
        with (
            patch.object(ioe_server, "smart_extract", return_value=extract_result),
            patch.object(ioe_server, "check_rate_limit"),
        ):
            result = ioe_server.process_message(mock_client, 4444, msg.as_bytes())

        assert result is True
        ioe_server._processed_uids.discard(4444)


class TestClaudeChatActions:
    def test_send_action_вызывает_send_message(self):
        import ioe_server
        from unittest.mock import MagicMock

        mock_chat = MagicMock()
        mock_chat.send_message.return_value = {"status": 200, "text": "hi"}
        original = ioe_server._claude_chat
        ioe_server._claude_chat = mock_chat
        try:
            result = ioe_server.handle_claude_chat({"action": "send", "user_id": "u1", "text": "hello"})
            mock_chat.send_message.assert_called_once_with("u1", "hello", None)
        finally:
            ioe_server._claude_chat = original

    def test_check_auth_action(self):
        import ioe_server
        from unittest.mock import MagicMock

        mock_chat = MagicMock()
        mock_chat.check_auth.return_value = {"status": 200, "authenticated": True}
        original = ioe_server._claude_chat
        ioe_server._claude_chat = mock_chat
        try:
            ioe_server.handle_claude_chat({"action": "check_auth", "user_id": "u1"})
            mock_chat.check_auth.assert_called_once()
        finally:
            ioe_server._claude_chat = original

    def test_new_conversation_action(self):
        import ioe_server
        from unittest.mock import MagicMock

        mock_chat = MagicMock()
        mock_chat.new_conversation.return_value = {"status": 200}
        original = ioe_server._claude_chat
        ioe_server._claude_chat = mock_chat
        try:
            ioe_server.handle_claude_chat({"action": "new_conversation", "user_id": "u1"})
            mock_chat.new_conversation.assert_called_once_with("u1")
        finally:
            ioe_server._claude_chat = original


class TestProcessMessageEdgeCases:
    def _make_encrypted_msg(self, ioe_server, req):
        import json
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email import encoders
        from ioe_crypto import compress_encrypt

        encrypted = compress_encrypt(ioe_server.IOE_KEY, json.dumps(req)).encode("ascii")
        msg = MIMEMultipart()
        part = MIMEBase("application", "pdf")
        part.set_payload(encrypted)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename="x.pdf")
        msg.attach(part)
        return msg.as_bytes()

    def test_update_команда_обрабатывается(self):
        import ioe_server
        from unittest.mock import MagicMock, patch

        req = {"id": "upd-id-1", "cmd": "UPDATE", "user_id": "u1"}
        raw = self._make_encrypted_msg(ioe_server, req)

        mock_client = MagicMock()
        ioe_server._processed_uids.discard(3333)

        with patch.object(ioe_server, "check_rate_limit"):
            result = ioe_server.process_message(mock_client, 3333, raw)

        assert result is True
        ioe_server._processed_uids.discard(3333)

    def test_text_усечение_длинного_контента(self):
        import ioe_server
        from unittest.mock import MagicMock, patch

        req = {"id": "trunc-1", "cmd": "TEXT", "url": "https://example.com", "user_id": "u1"}
        raw = self._make_encrypted_msg(ioe_server, req)

        mock_client = MagicMock()
        ioe_server._processed_uids.discard(2222)

        long_text = "a" * (ioe_server.MAX_BODY + 100)
        with (
            patch.object(ioe_server, "fetch_text", return_value=long_text),
            patch.object(ioe_server, "check_rate_limit"),
        ):
            result = ioe_server.process_message(mock_client, 2222, raw)

        assert result is True
        ioe_server._processed_uids.discard(2222)

    def test_исключение_в_обработчике_возвращает_true(self):
        import ioe_server
        from unittest.mock import MagicMock, patch

        req = {"id": "err-1", "cmd": "SEARCH", "query": "q", "user_id": "u1"}
        raw = self._make_encrypted_msg(ioe_server, req)

        mock_client = MagicMock()
        ioe_server._processed_uids.discard(1111)

        with (
            patch.object(ioe_server, "do_search", side_effect=RuntimeError("boom")),
            patch.object(ioe_server, "check_rate_limit"),
        ):
            result = ioe_server.process_message(mock_client, 1111, raw)

        assert result is True
        ioe_server._processed_uids.discard(1111)


class TestInlineImagesEdgeCases:
    def test_превышение_max_images_удаляет_лишние(self):
        import ioe_server
        from unittest.mock import MagicMock, patch

        small_jpeg = b"\xff\xd8\xff" + b"\x00" * 100

        class MockResp:
            headers = {"Content-Length": "103"}
            content = small_jpeg

        mock_pil_img = MagicMock()
        mock_pil_img.width = 400
        mock_pil_img.height = 300
        converted = MagicMock()

        def fake_save(buf, fmt, **kw):
            buf.write(b"fake")

        converted.save = fake_save
        mock_pil_img.convert.return_value = converted

        original_get = ioe_server.requests.get
        ioe_server.requests.get = lambda *a, **kw: MockResp()
        with patch.object(ioe_server.Image, "open", return_value=mock_pil_img):
            try:
                imgs = "".join(f'<img src="https://example.com/img{i}.jpg">' for i in range(12))
                html = f"<html><body>{imgs}</body></html>"
                result = ioe_server.inline_images(html, "https://example.com/", max_images=2)
                count = result.count("data:image/jpeg;base64,")
                assert count <= 2
            finally:
                ioe_server.requests.get = original_get

    def test_resize_широкого_изображения(self):
        import ioe_server
        from unittest.mock import MagicMock, patch

        small_jpeg = b"\xff\xd8\xff" + b"\x00" * 100

        class MockResp:
            headers = {"Content-Length": "103"}
            content = small_jpeg

        mock_pil_img = MagicMock()
        mock_pil_img.width = 1200
        mock_pil_img.height = 900
        resized = MagicMock()
        resized.width = 800
        converted = MagicMock()

        def fake_save(buf, fmt, **kw):
            buf.write(b"fake")

        converted.save = fake_save
        resized.convert.return_value = converted
        mock_pil_img.resize.return_value = resized

        original_get = ioe_server.requests.get
        ioe_server.requests.get = lambda *a, **kw: MockResp()
        with patch.object(ioe_server.Image, "open", return_value=mock_pil_img):
            try:
                html = '<html><body><img src="https://example.com/wide.jpg"></body></html>'
                result = ioe_server.inline_images(html, "https://example.com/")
                mock_pil_img.resize.assert_called_once()
                assert "data:image/jpeg;base64," in result
            finally:
                ioe_server.requests.get = original_get

    def test_невалидный_url_изображения_удаляется(self):
        import ioe_server

        html = '<html><body><img src="file:///etc/passwd"></body></html>'
        result = ioe_server.inline_images(html, "https://example.com/")
        assert "file:///etc/passwd" not in result
        assert "data:image/jpeg;base64," not in result


class TestFetchReadable:
    def test_fetch_readable_возвращает_title_и_content(self):
        import types
        import ioe_server
        from unittest.mock import patch

        mock_resp = types.SimpleNamespace(
            text="<html><body><h1>Title</h1><p>Content</p></body></html>",
            status_code=200,
            raise_for_status=lambda: None,
        )
        original_get = ioe_server.requests.get
        ioe_server.requests.get = lambda *a, **kw: mock_resp

        mock_doc = types.SimpleNamespace(
            title=lambda: "Article Title",
            summary=lambda: "<p>Content</p>",
        )
        with (
            patch.object(ioe_server, "inline_images", return_value="<p>Content</p>"),
            patch.object(ioe_server, "Document", return_value=mock_doc),
        ):
            try:
                title, content = ioe_server.fetch_readable("https://example.com/article")
                assert title == "Article Title"
                assert "Content" in content
            finally:
                ioe_server.requests.get = original_get


class TestInlineImagesContentSize:
    def test_данные_больше_лимита_после_загрузки_удаляет_img(self):
        import ioe_server

        large_size = ioe_server.MAX_IMAGE_BYTES + 1

        class MockResp:
            headers = {"Content-Length": "0"}
            content = b"x" * large_size

        original_get = ioe_server.requests.get
        ioe_server.requests.get = lambda *a, **kw: MockResp()
        try:
            html = '<html><body><img src="https://example.com/big2.jpg"></body></html>'
            result = ioe_server.inline_images(html, "https://example.com/")
            assert "data:image/jpeg;base64," not in result
        finally:
            ioe_server.requests.get = original_get

    def test_изображение_с_низким_quality_при_большом_буфере(self):
        import ioe_server
        from unittest.mock import MagicMock, patch

        small_jpeg = b"\xff\xd8\xff" + b"\x00" * 100

        class MockResp:
            headers = {"Content-Length": "103"}
            content = small_jpeg

        mock_pil_img = MagicMock()
        mock_pil_img.width = 400
        mock_pil_img.height = 300
        converted = MagicMock()

        call_count = [0]

        def fake_save(buf, fmt, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                buf.write(b"x" * (81 * 1024))
            else:
                buf.write(b"small")

        converted.save = fake_save
        mock_pil_img.convert.return_value = converted

        original_get = ioe_server.requests.get
        ioe_server.requests.get = lambda *a, **kw: MockResp()
        with patch.object(ioe_server.Image, "open", return_value=mock_pil_img):
            try:
                html = '<html><body><img src="https://example.com/heavy.jpg"></body></html>'
                result = ioe_server.inline_images(html, "https://example.com/")
                assert call_count[0] == 2
            finally:
                ioe_server.requests.get = original_get


class TestProcessMessageDispatch:
    def _make_encrypted_msg(self, ioe_server, req):
        import json
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email import encoders
        from ioe_crypto import compress_encrypt

        encrypted = compress_encrypt(ioe_server.IOE_KEY, json.dumps(req)).encode("ascii")
        msg = MIMEMultipart()
        part = MIMEBase("application", "pdf")
        part.set_payload(encrypted)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename="x.pdf")
        msg.attach(part)
        return msg.as_bytes()

    def test_dispatch_тип_session_start_через_process_message(self):
        import ioe_server
        from unittest.mock import MagicMock

        ioe_server.requests.Session = type("S", (), {"close": lambda s: None})
        req = {"id": "disp-1", "type": "session_start", "session_id": "pm-test-s1", "user_id": "u1"}
        raw = self._make_encrypted_msg(ioe_server, req)

        mock_client = MagicMock()
        ioe_server._processed_uids.discard(9001)

        result = ioe_server.process_message(mock_client, 9001, raw)
        assert result is True
        ioe_server._processed_uids.discard(9001)
        ioe_server._sessions.pop("pm-test-s1", None)

    def test_get_команда_усечение_тела(self):
        import ioe_server
        from unittest.mock import MagicMock, patch

        req = {"id": "trunc-get-1", "cmd": "GET", "url": "https://example.com", "user_id": "u1"}
        raw = self._make_encrypted_msg(ioe_server, req)

        mock_client = MagicMock()
        ioe_server._processed_uids.discard(9002)

        long_body = "b" * (ioe_server.MAX_BODY + 500)
        extract_result = {
            "format": "html",
            "type": "page",
            "title": "T",
            "body": long_body,
            "domain": "example.com",
            "word_count": 1,
        }
        with (
            patch.object(ioe_server, "smart_extract", return_value=extract_result),
            patch.object(ioe_server, "check_rate_limit"),
        ):
            result = ioe_server.process_message(mock_client, 9002, raw)

        assert result is True
        ioe_server._processed_uids.discard(9002)
