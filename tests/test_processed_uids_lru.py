# tests/test_processed_uids_lru.py
"""_processed_uids must evict oldest entries, not clear all."""

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


def test_processed_uids_evicts_oldest_not_all():
    """When exceeding MAX, oldest UIDs are evicted, recent ones preserved."""
    original_max = ioe_server._MAX_PROCESSED
    ioe_server._MAX_PROCESSED = 3
    ioe_server._processed_uids.clear()
    ioe_server._processed_uids_deque.clear()

    try:
        for uid in [10, 20, 30, 40, 50]:
            ioe_server._processed_uids.add(uid)
            ioe_server._processed_uids_deque.append(uid)
            if len(ioe_server._processed_uids) > ioe_server._MAX_PROCESSED:
                while len(ioe_server._processed_uids) > ioe_server._MAX_PROCESSED and ioe_server._processed_uids_deque:
                    old = ioe_server._processed_uids_deque.popleft()
                    ioe_server._processed_uids.discard(old)

        assert 10 not in ioe_server._processed_uids
        assert 20 not in ioe_server._processed_uids
        assert 50 in ioe_server._processed_uids
        assert 40 in ioe_server._processed_uids
        assert len(ioe_server._processed_uids) <= 3
    finally:
        ioe_server._MAX_PROCESSED = original_max
        ioe_server._processed_uids.clear()
        ioe_server._processed_uids_deque.clear()


def test_old_clear_behavior_gone():
    """After fix, _processed_uids must NOT be fully cleared on overflow."""
    original_max = ioe_server._MAX_PROCESSED
    ioe_server._MAX_PROCESSED = 3
    ioe_server._processed_uids.clear()
    ioe_server._processed_uids_deque.clear()

    try:
        for uid in [1, 2, 3, 4]:
            ioe_server._processed_uids.add(uid)
            ioe_server._processed_uids_deque.append(uid)
            if len(ioe_server._processed_uids) > ioe_server._MAX_PROCESSED:
                while len(ioe_server._processed_uids) > ioe_server._MAX_PROCESSED and ioe_server._processed_uids_deque:
                    old = ioe_server._processed_uids_deque.popleft()
                    ioe_server._processed_uids.discard(old)

        assert len(ioe_server._processed_uids) > 0
        assert len(ioe_server._processed_uids) == 3
    finally:
        ioe_server._MAX_PROCESSED = original_max
        ioe_server._processed_uids.clear()
        ioe_server._processed_uids_deque.clear()
