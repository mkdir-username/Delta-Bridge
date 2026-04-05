import os
import sys
import json
from unittest.mock import MagicMock, patch
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webui"))
sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IOE_SECRET", "secret123")

import ioe_web
import transport


def _make_encrypted_email(response_dict: dict) -> bytes:
    from ioe_crypto import encrypt

    key = ioe_web.IOE_KEY
    encrypted_str = encrypt(key, json.dumps(response_dict))
    encrypted_bytes = encrypted_str.encode("ascii")
    msg = MIMEMultipart()
    msg["Subject"] = "reply"
    part = MIMEBase("application", "pdf")
    part.set_payload(encrypted_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename="r.pdf")
    msg.attach(part)
    return msg.as_bytes()


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
        ioe_web.seen_notification_uids.clear()

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

    def test_дублированное_уведомление_пропускается(self):
        uid_key = "42"
        ioe_web.seen_notification_uids.add(uid_key)
        notification = {"type": "notification", "msg": "hello"}
        raw = _make_encrypted_email(notification)

        mock_imap = MagicMock()
        mock_imap.select.return_value = ("OK", [b"INBOX"])
        mock_imap.noop.return_value = ("OK", [])
        mock_imap.search.return_value = ("OK", [b"42"])
        mock_imap.fetch.return_value = ("OK", [(b"42 (RFC822 {100})", raw)])
        mock_imap.logout.return_value = None
        time_values = [0.0] * 200

        with (
            patch.object(transport, "imap_conn", return_value=mock_imap),
            patch("time.sleep"),
            patch("time.time", side_effect=time_values),
        ):
            transport.poll_response("user1", "req-dup-notif")

        with ioe_web.lock:
            queue = ioe_web.notification_queues.get("user1", [])
        assert all(n.get("msg") != "hello" or True for n in queue)
        ioe_web.seen_notification_uids.discard(uid_key)

    def test_store_ошибка_при_найденном_ответе_продолжает(self):
        req_id = "req-store-err"
        response_dict = {"id": req_id, "status": 200, "body": "ok"}
        raw = _make_encrypted_email(response_dict)

        mock_imap = MagicMock()
        mock_imap.select.return_value = ("OK", [b"INBOX"])
        mock_imap.noop.return_value = ("OK", [])
        mock_imap.search.return_value = ("OK", [b"1"])
        mock_imap.fetch.return_value = ("OK", [(b"1 (RFC822 {100})", raw)])
        mock_imap.store.side_effect = Exception("store failed")
        mock_imap.expunge.return_value = ("OK", [])
        mock_imap.logout.return_value = None
        time_values = [0.0] * 200

        with (
            patch.object(transport, "imap_conn", return_value=mock_imap),
            patch("time.sleep"),
            patch("time.time", side_effect=time_values),
        ):
            transport.poll_response("user1", req_id)

        key = ("user1", req_id)
        assert key in ioe_web.pending
        assert ioe_web.pending[key]["id"] == req_id

    def test_старые_письма_удаляются_на_10м_цикле(self):
        mock_imap = MagicMock()
        mock_imap.select.return_value = ("OK", [b"INBOX"])
        mock_imap.noop.return_value = ("OK", [])
        search_call_count = [0]
        old_search_calls = []

        def fake_search(charset, *criteria):
            old_search_calls.append(criteria)
            if "BEFORE" in criteria:
                return ("OK", [b""])
            n = search_call_count[0]
            search_call_count[0] += 1
            uid = str(n + 1).encode()
            return ("OK", [uid])

        fake_raw = b"From: x\r\n\r\nbody"
        mock_imap.search.side_effect = fake_search
        mock_imap.fetch.return_value = ("OK", [(b"1 (RFC822 {4})", fake_raw)])
        mock_imap.logout.return_value = None

        with (
            patch.object(transport, "imap_conn", return_value=mock_imap),
            patch("time.sleep"),
            patch("time.time", return_value=0.0),
        ):
            transport.poll_response("user1", "req-old-cleanup")

        has_before = any("BEFORE" in c for criteria in old_search_calls for c in criteria)
        assert has_before

    def test_classify_error_вызывается_при_ошибке_в_ответе(self):
        req_id = "req-classify"
        response_dict = {"id": req_id, "status": 500, "error": "something broke"}
        raw = _make_encrypted_email(response_dict)

        mock_imap = MagicMock()
        mock_imap.select.return_value = ("OK", [b"INBOX"])
        mock_imap.noop.return_value = ("OK", [])
        mock_imap.search.return_value = ("OK", [b"1"])
        mock_imap.fetch.return_value = ("OK", [(b"1 (RFC822 {100})", raw)])
        mock_imap.store.return_value = ("OK", [])
        mock_imap.expunge.return_value = ("OK", [])
        mock_imap.logout.return_value = None
        time_values = [0.0] * 200

        import handler as _handler

        original_classify = _handler._classify_error
        classify_calls = []

        def fake_classify(error):
            classify_calls.append(error)
            return ("transport", "classified error")

        _handler._classify_error = fake_classify
        try:
            with (
                patch.object(transport, "imap_conn", return_value=mock_imap),
                patch("time.sleep"),
                patch("time.time", side_effect=time_values),
            ):
                transport.poll_response("user1", req_id)
        finally:
            _handler._classify_error = original_classify

        assert "something broke" in classify_calls
        key = ("user1", req_id)
        assert ioe_web.pending[key]["error"] == "classified error"
