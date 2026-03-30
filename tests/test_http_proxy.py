"""Tests for HTTP proxy layer (Tasks 2-6)."""
import json
import sys
import os
import types
import time

_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "server"))
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
sys.modules["requests"].get = lambda *a, **kw: None
sys.modules["requests"].request = lambda *a, **kw: None
sys.modules["requests"].Session = type("Session", (), {
    "request": lambda *a, **kw: None,
    "close": lambda self: None,
})

def _mock_trafilatura_extract(html, **kw):
    return None

sys.modules["trafilatura"].extract = _mock_trafilatura_extract

os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IOE_SECRET", "test-secret-key")

import unittest
from unittest.mock import patch, MagicMock
import server as srv


class TestProtocolRouting(unittest.TestCase):

    def test_http_type_routes_to_handle_http_proxy(self):
        with patch.object(srv, "handle_http_proxy", return_value={"status_code": 200}) as mock_h:
            result = srv.dispatch_request({"type": "http", "url": "https://example.com", "method": "GET"})
            mock_h.assert_called_once()
            self.assertEqual(result["status_code"], 200)

    def test_command_type_unknown_service_returns_400(self):
        result = srv.dispatch_request({"type": "command", "service": "nonexistent"})
        self.assertEqual(result["status"], 400)
        self.assertIn("unknown service", result["error"])

    def test_unknown_type_returns_400(self):
        result = srv.dispatch_request({"type": "banana"})
        self.assertEqual(result["status"], 400)
        self.assertIn("banana", result["error"])

    def test_no_type_returns_none(self):
        result = srv.dispatch_request({"cmd": "GET", "url": "https://example.com"})
        self.assertIsNone(result)

    def test_session_start_type(self):
        result = srv.dispatch_request({"type": "session_start", "session_id": "s1"})
        self.assertIn("session_id", result)
        srv._sessions.clear()

    def test_session_end_type(self):
        srv._sessions["s2"] = {"session": MagicMock(), "created": time.time()}
        result = srv.dispatch_request({"type": "session_end", "session_id": "s2"})
        self.assertNotIn("s2", srv._sessions)


class TestHttpProxyGet(unittest.TestCase):

    @patch("server.requests.request")
    @patch("server.check_rate_limit")
    @patch("server.validate_url")
    def test_get_returns_status_and_body(self, mock_val, mock_rate, mock_req):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.text = '{"ok": true}'
        mock_resp.url = "https://api.example.com/data"
        mock_req.return_value = mock_resp

        result = srv.handle_http_proxy({"method": "GET", "url": "https://api.example.com/data"})
        self.assertEqual(result["type"], "http_response")
        self.assertEqual(result["status_code"], 200)
        self.assertIn("ok", result["body"])

    @patch("server.check_rate_limit")
    @patch("server.validate_url", side_effect=ValueError("Blocked host"))
    def test_blocked_url_returns_403(self, mock_val, mock_rate):
        result = srv.handle_http_proxy({"method": "GET", "url": "http://127.0.0.1/secret"})
        self.assertEqual(result["status_code"], 403)
        self.assertIn("Blocked", result["error"])

    @patch("server.requests.request", side_effect=Exception("Connection refused"))
    @patch("server.check_rate_limit")
    @patch("server.validate_url")
    def test_request_exception_returns_502(self, mock_val, mock_rate, mock_req):
        result = srv.handle_http_proxy({"method": "GET", "url": "https://down.example.com"})
        self.assertEqual(result["status_code"], 502)
        self.assertIn("Connection refused", result["error"])

    @patch("server.check_rate_limit", side_effect=ValueError("Rate limit exceeded"))
    def test_rate_limit_returns_403(self, mock_rate):
        result = srv.handle_http_proxy({"method": "GET", "url": "https://example.com"})
        self.assertEqual(result["status_code"], 403)

    @patch("server.requests.request")
    @patch("server.check_rate_limit")
    @patch("server.validate_url")
    def test_body_truncated_to_max(self, mock_val, mock_rate, mock_req):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "text/plain"}
        mock_resp.text = "x" * (srv.MAX_BODY + 1000)
        mock_resp.url = "https://example.com"
        mock_req.return_value = mock_resp

        result = srv.handle_http_proxy({"method": "GET", "url": "https://example.com"})
        self.assertLessEqual(len(result["body"]), srv.MAX_BODY)


