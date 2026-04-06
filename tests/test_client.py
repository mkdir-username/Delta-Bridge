import os
import sys
import json
import email as email_mod
from unittest.mock import MagicMock, patch

_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "client"))

os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IOE_SECRET", "secret123")

import client
from ioe_crypto import encrypt, derive_key

IOE_KEY = derive_key(os.environ["IOE_SECRET"])


def _make_response_mime(response_dict):
    from email.mime.multipart import MIMEMultipart
    from email.mime.base import MIMEBase
    from email.mime.text import MIMEText
    from email import encoders

    encrypted = encrypt(IOE_KEY, json.dumps(response_dict)).encode("ascii")
    msg = MIMEMultipart()
    msg.attach(MIMEText("body"))
    part = MIMEBase("application", "pdf")
    part.set_payload(encrypted)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename="report.pdf")
    msg.attach(part)
    return msg.as_bytes()


class TestClient:
    def test_send_request_builds_valid_mime(self):
        mock_imap = MagicMock()
        req = {"id": "r1", "cmd": "SEARCH", "query": "test"}
        client.send_request(mock_imap, req)
        mock_imap.append.assert_called_once()
        args = mock_imap.append.call_args[0]
        assert args[0] == client.QUEUE_FOLDER
        parsed = email_mod.message_from_bytes(args[3])
        valid_types = {"application/pdf", "application/octet-stream", "application/x-compressed"}
        has_attachment = any(
            p.get_content_disposition() == "attachment" and p.get_content_type() in valid_types for p in parsed.walk()
        )
        assert has_attachment

    def test_extract_attachment_returns_payload(self):
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email import encoders

        msg = MIMEMultipart()
        part = MIMEBase("application", "pdf")
        part.set_payload(b"test-payload")
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename="f.pdf")
        msg.attach(part)
        result = client.extract_attachment(msg.as_bytes())
        assert result == b"test-payload"

    def test_extract_attachment_no_attachment(self):
        from email.mime.text import MIMEText

        msg = MIMEText("just text")
        result = client.extract_attachment(msg.as_bytes())
        assert result is None

    def test_wait_response_matches_by_id(self):
        response_data = {"id": "req-42", "status": 200, "body": "ok"}
        raw = _make_response_mime(response_data)
        mock_imap = MagicMock()
        mock_imap.select.return_value = ("OK", [b"1"])
        mock_imap.noop.return_value = ("OK", [])
        mock_imap.search.return_value = ("OK", [b"1"])
        mock_imap.fetch.return_value = ("OK", [(b"1", raw)])
        with patch("time.sleep"):
            result = client.wait_response(mock_imap, "req-42")
        assert result["id"] == "req-42"
        assert result["status"] == 200

    def test_wait_response_timeout_returns_none(self):
        mock_imap = MagicMock()
        mock_imap.select.return_value = ("OK", [b"1"])
        mock_imap.noop.return_value = ("OK", [])
        mock_imap.search.return_value = ("OK", [b""])
        with patch("time.sleep"):
            result = client.wait_response(mock_imap, "req-missing", timeout=3)
        assert result is None

    def test_main_no_args_exits(self):
        import pytest

        with patch.object(sys, "argv", ["client.py"]), pytest.raises(SystemExit):
            client.main()

    def test_imap_conn_логинится(self):
        mock_imap = MagicMock()
        with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
            conn = client.imap_conn()
            mock_imap.login.assert_called_once_with(client.EMAIL, client.PASSWORD)
            assert conn is mock_imap

    def test_main_search_отправляет_запрос_и_печатает_результат(self, capsys):
        response = {"id": "x", "status": 200, "title": "", "body": "result text"}
        mock_imap = MagicMock()
        with (
            patch.object(sys, "argv", ["client.py", "search", "python news"]),
            patch("imaplib.IMAP4_SSL", return_value=mock_imap),
            patch.object(client, "send_request", return_value="x") as mock_send,
            patch.object(client, "wait_response", return_value=response),
            patch("time.sleep"),
        ):
            client.main()
        out = capsys.readouterr().out
        assert "result text" in out
        mock_send.assert_called_once()
        args = mock_send.call_args[0]
        assert args[1]["cmd"] == "SEARCH"
        assert args[1]["query"] == "python news"

    def test_main_update_записывает_файлы(self, tmp_path, capsys):
        fname = "ioe_test_update.py"
        response = {"id": "x", "status": 200, "cmd": "UPDATE", "files": {fname: "print('hello')"}}
        mock_imap = MagicMock()
        with (
            patch.object(sys, "argv", ["client.py", "update"]),
            patch("imaplib.IMAP4_SSL", return_value=mock_imap),
            patch.object(client, "send_request", return_value="x"),
            patch.object(client, "wait_response", return_value=response),
            patch("time.sleep"),
            patch("os.path.expanduser", return_value=str(tmp_path / fname)),
        ):
            client.main()
        out = capsys.readouterr().out
        assert "Updated" in out
        assert (tmp_path / fname).read_text() == "print('hello')"

    def test_main_нет_ответа_печатает_timeout(self, capsys):
        mock_imap = MagicMock()
        with (
            patch.object(sys, "argv", ["client.py", "get", "https://example.com"]),
            patch("imaplib.IMAP4_SSL", return_value=mock_imap),
            patch.object(client, "send_request", return_value="x"),
            patch.object(client, "wait_response", return_value=None),
            patch("time.sleep"),
        ):
            client.main()
        out = capsys.readouterr().out
        assert "Timeout" in out

    def test_main_error_response_печатает_ошибку(self, capsys):
        response = {"id": "x", "status": 500, "error": "something broke"}
        mock_imap = MagicMock()
        with (
            patch.object(sys, "argv", ["client.py", "get", "https://example.com"]),
            patch("imaplib.IMAP4_SSL", return_value=mock_imap),
            patch.object(client, "send_request", return_value="x"),
            patch.object(client, "wait_response", return_value=response),
            patch("time.sleep"),
        ):
            client.main()
        out = capsys.readouterr().out
        assert "something broke" in out

    def test_main_html_body_парсится_через_bs4(self, capsys):
        response = {"id": "x", "status": 200, "title": "Title", "body": "<p>Hello <b>world</b></p>"}
        mock_imap = MagicMock()
        with (
            patch.object(sys, "argv", ["client.py", "get", "https://example.com"]),
            patch("imaplib.IMAP4_SSL", return_value=mock_imap),
            patch.object(client, "send_request", return_value="x"),
            patch.object(client, "wait_response", return_value=response),
            patch("time.sleep"),
        ):
            client.main()
        out = capsys.readouterr().out
        assert "Hello" in out
        assert "world" in out
