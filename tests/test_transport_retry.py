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


class TestImapConnRetry:
    def test_первое_подключение_успешно(self):
        mock_imap = MagicMock()
        with (
            patch("imaplib.IMAP4_SSL", return_value=mock_imap),
            patch("ioe_web.IMAP_HOST", "imap.example.com"),
        ):
            result = transport.imap_conn()
        assert result is mock_imap
        mock_imap.login.assert_called_once()

    def test_первый_вызов_падает_второй_успешен(self):
        mock_imap = MagicMock()
        call_count = [0]

        def imap_factory(*args):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("temporary")
            return mock_imap

        with (
            patch("imaplib.IMAP4_SSL", side_effect=imap_factory),
            patch("ioe_web.IMAP_HOST", "imap.example.com"),
            patch("time.sleep"),
        ):
            result = transport.imap_conn()
        assert result is mock_imap
        assert call_count[0] == 2

    def test_все_попытки_упали_поднимает_исключение(self):
        import pytest

        with (
            patch("imaplib.IMAP4_SSL", side_effect=ConnectionError("down")),
            patch("ioe_web.IMAP_HOST", "imap.example.com"),
            patch("time.sleep"),
            pytest.raises(ConnectionError),
        ):
            transport.imap_conn()


class TestPollResponseErrors:
    def setup_method(self):
        ioe_web.pending.clear()

    def test_fetch_возвращает_none_данные_продолжает_цикл(self):
        mock_imap = MagicMock()
        mock_imap.select.return_value = ("OK", [b"INBOX"])
        mock_imap.noop.return_value = ("OK", [])
        mock_imap.search.return_value = ("OK", [b"1"])
        mock_imap.fetch.return_value = ("OK", [None])
        mock_imap.logout.return_value = None
        time_values = [0.0] * 200

        with (
            patch.object(transport, "imap_conn", return_value=mock_imap),
            patch("time.sleep"),
            patch("time.time", side_effect=time_values),
        ):
            transport.poll_response("user1", "req-none")

        key = ("user1", "req-none")
        assert key in ioe_web.pending
        assert ioe_web.pending[key]["status"] == 504

    def test_decrypt_ошибка_продолжает_цикл(self):
        mock_imap = MagicMock()
        mock_imap.select.return_value = ("OK", [b"INBOX"])
        mock_imap.noop.return_value = ("OK", [])
        mock_imap.search.return_value = ("OK", [b"1"])

        fake_raw = b"From: x\r\n\r\nbody"
        mock_imap.fetch.return_value = ("OK", [(b"1 (RFC822 {4})", fake_raw)])
        mock_imap.logout.return_value = None
        time_values = [0.0] * 200

        with (
            patch.object(transport, "imap_conn", return_value=mock_imap),
            patch("time.sleep"),
            patch("time.time", side_effect=time_values),
        ):
            transport.poll_response("user1", "req-bad-decrypt")

        key = ("user1", "req-bad-decrypt")
        assert key in ioe_web.pending
        assert ioe_web.pending[key]["status"] == 504

    def test_fetch_пустой_список_uids_пропускает(self):
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
            transport.poll_response("user1", "req-empty")

        key = ("user1", "req-empty")
        assert key in ioe_web.pending
        assert ioe_web.pending[key]["status"] == 504
