"""Tests for webui/auth.py"""
import sys
import os
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
