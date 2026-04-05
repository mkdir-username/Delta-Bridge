"""Tests for Claude-over-IoE proxy: crypto helpers, serialization, handler."""

import json
import sys
import os
import types

_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "server"))
sys.path.insert(0, os.path.join(_root, "client"))
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
        pass

    def title(self):
        return "Mock Title"

    def summary(self):
        return "<p>Mock</p>"


sys.modules["readability"].Document = _MockDoc
sys.modules["PIL.Image"] = sys.modules["PIL"]
sys.modules["PIL"].Image = sys.modules["PIL"]
sys.modules["trafilatura"].extract = lambda html, **kw: None

_mock_resp = types.SimpleNamespace(
    status_code=200,
    headers={"content-type": "application/json"},
    text='{"id":"msg_123","content":[{"type":"text","text":"hello"}]}',
    url="https://api.anthropic.com/v1/messages",
)

sys.modules["requests"].get = lambda *a, **kw: _mock_resp
sys.modules["requests"].request = lambda *a, **kw: _mock_resp
sys.modules["requests"].Session = type(
    "Session",
    (),
    {
        "request": lambda *a, **kw: _mock_resp,
        "close": lambda self: None,
    },
)
sys.modules["requests"].Timeout = TimeoutError

os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IOE_SECRET", "test-secret-key")

from ioe_crypto import derive_key, encrypt, compress_encrypt, decrypt_decompress
import server as ioe_server

ioe_server.requests = sys.modules["requests"]


class TestGzipCrypto:
    def test_compress_encrypt_roundtrip(self):
        key = derive_key("test-secret")
        original = "hello world" * 1000
        encrypted = compress_encrypt(key, original)
        decrypted = decrypt_decompress(key, encrypted)
        assert decrypted == original

    def test_compress_encrypt_smaller_than_plain_encrypt(self):
        key = derive_key("test-secret")
        large_json = json.dumps({"text": "a" * 10000, "id": "msg_123"})
        compressed = compress_encrypt(key, large_json)
        plain = encrypt(key, large_json)
        assert len(compressed) < len(plain)

    def test_decrypt_decompress_backward_compat(self):
        key = derive_key("test-secret")
        original = "short text"
        encrypted = encrypt(key, original)
        decrypted = decrypt_decompress(key, encrypted)
        assert decrypted == original

    def test_large_payload(self):
        key = derive_key("test-secret")
        payload = json.dumps({"content": [{"text": "x" * 500_000}]})
        encrypted = compress_encrypt(key, payload)
        decrypted = decrypt_decompress(key, encrypted)
        assert decrypted == payload


import pytest


@pytest.fixture(autouse=True)
def _patch_requests():
    old_request = ioe_server.requests.request
    old_session = ioe_server.requests.Session
    ioe_server.requests.request = lambda *a, **kw: _mock_resp
    ioe_server.requests.Session = type(
        "Session",
        (),
        {
            "request": lambda *a, **kw: _mock_resp,
            "close": lambda self: None,
        },
    )
    ioe_server._claude_session = None
    yield
    ioe_server.requests.request = old_request
    ioe_server.requests.Session = old_session
    ioe_server._claude_session = None


