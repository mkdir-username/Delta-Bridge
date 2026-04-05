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

import importlib.util

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

_spec = importlib.util.spec_from_file_location("client_ioe_web", os.path.join(_root, "client", "ioe_web.py"))
ioe_web = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ioe_web)  # type: ignore[union-attr]


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

    handler.send_response = send_response
    handler.send_header = send_header
    handler.end_headers = end_headers
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


if __name__ == "__main__":
    unittest.main()
