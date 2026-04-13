"""Тесты login flows: POST /login/tg и POST /login/email."""

import json
import os
import socket
import sys
import threading
from http.server import HTTPServer
from unittest.mock import MagicMock, patch
from urllib.request import Request, urlopen

_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "webui"))
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "pass")
os.environ.setdefault("IOE_SECRET", "secret123")

import auth
import handler
import ioe_web

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


def post_json(port, path, payload, *, n_requests=1):
    """Отправляет POST JSON, возвращает (status, dict)."""
    server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
    results = []

    def serve():
        for _ in range(n_requests):
            server.handle_request()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    data = json.dumps(payload).encode()
    req = Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urlopen(req, timeout=5)
        body = json.loads(resp.read().decode())
        results.append((resp.status, body))
    except Exception as exc:
        # HTTP errors (4xx) raise URLError — read the body from it
        import urllib.error

        if isinstance(exc, urllib.error.HTTPError):
            body = json.loads(exc.read().decode())
            results.append((exc.code, body))
        else:
            raise
    t.join(timeout=3)
    server.server_close()
    return results[0]


# ---------------------------------------------------------------------------
# /login/tg tests
# ---------------------------------------------------------------------------


class TestLoginTgPost:
    def test_tg_auth_start_not_whitelisted(self):
        """Телефон не в whitelist → возвращает pending (фейковый ответ)."""
        port = get_free_port()
        with (
            patch.object(auth, "is_whitelisted", return_value=False),
            patch.object(handler, "imap_conn"),
            patch.object(handler, "send_request"),
            patch.object(handler, "poll_response"),
        ):
            status, body = post_json(port, "/login/tg", {"action": "auth_start", "phone": "+70000000000"})
        assert status == 200
        assert body["status"] == "pending"
        assert "id" in body

    def test_tg_auth_start_ok(self):
        """Телефон в whitelist, auth_start → pending с id."""
        port = get_free_port()
        mock_m = MagicMock()
        with (
            patch.object(auth, "is_whitelisted", return_value=True),
            patch.object(handler, "imap_conn", return_value=mock_m),
            patch.object(handler, "send_request"),
            patch.object(handler, "poll_response"),
        ):
            status, body = post_json(port, "/login/tg", {"action": "auth_start", "phone": "+79001234567"})
        assert status == 200
        assert body["status"] == "pending"
        assert "id" in body

    def test_tg_auth_code_ok(self):
        """auth_code с корректными данными → pending."""
        port = get_free_port()
        mock_m = MagicMock()
        with (
            patch.object(auth, "is_whitelisted", return_value=True),
            patch.object(handler, "imap_conn", return_value=mock_m),
            patch.object(handler, "send_request"),
            patch.object(handler, "poll_response"),
        ):
            status, body = post_json(
                port, "/login/tg", {"action": "auth_code", "phone": "+79001234567", "code": "12345"}
            )
        assert status == 200
        assert body["status"] == "pending"

    def test_tg_check_auth_ok(self):
        """check_auth → pending."""
        port = get_free_port()
        mock_m = MagicMock()
        with (
            patch.object(auth, "is_whitelisted", return_value=True),
            patch.object(handler, "imap_conn", return_value=mock_m),
            patch.object(handler, "send_request"),
            patch.object(handler, "poll_response"),
        ):
            status, body = post_json(port, "/login/tg", {"action": "check_auth", "phone": "+79001234567"})
        assert status == 200
        assert body["status"] == "pending"

    def test_tg_auth_logout(self):
        """auth_logout → pending."""
        port = get_free_port()
        mock_m = MagicMock()
        with (
            patch.object(auth, "is_whitelisted", return_value=True),
            patch.object(handler, "imap_conn", return_value=mock_m),
            patch.object(handler, "send_request"),
            patch.object(handler, "poll_response"),
        ):
            status, body = post_json(port, "/login/tg", {"action": "auth_logout", "phone": "+79001234567"})
        assert status == 200
        assert body["status"] == "pending"

    def test_tg_forbidden_action(self):
        """Неизвестный action → error."""
        port = get_free_port()
        with (
            patch.object(handler, "imap_conn"),
            patch.object(handler, "send_request"),
            patch.object(handler, "poll_response"),
        ):
            status, body = post_json(port, "/login/tg", {"action": "hack"})
        assert body["status"] == "error"

    def test_tg_auth_ip_rate_limited(self):
        """IP rate limit превышен → error."""
        port = get_free_port()
        with patch.object(auth, "check_rate_limit", return_value=False):
            status, body = post_json(port, "/login/tg", {"action": "auth_start", "phone": "+79001234567"})
        assert status == 200
        assert body["status"] == "error"
        assert "одожд" in body["error"].lower() or "минут" in body["error"].lower()

    def test_tg_imap_error(self):
        """Ошибка IMAP при send → возвращает error."""
        port = get_free_port()
        with (
            patch.object(auth, "is_whitelisted", return_value=True),
            patch.object(handler, "imap_conn", side_effect=Exception("timeout")),
            patch.object(handler, "send_request"),
            patch.object(handler, "poll_response"),
        ):
            status, body = post_json(port, "/login/tg", {"action": "auth_start", "phone": "+79001234567"})
        assert body["status"] == "error"


