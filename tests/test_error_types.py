import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webui"))

from handler import _classify_error


def test_imap_unavailable_is_transport():
    err_type, msg = _classify_error("UNAVAILABLE LOGIN internal server error")
    assert err_type == "transport"
    assert "недоступен" in msg


def test_timeout_is_transport():
    err_type, msg = _classify_error("timeout (60s)")
    assert err_type == "transport"


def test_session_expired_is_auth():
    err_type, msg = _classify_error("session expired, re-auth needed")
    assert err_type == "auth"


def test_not_registered_is_auth():
    err_type, msg = _classify_error("user not registered")
    assert err_type == "auth"


def test_flood_wait_is_rate_limit():
    err_type, msg = _classify_error("A wait of 300 seconds is required")
    assert err_type == "rate_limit"
    assert "мин" in msg


def test_unknown_error_is_vps():
    err_type, msg = _classify_error("something unexpected broke")
    assert err_type == "vps"
    assert "something unexpected" in msg


def test_phone_invalid_is_vps():
    err_type, msg = _classify_error("The phone number is invalid")
    assert err_type == "vps"
    assert "Неверный" in msg