class TestHandleClaudeProxy:
    def test_basic_request(self):
        request = {
            "type": "claude_proxy",
            "id": "req-1",
            "user_id": "claude",
            "http_request": {
                "method": "POST",
                "path": "/v1/messages",
                "headers": {
                    "authorization": "Bearer sk-ant-oat01-test",
                    "content-type": "application/json",
                    "host": "api.anthropic.com",
                },
                "body": json.dumps({"model": "claude-opus-4-20250514", "stream": True, "messages": []}),
            },
        }
        result = ioe_server.handle_claude_proxy(request)
        assert result["type"] == "claude_proxy_response"
        assert result["http_response"]["status_code"] == 200
        assert "msg_123" in result["http_response"]["body"]

    def test_stream_passthrough(self):
        captured = {}

        class CapturingSession:
            def request(self, method, url, **kwargs):
                data = kwargs.get("data", b"")
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                captured["body"] = data
                return _mock_resp

            def close(self):
                pass

        ioe_server._claude_session = CapturingSession()
        try:
            request = {
                "type": "claude_proxy",
                "http_request": {
                    "method": "POST",
                    "path": "/v1/messages",
                    "headers": {
                        "host": "api.anthropic.com",
                        "content-type": "application/json",
                    },
                    "body": json.dumps({"model": "claude-opus-4-20250514", "stream": True}),
                },
            }
            ioe_server.handle_claude_proxy(request)
            body = json.loads(captured["body"])
            assert body["stream"] is True
        finally:
            ioe_server._claude_session = None

    def test_localhost_host_replaced(self):
        captured = {}

        class CapturingSession:
            def request(self, method, url, **kwargs):
                captured["url"] = url
                return _mock_resp

            def close(self):
                pass

        ioe_server._claude_session = CapturingSession()
        try:
            request = {
                "type": "claude_proxy",
                "http_request": {
                    "method": "GET",
                    "path": "/v1/models",
                    "headers": {"host": "localhost:8090"},
                    "body": None,
                },
            }
            ioe_server.handle_claude_proxy(request)
            assert "api.anthropic.com" in captured["url"]
        finally:
            ioe_server._claude_session = None

    def test_timeout_returns_504(self):
        class TimeoutSession:
            def request(self, *a, **kw):
                raise TimeoutError("timeout")

            def close(self):
                pass

        ioe_server._claude_session = TimeoutSession()
        try:
            request = {
                "type": "claude_proxy",
                "http_request": {
                    "method": "GET",
                    "path": "/",
                    "headers": {},
                    "body": None,
                },
            }
            result = ioe_server.handle_claude_proxy(request)
            assert result["http_response"]["status_code"] == 504
        finally:
            ioe_server._claude_session = None

    def test_dispatch_routes_claude_proxy(self):
        request = {
            "type": "claude_proxy",
            "id": "req-2",
            "user_id": "claude",
            "http_request": {
                "method": "POST",
                "path": "/v1/messages",
                "headers": {"host": "api.anthropic.com"},
                "body": "{}",
            },
        }
        result = ioe_server.dispatch_request(request)
        assert result is not None
        assert result["type"] == "claude_proxy_response"
        assert result["user_id"] == "claude"

    def test_session_reused_across_calls(self):
        call_count = {"n": 0}
        OrigSession = ioe_server.requests.Session

        class CountingSession:
            def __init__(self):
                call_count["n"] += 1

            def request(self, *a, **kw):
                return _mock_resp

            def close(self):
                pass

        ioe_server.requests.Session = CountingSession
        ioe_server._claude_session = None
        try:
            req = {
                "type": "claude_proxy",
                "http_request": {
                    "method": "POST",
                    "path": "/v1/messages",
                    "headers": {"host": "api.anthropic.com"},
                    "body": "{}",
                },
            }
            for _ in range(3):
                ioe_server.handle_claude_proxy(req)
            assert call_count["n"] == 1
        finally:
            ioe_server.requests.Session = OrigSession
            ioe_server._claude_session = None


class TestSerialization:
    def test_full_roundtrip(self):
        key = derive_key("test-secret")
        request = {
            "type": "claude_proxy",
            "id": "test-123",
            "http_request": {
                "method": "POST",
                "path": "/v1/messages",
                "headers": {"authorization": "Bearer token"},
                "body": json.dumps(
                    {
                        "model": "claude-opus-4-20250514",
                        "messages": [{"role": "user", "content": "hi"}],
                    }
                ),
            },
        }
        encrypted = compress_encrypt(key, json.dumps(request))
        decrypted = decrypt_decompress(key, encrypted)
        restored = json.loads(decrypted)
        assert restored["id"] == "test-123"
        assert restored["http_request"]["headers"]["authorization"] == "Bearer token"


