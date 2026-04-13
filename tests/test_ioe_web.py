"""Tests for IoE WebUI v4."""

import json
import sys
import os
import types
import threading
from urllib.request import urlopen
from unittest.mock import patch, MagicMock
from http.server import HTTPServer
import socket

_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "webui"))
sys.path.insert(0, os.path.dirname(__file__))

if "imapclient" not in sys.modules:
    sys.modules["imapclient"] = types.ModuleType("imapclient")
    sys.modules["imapclient"].IMAPClient = type("IMAPClient", (), {})
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
    s.bind(("", 0))
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
        assert ".loading" in html
        assert ".spinner" in html
        assert "@keyframes spin" in html

    def test_has_result_card_styles(self):
        html = get_html()
        assert ".result-card" in html
        assert ".snippet" in html

    def test_has_reader_styles(self):
        html = get_html()
        assert ".reader-body" in html
        assert ".reader-meta" in html
        assert ".back-btn" in html
        assert "font-read" in html

    def test_has_footer(self):
        assert 'id="statusText"' in get_html()
        assert "<footer>" in get_html()

    def test_has_scroll_top(self):
        assert "scroll-top" in get_html()

    def test_button_disabled(self):
        assert "disabled" in get_html()

    def test_no_pico_css(self):
        assert "picocss" not in get_html()

    def test_has_format_raw_text(self):
        assert "formatRawText" in get_html()

    def test_has_marked_js(self):
        html = get_html()
        assert "marked" in html
        assert "Lexer" in html  # inlined marked.js contains Lexer class

    def test_has_markdown_render_logic(self):
        assert "marked.parse" in get_html()

    def test_has_custom_renderer(self):
        html = get_html()
        assert "new marked.Renderer" in html or "ioeRenderer" in html

    def test_marked_js_is_inlined(self):
        html = get_html()
        assert "cdn.jsdelivr.net" not in html
        assert "Lexer" in html or "marked" in html

    def test_url_detection_requires_latin_tld(self):
        html = get_html()
        assert "[a-zA-Z]" in html

    def test_has_copy_markdown(self):
        html = get_html()
        assert "copyMd" in html or "clipboard" in html

    def test_has_word_count_display(self):
        assert "word_count" in get_html()

    def test_cmd_click_support(self):
        assert "metaKey" in get_html()
        assert "ctrlKey" in get_html()


class TestRewriteLinks:
    def test_double_quote_href(self):
        result = transport.rewrite_links('<a href="https://example.com/page">Link</a>')
        assert "/get?url=https://example.com/page" in result

    def test_relative_links_untouched(self):
        result = transport.rewrite_links('<a href="/about">About</a>')
        assert 'href="/about"' in result