class TestHttpProxyPost(unittest.TestCase):

    @patch("server.requests.request")
    @patch("server.check_rate_limit")
    @patch("server.validate_url")
    def test_post_json_body(self, mock_val, mock_rate, mock_req):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.text = '{"id": 1}'
        mock_resp.url = "https://api.example.com/items"
        mock_req.return_value = mock_resp

        result = srv.handle_http_proxy({
            "method": "POST", "url": "https://api.example.com/items",
            "body": {"name": "test"}, "content_type": "json",
        })
        self.assertEqual(result["status_code"], 201)
        mock_req.assert_called_once()
        _, kwargs = mock_req.call_args
        self.assertEqual(kwargs["json"], {"name": "test"})

    @patch("server.requests.request")
    @patch("server.check_rate_limit")
    @patch("server.validate_url")
    def test_post_form_body(self, mock_val, mock_rate, mock_req):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.text = "ok"
        mock_resp.url = "https://example.com/form"
        mock_req.return_value = mock_resp

        result = srv.handle_http_proxy({
            "method": "POST", "url": "https://example.com/form",
            "body": "key=value", "content_type": "form",
        })
        _, kwargs = mock_req.call_args
        self.assertEqual(kwargs["data"], "key=value")

    @patch("server.requests.request")
    @patch("server.check_rate_limit")
    @patch("server.validate_url")
    def test_put_with_body(self, mock_val, mock_rate, mock_req):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.text = "updated"
        mock_resp.url = "https://example.com/item/1"
        mock_req.return_value = mock_resp

        srv.handle_http_proxy({
            "method": "PUT", "url": "https://example.com/item/1",
            "body": {"name": "updated"},
        })
        _, kwargs = mock_req.call_args
        self.assertEqual(kwargs["json"], {"name": "updated"})

    @patch("server.requests.request")
    @patch("server.check_rate_limit")
    @patch("server.validate_url")
    def test_delete_no_body(self, mock_val, mock_rate, mock_req):
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_resp.headers = {}
        mock_resp.text = ""
        mock_resp.url = "https://example.com/item/1"
        mock_req.return_value = mock_resp

        srv.handle_http_proxy({"method": "DELETE", "url": "https://example.com/item/1"})
        _, kwargs = mock_req.call_args
        self.assertNotIn("json", kwargs)
        self.assertNotIn("data", kwargs)


class TestContentPipeline(unittest.TestCase):

    @patch("server.smart_extract")
    @patch("server.requests.request")
    @patch("server.check_rate_limit")
    @patch("server.validate_url")
    def test_html_triggers_extraction(self, mock_val, mock_rate, mock_req, mock_extract):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "text/html; charset=utf-8"}
        mock_resp.text = "<html><body>Hello</body></html>"
        mock_resp.url = "https://example.com/page"
        mock_req.return_value = mock_resp
        mock_extract.return_value = {
            "title": "Page", "body": "Hello", "format": "markdown",
            "type": "article", "domain": "example.com", "word_count": 1,
        }

        result = srv.handle_http_proxy({"method": "GET", "url": "https://example.com/page"})
        mock_extract.assert_called_once()
        self.assertIn("extracted", result)
        self.assertEqual(result["page_type"], "article")

    @patch("server.requests.request")
    @patch("server.check_rate_limit")
    @patch("server.validate_url")
    def test_json_no_extraction(self, mock_val, mock_rate, mock_req):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.text = '{"data": 1}'
        mock_resp.url = "https://api.example.com"
        mock_req.return_value = mock_resp

        with patch.object(srv, "smart_extract") as mock_extract:
            result = srv.handle_http_proxy({"method": "GET", "url": "https://api.example.com"})
            mock_extract.assert_not_called()
            self.assertNotIn("extracted", result)

    @patch("server.smart_extract")
    @patch("server.requests.request")
    @patch("server.check_rate_limit")
    @patch("server.validate_url")
    def test_extract_false_disables(self, mock_val, mock_rate, mock_req, mock_extract):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.text = "<html>hi</html>"
        mock_resp.url = "https://example.com"
        mock_req.return_value = mock_resp

        result = srv.handle_http_proxy({
            "method": "GET", "url": "https://example.com", "extract": False,
        })
        mock_extract.assert_not_called()
        self.assertNotIn("extracted", result)

    @patch("server.smart_extract", side_effect=Exception("extraction failed"))
    @patch("server.requests.request")
    @patch("server.check_rate_limit")
    @patch("server.validate_url")
    def test_extract_failure_doesnt_break_response(self, mock_val, mock_rate, mock_req, mock_extract):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.text = "<html>hi</html>"
        mock_resp.url = "https://example.com"
        mock_req.return_value = mock_resp

        result = srv.handle_http_proxy({"method": "GET", "url": "https://example.com"})
        self.assertEqual(result["status_code"], 200)
        self.assertNotIn("extracted", result)


