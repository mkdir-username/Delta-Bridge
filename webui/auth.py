"""Authentication: phone whitelist, httponly sessions, rate limiting, TOTP."""

from __future__ import annotations
import os
import json
import re
import time
import secrets
import hmac
import logging
import sys

import pyotp

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from ioe_types import Whitelist, SessionStore, RateStore  # noqa: E402

log = logging.getLogger("ioe.auth")

SESSION_TTL = 2592000
SESSION_IDLE_TTL = 86400
RATE_LIMIT = 5
RATE_WINDOW = 60
STATUS_RATE_LIMIT = 30
STATUS_RATE_WINDOW = 60
_CLEANUP_INTERVAL = 60

_whitelist: Whitelist = {}
_whitelist_path: str = ""
_sessions: SessionStore = {}
_sessions_path: str = ""
_rate: RateStore = {}
_status_rate: RateStore = {}
_last_cleanup: float = 0


def sign_whitelist(path: str, secret: str) -> None:
    with open(path, "rb") as f:
        content = f.read()
    sig = hmac.new(secret.encode(), content, "sha256").hexdigest()
    with open(path + ".sig", "w") as f:
        f.write(sig)


def load_whitelist(path: str | None = None, secret: str | None = None) -> None:
    global _whitelist, _whitelist_path
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "users.json")
    _whitelist_path = os.path.abspath(path)
    if not os.path.exists(_whitelist_path):
        _whitelist = {}
        log.warning("No users.json at %s", _whitelist_path)
        return

    with open(_whitelist_path, "rb") as f:
        raw = f.read()

    if secret is None and os.environ.get("IOE_REQUIRE_SIGNED_WHITELIST") == "1":
        secret = os.environ.get("IOE_SECRET")
        if not secret:
            raise ValueError("IOE_REQUIRE_SIGNED_WHITELIST=1 but IOE_SECRET unset")

    if secret:
        sig_path = _whitelist_path + ".sig"
        if not os.path.exists(sig_path):
            raise ValueError("users.json integrity: .sig file missing")
        with open(sig_path) as f:
            expected_sig = f.read().strip()
        actual_sig = hmac.new(secret.encode(), raw, "sha256").hexdigest()
        if not hmac.compare_digest(expected_sig, actual_sig):
            raise ValueError("users.json integrity: signature mismatch — file tampered")

    _whitelist = json.loads(raw)
    log.info("Loaded %d phones from %s", len(_whitelist), _whitelist_path)
    if not _whitelist:
        log.error("WHITELIST EMPTY — no users can log in")


def init_sessions(path: str | None = None) -> None:
    global _sessions, _sessions_path
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sessions.json")
    _sessions_path = os.path.abspath(path)
    if os.path.exists(_sessions_path):
        try:
            with open(_sessions_path) as f:
                _sessions = json.load(f)
            expired = [s for s, d in _sessions.items() if time.time() - d["last_seen"] > SESSION_TTL]
            for s in expired:
                _sessions.pop(s, None)
            log.info("Loaded %d sessions from %s", len(_sessions), _sessions_path)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load sessions: %s", e)
            _sessions = {}
    if _sessions:
        _save_sessions()


def _save_sessions() -> None:
    if not _sessions_path:
        return
    try:
        tmp = _sessions_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(_sessions, f)
        os.replace(tmp, _sessions_path)
    except OSError as e:
        log.warning("Failed to save sessions: %s", e)


def _normalize_phone(phone: str) -> str:
    phone = re.sub(r"[\s\-()]", "", phone)
    if not phone.startswith("+"):
        phone = "+" + phone
    return phone


def is_whitelisted(phone: str) -> bool:
    return _normalize_phone(phone) in _whitelist


def verify_password(phone: str, password: str) -> bool:
    import bcrypt

    phone = _normalize_phone(phone)
    entry = _whitelist.get(phone)
    if not entry or not isinstance(entry, dict):
        return False
    stored = entry.get("password")
    if not stored:
        return False
    return bcrypt.checkpw(password.encode(), stored.encode())


def hash_password(password: str) -> str:
    import bcrypt

    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def create_session(user_id: str) -> str:
    sid = secrets.token_hex(32)
    _sessions[sid] = {
        "user_id": user_id,
        "created": time.time(),
        "last_seen": time.time(),
    }
    _save_sessions()
    log.info("Session created for %s (sid=%s...)", user_id, sid[:8])
    return sid


