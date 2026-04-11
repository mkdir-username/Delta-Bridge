import imaplib
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

import ioe_web
import transport


class TestNoLogoutOnPooledConnection:
    """Bug 1: m.logout() после send_request убивает pooled connection."""

    def setup_method(self):
        transport._pool.clear()

    def test_connection_alive_after_send_request(self):
        """После imap_conn() + send_request(), connection НЕ должен быть logout-нут."""
        mock_client = MagicMock()
        mock_client.noop.return_value = None
        mock_client.append.return_value = None

        with patch("transport.IMAPClient", return_value=mock_client):
            m = transport.imap_conn()
            transport.send_request(m, {"id": "test-1", "type": "command"})

        mock_client.logout.assert_not_called()

        with patch("transport.IMAPClient", return_value=mock_client):
            m2 = transport.imap_conn()

        assert m is m2, "Тот же pooled connection должен вернуться"


class TestPollUsesOwnConnection:
    """Bug 4: poll_response НЕ должен использовать shared pool — thread safety."""

    def setup_method(self):
        transport._pool.clear()
        ioe_web.pending.clear()
        ioe_web.seen_notification_uids.clear()

    def test_poll_does_not_use_pool(self):
        """poll_response создаёт dedicated connection, не трогает _pool."""
        pool_conn = MagicMock(name="pool_conn")
        pool_conn.noop.return_value = None
        transport._pool["test@test.com@imap.yandex.ru"] = pool_conn

        poll_conn = MagicMock(name="poll_conn")
        poll_conn.select_folder.return_value = {}
        poll_conn.search.return_value = []
        poll_conn.noop.return_value = None

        time_values = [0.0] * 300

        with (
            patch.object(transport, "_create_conn", return_value=poll_conn) as mock_create,
            patch.object(transport, "imap_conn") as mock_pool,
            patch("time.sleep"),
            patch("time.time", side_effect=time_values),
        ):
            transport.poll_response("user1", "req-own-conn")

        mock_create.assert_called_once()
        mock_pool.assert_not_called()
        poll_conn.select_folder.assert_called_with("INBOX")
        poll_conn.logout.assert_called_once()

    def test_poll_connection_closed_on_exit(self):
        """poll_response закрывает свой connection при выходе (timeout или success)."""
        poll_conn = MagicMock(name="poll_conn")
        poll_conn.select_folder.return_value = {}
        poll_conn.search.return_value = []
        poll_conn.noop.return_value = None

        time_values = [0.0] * 300

        with (
            patch.object(transport, "_create_conn", return_value=poll_conn),
            patch("time.sleep"),
            patch("time.time", side_effect=time_values),
        ):
            transport.poll_response("user1", "req-cleanup")

        poll_conn.logout.assert_called_once()


class TestIdleNoopFailureReconnects:
    """Bug 2: IDLE + noop оба падают -> poll_response должен переподключиться."""

    def setup_method(self):
        transport._pool.clear()
        ioe_web.pending.clear()
        ioe_web.seen_notification_uids.clear()

    def test_idle_and_noop_both_fail_triggers_reconnect(self):
        """Когда IDLE упал и recovery noop() тоже, poll должен reconnect через _create_conn."""
        mock_dead = MagicMock()
        mock_dead.select_folder.return_value = {}
        mock_dead.search.return_value = []
        mock_dead.idle.side_effect = Exception("IDLE connection dropped")
        mock_dead.noop.side_effect = Exception("protocol violation")

        mock_fresh = MagicMock()
        mock_fresh.select_folder.return_value = {}
        mock_fresh.noop.return_value = None
        mock_fresh.search.return_value = []
        mock_fresh.logout.return_value = None

        create_calls = [0]

        def fake_create():
            create_calls[0] += 1
            if create_calls[0] == 1:
                return mock_dead
            return mock_fresh

        time_values = [0.0] * 300

        with (
            patch.object(transport, "_create_conn", side_effect=fake_create),
            patch("time.sleep"),
            patch("time.time", side_effect=time_values),
        ):
            transport.poll_response("user1", "req-idle-fail")

        assert create_calls[0] >= 2, "Должен был переподключиться после IDLE+noop failure"
        mock_fresh.select_folder.assert_called_with("INBOX")

        key = ("user1", "req-idle-fail")
        assert key in ioe_web.pending
        assert ioe_web.pending[key]["status"] == 504


class TestMidPollReconnection:
    """Bug 3: connection dies mid-poll -> reconnection и продолжение."""

    def setup_method(self):
        transport._pool.clear()
        ioe_web.pending.clear()
        ioe_web.seen_notification_uids.clear()

    def test_search_abort_midpoll_reconnects(self):
        """search() падает с IMAP4.abort mid-poll -> reconnect через _create_conn."""
        mock_conn = MagicMock()
        mock_conn.select_folder.return_value = {}
        mock_conn.noop.return_value = None
        mock_conn.search.side_effect = [
            [],
            imaplib.IMAP4.abort("connection lost"),
        ]

        mock_fresh = MagicMock()
        mock_fresh.select_folder.return_value = {}
        mock_fresh.noop.return_value = None
        mock_fresh.search.return_value = []
        mock_fresh.logout.return_value = None

        conns = iter([mock_conn, mock_fresh])
        time_values = [0.0] * 300

        with (
            patch.object(transport, "_create_conn", side_effect=lambda: next(conns)),
            patch("time.sleep"),
            patch("time.time", side_effect=time_values),
        ):
            transport.poll_response("user1", "req-abort")

        mock_fresh.select_folder.assert_called_with("INBOX")

        key = ("user1", "req-abort")
        assert key in ioe_web.pending
        assert ioe_web.pending[key]["status"] == 504
