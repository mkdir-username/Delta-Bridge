import json
import os
import sys
import types
import re
import email as email_mod
from unittest.mock import MagicMock

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


class TestEnvelope:
    def test_make_envelope_returns_valid_mime(self):
        msg = server.make_envelope(b"encrypted-payload")
        parsed = email_mod.message_from_bytes(msg.as_bytes())
        has_attachment = False
        for part in parsed.walk():
            if part.get_content_disposition() == "attachment":
                has_attachment = True
                assert part.get_content_type() in (
                    "application/pdf",
                    "application/octet-stream",
                    "application/x-compressed",
                )
        assert has_attachment

    def test_subject_contains_hex(self):
        msg = server.make_envelope(b"data")
        assert re.search(r"[0-9a-f]{8}", msg["Subject"])

    def test_filename_from_filenames_list(self):
        msg = server.make_envelope(b"data")
        for part in msg.walk():
            fn = part.get_filename()
            if fn:
                assert fn in server.FILENAMES
                return
        raise AssertionError("No filename found")

    def test_append_response_encrypts_and_appends(self):
        mock_client = MagicMock()
        server.append_response(mock_client, {"id": "test", "status": 200})
        mock_client.append.assert_called_once()
        args = mock_client.append.call_args
        assert args[0][0] == "INBOX"
        assert isinstance(args[0][1], bytes)

    def test_append_response_uses_compression(self):
        from ioe_crypto import decrypt_decompress, derive_key, encrypt

        key = derive_key(os.environ["IOE_SECRET"])
        mock_client = MagicMock()
        large_response = {"id": "test", "status": 200, "body": "x" * 5000}
        server.append_response(mock_client, large_response)
        raw_mime = mock_client.append.call_args[0][1]
        parsed = email_mod.message_from_bytes(raw_mime)
        for part in parsed.walk():
            if part.get_content_disposition() == "attachment":
                payload = part.get_payload(decode=True)
                blob = payload.decode("ascii").strip()
                result = decrypt_decompress(key, blob)
                assert json.loads(result) == large_response
                plain_encrypted = encrypt(key, json.dumps(large_response, ensure_ascii=False))
                assert len(blob) < len(plain_encrypted)
                return
        raise AssertionError("No attachment found")


class TestMimeVariance:
    def _get_mime_fingerprint(self, msg: email_mod.message.Message) -> str:
        parts = []
        for part in msg.walk():
            ct = part.get_content_type()
            parts.append(ct)
        headers = []
        for h in ("CC", "Reply-To", "In-Reply-To", "References"):
            if msg[h]:
                headers.append(h)
        return f"{msg.get_content_type()}|{'|'.join(parts)}|{'|'.join(headers)}"

    def test_mime_structure_varies_across_messages(self):
        fingerprints = set()
        for _ in range(30):
            msg = server.make_envelope(b"data")
            parsed = email_mod.message_from_bytes(msg.as_bytes())
            fingerprints.add(self._get_mime_fingerprint(parsed))
        assert len(fingerprints) > 1, "All 30 messages have identical MIME structure"

    def test_attachment_content_type_varies(self):
        content_types = set()
        for _ in range(30):
            msg = server.make_envelope(b"data")
            for part in msg.walk():
                if part.get_content_disposition() == "attachment":
                    content_types.add(part.get_content_type())
        assert len(content_types) > 1, "All 30 attachments have same Content-Type"

    def test_envelope_always_has_attachment_with_payload(self):
        for _ in range(20):
            msg = server.make_envelope(b"test-payload")
            parsed = email_mod.message_from_bytes(msg.as_bytes())
            found = False
            for part in parsed.walk():
                if part.get_content_disposition() == "attachment":
                    payload = part.get_payload(decode=True)
                    assert payload is not None
                    assert len(payload) > 0
                    found = True
            assert found, "No attachment found"
