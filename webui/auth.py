"""Authentication: phone whitelist, httponly sessions, rate limiting, email OTP."""

from __future__ import annotations
import os
import json
import re
import time
import secrets
import hmac
import smtplib
import threading
import logging
import sys
from email.mime.text import MIMEText as _MIMEText

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from ioe_types import OTPEntry, Whitelist, SessionStore, RateStore  # noqa: E402

log = logging.getLogger("ioe.auth")

SESSION_TTL = 2592000
RATE_LIMIT = 5
RATE_WINDOW = 60
_CLEANUP_INTERVAL = 60

_whitelist: Whitelist = {}
_whitelist_path: str = ""
_sessions: SessionStore = {}
_sessions_path: str = ""
_rate: RateStore = {}
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
            if time.time() - data["last_seen"] > SESSION_TTL:
                _sessions.pop(stored_sid, None)
                _save_sessions()
                return None
            data["last_seen"] = time.time()
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
SMTP_HOST = "smtp.yandex.ru"
SMTP_PORT = 465
_otp_lock = threading.Lock()
_otp_store: dict[str, OTPEntry] = {}
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


def create_otp(phone: str, ip: str | None = None) -> str:
    code = f"{secrets.randbelow(1000000):06d}"
    with _otp_lock:
        _otp_store[_normalize_phone(phone)] = {
            "code": code,
            "created": time.time(),
            "ip": ip,
        }
    return code


def verify_otp(phone: str, code: str, ip: str | None = None) -> bool:
    phone = _normalize_phone(phone)
    with _otp_lock:
        entry = _otp_store.get(phone)
        if not entry:
            return False
        if time.time() - entry["created"] > OTP_TTL:
            _otp_store.pop(phone, None)
            return False
        if entry.get("ip") and ip and entry["ip"] != ip:
            _otp_store.pop(phone, None)
            return False
        if hmac.compare_digest(entry["code"], code):
            _otp_store.pop(phone, None)
            return True
        return False


def send_otp_email(to_email: str, code: str, from_email: str, smtp_password: str) -> None:
    msg = _MIMEText(f"Kod vhoda IoE: {code}", "plain", "utf-8")
    msg["Subject"] = "IoE: kod vhoda"
    msg["From"] = from_email
    msg["To"] = to_email
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(from_email, smtp_password)
        server.send_message(msg)
    log.info("OTP sent to %s", to_email)
