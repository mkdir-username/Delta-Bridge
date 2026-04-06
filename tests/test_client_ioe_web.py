import sys
import os
import types
import json
import email as email_mod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from io import BytesIO
from unittest.mock import MagicMock, patch
import unittest

_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, _root)

for _mod in ["truststore", "imapclient", "readability", "PIL", "PIL.Image", "requests", "trafilatura"]:
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)
sys.modules["truststore"].inject_into_ssl = lambda: None
if not hasattr(sys.modules.get("imapclient", None), "IMAPClient"):
    sys.modules["imapclient"].IMAPClient = type("IMAPClient", (), {})

os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IOE_SECRET", "test-secret-key")

_client_dir = os.path.join(_root, "client")
sys.path.insert(0, _client_dir)
import ioe_web as _client_ioe_web  # noqa: E402

sys.path.remove(_client_dir)
# Re-register under unique name to avoid collision with webui/ioe_web.py
sys.modules["client_ioe_web"] = _client_ioe_web
sys.modules.pop("ioe_web", None)
ioe_web = _client_ioe_web


def _make_email_with_attachment(payload: bytes) -> bytes:
    msg = MIMEMultipart()
    msg["Subject"] = "test"
    msg["From"] = "a@b.com"
    msg["To"] = "a@b.com"
    msg.attach(MIMEText("body", "plain", "utf-8"))
    part = MIMEBase("application", "pdf")
    part.set_payload(payload)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename="doc.pdf")
    msg.attach(part)
    return msg.as_bytes()


class TestExtractAttachment(unittest.TestCase):
    def test_возвращает_байты_при_наличии_вложения(self):
        raw = _make_email_with_attachment(b"hello binary")
        result = ioe_web.extract_attachment(raw)
        assert result == b"hello binary"

    def test_возвращает_none_если_вложений_нет(self):
        msg = MIMEText("plain text", "plain", "utf-8")
        result = ioe_web.extract_attachment(msg.as_bytes())
        assert result is None

    def test_возвращает_первое_вложение_из_нескольких(self):
        outer = MIMEMultipart()
        outer["Subject"] = "multi"
        for content in [b"first", b"second"]:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(content)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename="f.bin")
            outer.attach(part)
        result = ioe_web.extract_attachment(outer.as_bytes())
        assert result == b"first"


class TestRewriteLinks(unittest.TestCase):
    def test_перезаписывает_href_с_двойными_кавычками(self):
        html = '<a href="https://example.com/page">link</a>'
        result = ioe_web.rewrite_links(html)
        assert 'href="/get?url=https://example.com/page"' in result

    def test_перезаписывает_href_с_одинарными_кавычками(self):
        html = "<a href='https://example.com/page'>link</a>"
        result = ioe_web.rewrite_links(html)
        assert "href='/get?url=https://example.com/page'" in result

    def test_не_трогает_относительные_ссылки(self):
        html = '<a href="/local/path">link</a>'
        result = ioe_web.rewrite_links(html)
        assert result == html

    def test_обрабатывает_несколько_ссылок(self):
        html = '<a href="https://a.com">1</a><a href="https://b.com">2</a>'
        result = ioe_web.rewrite_links(html)
        assert "/get?url=https://a.com" in result
        assert "/get?url=https://b.com" in result


class TestIMapConn(unittest.TestCase):
    def test_создаёт_ssl_подключение_и_логинится(self):
        mock_instance = MagicMock()
        with patch("imaplib.IMAP4_SSL", return_value=mock_instance) as mock_ssl:
            result = ioe_web.imap_conn()
        mock_ssl.assert_called_once_with("imap.yandex.ru", 993)
        mock_instance.login.assert_called_once_with(ioe_web.EMAIL, ioe_web.IMAP_PASSWORD)
        assert result is mock_instance


