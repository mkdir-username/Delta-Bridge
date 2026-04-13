# tests/test_session_fixation.py
"""Session fixation: server MUST ignore client-provided session_id."""

import sys
import os
import types

_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "server"))
sys.path.insert(0, os.path.join(_root, "webui"))
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
sys.modules["imapclient"].IMAPClient = type(
    "IMAPClient", (), {"__init__": lambda self, *a, **kw: None, "login": lambda self, *a, **kw: None}
)
sys.modules["readability"].Document = type(
    "Document", (), {"__init__": lambda self, html="": None, "title": lambda self: "", "summary": lambda self: ""}
)
sys.modules["PIL.Image"] = sys.modules["PIL"]
sys.modules["PIL"].Image = sys.modules["PIL"]
sys.modules["trafilatura"].extract = lambda html, **kw: None

_mock_resp = types.SimpleNamespace(status_code=200, headers={}, text="{}", url="")
sys.modules["requests"].get = lambda *a, **kw: _mock_resp
sys.modules["requests"].request = lambda *a, **kw: _mock_resp
sys.modules["requests"].Session = type(
    "Session", (), {"request": lambda *a, **kw: _mock_resp, "close": lambda self: None}
)
sys.modules["requests"].Timeout = TimeoutError

os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IOE_SECRET", "test-secret-key")

import server as ioe_server


def test_session_start_ignores_client_session_id():
    """Server must generate its own session_id, not accept client's."""
    attacker_sid = "attacker-controlled-session-id"
    request = {
        "type": "session_start",
        "session_id": attacker_sid,
        "user_id": "test-user",
    }
    result = ioe_server.dispatch_request(request)
    assert result is not None
    assert result["status"] == 200
    assert result["session_id"] != attacker_sid
    assert len(result["session_id"]) == 32  # uuid4 hex


def test_session_start_generates_unique_ids():
    """Each session_start must produce a unique session_id."""
    ids = set()
    for _ in range(10):
        result = ioe_server.dispatch_request({"type": "session_start", "user_id": "test"})
        ids.add(result["session_id"])
    assert len(ids) == 10
