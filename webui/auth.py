"""Authentication: phone whitelist, httponly sessions, rate limiting, email OTP."""
import os
import json
import re
import time
import secrets
import hmac
import smtplib
import logging
from email.mime.text import MIMEText as _MIMEText

log = logging.getLogger("ioe.auth")

SESSION_TTL = 2592000
RATE_LIMIT = 5
RATE_WINDOW = 60
_CLEANUP_INTERVAL = 60

_whitelist = {}
_whitelist_path = ""
_sessions = {}
_sessions_path = ""
_rate = {}
_last_cleanup = 0


def load_whitelist(path=None):
    global _whitelist, _whitelist_path
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "users.json")
    _whitelist_path = os.path.abspath(path)
    if os.path.exists(_whitelist_path):
        with open(_whitelist_path) as f:
            _whitelist = json.load(f)
        log.info("Loaded %d phones from %s", len(_whitelist), _whitelist_path)
        if not _whitelist:
            log.error("WHITELIST EMPTY — no users can log in")
    else:
        _whitelist = {}
        log.warning("No users.json at %s", _whitelist_path)


def init_sessions(path=None):
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


def _save_sessions():
    if not _sessions_path:
        return
    try:
        tmp = _sessions_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(_sessions, f)
        os.replace(tmp, _sessions_path)
    except OSError as e:
        log.warning("Failed to save sessions: %s", e)


def _normalize_phone(phone):
    phone = re.sub(r"[\s\-()]", "", phone)
    if not phone.startswith("+"):
        phone = "+" + phone
    return phone


def is_whitelisted(phone):
    return _normalize_phone(phone) in _whitelist


def verify_password(phone, password):
    phone = _normalize_phone(phone)
    entry = _whitelist.get(phone)
    if not entry or not isinstance(entry, dict):
        return False
    stored = entry.get("password")
    if not stored:
        return False
    return hmac.compare_digest(stored, password)


def create_session(user_id):
    sid = secrets.token_hex(32)
    _sessions[sid] = {"user_id": user_id, "created": time.time(), "last_seen": time.time()}
    _save_sessions()
    log.info("Session created for %s (sid=%s...)", user_id, sid[:8])
    return sid


def get_authenticated_user(cookie_header):
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


def delete_session(cookie_header):
    if not cookie_header:
        return
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith("sid="):
            sid = part[4:]
            if _sessions.pop(sid, None) is not None:
                _save_sessions()
            return


def check_rate_limit(ip):
    now = time.time()
    timestamps = _rate.get(ip, [])
    timestamps = [t for t in timestamps if now - t < RATE_WINDOW]
    if len(timestamps) >= RATE_LIMIT:
        _rate[ip] = timestamps
        return False
    timestamps.append(now)
    _rate[ip] = timestamps
    return True


def _maybe_cleanup():
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
SMTP_HOST = "smtp.yandex.ru"
SMTP_PORT = 465
_otp_store = {}


def get_user_email(phone):
    phone = _normalize_phone(phone)
    entry = _whitelist.get(phone)
    if not entry or not isinstance(entry, dict):
        return None
    return entry.get("email")


def mask_email(email):
    if not email or "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked = local[0] + "***"
    else:
        masked = local[0] + "***" + local[-1]
    return "{}@{}".format(masked, domain)


def create_otp(phone):
    code = "{:05d}".format(secrets.randbelow(100000))
    _otp_store[_normalize_phone(phone)] = {"code": code, "created": time.time()}
    return code


def verify_otp(phone, code):
    phone = _normalize_phone(phone)
    entry = _otp_store.get(phone)
    if not entry:
        return False
    if time.time() - entry["created"] > OTP_TTL:
        _otp_store.pop(phone, None)
        return False
    if hmac.compare_digest(entry["code"], code):
        _otp_store.pop(phone, None)
        return True
    return False


def send_otp_email(to_email, code, from_email, smtp_password):
    msg = _MIMEText("Kod vhoda IoE: {}".format(code), "plain", "utf-8")
    msg["Subject"] = "IoE: kod vhoda"
    msg["From"] = from_email
    msg["To"] = to_email
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(from_email, smtp_password)
        server.send_message(msg)
    log.info("OTP sent to %s", to_email)