class TestSessions(unittest.TestCase):

    def setUp(self):
        srv._sessions.clear()

    def test_session_start_creates_session(self):
        result = srv.dispatch_request({"type": "session_start", "session_id": "test-s1"})
        self.assertIn("test-s1", srv._sessions)
        self.assertEqual(result["session_id"], "test-s1")

    def test_session_end_removes_session(self):
        mock_session = MagicMock()
        srv._sessions["test-s2"] = {"session": mock_session, "created": time.time()}
        result = srv.dispatch_request({"type": "session_end", "session_id": "test-s2"})
        self.assertNotIn("test-s2", srv._sessions)
        mock_session.close.assert_called_once()

    def test_session_end_nonexistent_returns_error(self):
        result = srv.dispatch_request({"type": "session_end", "session_id": "nope"})
        self.assertIn("error", result)

    @patch("server.requests.request")
    @patch("server.check_rate_limit")
    @patch("server.validate_url")
    def test_http_uses_session_when_provided(self, mock_val, mock_rate, mock_req):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.text = "{}"
        mock_resp.url = "https://example.com"
        mock_session.request.return_value = mock_resp
        srv._sessions["s-http"] = {"session": mock_session, "created": time.time()}

        result = srv.handle_http_proxy({
            "method": "GET", "url": "https://example.com", "session_id": "s-http",
        })
        mock_session.request.assert_called_once()
        mock_req.assert_not_called()
        self.assertEqual(result["status_code"], 200)

    def test_cleanup_removes_expired(self):
        srv._sessions["old"] = {"session": MagicMock(), "created": time.time() - srv.SESSION_TTL - 10}
        srv._sessions["new"] = {"session": MagicMock(), "created": time.time()}
        srv._cleanup_sessions()
        self.assertNotIn("old", srv._sessions)
        self.assertIn("new", srv._sessions)


class TestUserIdRouting(unittest.TestCase):

    def test_dispatch_session_start_includes_user_id_from_request(self):
        result = srv.dispatch_request({"type": "session_start", "user_id": "denis"})
        self.assertEqual(result["status"], 200)
        self.assertEqual(result.get("user_id"), "denis")

    def test_dispatch_default_user_id_when_missing(self):
        result = srv.dispatch_request({"type": "session_start"})
        self.assertEqual(result["status"], 200)
        self.assertEqual(result.get("user_id"), "default")

    def test_dispatch_unknown_type_preserves_user_id(self):
        result = srv.dispatch_request({"type": "banana", "user_id": "alice"})
        self.assertEqual(result["status"], 400)
        self.assertEqual(result.get("user_id"), "alice")

    def test_dispatch_http_preserves_user_id(self):
        with patch.object(srv, "handle_http_proxy", return_value={"status_code": 200}) as mock_h:
            result = srv.dispatch_request({"type": "http", "url": "https://x.com", "method": "GET", "user_id": "bob"})
            self.assertEqual(result.get("user_id"), "bob")

    def test_dispatch_session_end_preserves_user_id(self):
        srv._sessions["test-sid"] = {"session": MagicMock(), "created": time.time()}
        result = srv.dispatch_request({"type": "session_end", "session_id": "test-sid", "user_id": "carol"})
        self.assertEqual(result["status"], 200)
        self.assertEqual(result.get("user_id"), "carol")

    def test_dispatch_none_type_returns_none_unchanged(self):
        result = srv.dispatch_request({"cmd": "GET", "user_id": "denis"})
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