def get_authenticated_user(cookie_header: str | None) -> str | None:
    _maybe_cleanup()
    if not cookie_header:
        return None
    sid = None
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith("sid="):
            sid = part[4:]
            break
    if not sid:
        return None
    for stored_sid, data in _sessions.items():
        if hmac.compare_digest(stored_sid, sid):
            now = time.time()
            created = data.get("created", now)
            if now - created > SESSION_TTL or now - data["last_seen"] > SESSION_IDLE_TTL:
                _sessions.pop(stored_sid, None)
                _save_sessions()
                return None
            data["last_seen"] = now
            return data["user_id"]
    return None


def delete_session(cookie_header: str | None) -> None:
    if not cookie_header:
        return
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith("sid="):
            sid = part[4:]
            if _sessions.pop(sid, None) is not None:
                _save_sessions()
            return


def check_rate_limit(ip: str) -> bool:
    now = time.time()
    timestamps = _rate.get(ip, [])
    timestamps = [t for t in timestamps if now - t < RATE_WINDOW]
    if len(timestamps) >= RATE_LIMIT:
        _rate[ip] = timestamps
        return False
    timestamps.append(now)
    _rate[ip] = timestamps
    return True


def check_status_rate_limit(ip: str) -> bool:
    now = time.time()
    timestamps = _status_rate.get(ip, [])
    timestamps = [t for t in timestamps if now - t < STATUS_RATE_WINDOW]
    if len(timestamps) >= STATUS_RATE_LIMIT:
        _status_rate[ip] = timestamps
        return False
    timestamps.append(now)
    _status_rate[ip] = timestamps
    return True


def _maybe_cleanup() -> None:
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return
    _last_cleanup = now
    expired = [s for s, d in _sessions.items() if now - d["last_seen"] > SESSION_TTL]
    for s in expired:
        _sessions.pop(s, None)
    if expired:
        _save_sessions()
    old_ips = [ip for ip, ts in _rate.items() if all(now - t > RATE_WINDOW for t in ts)]
    for ip in old_ips:
        _rate.pop(ip, None)


OTP_TTL = 300
OTP_RATE_LIMIT = 3
OTP_RATE_WINDOW = 300
_otp_phone_rate: RateStore = {}


def check_otp_rate_limit(phone: str) -> bool:
    phone = _normalize_phone(phone)
    now = time.time()
    timestamps = _otp_phone_rate.get(phone, [])
    timestamps = [t for t in timestamps if now - t < OTP_RATE_WINDOW]
    if len(timestamps) >= OTP_RATE_LIMIT:
        _otp_phone_rate[phone] = timestamps
        return False
    timestamps.append(now)
    _otp_phone_rate[phone] = timestamps
    return True


def get_user_email(phone: str) -> str | None:
    phone = _normalize_phone(phone)
    entry = _whitelist.get(phone)
    if not entry or not isinstance(entry, dict):
        return None
    return entry.get("email")


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked = local[0] + "***"
    else:
        masked = local[0] + "***" + local[-1]
    return f"{masked}@{domain}"


_pending_totp: dict[str, dict[str, float | str]] = {}
PENDING_TOTP_TTL = 300


def set_pending_totp(phone: str, secret: str) -> None:
    phone = _normalize_phone(phone)
    _pending_totp[phone] = {"secret": secret, "ts": time.time()}


def get_pending_totp(phone: str) -> str | None:
    phone = _normalize_phone(phone)
    entry = _pending_totp.get(phone)
    if not entry:
        return None
    if time.time() - float(entry["ts"]) > PENDING_TOTP_TTL:
        _pending_totp.pop(phone, None)
        return None
    return str(entry["secret"])


def clear_pending_totp(phone: str) -> None:
    _pending_totp.pop(_normalize_phone(phone), None)


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def get_user_totp_secret(phone: str) -> str | None:
    phone = _normalize_phone(phone)
    entry = _whitelist.get(phone)
    if not entry or not isinstance(entry, dict):
        return None
    return entry.get("totp_secret")


def verify_totp(phone: str, code: str) -> bool:
    secret = get_user_totp_secret(phone)
    if not secret:
        return False
    return verify_totp_with_secret(secret, code)


def verify_totp_with_secret(secret: str, code: str) -> bool:
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def get_totp_provisioning_uri(phone: str, secret: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=phone, issuer_name="IoE")


def set_user_totp_secret(phone: str, secret: str) -> None:
    phone = _normalize_phone(phone)
    entry = _whitelist.get(phone)
    if entry is None:
        return
    if not isinstance(entry, dict):
        _whitelist[phone] = {"totp_secret": secret}
    else:
        entry["totp_secret"] = secret
    _save_whitelist()


def _save_whitelist() -> None:
    if not _whitelist_path:
        return
    try:
        tmp = _whitelist_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(_whitelist, f, indent=2, ensure_ascii=False)
        os.replace(tmp, _whitelist_path)
    except OSError as e:
        log.warning("Failed to save whitelist: %s", e)
