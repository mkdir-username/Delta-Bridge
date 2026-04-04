"""Tests for webui/auth.py"""
import sys
import os
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webui"))
import auth


def test_whitelisted_phone():
    auth._whitelist = {"+79274918222": {}, "+77479886313": {}}
    assert auth.is_whitelisted("+79274918222") is True
    assert auth.is_whitelisted("+79999999999") is False


def test_whitelist_normalization():
    auth._whitelist = {"+79274918222": {}}
    assert auth.is_whitelisted("79274918222") is True
    assert auth.is_whitelisted("+7 927 491 8222") is True
    assert auth.is_whitelisted("+7-927-491-8222") is True


def test_not_whitelisted():
    auth._whitelist = {}
    assert auth.is_whitelisted("+79999999999") is False


def test_create_and_get_session():
    auth._sessions.clear()
    sid = auth.create_session("alice")
    user = auth.get_authenticated_user("sid=" + sid)
    assert user == "alice"


def test_expired_session():
    auth._sessions.clear()
    sid = auth.create_session("bob")
    auth._sessions[sid]["last_seen"] = time.time() - auth.SESSION_TTL - 1
    user = auth.get_authenticated_user("sid=" + sid)
    assert user is None


def test_invalid_session():
    auth._sessions.clear()
    user = auth.get_authenticated_user("sid=nonexistent")
    assert user is None


def test_no_cookie():
    assert auth.get_authenticated_user("") is None
    assert auth.get_authenticated_user(None) is None


def test_rate_limit():
    auth._rate.clear()
    for _ in range(5):
        assert auth.check_rate_limit("1.2.3.4") is True
    assert auth.check_rate_limit("1.2.3.4") is False


def test_rate_limit_different_ips():
    auth._rate.clear()
    for _ in range(5):
        auth.check_rate_limit("1.1.1.1")
    assert auth.check_rate_limit("2.2.2.2") is True


def test_delete_session():
    auth._sessions.clear()
    sid = auth.create_session("carol")
    auth.delete_session("sid=" + sid)
    assert auth.get_authenticated_user("sid=" + sid) is None


def test_session_persistence(tmp_path):
    auth._sessions.clear()
    sessions_file = str(tmp_path / "sessions.json")
    auth._sessions_path = sessions_file

    sid = auth.create_session("alice")
    assert os.path.exists(sessions_file)

    with open(sessions_file) as f:
        data = json.load(f)
    assert sid in data
    assert data[sid]["user_id"] == "alice"


def test_session_load_on_init(tmp_path):
    auth._sessions.clear()
    sessions_file = str(tmp_path / "sessions.json")

    fake_data = {"abc123": {"user_id": "bob", "created": time.time(), "last_seen": time.time()}}
    with open(sessions_file, "w") as f:
        json.dump(fake_data, f)

    auth.init_sessions(sessions_file)
    user = auth.get_authenticated_user("sid=abc123")
    assert user == "bob"


def test_expired_sessions_not_loaded(tmp_path):
    auth._sessions.clear()
    sessions_file = str(tmp_path / "sessions.json")

    old_time = time.time() - auth.SESSION_TTL - 100
    fake_data = {"old_sid": {"user_id": "expired_user", "created": old_time, "last_seen": old_time}}
    with open(sessions_file, "w") as f:
        json.dump(fake_data, f)

    auth.init_sessions(sessions_file)
    assert auth.get_authenticated_user("sid=old_sid") is None


def test_session_auto_renew():
    auth._sessions.clear()
    auth._sessions_path = ""
    sid = auth.create_session("denis")
    auth._sessions[sid]["created"] = time.time() - 86400 * 20
    auth._sessions[sid]["last_seen"] = time.time() - 10
    user = auth.get_authenticated_user("sid=" + sid)
    assert user == "denis"


def test_otp_create_and_verify():
    auth._otp_store.clear()
    phone = "+79274918222"
    code = auth.create_otp(phone)
    assert len(code) == 5
    assert code.isdigit()
    assert auth.verify_otp(phone, code) is True
    assert auth.verify_otp(phone, code) is False


def test_otp_expired():
    auth._otp_store.clear()
    phone = "+79274918222"
    code = auth.create_otp(phone)
    auth._otp_store[phone]["created"] = time.time() - 600
    assert auth.verify_otp(phone, code) is False


def test_otp_wrong_code():
    auth._otp_store.clear()
    phone = "+79274918222"
    auth.create_otp(phone)
    assert auth.verify_otp(phone, "00000") is False


def test_get_user_email():
    auth._whitelist = {"+79274918222": {"email": "test@example.com"}}
    assert auth.get_user_email("+79274918222") == "test@example.com"
    assert auth.get_user_email("+79999999999") is None
    auth._whitelist = {"+79274918222": {}}
    assert auth.get_user_email("+79274918222") is None


def test_mask_email():
    assert auth.mask_email("cherba.denis1@gmail.com") == "c***1@gmail.com"
    assert auth.mask_email("ab@x.ru") == "a***@x.ru"
    assert auth.mask_email("a@x.ru") == "a***@x.ru"
    assert auth.mask_email(None) is None


def test_verify_password_no_password_in_whitelist():
    auth._whitelist = {"+79274918222": {"email": "test@example.com"}}
    assert auth.verify_password("+79274918222", "any") is False


def test_verify_password_correct():
    auth._whitelist = {"+79274918222": {"email": "t@t.com", "password": "secret123"}}
    assert auth.verify_password("+79274918222", "secret123") is True
    assert auth.verify_password("+79274918222", "wrong") is False


def test_verify_password_not_whitelisted():
    auth._whitelist = {}
    assert auth.verify_password("+79999999999", "any") is False


def test_send_otp_email():
    from unittest.mock import patch, MagicMock

    with patch("auth.smtplib.SMTP_SSL") as mock_smtp:
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        auth.send_otp_email("test@gmail.com", "42567", "user@yandex.ru", "pass123")

        mock_smtp.assert_called_once_with("smtp.yandex.ru", 465)
        mock_server.login.assert_called_once_with("user@yandex.ru", "pass123")
        mock_server.send_message.assert_called_once()
        msg = mock_server.send_message.call_args[0][0]
        assert "42567" in msg.get_payload(decode=True).decode()
        assert msg["To"] == "test@gmail.com"
