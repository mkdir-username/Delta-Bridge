"""Tests for Claude-over-IoE proxy: crypto helpers, serialization, handler."""
import json
import sys
import os
import types

_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "server"))
sys.path.insert(0, os.path.join(_root, "client"))
sys.path.insert(0, os.path.dirname(__file__))

for _mod in ["truststore", "imapclient", "readability", "PIL", "PIL.Image", "requests", "trafilatura"]:
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
sys.modules["requests"].Session = type("Session", (), {
    "request": lambda *a, **kw: _mock_resp,
    "close": lambda self: None,
})
sys.modules["requests"].Timeout = TimeoutError

os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IOE_SECRET", "test-secret-key")

from ioe_crypto import derive_key, encrypt, decrypt, compress_encrypt, decrypt_decompress
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
    ioe_server.requests.Session = type("Session", (), {
        "request": lambda *a, **kw: _mock_resp,
        "close": lambda self: None,
    })
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
                    "headers": {"host": "api.anthropic.com", "content-type": "application/json"},
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
                "http_request": {"method": "GET", "path": "/", "headers": {}, "body": None},
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
                "body": json.dumps({"model": "claude-opus-4-20250514", "messages": [{"role": "user", "content": "hi"}]}),
            },
        }
        encrypted = compress_encrypt(key, json.dumps(request))
        decrypted = decrypt_decompress(key, encrypted)
        restored = json.loads(decrypted)
        assert restored["id"] == "test-123"
        assert restored["http_request"]["headers"]["authorization"] == "Bearer token"
