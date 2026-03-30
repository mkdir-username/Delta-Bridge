"""Tests for webui/auth.py"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webui"))
import auth


def test_verify_correct_password():
    import bcrypt
    pw = "testpass123"
    hashed = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    auth._users = {"testuser": {"password_hash": hashed}}
    assert auth.verify_password("testuser", pw) is True


def test_verify_wrong_password():
    import bcrypt
    hashed = bcrypt.hashpw(b"correct", bcrypt.gensalt()).decode()
    auth._users = {"testuser": {"password_hash": hashed}}
    assert auth.verify_password("testuser", "wrong") is False


def test_verify_nonexistent_user():
    auth._users = {}
    assert auth.verify_password("ghost", "anything") is False


def test_create_and_get_session():
    auth._sessions.clear()
    sid = auth.create_session("alice")
    user = auth.get_authenticated_user("sid=" + sid)
    assert user == "alice"


def test_expired_session():
    auth._sessions.clear()
    sid = auth.create_session("bob")
    auth._sessions[sid]["created"] = time.time() - auth.SESSION_TTL - 1
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