# ---------------------------------------------------------------------------
# /login/email tests
# ---------------------------------------------------------------------------


class TestLoginEmailPost:
    def test_email_send_code_not_whitelisted(self):
        """Телефон не в whitelist → code_sent (honeypot, не раскрываем что не whitelist)."""
        port = get_free_port()
        with patch.object(auth, "is_whitelisted", return_value=False):
            status, body = post_json(port, "/login/email", {"action": "send_code", "phone": "+70000000000"})
        assert status == 200
        assert body["status"] == "code_sent"

    def test_email_send_code_ok(self):
        """Телефон в whitelist, TOTP secret есть → code_sent."""
        port = get_free_port()
        with (
            patch.object(auth, "is_whitelisted", return_value=True),
            patch.object(auth, "check_rate_limit", return_value=True),
            patch.object(auth, "get_user_totp_secret", return_value="TESTSECRET"),
        ):
            status, body = post_json(port, "/login/email", {"action": "send_code", "phone": "+79001234567"})
        assert status == 200
        assert body["status"] == "code_sent"

    def test_email_send_code_rate_limited(self):
        """Превышен rate limit → error."""
        port = get_free_port()
        with (
            patch.object(auth, "is_whitelisted", return_value=True),
            patch.object(auth, "check_rate_limit", return_value=False),
        ):
            status, body = post_json(port, "/login/email", {"action": "send_code", "phone": "+79001234567"})
        assert status == 200
        assert body["status"] == "error"

    def test_email_send_code_no_email_configured(self):
        """TOTP secret не настроен → setup_required."""
        port = get_free_port()
        with (
            patch.object(auth, "is_whitelisted", return_value=True),
            patch.object(auth, "check_rate_limit", return_value=True),
            patch.object(auth, "get_user_totp_secret", return_value=None),
        ):
            status, body = post_json(port, "/login/email", {"action": "send_code", "phone": "+79001234567"})
        assert status == 200
        assert body["status"] == "setup_required"

    def test_email_verify_code_ok(self):
        """Верный код → authorized + Set-Cookie."""
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        with (
            patch.object(auth, "check_rate_limit", return_value=True),
            patch.object(auth, "verify_totp", return_value=True),
            patch.object(auth, "create_session", return_value="abc123"),
        ):
            data = json.dumps({"action": "verify_code", "phone": "+79001234567", "code": "123456"}).encode()
            req = Request(
                f"http://127.0.0.1:{port}/login/email",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urlopen(req, timeout=5)
            body = json.loads(resp.read().decode())
            cookie = resp.headers.get("Set-Cookie", "")
        t.join(timeout=3)
        server.server_close()
        assert body["status"] == "authorized"
        assert "sid=abc123" in cookie

    def test_email_verify_code_wrong(self):
        """Неверный код → error."""
        port = get_free_port()
        with (
            patch.object(auth, "check_rate_limit", return_value=True),
            patch.object(auth, "verify_totp", return_value=False),
        ):
            status, body = post_json(
                port, "/login/email", {"action": "verify_code", "phone": "+79001234567", "code": "000000"}
            )
        assert status == 200
        assert body["status"] == "error"

    def test_email_verify_code_missing_fields(self):
        """Пустые code/phone → error."""
        port = get_free_port()
        status, body = post_json(port, "/login/email", {"action": "verify_code", "phone": "", "code": ""})
        assert body["status"] == "error"

    def test_email_unknown_action(self):
        """Неизвестный action → error."""
        port = get_free_port()
        status, body = post_json(port, "/login/email", {"action": "unknown"})
        assert body["status"] == "error"

    def test_confirm_totp_rejects_non_whitelisted(self):
        """confirm_totp отклоняет номер не из whitelist."""
        port = get_free_port()
        with patch.object(auth, "is_whitelisted", return_value=False):
            status, body = post_json(
                port,
                "/login/email",
                {"action": "confirm_totp", "phone": "+70000000000", "secret": "JBSWY3DPEHPK3PXP", "code": "123456"},
            )
        assert body["status"] == "error"

    def test_confirm_totp_rejects_when_secret_exists(self):
        """confirm_totp нельзя перезаписать существующий TOTP secret."""
        port = get_free_port()
        with (
            patch.object(auth, "is_whitelisted", return_value=True),
            patch.object(auth, "check_rate_limit", return_value=True),
            patch.object(auth, "get_user_totp_secret", return_value="EXISTING_SECRET"),
        ):
            status, body = post_json(
                port,
                "/login/email",
                {"action": "confirm_totp", "phone": "+79001234567", "secret": "NEW_SECRET", "code": "123456"},
            )
        assert body["status"] == "error"
        assert "уже настроен" in body["error"]

    def test_confirm_totp_rejects_arbitrary_client_secret(self):
        """confirm_totp без server-side pending secret — отклоняет."""
        port = get_free_port()
        with (
            patch.object(auth, "is_whitelisted", return_value=True),
            patch.object(auth, "check_rate_limit", return_value=True),
            patch.object(auth, "get_user_totp_secret", return_value=None),
            patch.object(auth, "get_pending_totp", return_value=None),
        ):
            status, body = post_json(
                port,
                "/login/email",
                {"action": "confirm_totp", "phone": "+79001234567", "secret": "ATTACKER_SECRET", "code": "123456"},
            )
        assert body["status"] == "error"

    def test_confirm_totp_uses_pending_secret(self):
        """confirm_totp использует server-side pending secret, а не secret из body."""
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        pending = "SERVER_SIDE_SECRET"
        with (
            patch.object(auth, "is_whitelisted", return_value=True),
            patch.object(auth, "check_rate_limit", return_value=True),
            patch.object(auth, "get_user_totp_secret", return_value=None),
            patch.object(auth, "get_pending_totp", return_value=pending),
            patch.object(auth, "verify_totp_with_secret", return_value=True) as mock_verify,
            patch.object(auth, "set_user_totp_secret") as mock_set,
            patch.object(auth, "clear_pending_totp") as mock_clear,
            patch.object(auth, "create_session", return_value="sess123"),
        ):
            data = json.dumps(
                {"action": "confirm_totp", "phone": "+79001234567", "secret": "IGNORED_CLIENT_SECRET", "code": "123456"}
            ).encode()
            req = Request(
                f"http://127.0.0.1:{port}/login/email",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urlopen(req, timeout=5)
            body = json.loads(resp.read().decode())
        t.join(timeout=3)
        server.server_close()
        assert body["status"] == "authorized"
        mock_verify.assert_called_once_with(pending, "123456")
        mock_set.assert_called_once_with("+79001234567", pending)
        mock_clear.assert_called_once()

    def test_verify_code_rate_limited(self):
        """verify_code блокируется при rate limit."""
        port = get_free_port()
        with (
            patch.object(auth, "check_rate_limit", return_value=False),
            patch.object(auth, "is_whitelisted", return_value=True),
        ):
            status, body = post_json(
                port,
                "/login/email",
                {"action": "verify_code", "phone": "+79001234567", "code": "000000"},
            )
        assert body["status"] == "error"
        assert "одожд" in body["error"].lower() or "минут" in body["error"].lower()