class TestSendRequest(unittest.TestCase):
    def test_отправляет_зашифрованное_mime_сообщение(self):
        mock_imap = MagicMock()
        req = {"id": "abc123", "cmd": "GET", "url": "https://example.com"}

        ioe_web.send_request(mock_imap, req)

        assert mock_imap.append.called
        args = mock_imap.append.call_args[0]
        assert args[0] == ioe_web.QUEUE_FOLDER
        raw_bytes = args[3]
        parsed = email_mod.message_from_bytes(raw_bytes)
        assert parsed["From"] == ioe_web.EMAIL
        assert parsed["To"] == ioe_web.EMAIL
        att = ioe_web.extract_attachment(raw_bytes)
        assert att is not None

    def test_subject_содержит_случайный_суффикс(self):
        mock_imap = MagicMock()
        req = {"id": "x", "cmd": "SEARCH", "query": "test"}

        ioe_web.send_request(mock_imap, req)

        subject = email_mod.message_from_bytes(mock_imap.append.call_args[0][3])["Subject"]
        assert subject is not None
        assert len(subject) > 0


def _make_handler(path: str, query: str = "") -> ioe_web.Handler:
    handler = ioe_web.Handler.__new__(ioe_web.Handler)
    handler.path = path + ("?" + query if query else "")

    buf = BytesIO()
    handler.wfile = buf
    handler.rfile = BytesIO()

    responses: list = []
    handler._responses = responses

    def send_response(code: int, message: str = "") -> None:
        responses.append(("status", code))

    def send_header(k: str, v: str) -> None:
        responses.append(("header", k, v))

    def end_headers() -> None:
        responses.append(("end_headers",))

    def send_error(code: int, message: str = "") -> None:
        responses.append(("error", code))

    handler.send_response = send_response
    handler.send_header = send_header
    handler.end_headers = end_headers
    handler.send_error = send_error
    return handler


class TestHandlerLogMessage(unittest.TestCase):
    def test_не_бросает_исключений(self):
        h = ioe_web.Handler.__new__(ioe_web.Handler)
        h.log_message("%s %s", "GET", "/")


class TestHandlerRespondJson(unittest.TestCase):
    def test_пишет_json_в_wfile(self):
        h = _make_handler("/")
        h.respond_json({"ok": True})
        h.wfile.seek(0)
        body = json.loads(h.wfile.read())
        assert body == {"ok": True}

    def test_использует_переданный_код_ответа(self):
        h = _make_handler("/")
        h.respond_json({"error": "not found"}, code=404)
        assert any(r == ("status", 404) for r in h._responses)


class TestHandlerDemo(unittest.TestCase):
    def test_demo_search_возвращает_результаты(self):
        h = _make_handler("/search", "q=погода")
        h.respond_json = MagicMock()
        h._handle_demo("SEARCH", {"q": ["погода"]}, "req1")
        h.respond_json.assert_called_once()
        resp = h.respond_json.call_args[0][0]
        assert resp["status"] == "ready"
        assert isinstance(resp["results"], list)
        assert len(resp["results"]) > 0

    def test_demo_get_возвращает_страницу(self):
        h = _make_handler("/get", "url=https://example.com")
        h.respond_json = MagicMock()
        h._handle_demo("GET", {"url": ["https://example.com"]}, "req2")
        resp = h.respond_json.call_args[0][0]
        assert resp["status"] == "ready"
        assert "title" in resp
        assert "body" in resp

    def test_demo_неизвестная_команда_возвращает_ошибку(self):
        h = _make_handler("/")
        h.respond_json = MagicMock()
        h._handle_demo("UNKNOWN", {}, "req3")
        resp = h.respond_json.call_args[0][0]
        assert resp["status"] == "error"