class TestEndpoints:
    def test_root_returns_html(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen(f"http://127.0.0.1:{port}/", timeout=5)
        body = resp.read().decode()
        assert resp.status == 200
        assert "IoE" in body
        assert 'class="toolbar"' in body
        server.server_close()

    def test_search_returns_pending(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with patch.object(handler, "imap_conn") as mock:
            mock.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            resp = urlopen(f"http://127.0.0.1:{port}/search?q=test", timeout=5)
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
            ioe_web.pending[(TEST_USER, "test123")] = {
                "id": "test123",
                "status": 200,
                "results": test_results,
            }
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen(f"http://127.0.0.1:{port}/status?id=test123", timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "ready"
        assert data["results"] == test_results
        server.server_close()

    def test_status_returns_body_for_page(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with ioe_web.lock:
            ioe_web.pending[(TEST_USER, "page123")] = {
                "id": "page123",
                "status": 200,
                "title": "Page",
                "body": "<p>Content</p>",
            }
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen(f"http://127.0.0.1:{port}/status?id=page123", timeout=5)
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
        resp = urlopen(f"http://127.0.0.1:{port}/search?q=weather", timeout=5)
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
        resp = urlopen(f"http://127.0.0.1:{port}/get?url=https://example.com", timeout=5)
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
                "id": "fmt123",
                "status": 200,
                "title": "T",
                "body": "B",
                "format": "markdown",
            }
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen(f"http://127.0.0.1:{port}/status?id=fmt123", timeout=5)
        data = json.loads(resp.read().decode())
        assert data["format"] == "markdown"
        server.server_close()

    def test_status_error_response(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with ioe_web.lock:
            ioe_web.pending[(TEST_USER, "err123")] = {
                "id": "err123",
                "status": 500,
                "error": "HTTPError",
            }
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen(f"http://127.0.0.1:{port}/status?id=err123", timeout=5)
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
                "id": "nofmt",
                "status": 200,
                "title": "T",
                "body": "<p>B</p>",
            }
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen(f"http://127.0.0.1:{port}/status?id=nofmt", timeout=5)
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
            urlopen(f"http://127.0.0.1:{port}/nonexistent", timeout=5)
            raise AssertionError("expected 404")
        except UrlHTTPError as e:
            assert e.code == 404
        server.server_close()


class TestProxyEndpoint:
    def test_proxy_returns_pending(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with patch.object(handler, "imap_conn") as mock:
            mock.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            resp = urlopen(
                f"http://127.0.0.1:{port}/proxy?method=GET&url=https://example.com",
                timeout=5,
            )
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

        with (
            patch.object(handler, "imap_conn") as mock_conn,
            patch.object(handler, "send_request", side_effect=capture_send),
        ):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            urlopen(
                f"http://127.0.0.1:{port}/proxy?method=POST&url=https://api.test.com&extract=false",
                timeout=5,
            )
        assert sent_data.get("type") == "http"
        assert sent_data.get("method") == "POST"
        assert not sent_data.get("extract")
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
        resp = urlopen(f"http://127.0.0.1:{port}/get?url=https://example.com", timeout=5)
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

        with (
            patch.object(handler, "imap_conn") as mock_conn,
            patch.object(handler, "send_request", side_effect=capture_send),
        ):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            urlopen(f"http://127.0.0.1:{port}/search?q=test", timeout=5)
        assert sent_data.get("user_id") == TEST_USER
        server.server_close()

    def test_get_request_includes_user_id(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        sent_data = {}

        def capture_send(m, req):
            sent_data.update(req)

        with (
            patch.object(handler, "imap_conn") as mock_conn,
            patch.object(handler, "send_request", side_effect=capture_send),
        ):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            urlopen(f"http://127.0.0.1:{port}/get?url=https://example.com", timeout=5)
        assert sent_data.get("user_id") == TEST_USER
        server.server_close()

    def test_proxy_request_includes_user_id(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        sent_data = {}

        def capture_send(m, req):
            sent_data.update(req)

        with (
            patch.object(handler, "imap_conn") as mock_conn,
            patch.object(handler, "send_request", side_effect=capture_send),
        ):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            urlopen(
                f"http://127.0.0.1:{port}/proxy?method=GET&url=https://example.com",
                timeout=5,
            )
        assert sent_data.get("user_id") == TEST_USER
        server.server_close()

    def test_tg_request_includes_user_id(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        sent_data = {}

        def capture_send(m, req):
            sent_data.update(req)

        with (
            patch.object(handler, "imap_conn") as mock_conn,
            patch.object(handler, "send_request", side_effect=capture_send),
        ):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            urlopen(f"http://127.0.0.1:{port}/tg?action=get_dialogs", timeout=5)
        assert sent_data.get("user_id") == TEST_USER
        server.server_close()


class TestNotifications:
    def test_notification_queues_exists(self):
        import ioe_web

        assert hasattr(ioe_web, "notification_queues")
        assert isinstance(ioe_web.notification_queues, dict)

    def test_notifications_endpoint_returns_empty(self):
        import ioe_web

        ioe_web.notification_queues[TEST_USER] = []
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen(f"http://127.0.0.1:{port}/notifications", timeout=5)
        data = json.loads(resp.read().decode())
        assert data["notifications"] == []
        server.server_close()

    def test_notifications_endpoint_returns_and_clears(self):
        import ioe_web

        ioe_web.notification_queues[TEST_USER] = []
        with ioe_web.lock:
            ioe_web.notification_queues.setdefault(TEST_USER, []).append(
                {"type": "notification", "service": "telegram", "text": "hello"}
            )
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen(f"http://127.0.0.1:{port}/notifications", timeout=5)
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

        encrypted_notif = transport.compress_encrypt(ioe_web.IOE_KEY, json.dumps(notif_msg))
        encrypted_resp = transport.compress_encrypt(ioe_web.IOE_KEY, json.dumps(normal_resp))

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
        mock_imap.select_folder.return_value = {}
        mock_imap.noop.return_value = None
        mock_imap.search.return_value = [1, 2]
        mock_imap.fetch.side_effect = lambda uids, _: {
            uid: {b"RFC822": raw_notif if uid == 2 else raw_resp} for uid in uids
        }
        mock_imap.set_flags.return_value = {}
        mock_imap.expunge.return_value = None
        mock_imap.logout.return_value = None

        with (
            patch.object(transport, "_create_conn", return_value=mock_imap),
            patch("time.sleep"),
        ):
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
        resp = urlopen(f"http://127.0.0.1:{port}/kit", timeout=5)
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
        resp = urlopen(f"http://127.0.0.1:{port}/kit", timeout=5)
        data = json.loads(resp.read().decode())
        services = [k["service"] for k in data["kits"]]
        assert "_template_auth" not in services
        server.server_close()


class TestLoginCheckPhone:
    def test_login_tg_get_returns_405(self):
        import ioe_web
        from urllib.error import HTTPError as UrlHTTPError

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        try:
            urlopen(f"http://127.0.0.1:{port}/login/tg", timeout=5)
            raise AssertionError("ожидался 405")
        except UrlHTTPError as e:
            assert e.code == 405
        server.server_close()

    def test_login_status_pending_unknown_id(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen(f"http://127.0.0.1:{port}/login/status?id=nonexistent", timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "pending"
        server.server_close()

    def test_login_status_ready_for_known_id(self):
        import ioe_web
        import handler as h

        req_id = "loginreq1"
        login_user_id = "login"
        import time as _time

        h._login_request_owners[req_id] = (login_user_id, _time.time())
        with ioe_web.lock:
            ioe_web.pending[(login_user_id, req_id)] = {
                "id": req_id,
                "status": 200,
                "auth_status": "code_sent",
                "hint": "check phone",
                "_created": _time.time(),
            }
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen(f"http://127.0.0.1:{port}/login/status?id={req_id}", timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "ready"
        assert data["auth_status"] == "code_sent"
        server.server_close()

    def test_logout_redirects_to_login(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        import urllib.request

        opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
        opener.addheaders = []
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/logout")
            with urllib.request.urlopen(req, timeout=5) as resp:
                pass
        except Exception:
            pass
        server.server_close()


class TestSendEndpoints:
    def test_send_post_not_found(self):
        import ioe_web
        from urllib.error import HTTPError as UrlHTTPError
        import urllib.request

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/send",
                data=b"{}",
                headers={"Content-Type": "application/json", "Content-Length": "2"},
                method="POST",
            )
            urlopen(req, timeout=5)
            raise AssertionError("ожидался 404")
        except UrlHTTPError as e:
            assert e.code == 404
        server.server_close()

    def test_tg_post_returns_pending(self):
        import ioe_web
        import urllib.request

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        payload = json.dumps({"action": "get_dialogs"}).encode()
        with (
            patch.object(handler, "imap_conn") as mock_conn,
            patch.object(handler, "send_request"),
        ):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/tg",
                data=payload,
                headers={"Content-Type": "application/json", "Content-Length": str(len(payload))},
                method="POST",
            )
            resp = urlopen(req, timeout=5)
            data = json.loads(resp.read().decode())
            assert data["status"] == "pending"
            assert "id" in data
        server.server_close()

    def test_tg_post_includes_user_id(self):
        import ioe_web
        import urllib.request

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        payload = json.dumps({"action": "send_message", "chat_id": "123", "text": "hi"}).encode()
        sent_data = {}

        def capture_send(m, req):
            sent_data.update(req)

        with (
            patch.object(handler, "imap_conn") as mock_conn,
            patch.object(handler, "send_request", side_effect=capture_send),
        ):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/tg",
                data=payload,
                headers={"Content-Type": "application/json", "Content-Length": str(len(payload))},
                method="POST",
            )
            urlopen(req, timeout=5)
        assert sent_data.get("user_id") == TEST_USER
        assert sent_data.get("service") == "telegram"
        server.server_close()

    def test_tg_post_demo_mode(self):
        import ioe_web
        import urllib.request

        old = ioe_web.DEMO_MODE
        ioe_web.DEMO_MODE = True
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        payload = json.dumps({"action": "get_dialogs"}).encode()
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/tg",
            data=payload,
            headers={"Content-Type": "application/json", "Content-Length": str(len(payload))},
            method="POST",
        )
        resp = urlopen(req, timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "error"
        assert "demo" in data["error"]
        server.server_close()
        ioe_web.DEMO_MODE = old

    def test_tg_post_invalid_json(self):
        import ioe_web
        import urllib.request

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        payload = b"not-json"
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/tg",
            data=payload,
            headers={"Content-Type": "application/json", "Content-Length": str(len(payload))},
            method="POST",
        )
        from urllib.error import HTTPError as UrlHTTPError

        try:
            urlopen(req, timeout=5)
        except UrlHTTPError as e:
            assert e.code == 400
        server.server_close()


class TestClaudeEndpoint:
    def test_claude_get_returns_pending(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with (
            patch.object(handler, "imap_conn") as mock_conn,
            patch.object(handler, "send_request"),
        ):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            resp = urlopen(f"http://127.0.0.1:{port}/claude?action=chat&text=hello", timeout=5)
            data = json.loads(resp.read().decode())
            assert data["status"] == "pending"
            assert "id" in data
        server.server_close()

    def test_claude_get_sends_correct_type(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        sent_data = {}

        def capture_send(m, req):
            sent_data.update(req)

        with (
            patch.object(handler, "imap_conn") as mock_conn,
            patch.object(handler, "send_request", side_effect=capture_send),
        ):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            urlopen(f"http://127.0.0.1:{port}/claude?action=chat&text=hello&model=haiku", timeout=5)
        assert sent_data.get("type") == "claude_chat"
        assert sent_data.get("action") == "chat"
        assert sent_data.get("text") == "hello"
        assert sent_data.get("model") == "haiku"
        assert sent_data.get("user_id") == TEST_USER
        server.server_close()


class TestStatusCommandResponse:
    def test_status_returns_dialogs_field(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with ioe_web.lock:
            ioe_web.pending[(TEST_USER, "dlg123")] = {
                "id": "dlg123",
                "status": 200,
                "type": "command",
                "dialogs": [{"id": 1, "name": "Chat"}],
            }
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen(f"http://127.0.0.1:{port}/status?id=dlg123", timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "ready"
        assert "dialogs" in data
        server.server_close()

    def test_status_unknown_error_field_added(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with ioe_web.lock:
            ioe_web.pending[(TEST_USER, "err456")] = {
                "id": "err456",
                "status": 500,
            }
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen(f"http://127.0.0.1:{port}/status?id=err456", timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "error"
        assert data["error"] == "unknown"
        server.server_close()


class TestProxyBodyAndSession:
    def test_proxy_body_json_parsed(self):
        import ioe_web
        import json as _json

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        sent_data = {}

        def capture_send(m, req):
            sent_data.update(req)

        body_obj = _json.dumps({"key": "value"})
        with (
            patch.object(handler, "imap_conn") as mock_conn,
            patch.object(handler, "send_request", side_effect=capture_send),
        ):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            import urllib.parse

            params = urllib.parse.urlencode({"method": "POST", "url": "https://api.test.com", "body": body_obj})
            urlopen(f"http://127.0.0.1:{port}/proxy?{params}", timeout=5)
        assert sent_data.get("body") == {"key": "value"}
        server.server_close()

    def test_proxy_session_id_forwarded(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        sent_data = {}

        def capture_send(m, req):
            sent_data.update(req)

        with (
            patch.object(handler, "imap_conn") as mock_conn,
            patch.object(handler, "send_request", side_effect=capture_send),
        ):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            urlopen(
                f"http://127.0.0.1:{port}/proxy?method=GET&url=https://api.test.com&session_id=sess42",
                timeout=5,
            )
        assert sent_data.get("session_id") == "sess42"
        server.server_close()

    def test_proxy_demo_mode_returns_error(self):
        import ioe_web

        old = ioe_web.DEMO_MODE
        ioe_web.DEMO_MODE = True
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen(f"http://127.0.0.1:{port}/proxy?method=GET&url=https://example.com", timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "error"
        assert "demo" in data["error"]
        server.server_close()
        ioe_web.DEMO_MODE = old


class TestTgGetParams:
    def test_tg_get_chat_id_cast_to_int(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        sent_data = {}

        def capture_send(m, req):
            sent_data.update(req)

        with (
            patch.object(handler, "imap_conn") as mock_conn,
            patch.object(handler, "send_request", side_effect=capture_send),
        ):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            urlopen(f"http://127.0.0.1:{port}/tg?action=get_messages&chat_id=999&limit=20", timeout=5)
        assert sent_data.get("chat_id") == 999
        assert sent_data.get("limit") == 20
        server.server_close()

    def test_tg_demo_mode_returns_error(self):
        import ioe_web

        old = ioe_web.DEMO_MODE
        ioe_web.DEMO_MODE = True
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen(f"http://127.0.0.1:{port}/tg?action=get_dialogs", timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "error"
        assert "demo" in data["error"]
        server.server_close()
        ioe_web.DEMO_MODE = old


class TestTextEndpoint:
    def test_text_endpoint_returns_pending(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with (
            patch.object(handler, "imap_conn") as mock_conn,
            patch.object(handler, "send_request"),
        ):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            resp = urlopen(f"http://127.0.0.1:{port}/text?url=https://example.com", timeout=5)
            data = json.loads(resp.read().decode())
            assert data["status"] == "pending"
        server.server_close()

    def test_text_endpoint_sends_cmd_text(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        sent_data = {}

        def capture_send(m, req):
            sent_data.update(req)

        with (
            patch.object(handler, "imap_conn") as mock_conn,
            patch.object(handler, "send_request", side_effect=capture_send),
        ):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            urlopen(f"http://127.0.0.1:{port}/text?url=https://example.com", timeout=5)
        assert sent_data.get("cmd") == "TEXT"
        assert sent_data.get("url") == "https://example.com"
        server.server_close()


class TestBrowserMode:
    def test_html_has_browser_mode_toggle(self):
        html = get_html()
        assert 'id="btnBrowser"' in html
        assert "toggleBrowserMode" in html

    def test_css_has_browser_toggle_style(self):
        html = get_html()
        assert ".toolbar-toggle" in html

    def test_js_has_browser_mode_var(self):
        html = get_html()
        assert "var browserMode" in html
        assert "toggleBrowserMode" in html

    def test_js_openpage_checks_browser_mode(self):
        html = get_html()
        assert "browserMode" in html
        assert "/browser?" in html

    def test_browser_endpoint_demo_mode(self):
        import ioe_web

        old = ioe_web.DEMO_MODE
        ioe_web.DEMO_MODE = True
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen(f"http://127.0.0.1:{port}/browser?url=https://example.com", timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "error"
        assert "demo" in data["error"]
        server.server_close()
        ioe_web.DEMO_MODE = old

    def test_browser_endpoint_returns_pending(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with (
            patch.object(handler, "imap_conn") as mock_conn,
            patch.object(handler, "send_request"),
        ):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            resp = urlopen(f"http://127.0.0.1:{port}/browser?url=https://example.com", timeout=5)
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

        with (
            patch.object(handler, "imap_conn") as mock_conn,
            patch.object(handler, "send_request", side_effect=capture_send),
        ):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            urlopen(f"http://127.0.0.1:{port}/browser?url=https://example.com", timeout=5)
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

        with (
            patch.object(handler, "imap_conn") as mock_conn,
            patch.object(handler, "send_request", side_effect=capture_send),
        ):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            urlopen(f"http://127.0.0.1:{port}/browser?url=https://example.com", timeout=5)
        assert sent_data.get("user_id") == TEST_USER
        server.server_close()


class TestClassifyError:
    def test_rate_limit_with_seconds(self):
        err_type, msg = handler._classify_error("A]> wait of 120 seconds is required")
        assert err_type == "rate_limit"
        assert "2 мин" in msg

    def test_transport_timeout(self):
        err_type, msg = handler._classify_error("Connection timeout reached")
        assert err_type == "transport"

    def test_unknown_error(self):
        err_type, msg = handler._classify_error("something weird")
        assert err_type == "vps"


class TestLoginFlow:
    def test_login_get_returns_html(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        old_auth = auth.get_authenticated_user
        auth.get_authenticated_user = lambda cookie_header: None
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen(f"http://127.0.0.1:{port}/login", timeout=5)
        body = resp.read().decode()
        assert resp.status == 200
        server.server_close()
        auth.get_authenticated_user = old_auth

    def test_unauthenticated_redirects_to_login(self):
        import ioe_web
        import http.client

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        old_auth = auth.get_authenticated_user
        auth.get_authenticated_user = lambda cookie_header: None
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/")
        resp = conn.getresponse()
        assert resp.status == 302
        assert resp.getheader("Location") == "/login"
        conn.close()
        server.server_close()
        auth.get_authenticated_user = old_auth

    def test_login_post_form_success(self):
        import ioe_web
        import http.client

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        old_auth = auth.get_authenticated_user
        auth.get_authenticated_user = lambda cookie_header: None

        with (
            patch.object(auth, "check_rate_limit", return_value=True),
            patch.object(auth, "verify_password", return_value=True),
            patch.object(auth, "create_session", return_value="sid123"),
        ):
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request(
                "POST",
                "/login",
                body="username=admin&password=secret",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp = conn.getresponse()
            assert resp.status == 302
            assert "sid123" in (resp.getheader("Set-Cookie") or "")
            conn.close()
        server.server_close()
        auth.get_authenticated_user = old_auth

    def test_login_post_form_failure(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        old_auth = auth.get_authenticated_user
        auth.get_authenticated_user = lambda cookie_header: None

        with (
            patch.object(auth, "check_rate_limit", return_value=True),
            patch.object(auth, "verify_password", return_value=False),
        ):
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            body = b"username=admin&password=wrong"
            from urllib.request import Request

            req = Request(
                f"http://127.0.0.1:{port}/login",
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp = urlopen(req, timeout=5)
            assert resp.status == 200
        server.server_close()
        auth.get_authenticated_user = old_auth

    def test_login_status_rate_limited(self):
        import ioe_web
        import auth

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)

        for i in range(auth.STATUS_RATE_LIMIT):
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            resp = urlopen(f"http://127.0.0.1:{port}/login/status?id=test{i}", timeout=5)
            assert resp.status == 200

        from urllib.error import HTTPError as UrlHTTPError

        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        try:
            urlopen(f"http://127.0.0.1:{port}/login/status?id=over", timeout=5)
            raise AssertionError("expected 429")
        except UrlHTTPError as e:
            assert e.code == 429
        server.server_close()

    def test_login_post_rate_limited(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        old_auth = auth.get_authenticated_user
        auth.get_authenticated_user = lambda cookie_header: None

        with patch.object(auth, "check_rate_limit", return_value=False):
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            body = b"username=admin&password=x"
            from urllib.request import Request
            from urllib.error import HTTPError as UrlHTTPError

            req = Request(
                f"http://127.0.0.1:{port}/login",
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            try:
                resp = urlopen(req, timeout=5)
                assert resp.status in (200, 429)
            except UrlHTTPError as e:
                assert e.code == 429
        server.server_close()
        auth.get_authenticated_user = old_auth

    def test_login_status_filters_unexpected_keys(self):
        import ioe_web
        import handler as h
        import time as _time

        req_id = "filtertest1"
        login_user_id = "login"
        h._login_request_owners[req_id] = (login_user_id, _time.time())
        with ioe_web.lock:
            ioe_web.pending[(login_user_id, req_id)] = {
                "id": req_id,
                "status": 200,
                "auth_status": "code_sent",
                "hint": "check phone",
                "internal_debug": "should_not_leak",
                "stack_trace": "also_secret",
                "_created": _time.time(),
            }
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        with patch.object(auth, "check_status_rate_limit", return_value=True):
            resp = urlopen(f"http://127.0.0.1:{port}/login/status?id={req_id}", timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "ready"
        assert data["auth_status"] == "code_sent"
        assert data.get("hint") == "check phone"
        assert "internal_debug" not in data
        assert "stack_trace" not in data
        assert "_created" not in data
        server.server_close()

    def test_login_status_authorized_sets_cookie(self):
        import ioe_web
        import handler as h
        import time as _time

        req_id = "authcookie1"
        login_user_id = "login"
        h._login_request_owners[req_id] = (login_user_id, _time.time())
        with ioe_web.lock:
            ioe_web.pending[(login_user_id, req_id)] = {
                "id": req_id,
                "status": 200,
                "auth_status": "authorized",
                "set_session": True,
                "internal_token": "should_not_leak",
                "_created": _time.time(),
            }
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        with (
            patch.object(auth, "check_status_rate_limit", return_value=True),
            patch.object(auth, "create_session", return_value="test-sid-abc"),
        ):
            resp = urlopen(f"http://127.0.0.1:{port}/login/status?id={req_id}", timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "ready"
        assert data["auth_status"] == "authorized"
        assert data["set_session"] is True
        assert "internal_token" not in data
        assert "_created" not in data
        cookie = resp.headers.get("Set-Cookie", "")
        assert "sid=test-sid-abc" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=Strict" in cookie
        server.server_close()


class TestPostTgEndpoint:
    def test_post_tg_returns_pending(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with patch.object(handler, "imap_conn") as mock_conn, patch.object(handler, "send_request"):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            from urllib.request import Request

            body = json.dumps({"action": "get_dialogs"}).encode()
            req = Request(
                f"http://127.0.0.1:{port}/tg",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            resp = urlopen(req, timeout=5)
            data = json.loads(resp.read().decode())
            assert data["status"] == "pending"
        server.server_close()

    def test_post_tg_invalid_json(self):
        import ioe_web
        import http.client

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("POST", "/tg", body="not json", headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = json.loads(resp.read().decode())
        assert data["status"] == "error"
        conn.close()
        server.server_close()

    def test_post_tg_imap_failure(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with patch.object(handler, "imap_conn", side_effect=Exception("conn fail")):
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            from urllib.request import Request

            body = json.dumps({"action": "get_dialogs"}).encode()
            req = Request(
                f"http://127.0.0.1:{port}/tg",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            resp = urlopen(req, timeout=5)
            data = json.loads(resp.read().decode())
            assert data["status"] == "error"
        server.server_close()

    def test_post_tg_unauthenticated(self):
        import ioe_web
        import http.client

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        old_auth = auth.get_authenticated_user
        auth.get_authenticated_user = lambda cookie_header: None
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        body = json.dumps({"action": "get_dialogs"})
        conn.request("POST", "/tg", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        assert resp.status == 302
        conn.close()
        server.server_close()
        auth.get_authenticated_user = old_auth


class TestIoeWebMain:
    def test_main_default_port(self):
        import ioe_web
        import webbrowser

        with (
            patch("sys.argv", ["ioe_web.py"]),
            patch.object(ioe_web, "HTTPServer") as mock_srv,
            patch.object(auth, "load_whitelist"),
            patch.object(auth, "init_sessions"),
            patch.object(auth, "_whitelist", ["x"]),
            patch("threading.Timer"),
            patch.object(webbrowser, "open", create=True),
        ):
            mock_instance = MagicMock()
            mock_srv.return_value = mock_instance
            mock_instance.serve_forever.side_effect = KeyboardInterrupt
            ioe_web.main()
            mock_srv.assert_called_once()

    def test_main_demo_port_arg(self):
        import ioe_web
        import webbrowser

        with (
            patch("sys.argv", ["ioe_web.py", "--demo", "9090"]),
            patch.object(ioe_web, "HTTPServer") as mock_srv,
            patch.object(auth, "load_whitelist"),
            patch.object(auth, "init_sessions"),
            patch.object(auth, "_whitelist", ["x"]),
            patch("threading.Timer"),
            patch.object(webbrowser, "open", create=True),
        ):
            mock_instance = MagicMock()
            mock_srv.return_value = mock_instance
            mock_instance.serve_forever.side_effect = KeyboardInterrupt
            ioe_web.main()
            call_args = mock_srv.call_args[0]
            assert call_args[0] == ("0.0.0.0", 9090)

    def test_main_empty_whitelist_warning(self, capsys):
        import ioe_web
        import webbrowser

        with (
            patch("sys.argv", ["ioe_web.py"]),
            patch.object(ioe_web, "HTTPServer") as mock_srv,
            patch.object(auth, "load_whitelist"),
            patch.object(auth, "init_sessions"),
            patch.object(auth, "_whitelist", set()),
            patch("threading.Timer"),
            patch.object(webbrowser, "open", create=True),
        ):
            mock_instance = MagicMock()
            mock_srv.return_value = mock_instance
            mock_instance.serve_forever.side_effect = KeyboardInterrupt
            ioe_web.main()
            captured = capsys.readouterr()
            assert "WHITELIST EMPTY" in captured.out


class TestGetImapFailure:
    def test_get_imap_failure_classifies_error(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with patch.object(handler, "imap_conn", side_effect=Exception("Connection refused")):
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            resp = urlopen(f"http://127.0.0.1:{port}/get?url=https://example.com", timeout=5)
            data = json.loads(resp.read().decode())
            assert data["status"] == "error"
            assert data.get("error_type") == "transport"
        server.server_close()

    def test_proxy_body_json_parsing(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        sent_data = {}

        def capture_send(m, req):
            sent_data.update(req)

        with (
            patch.object(handler, "imap_conn") as mock_conn,
            patch.object(handler, "send_request", side_effect=capture_send),
        ):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            import urllib.parse

            body_json = urllib.parse.quote('{"key": "val"}')
            urlopen(
                f"http://127.0.0.1:{port}/proxy?method=POST&url=https://api.test.com&body={body_json}&session_id=sess1",
                timeout=5,
            )
        assert sent_data.get("body") == {"key": "val"}
        assert sent_data.get("session_id") == "sess1"
        server.server_close()

    def test_browser_imap_failure(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with patch.object(handler, "imap_conn", side_effect=Exception("timeout")):
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            resp = urlopen(f"http://127.0.0.1:{port}/browser?url=https://example.com", timeout=5)
            data = json.loads(resp.read().decode())
            assert data["status"] == "error"
        server.server_close()

    def test_claude_imap_failure(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with patch.object(handler, "imap_conn", side_effect=Exception("timeout")):
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            resp = urlopen(f"http://127.0.0.1:{port}/claude?action=send&text=hi", timeout=5)
            data = json.loads(resp.read().decode())
            assert data["status"] == "error"
        server.server_close()

    def test_tg_imap_failure(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with patch.object(handler, "imap_conn", side_effect=Exception("Connection refused")):
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            resp = urlopen(f"http://127.0.0.1:{port}/tg?action=get_dialogs", timeout=5)
            data = json.loads(resp.read().decode())
            assert data["status"] == "error"
            assert data.get("error_type") == "transport"
        server.server_close()

    def test_tg_chat_id_int_parsing(self):
        import ioe_web

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        sent_data = {}

        def capture_send(m, req):
            sent_data.update(req)

        with (
            patch.object(handler, "imap_conn") as mock_conn,
            patch.object(handler, "send_request", side_effect=capture_send),
        ):
            mock_conn.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            urlopen(
                f"http://127.0.0.1:{port}/tg?action=get_messages&chat_id=123&limit=10",
                timeout=5,
            )
        assert sent_data.get("chat_id") == 123
        assert sent_data.get("limit") == 10
        server.server_close()
