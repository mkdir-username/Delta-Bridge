import os
import sys
import types
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webui"))
sys.path.insert(0, os.path.dirname(__file__))

if "imapclient" not in sys.modules:
    sys.modules["imapclient"] = types.ModuleType("imapclient")
    sys.modules["imapclient"].IMAPClient = type("IMAPClient", (), {})

os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IOE_SECRET", "secret123")

import transport


class TestConnectionPool:
    def setup_method(self):
        if hasattr(transport, "_pool"):
            transport._pool.clear()

    def test_second_call_reuses_connection(self):
        mock1 = MagicMock()
        mock1.noop.return_value = None
        call_count = [0]

        def factory(*a, **kw):
            call_count[0] += 1
            return mock1

        with patch("transport.IMAPClient", side_effect=factory):
            c1 = transport.imap_conn()
            c2 = transport.imap_conn()
        assert call_count[0] == 1, "Should reuse existing connection"
        assert c1 is c2

    def test_creates_new_after_noop_fails(self):
        mock_stale = MagicMock()
        mock_stale.noop.side_effect = Exception("dead")
        mock_fresh = MagicMock()
        mock_fresh.noop.return_value = None

        clients = iter([mock_stale, mock_fresh])

        with patch("transport.IMAPClient", side_effect=lambda *a, **kw: next(clients)):
            c1 = transport.imap_conn()
            assert c1 is mock_stale
            c2 = transport.imap_conn()
        assert c2 is mock_fresh

    def test_pool_survives_logout_failure(self):
        mock_stale = MagicMock()
        mock_stale.noop.side_effect = Exception("dead")
        mock_stale.logout.side_effect = Exception("already gone")
        mock_fresh = MagicMock()
        mock_fresh.noop.return_value = None

        clients = iter([mock_stale, mock_fresh])
        with patch("transport.IMAPClient", side_effect=lambda *a, **kw: next(clients)):
            transport.imap_conn()
            c2 = transport.imap_conn()
        assert c2 is mock_fresh
