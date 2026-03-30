"""Tests for IoE WebUI v4."""
import json
import sys
import os
import threading
from urllib.request import urlopen
from unittest.mock import patch, MagicMock
from http.server import HTTPServer
import socket

_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "webui"))
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "pass")
os.environ.setdefault("IOE_SECRET", "secret123")


import auth
import handler
import transport

TEST_USER = "testuser"
_real_get_auth = auth.get_authenticated_user


def setup_module(module):
    auth.get_authenticated_user = lambda cookie_header: TEST_USER


def teardown_module(module):
    auth.get_authenticated_user = _real_get_auth


def get_html():
    import ioe_web
    return ioe_web.HTML_PAGE


def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestV4Design:
    def test_has_empty_state(self):
        assert 'class="empty"' in get_html()

    def test_has_toolbar(self):
        assert 'class="toolbar"' in get_html()
        assert 'id="url"' in get_html()
        assert 'id="btnGo"' in get_html()

    def test_has_loading_styles(self):
        html = get_html()
        assert '.loading' in html
        assert '.spinner' in html
        assert '@keyframes spin' in html

    def test_has_result_card_styles(self):
        html = get_html()
        assert '.result-card' in html
        assert '.snippet' in html

    def test_has_reader_styles(self):
        html = get_html()
        assert '.reader-body' in html
        assert '.reader-meta' in html
        assert '.back-btn' in html
        assert 'font-read' in html

    def test_has_footer(self):
        assert 'id="statusText"' in get_html()
        assert '<footer>' in get_html()

    def test_has_scroll_top(self):
        assert 'scroll-top' in get_html()

    def test_button_disabled(self):
        assert 'disabled' in get_html()

    def test_no_pico_css(self):
        assert 'picocss' not in get_html()

    def test_has_format_raw_text(self):
        assert 'formatRawText' in get_html()

    def test_has_marked_js(self):
        html = get_html()
        assert 'marked' in html
        assert 'Lexer' in html  # inlined marked.js contains Lexer class

    def test_has_markdown_render_logic(self):
        assert 'marked.parse' in get_html()

    def test_has_custom_renderer(self):
        html = get_html()
        assert 'new marked.Renderer' in html or 'ioeRenderer' in html

    def test_marked_js_is_inlined(self):
        html = get_html()
        assert 'cdn.jsdelivr.net' not in html
        assert 'Lexer' in html or 'marked' in html

    def test_url_detection_requires_latin_tld(self):
        html = get_html()
        assert '[a-zA-Z]' in html

    def test_has_copy_markdown(self):
        html = get_html()
        assert 'copyMd' in html or 'clipboard' in html

    def test_has_word_count_display(self):
        assert 'word_count' in get_html()

    def test_cmd_click_support(self):
        assert 'metaKey' in get_html()
        assert 'ctrlKey' in get_html()


class TestRewriteLinks:
    def test_double_quote_href(self):
        import ioe_web
        result = transport.rewrite_links('<a href="https://example.com/page">Link</a>')
        assert '/get?url=https://example.com/page' in result

    def test_relative_links_untouched(self):
        import ioe_web
        result = transport.rewrite_links('<a href="/about">About</a>')
        assert 'href="/about"' in result