import importlib.util
from io import BytesIO
from unittest.mock import MagicMock, patch
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

_cp_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "client", "claude_proxy.py")
_cp_spec = importlib.util.spec_from_file_location("claude_proxy", _cp_path)
claude_proxy = importlib.util.module_from_spec(_cp_spec)  # type: ignore[arg-type]
_cp_spec.loader.exec_module(claude_proxy)  # type: ignore[union-attr]


class TestExtractAttachment:
    def test_извлекает_pdf_вложение(self):
        msg = MIMEMultipart()
        msg["Subject"] = "test"
        msg["From"] = "a@b.com"
        msg["To"] = "a@b.com"
        msg.attach(MIMEText("body", "plain", "utf-8"))
        part = MIMEBase("application", "pdf")
        part.set_payload(b"pdf-data")
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename="file.pdf")
        msg.attach(part)
        result = claude_proxy._extract_attachment(msg.as_bytes())
        assert result == b"pdf-data"

    def test_нет_вложения(self):
        msg = MIMEText("just text", "plain", "utf-8")
        result = claude_proxy._extract_attachment(msg.as_bytes())
        assert result is None


class TestImapConnect:
    def test_подключение_и_логин(self):
        mock_imap = MagicMock()
        with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
            conn = claude_proxy._imap_connect()
        mock_imap.login.assert_called_once()
        assert conn is mock_imap


class TestGetSendConn:
    def setup_method(self, method):
        claude_proxy._send_conn = None

    def teardown_method(self, method):
        claude_proxy._send_conn = None

    def test_создаёт_новое_подключение(self):
        mock_conn = MagicMock()
        with patch.object(claude_proxy, "_imap_connect", return_value=mock_conn):
            result = claude_proxy._get_send_conn()
        assert result is mock_conn
        assert claude_proxy._send_conn is mock_conn

    def test_переиспользует_живое(self):
        mock_conn = MagicMock()
        mock_conn.noop.return_value = ("OK", [])
        claude_proxy._send_conn = mock_conn
        result = claude_proxy._get_send_conn()
        mock_conn.noop.assert_called_once()
        assert result is mock_conn

    def test_пересоздаёт_при_ошибке_noop(self):
        old_conn = MagicMock()
        old_conn.noop.side_effect = Exception("broken")
        claude_proxy._send_conn = old_conn
        new_conn = MagicMock()
        with patch.object(claude_proxy, "_imap_connect", return_value=new_conn):
            result = claude_proxy._get_send_conn()
        assert result is new_conn
        assert claude_proxy._send_conn is new_conn


class TestSendViaImap:
    def test_отправляет_mime_с_вложением(self):
        mock_conn = MagicMock()
        with patch.object(claude_proxy, "_get_send_conn", return_value=mock_conn):
            claude_proxy._send_via_imap(b"encrypted-payload")
        mock_conn.append.assert_called_once()
        args = mock_conn.append.call_args[0]
        assert args[0] == claude_proxy.QUEUE_FOLDER


