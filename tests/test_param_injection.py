"""Tests for parameter injection prevention (Task 0 security fix)."""

import json
import sys
import os
import threading
from urllib.request import urlopen, Request
from unittest.mock import patch, MagicMock
from http.server import HTTPServer
import socket

_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "webui"))
os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "pass")
os.environ.setdefault("IOE_SECRET", "secret123")

import auth
import handler

TEST_USER = "testuser"
_real_get_auth = auth.get_authenticated_user


def setup_module(module):
    auth.get_authenticated_user = lambda cookie_header: TEST_USER


def teardown_module(module):
    auth.get_authenticated_user = _real_get_auth


def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestParamInjection:
    def test_tg_get_blocks_type_injection(self):
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
                f"http://127.0.0.1:{port}/tg?action=get_dialogs&type=http&url=http://169.254.169.254/",
                timeout=5,
            )

        assert sent_data.get("type") == "command", "type should be 'command', not injected value"
        assert "url" not in sent_data, "url should not be forwarded"
        server.server_close()

    def test_tg_get_blocks_service_injection(self):
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
                f"http://127.0.0.1:{port}/tg?action=get_dialogs&service=browser&method=GET",
                timeout=5,
            )

        assert sent_data.get("service") == "telegram", "service should be 'telegram', not injected"
        assert "method" not in sent_data, "method should not be forwarded"
        server.server_close()

    def test_tg_get_allows_whitelisted_keys(self):
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
                f"http://127.0.0.1:{port}/tg?action=get_messages&chat_id=123&limit=20",
                timeout=5,
            )

        assert sent_data.get("chat_id") == 123
        assert sent_data.get("limit") == 20
        server.server_close()

    def test_tg_post_blocks_type_injection(self):
        import ioe_web
        import transport as transport_mod

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        sent_data = {}

        def capture_send(m, req):
            sent_data.update(req)

        with (
            patch.object(handler, "imap_conn") as mc1,
            patch.object(handler, "send_request", side_effect=capture_send),
            patch.object(transport_mod, "_create_conn") as mc2,
            patch.object(transport_mod, "send_request", side_effect=capture_send),
        ):
            mc1.return_value = MagicMock()
            mc2.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            body = json.dumps(
                {
                    "action": "get_dialogs",
                    "type": "http",
                    "url": "http://169.254.169.254/",
                }
            ).encode()
            req = Request(
                f"http://127.0.0.1:{port}/tg",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            urlopen(req, timeout=5)

        assert sent_data.get("type") == "command"
        assert "url" not in sent_data
        server.server_close()

    def test_login_tg_post_blocks_type_injection(self):
        import ioe_web
        import transport as transport_mod

        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        sent_data = {}

        def capture_send(m, req):
            sent_data.update(req)

        with (
            patch.object(handler, "imap_conn") as mc1,
            patch.object(handler, "send_request", side_effect=capture_send),
            patch.object(transport_mod, "_create_conn") as mc2,
            patch.object(transport_mod, "send_request", side_effect=capture_send),
            patch.object(auth, "is_whitelisted", return_value=True),
            patch.object(auth, "check_rate_limit", return_value=True),
        ):
            mc1.return_value = MagicMock()
            mc2.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            body = json.dumps(
                {
                    "action": "auth_start",
                    "phone": "+79991234567",
                    "type": "http",
                    "url": "http://169.254.169.254/",
                }
            ).encode()
            req = Request(
                f"http://127.0.0.1:{port}/login/tg",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            urlopen(req, timeout=5)

        assert sent_data.get("type") == "command", "type should be 'command' in login/tg POST"
        assert "url" not in sent_data, "url should not be forwarded in login/tg POST"
        server.server_close()
