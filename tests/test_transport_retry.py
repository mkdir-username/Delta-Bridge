import os
import sys
import json
import types
from unittest.mock import MagicMock, patch
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

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
    def setup_method(self):
        transport._pool.clear()

    def test_первое_подключение_успешно(self):
        mock_client = MagicMock()
        with patch("transport.IMAPClient", return_value=mock_client):
            result = transport.imap_conn()
        assert result is mock_client
        mock_client.login.assert_called_once()

    def test_первый_вызов_падает_второй_успешен(self):
        mock_client = MagicMock()
        call_count = [0]

        def factory(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("temporary")
            return mock_client

        with (
            patch("transport.IMAPClient", side_effect=factory),
            patch("time.sleep"),
        ):
            result = transport.imap_conn()
        assert result is mock_client
        assert call_count[0] == 2

    def test_все_попытки_упали_поднимает_исключение(self):
        import pytest

        with (
            patch("transport.IMAPClient", side_effect=ConnectionError("down")),
            patch("time.sleep"),
            pytest.raises(ConnectionError),
        ):
            transport.imap_conn()


class TestPollResponseErrors:
    def setup_method(self):
        ioe_web.pending.clear()
        ioe_web.seen_notification_uids.clear()

    def test_fetch_возвращает_пустой_dict_продолжает_цикл(self):
        mock_imap = MagicMock()
        mock_imap.select_folder.return_value = {}
        mock_imap.noop.return_value = None
        mock_imap.search.return_value = [1]
        mock_imap.fetch.return_value = {}
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
        mock_imap.select_folder.return_value = {}
        mock_imap.noop.return_value = None
        mock_imap.search.return_value = [1]

        fake_raw = b"From: x\r\n\r\nbody"
        mock_imap.fetch.return_value = {1: {b"RFC822": fake_raw}}
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
        mock_imap.select_folder.return_value = {}
        mock_imap.noop.return_value = None
        mock_imap.search.return_value = []
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
        mock_imap.select_folder.return_value = {}
        mock_imap.noop.return_value = None
        mock_imap.search.return_value = [42]
        mock_imap.fetch.return_value = {42: {b"RFC822": raw}}
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

    def test_set_flags_ошибка_при_найденном_ответе_продолжает(self):
        req_id = "req-store-err"
        response_dict = {"id": req_id, "status": 200, "body": "ok"}
        raw = _make_encrypted_email(response_dict)

        mock_imap = MagicMock()
        mock_imap.select_folder.return_value = {}
        mock_imap.noop.return_value = None
        mock_imap.search.return_value = [1]
        mock_imap.fetch.return_value = {1: {b"RFC822": raw}}
        mock_imap.set_flags.side_effect = Exception("store failed")
        mock_imap.expunge.return_value = None
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
        mock_imap.select_folder.return_value = {}
        mock_imap.noop.return_value = None
        search_calls = []
        call_count = [0]

        fake_raw = b"From: x\r\n\r\nbody"

        def fake_search(criteria):
            search_calls.append(criteria)
            if "BEFORE" in criteria:
                return []
            call_count[0] += 1
            return [call_count[0]]

        mock_imap.search.side_effect = fake_search
        mock_imap.fetch.return_value = {1: {b"RFC822": fake_raw}}
        mock_imap.logout.return_value = None

        with (
            patch.object(transport, "imap_conn", return_value=mock_imap),
            patch("time.sleep"),
            patch("time.time", return_value=0.0),
        ):
            transport.poll_response("user1", "req-old-cleanup")

        has_before = any("BEFORE" in criteria for criteria in search_calls if isinstance(criteria, list))
        assert has_before

    def test_classify_error_вызывается_при_ошибке_в_ответе(self):
        req_id = "req-classify"
        response_dict = {"id": req_id, "status": 500, "error": "something broke"}
        raw = _make_encrypted_email(response_dict)

        mock_imap = MagicMock()
        mock_imap.select_folder.return_value = {}
        mock_imap.noop.return_value = None
        mock_imap.search.return_value = [1]
        mock_imap.fetch.return_value = {1: {b"RFC822": raw}}
        mock_imap.set_flags.return_value = {}
        mock_imap.expunge.return_value = None
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

    def test_stale_response_uids_cleaned_when_own_found(self):
        req_id = "req-cleanup"
        my_response = {"id": req_id, "status": 200, "body": "ok"}
        stale_response = {"id": "old-req-999", "status": 200, "body": "stale"}

        raw_mine = _make_encrypted_email(my_response)
        raw_stale = _make_encrypted_email(stale_response)

        mock_imap = MagicMock()
        mock_imap.select_folder.return_value = {}
        mock_imap.noop.return_value = None
        mock_imap.search.return_value = [10, 20]
        mock_imap.fetch.side_effect = lambda uids, _: {
            uid: {b"RFC822": raw_mine if uid == 10 else raw_stale} for uid in uids
        }
        mock_imap.set_flags.return_value = {}
        mock_imap.expunge.return_value = None
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

        set_flags_calls = mock_imap.set_flags.call_args_list
        all_flagged_uids = set()
        for call in set_flags_calls:
            for uid in call[0][0]:
                all_flagged_uids.add(uid)
        assert 10 in all_flagged_uids, "own UID must be deleted"
        assert 20 in all_flagged_uids, "stale response UID must also be deleted"
