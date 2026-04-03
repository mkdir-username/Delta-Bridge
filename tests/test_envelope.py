import os
import sys
import types
import re
import email as email_mod
from unittest.mock import MagicMock

_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "server"))
sys.path.insert(0, os.path.dirname(__file__))

for _mod in ["truststore", "imapclient", "readability", "PIL", "PIL.Image",
             "requests", "trafilatura"]:
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)
sys.modules["truststore"].inject_into_ssl = lambda: None
sys.modules["imapclient"].IMAPClient = type("IMAPClient", (), {})
sys.modules["readability"].Document = type("Document", (), {
    "__init__": lambda self, html="": None, "title": lambda self: "", "summary": lambda self: ""})
sys.modules["PIL.Image"] = sys.modules["PIL"]
sys.modules["PIL"].Image = sys.modules["PIL"]
sys.modules["requests"].get = lambda *a, **kw: None
sys.modules["requests"].request = lambda *a, **kw: None
sys.modules["requests"].Session = type("Session", (), {
    "request": lambda *a, **kw: None, "close": lambda self: None})
sys.modules["trafilatura"].extract = lambda html, **kw: None

os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IOE_SECRET", "test-secret-key")

import server


class TestEnvelope:
    def test_make_envelope_returns_valid_mime(self):
        msg = server.make_envelope(b"encrypted-payload")
        parsed = email_mod.message_from_bytes(msg.as_bytes())
        parts = list(parsed.walk())
        content_types = [p.get_content_type() for p in parts]
        assert "application/pdf" in content_types

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