class TestPollResponse(unittest.TestCase):
    def _make_imap_with_response(self, req_id, response_dict):
        """Create mock IMAP that returns an encrypted response on first search."""
        from ioe_crypto import encrypt

        encrypted = encrypt(ioe_web.IOE_KEY, json.dumps(response_dict)).encode("ascii")
        raw_email = _make_email_with_attachment(encrypted)

        mock_imap = MagicMock()
        mock_imap.search.return_value = ("OK", [b"1"])
        mock_imap.fetch.return_value = ("OK", [(b"1", raw_email)])
        return mock_imap

    @patch.object(ioe_web, "imap_conn")
    @patch("time.sleep")
    def test_response_found_updates_pending(self, mock_sleep, mock_conn):
        req_id = "test-resp-1"
        response = {"id": req_id, "status": 200, "title": "Hello", "body": "World"}
        mock_conn.return_value = self._make_imap_with_response(req_id, response)

        ioe_web.pending.pop(req_id, None)
        ioe_web.poll_response(req_id)

        assert req_id in ioe_web.pending
        assert ioe_web.pending[req_id]["title"] == "Hello"
        ioe_web.pending.pop(req_id, None)

    @patch.object(ioe_web, "imap_conn")
    @patch("time.sleep")
    def test_notification_queued_and_deduped(self, mock_sleep, mock_conn):
        from ioe_crypto import encrypt

        notif = {"type": "notification", "service": "telegram", "text": "hi"}
        encrypted = encrypt(ioe_web.IOE_KEY, json.dumps(notif)).encode("ascii")
        raw_email = _make_email_with_attachment(encrypted)

        mock_imap = MagicMock()
        mock_imap.search.return_value = ("OK", [b"42"])
        mock_imap.fetch.return_value = ("OK", [(b"42", raw_email)])
        mock_conn.return_value = mock_imap

        ioe_web.seen_notification_uids.discard("42")
        ioe_web.notification_queues.pop("default", None)
        ioe_web.pending.pop("notif-test", None)

        ioe_web.poll_response("notif-test")

        assert "default" in ioe_web.notification_queues
        assert len(ioe_web.notification_queues["default"]) >= 1
        assert ioe_web.notification_queues["default"][0]["type"] == "notification"
        assert "42" in ioe_web.seen_notification_uids
        # Cleanup
        ioe_web.seen_notification_uids.discard("42")
        ioe_web.notification_queues.pop("default", None)
        ioe_web.pending.pop("notif-test", None)

    @patch.object(ioe_web, "imap_conn")
    @patch("time.sleep")
    def test_timeout_sets_504(self, mock_sleep, mock_conn):
        mock_imap = MagicMock()
        mock_imap.search.return_value = ("OK", [b""])
        mock_conn.return_value = mock_imap

        ioe_web.pending.pop("timeout-test", None)
        ioe_web.poll_response("timeout-test")

        assert "timeout-test" in ioe_web.pending
        assert ioe_web.pending["timeout-test"]["status"] == 504
        ioe_web.pending.pop("timeout-test", None)

    @patch.object(ioe_web, "imap_conn", side_effect=Exception("connection refused"))
    def test_imap_error_sets_500(self, mock_conn):
        ioe_web.pending.pop("err-test", None)
        ioe_web.poll_response("err-test")

        assert "err-test" in ioe_web.pending
        assert ioe_web.pending["err-test"]["status"] == 500
        assert "connection refused" in ioe_web.pending["err-test"]["error"]
        ioe_web.pending.pop("err-test", None)