class TestPollResponse:
    def test_находит_ответ_по_id(self):
        key = derive_key("test-secret-key")
        req_id = "test-req-123"
        response_dict = {
            "id": req_id,
            "type": "claude_proxy_response",
            "http_response": {"status_code": 200, "headers": {}, "body": "ok"},
        }
        encrypted_str = compress_encrypt(key, json.dumps(response_dict))
        encrypted_bytes = encrypted_str.encode("ascii")

        msg = MIMEMultipart()
        msg["Subject"] = "reply"
        part = MIMEBase("application", "pdf")
        part.set_payload(encrypted_bytes)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename="r.pdf")
        msg.attach(part)
        raw = msg.as_bytes()

        mock_imap = MagicMock()
        mock_imap.select.return_value = ("OK", [])
        mock_imap.noop.return_value = ("OK", [])
        mock_imap.search.return_value = ("OK", [b"1"])
        mock_imap.fetch.return_value = ("OK", [(b"1 (RFC822 {100})", raw)])
        mock_imap.store.return_value = ("OK", [])
        mock_imap.expunge.return_value = ("OK", [])

        with (
            patch.object(claude_proxy, "_imap_connect", return_value=mock_imap),
            patch.object(claude_proxy, "IOE_KEY", key),
        ):
            result = claude_proxy._poll_response(req_id)

        assert result is not None
        assert result["id"] == req_id

    def test_таймаут_без_ответа(self):
        mock_imap = MagicMock()
        mock_imap.select.return_value = ("OK", [])
        mock_imap.noop.return_value = ("OK", [])
        mock_imap.search.return_value = ("OK", [b""])

        with (
            patch.object(claude_proxy, "_imap_connect", return_value=mock_imap),
            patch.object(claude_proxy, "POLL_CYCLES", 3),
            patch("time.sleep"),
        ):
            result = claude_proxy._poll_response("no-such-id")

        assert result is None

    def test_ошибка_imap_возвращает_none(self):
        with patch.object(claude_proxy, "_imap_connect", side_effect=Exception("conn refused")):
            result = claude_proxy._poll_response("some-id")
        assert result is None


class TestClaudeProxyHandler:
    def _make_handler(self, method="GET", path="/v1/messages", body=b""):
        handler = claude_proxy.ClaudeProxyHandler.__new__(claude_proxy.ClaudeProxyHandler)
        handler.command = method
        handler.path = path
        handler.headers = {"Content-Length": str(len(body)), "host": "localhost"}
        handler.rfile = BytesIO(body)
        handler.wfile = BytesIO()
        handler.requestline = f"{method} {path} HTTP/1.1"
        handler.client_address = ("127.0.0.1", 12345)
        handler.request_version = "HTTP/1.1"
        handler._headers_buffer = []
        return handler

    def test_отправка_и_получение_ответа(self):
        handler = self._make_handler("POST", "/v1/messages", b'{"model":"test"}')
        response_dict = {
            "id": "x",
            "http_response": {"status_code": 200, "headers": {"content-type": "application/json"}, "body": "{}"},
        }
        with (
            patch.object(claude_proxy, "_send_via_imap"),
            patch.object(claude_proxy, "_poll_response", return_value=response_dict),
            patch.object(claude_proxy, "compress_encrypt", return_value="enc"),
        ):
            handler._handle_request("POST")
        handler.wfile.seek(0)
        out = handler.wfile.read()
        assert b"200" in out

    def test_imap_send_fail_503(self):
        handler = self._make_handler("POST", "/v1/messages", b"{}")
        with (
            patch.object(claude_proxy, "_send_via_imap", side_effect=Exception("IMAP down")),
            patch.object(claude_proxy, "compress_encrypt", return_value="enc"),
        ):
            handler._handle_request("POST")
        handler.wfile.seek(0)
        out = handler.wfile.read()
        assert b"503" in out

    def test_poll_timeout_504(self):
        handler = self._make_handler("GET", "/v1/models")
        with (
            patch.object(claude_proxy, "_send_via_imap"),
            patch.object(claude_proxy, "_poll_response", return_value=None),
            patch.object(claude_proxy, "compress_encrypt", return_value="enc"),
        ):
            handler._handle_request("GET")
        handler.wfile.seek(0)
        out = handler.wfile.read()
        assert b"504" in out

    def test_do_GET_делегирует(self):
        handler = self._make_handler("GET", "/v1/models")
        with patch.object(handler, "_handle_request") as mock_handle:
            handler.do_GET()
        mock_handle.assert_called_once_with("GET")

    def test_log_message(self):
        handler = self._make_handler()
        handler.log_message("%s", "test")


class TestThreadedServer:
    def test_создание_сервера(self):
        server = claude_proxy.ThreadedHTTPServer(("127.0.0.1", 0), claude_proxy.ClaudeProxyHandler)
        assert server.socket is not None
        server.server_close()
