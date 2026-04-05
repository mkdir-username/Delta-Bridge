import os
import sys
import types
import json
import email as email_mod
from unittest.mock import MagicMock, patch
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "server"))
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
sys.modules["readability"].Document = type(
    "Document",
    (),
    {
        "__init__": lambda self, html="": None,
        "title": lambda self: "",
        "summary": lambda self: "",
    },
)
sys.modules["PIL.Image"] = sys.modules["PIL"]
sys.modules["PIL"].Image = sys.modules["PIL"]
sys.modules["requests"].get = lambda *a, **kw: None
sys.modules["requests"].request = lambda *a, **kw: None
sys.modules["requests"].Session = type("Session", (), {"request": lambda *a, **kw: None, "close": lambda self: None})
sys.modules["trafilatura"].extract = lambda html, **kw: None

os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IOE_SECRET", "test-secret-key")

import server
from ioe_crypto import encrypt, decrypt, derive_key

IOE_KEY = derive_key(os.environ["IOE_SECRET"])


def _make_mime(payload_dict):
    encrypted = encrypt(IOE_KEY, json.dumps(payload_dict)).encode("ascii")
    msg = MIMEMultipart()
    msg.attach(MIMEText("body"))
    part = MIMEBase("application", "pdf")
    part.set_payload(encrypted)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename="report.pdf")
    msg.attach(part)
    return msg.as_bytes()


class TestProcessMessage:
    def setup_method(self):
        server._processed_uids.clear()
        server._rate_timestamps.clear()

    def test_duplicate_uid_returns_true(self):
        server._processed_uids.add(b"999")
        mock_client = MagicMock()
        result = server.process_message(mock_client, b"999", b"")
        assert result is True
        mock_client.append.assert_not_called()

    def test_no_attachment_returns_false(self):
        msg = MIMEText("no attachment here")
        mock_client = MagicMock()
        result = server.process_message(mock_client, b"1", msg.as_bytes())
        assert result is False

    def test_decrypt_failure_returns_false(self):
        msg = MIMEMultipart()
        part = MIMEBase("application", "pdf")
        part.set_payload(b"not-valid-base64-encrypted")
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename="bad.pdf")
        msg.attach(part)
        mock_client = MagicMock()
        result = server.process_message(mock_client, b"2", msg.as_bytes())
        assert result is False

    def test_valid_message_dispatches(self):
        raw = _make_mime(
            {
                "id": "req-1",
                "type": "http",
                "url": "http://example.com",
                "method": "GET",
            }
        )
        mock_client = MagicMock()
        with patch.object(server, "dispatch_request", return_value={"status": 200, "body": "ok"}) as mock_dispatch:
            result = server.process_message(mock_client, b"3", raw)
        assert result is True
        mock_dispatch.assert_called_once()
        mock_client.append.assert_called_once()

    def test_legacy_cmd_search(self):
        raw = _make_mime({"id": "req-2", "cmd": "SEARCH", "query": "python"})
        mock_client = MagicMock()
        with patch.object(server, "do_search", return_value=[{"title": "Result"}]) as mock_search:
            result = server.process_message(mock_client, b"4", raw)
        assert result is True
        mock_search.assert_called_once_with("python")
        mock_client.append.assert_called_once()

    def test_exception_appends_error(self):
        raw = _make_mime({"id": "req-3", "cmd": "GET", "url": "http://example.com"})
        mock_client = MagicMock()
        with patch.object(server, "check_rate_limit", side_effect=RuntimeError("boom")):
            result = server.process_message(mock_client, b"5", raw)
        assert result is True
        call_args = mock_client.append.call_args[0]
        raw_mime = call_args[1]
        parsed = email_mod.message_from_bytes(raw_mime)
        for part in parsed.walk():
            payload = part.get_payload(decode=True)
            if payload:
                try:
                    decrypted = decrypt(IOE_KEY, payload.decode("ascii").strip())
                    data = json.loads(decrypted)
                    if "status" in data:
                        assert data["status"] == 500
                        return
                except Exception:
                    continue
        raise AssertionError("No error response found in MIME")
