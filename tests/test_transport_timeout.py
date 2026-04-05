import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webui"))
sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IOE_SECRET", "secret123")

import ioe_web
import transport


class TestTransportTimeout:
    def setup_method(self):
        ioe_web.pending.clear()

    def test_poll_response_timeout_504(self):
        mock_imap = MagicMock()
        mock_imap.select.return_value = ("OK", [b"INBOX"])
        mock_imap.noop.return_value = ("OK", [])
        mock_imap.search.return_value = ("OK", [b""])
        mock_imap.logout.return_value = None
        time_values = [0.0] * 200
        with (
            patch.object(transport, "imap_conn", return_value=mock_imap),
            patch("time.sleep"),
            patch("time.time", side_effect=time_values),
        ):
            transport.poll_response("user1", "req-timeout")
        key = ("user1", "req-timeout")
        assert key in ioe_web.pending
        result = ioe_web.pending[key]
        assert result["status"] == 504

    def test_poll_response_exception_500(self):
        with (
            patch.object(transport, "imap_conn", side_effect=ConnectionError("down")),
            patch("time.time", return_value=0.0),
        ):
            transport.poll_response("user1", "req-err")
        key = ("user1", "req-err")
        assert key in ioe_web.pending
        assert ioe_web.pending[key]["status"] == 500

    def test_rewrite_links_single_quote(self):
        html = "<a href='https://example.com/page'>link</a>"
        result = transport.rewrite_links(html)
        assert "/get?url=" in result

    def test_old_message_cleanup(self):
        mock_imap = MagicMock()
        mock_imap.select.return_value = ("OK", [b"INBOX"])
        mock_imap.noop.return_value = ("OK", [])
        mock_imap.search.return_value = ("OK", [b""])
        mock_imap.logout.return_value = None
        time_values = [0.0] * 200
        with (
            patch.object(transport, "imap_conn", return_value=mock_imap),
            patch("time.sleep"),
            patch("time.time", side_effect=time_values),
        ):
            transport.poll_response("user1", "req-clean")
        assert mock_imap.search.call_count > 1