class TestHandlerDoGET(unittest.TestCase):
    def test_root_returns_html(self):
        h = _make_handler("/")
        h.do_GET()
        assert any(r == ("status", 200) for r in h._responses)
        h.wfile.seek(0)
        body = h.wfile.read().decode("utf-8")
        assert "IoE" in body

    def test_status_pending_when_no_response(self):
        h = _make_handler("/status", "id=nonexistent")
        h.respond_json = MagicMock()
        h.do_GET()
        h.respond_json.assert_called_once_with({"status": "pending"})

    def test_status_ready_with_results(self):
        req_id = "status-test-1"
        ioe_web.pending[req_id] = {"id": req_id, "status": 200, "results": [{"title": "R1"}]}
        h = _make_handler("/status", f"id={req_id}")
        h.respond_json = MagicMock()
        h.do_GET()
        resp = h.respond_json.call_args[0][0]
        assert resp["status"] == "ready"
        assert resp["results"] == [{"title": "R1"}]

    def test_status_ready_with_body(self):
        req_id = "status-test-2"
        ioe_web.pending[req_id] = {"id": req_id, "status": 200, "title": "T", "body": "B", "format": "html"}
        h = _make_handler("/status", f"id={req_id}")
        h.respond_json = MagicMock()
        h.do_GET()
        resp = h.respond_json.call_args[0][0]
        assert resp["status"] == "ready"
        assert resp["title"] == "T"
        assert resp["body"] == "B"

    def test_status_error_response(self):
        req_id = "status-test-3"
        ioe_web.pending[req_id] = {"id": req_id, "status": 500, "error": "oops"}
        h = _make_handler("/status", f"id={req_id}")
        h.respond_json = MagicMock()
        h.do_GET()
        resp = h.respond_json.call_args[0][0]
        assert resp["status"] == "error"
        assert resp["error"] == "oops"

    @patch.object(ioe_web, "imap_conn")
    @patch.object(ioe_web, "send_request")
    @patch("threading.Thread")
    def test_get_sends_request_and_starts_poll(self, mock_thread, mock_send, mock_conn):
        mock_conn.return_value = MagicMock()
        h = _make_handler("/get", "url=https://example.com")
        h.respond_json = MagicMock()
        h.do_GET()
        mock_send.assert_called_once()
        mock_thread.return_value.start.assert_called_once()
        resp = h.respond_json.call_args[0][0]
        assert resp["status"] == "pending"
        assert "id" in resp

    @patch.object(ioe_web, "imap_conn")
    @patch.object(ioe_web, "send_request")
    @patch("threading.Thread")
    def test_search_sends_request(self, mock_thread, mock_send, mock_conn):
        mock_conn.return_value = MagicMock()
        h = _make_handler("/search", "q=hello")
        h.respond_json = MagicMock()
        h.do_GET()
        req_arg = mock_send.call_args[0][1]
        assert req_arg["cmd"] == "SEARCH"
        assert req_arg["query"] == "hello"

    @patch.object(ioe_web, "imap_conn", side_effect=Exception("fail"))
    def test_get_imap_failure_returns_error(self, mock_conn):
        h = _make_handler("/get", "url=https://example.com")
        h.respond_json = MagicMock()
        h.do_GET()
        resp = h.respond_json.call_args[0][0]
        assert resp["status"] == "error"

    def test_unknown_path_returns_404(self):
        h = _make_handler("/nonexistent")
        h.do_GET()
        assert any(r[0] == "error" and r[1] == 404 for r in h._responses)


class TestClientMain(unittest.TestCase):
    @patch.object(ioe_web, "HTTPServer")
    def test_main_default_port(self, mock_server_cls):
        mock_instance = MagicMock()
        mock_server_cls.return_value = mock_instance
        mock_instance.serve_forever.side_effect = KeyboardInterrupt
        with patch("sys.argv", ["ioe_web.py"]):
            ioe_web.main()
        mock_server_cls.assert_called_once_with(("0.0.0.0", 8080), ioe_web.Handler)

    @patch.object(ioe_web, "HTTPServer")
    def test_main_custom_port(self, mock_server_cls):
        mock_instance = MagicMock()
        mock_server_cls.return_value = mock_instance
        mock_instance.serve_forever.side_effect = KeyboardInterrupt
        with patch("sys.argv", ["ioe_web.py", "9090"]):
            ioe_web.main()
        mock_server_cls.assert_called_once_with(("0.0.0.0", 9090), ioe_web.Handler)


if __name__ == "__main__":
    unittest.main()
