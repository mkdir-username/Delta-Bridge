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


class TestTransportTimeout:
    def setup_method(self):
        ioe_web.pending.clear()
        transport._poll_pool.clear()

    def test_poll_response_timeout_504(self):
        mock_imap = MagicMock()
        mock_imap.select_folder.return_value = {}
        mock_imap.noop.return_value = None
        mock_imap.search.return_value = []
        mock_imap.logout.return_value = None
        clock = [0.0]

        def fake_time():
            val = clock[0]
            clock[0] += 0.1
            return val

        with (
            patch.object(transport, "_create_conn", return_value=mock_imap),
            patch("time.sleep"),
            patch("time.time", side_effect=fake_time),
        ):
            transport.poll_response("user1", "req-timeout", timeout=5)
        key = ("user1", "req-timeout")
        assert key in ioe_web.pending
        result = ioe_web.pending[key]
        assert result["status"] == 504

    def test_poll_response_exception_500(self):
        clock = [0.0]

        def fake_time():
            val = clock[0]
            clock[0] += 5.0
            return val

        with (
            patch.object(transport, "_create_conn", side_effect=ConnectionError("down")),
            patch("time.time", side_effect=fake_time),
        ):
            transport.poll_response("user1", "req-err")
        key = ("user1", "req-err")
        assert key in ioe_web.pending
        assert ioe_web.pending[key]["status"] == 500

    def test_rewrite_links_single_quote(self):
        html = "<a href='https://example.com/page'>link</a>"
        result = transport.rewrite_links(html)
        assert "/get?url=" in result

    def test_deadline_bounds_cycle_count(self):
        mock_imap = MagicMock()
        mock_imap.select_folder.return_value = {}
        mock_imap.noop.return_value = None
        mock_imap.logout.return_value = None
        search_call_count = [0]
        clock = [0.0]

        def fake_time():
            return clock[0]

        def fake_search(_criteria):
            search_call_count[0] += 1
            clock[0] += 15.0
            return []

        mock_imap.search.side_effect = fake_search

        with (
            patch.object(transport, "_create_conn", return_value=mock_imap),
            patch("time.sleep"),
            patch("time.time", side_effect=fake_time),
        ):
            transport.poll_response("user1", "req-deadline", timeout=30)
        assert search_call_count[0] <= 4

    def test_old_message_cleanup(self):
        mock_imap = MagicMock()
        mock_imap.select_folder.return_value = {}
        mock_imap.noop.return_value = None
        mock_imap.logout.return_value = None

        old_uids = [100, 101, 102]

        uid_counter = [0]

        def fake_search(criteria):
            if isinstance(criteria, list) and "BEFORE" in criteria:
                return old_uids
            uid_counter[0] += 1
            return [uid_counter[0]]

        mock_imap.search.side_effect = fake_search
        fake_raw = b"From: x\r\n\r\nbody"
        mock_imap.fetch.side_effect = lambda uids, _: {u: {b"RFC822": fake_raw} for u in uids}
        mock_imap.set_flags.return_value = {}
        mock_imap.expunge.return_value = None
        clock = [0.0]

        def fake_time():
            val = clock[0]
            clock[0] += 0.01
            return val

        with (
            patch.object(transport, "_create_conn", return_value=mock_imap),
            patch("time.sleep"),
            patch("time.time", side_effect=fake_time),
        ):
            transport.poll_response("user1", "req-clean", timeout=3)
        assert mock_imap.search.call_count > 1
        has_before = any(isinstance(c[0][0], list) and "BEFORE" in c[0][0] for c in mock_imap.search.call_args_list)
        assert has_before, "cleanup должен искать старые письма с BEFORE"
        assert mock_imap.set_flags.called, "старые письма должны быть помечены удалёнными"
        assert mock_imap.expunge.called, "expunge должен быть вызван"