class TestEndpoints:
    def test_root_returns_html(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/".format(port), timeout=5)
        body = resp.read().decode()
        assert resp.status == 200
        assert "IoE" in body
        assert 'class="toolbar"' in body
        server.server_close()

    def test_search_returns_pending(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with patch.object(handler, 'imap_conn') as mock:
            mock.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            resp = urlopen("http://127.0.0.1:{}/search?q=test".format(port), timeout=5)
            data = json.loads(resp.read().decode())
            assert data["status"] == "pending"
            assert "id" in data
        server.server_close()

    def test_status_returns_results_for_search(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        test_results = [{"title": "Test", "href": "https://test.com", "snippet": "Desc"}]
        with ioe_web.lock:
            ioe_web.pending[(TEST_USER, "test123")] = {"id": "test123", "status": 200, "results": test_results}
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/status?id=test123".format(port), timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "ready"
        assert data["results"] == test_results
        server.server_close()

    def test_status_returns_body_for_page(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with ioe_web.lock:
            ioe_web.pending[(TEST_USER, "page123")] = {"id": "page123", "status": 200, "title": "Page", "body": "<p>Content</p>"}
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/status?id=page123".format(port), timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "ready"
        assert data["title"] == "Page"
        assert data["body"] == "<p>Content</p>"
        server.server_close()


class TestDemoMode:
    def test_demo_search_returns_results(self):
        import ioe_web
        old = ioe_web.DEMO_MODE
        ioe_web.DEMO_MODE = True
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/search?q=weather".format(port), timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "ready"
        assert isinstance(data["results"], list)
        assert len(data["results"]) >= 3
        server.server_close()
        ioe_web.DEMO_MODE = old

    def test_demo_get_returns_body(self):
        import ioe_web
        old = ioe_web.DEMO_MODE
        ioe_web.DEMO_MODE = True
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/get?url=https://example.com".format(port), timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "ready"
        assert "title" in data
        assert "body" in data
        server.server_close()
        ioe_web.DEMO_MODE = old


class TestStatusEndpoint:
    def test_status_passes_format_field(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with ioe_web.lock:
            ioe_web.pending[(TEST_USER, "fmt123")] = {
                "id": "fmt123", "status": 200,
                "title": "T", "body": "B", "format": "markdown",
            }
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/status?id=fmt123".format(port), timeout=5)
        data = json.loads(resp.read().decode())
        assert data["format"] == "markdown"
        server.server_close()

    def test_status_error_response(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with ioe_web.lock:
            ioe_web.pending[(TEST_USER, "err123")] = {
                "id": "err123", "status": 500, "error": "HTTPError",
            }
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/status?id=err123".format(port), timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "error"
        assert data["error"] == "HTTPError"
        server.server_close()

    def test_status_default_format_html(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with ioe_web.lock:
            ioe_web.pending[(TEST_USER, "nofmt")] = {
                "id": "nofmt", "status": 200,
                "title": "T", "body": "<p>B</p>",
            }
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/status?id=nofmt".format(port), timeout=5)
        data = json.loads(resp.read().decode())
        assert data["format"] == "html"
        server.server_close()

    def test_404_for_unknown_path(self):
        import ioe_web
        from urllib.error import HTTPError as UrlHTTPError
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        try:
            urlopen("http://127.0.0.1:{}/nonexistent".format(port), timeout=5)
            assert False, "expected 404"
        except UrlHTTPError as e:
            assert e.code == 404
        server.server_close()


class TestProxyEndpoint:
    def test_proxy_returns_pending(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with patch.object(handler, 'imap_conn') as mock:
            mock.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            resp = urlopen("http://127.0.0.1:{}/proxy?method=GET&url=https://example.com".format(port), timeout=5)
            data = json.loads(resp.read().decode())
            assert data["status"] == "pending"
            assert "id" in data
        server.server_close()

    def test_proxy_sends_type_http(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        sent_data = {}
        def capture_send(m, req):
            sent_data.update(req)
        with patch.object(handler, 'imap_conn') as mock_conn, \
             patch.object(handler, 'send_request', side_effect=capture_send):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            urlopen("http://127.0.0.1:{}/proxy?method=POST&url=https://api.test.com&extract=false".format(port), timeout=5)
        assert sent_data.get("type") == "http"
        assert sent_data.get("method") == "POST"
        assert sent_data.get("extract") == False
        server.server_close()


class TestDemoFormatField:
    def test_demo_get_has_format(self):
        import ioe_web
        old = ioe_web.DEMO_MODE
        ioe_web.DEMO_MODE = True
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/get?url=https://example.com".format(port), timeout=5)
        data = json.loads(resp.read().decode())
        assert "format" in data
        server.server_close()
        ioe_web.DEMO_MODE = old


class TestUserIdInRequests:
    def test_user_id_from_auth_session(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        sent_data = {}
        def capture_send(m, req):
            sent_data.update(req)
        with patch.object(handler, 'imap_conn') as mock_conn, \
             patch.object(handler, 'send_request', side_effect=capture_send):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            urlopen("http://127.0.0.1:{}/search?q=test".format(port), timeout=5)
        assert sent_data.get("user_id") == TEST_USER
        server.server_close()

    def test_get_request_includes_user_id(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        sent_data = {}
        def capture_send(m, req):
            sent_data.update(req)
        with patch.object(handler, 'imap_conn') as mock_conn, \
             patch.object(handler, 'send_request', side_effect=capture_send):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            urlopen("http://127.0.0.1:{}/get?url=https://example.com".format(port), timeout=5)
        assert sent_data.get("user_id") == TEST_USER
        server.server_close()

    def test_proxy_request_includes_user_id(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        sent_data = {}
        def capture_send(m, req):
            sent_data.update(req)
        with patch.object(handler, 'imap_conn') as mock_conn, \
             patch.object(handler, 'send_request', side_effect=capture_send):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            urlopen("http://127.0.0.1:{}/proxy?method=GET&url=https://example.com".format(port), timeout=5)
        assert sent_data.get("user_id") == TEST_USER
        server.server_close()

    def test_tg_request_includes_user_id(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        sent_data = {}
        def capture_send(m, req):
            sent_data.update(req)
        with patch.object(handler, 'imap_conn') as mock_conn, \
             patch.object(handler, 'send_request', side_effect=capture_send):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            urlopen("http://127.0.0.1:{}/tg?action=get_dialogs".format(port), timeout=5)
        assert sent_data.get("user_id") == TEST_USER
        server.server_close()


class TestNotifications:
    def test_notification_queues_exists(self):
        import ioe_web
        assert hasattr(ioe_web, 'notification_queues')
        assert isinstance(ioe_web.notification_queues, dict)

    def test_notifications_endpoint_returns_empty(self):
        import ioe_web
        ioe_web.notification_queues[TEST_USER] = []
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/notifications".format(port), timeout=5)
        data = json.loads(resp.read().decode())
        assert data["notifications"] == []
        server.server_close()

    def test_notifications_endpoint_returns_and_clears(self):
        import ioe_web
        ioe_web.notification_queues[TEST_USER] = []
        with ioe_web.lock:
            ioe_web.notification_queues.setdefault(TEST_USER, []).append({"type": "notification", "service": "telegram", "text": "hello"})
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/notifications".format(port), timeout=5)
        data = json.loads(resp.read().decode())
        assert len(data["notifications"]) == 1
        assert data["notifications"][0]["text"] == "hello"
        with ioe_web.lock:
            assert len(ioe_web.notification_queues.get(TEST_USER, [])) == 0
        server.server_close()

    def test_poll_response_captures_notification(self):
        import ioe_web
        ioe_web.notification_queues[TEST_USER] = []
        notif_msg = {"type": "notification", "service": "telegram", "text": "new msg"}
        normal_resp = {"id": "req123", "status": 200, "body": "ok"}

        encrypted_notif = transport.encrypt(ioe_web.IOE_KEY, json.dumps(notif_msg))
        encrypted_resp = transport.encrypt(ioe_web.IOE_KEY, json.dumps(normal_resp))

        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email import encoders

        def make_raw(payload_str):
            msg = MIMEMultipart()
            msg["Subject"] = "test"
            part = MIMEBase("application", "pdf")
            part.set_payload(payload_str.encode("ascii"))
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename="doc.pdf")
            msg.attach(part)
            return msg.as_bytes()

        raw_notif = make_raw(encrypted_notif)
        raw_resp = make_raw(encrypted_resp)

        mock_imap = MagicMock()
        mock_imap.select.return_value = ("OK", [b"INBOX"])
        mock_imap.noop.return_value = ("OK", [])
        mock_imap.search.return_value = ("OK", [b"1 2"])
        mock_imap.fetch.side_effect = lambda uid, _: ("OK", [(uid, raw_notif if uid == b"2" else raw_resp)])

        with patch.object(transport, 'imap_conn', return_value=mock_imap), \
             patch('time.sleep'):
            poll_thread = threading.Thread(target=transport.poll_response, args=(TEST_USER, "req123"), daemon=True)
            poll_thread.start()
            poll_thread.join(timeout=10)

        with ioe_web.lock:
            assert len(ioe_web.notification_queues.get(TEST_USER, [])) == 1
            assert ioe_web.notification_queues[TEST_USER][0]["text"] == "new msg"
            assert (TEST_USER, "req123") in ioe_web.pending
        ioe_web.notification_queues[TEST_USER] = []
        ioe_web.pending.pop((TEST_USER, "req123"), None)


class TestKitEndpoint:
    def test_kit_list_returns_kits(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/kit".format(port), timeout=5)
        data = json.loads(resp.read().decode())
        assert "kits" in data
        services = [k["service"] for k in data["kits"]]
        assert "hackernews" in services
        server.server_close()

    def test_kit_list_excludes_templates(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/kit".format(port), timeout=5)
        data = json.loads(resp.read().decode())
        services = [k["service"] for k in data["kits"]]
        assert "_template_auth" not in services
        server.server_close()


class TestBrowserMode:
    def test_html_has_browser_mode_toggle(self):
        html = get_html()
        assert 'id="btnBrowser"' in html
        assert 'toggleBrowserMode' in html

    def test_css_has_browser_toggle_style(self):
        html = get_html()
        assert '.toolbar-toggle' in html

    def test_js_has_browser_mode_var(self):
        html = get_html()
        assert 'var browserMode' in html
        assert 'toggleBrowserMode' in html

    def test_js_openpage_checks_browser_mode(self):
        html = get_html()
        assert 'browserMode' in html
        assert '/browser?' in html

    def test_browser_endpoint_demo_mode(self):
        import ioe_web
        old = ioe_web.DEMO_MODE
        ioe_web.DEMO_MODE = True
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/browser?url=https://example.com".format(port), timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "error"
        assert "demo" in data["error"]
        server.server_close()
        ioe_web.DEMO_MODE = old

    def test_browser_endpoint_returns_pending(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with patch.object(handler, 'imap_conn') as mock_conn, \
             patch.object(handler, 'send_request'):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            resp = urlopen("http://127.0.0.1:{}/browser?url=https://example.com".format(port), timeout=5)
            data = json.loads(resp.read().decode())
            assert data["status"] == "pending"
            assert "id" in data
        server.server_close()

    def test_browser_endpoint_sends_browser_type(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        sent_data = {}
        def capture_send(m, req):
            sent_data.update(req)
        with patch.object(handler, 'imap_conn') as mock_conn, \
             patch.object(handler, 'send_request', side_effect=capture_send):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            urlopen("http://127.0.0.1:{}/browser?url=https://example.com".format(port), timeout=5)
        assert sent_data.get("type") == "browser"
        assert sent_data.get("url") == "https://example.com"
        assert "goto" in sent_data.get("actions", [])
        server.server_close()

    def test_browser_endpoint_includes_user_id(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        sent_data = {}
        def capture_send(m, req):
            sent_data.update(req)
        with patch.object(handler, 'imap_conn') as mock_conn, \
             patch.object(handler, 'send_request', side_effect=capture_send):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            urlopen("http://127.0.0.1:{}/browser?url=https://example.com".format(port), timeout=5)
        assert sent_data.get("user_id") == TEST_USER
        server.server_close()
