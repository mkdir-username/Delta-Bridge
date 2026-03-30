"""Authentication: phone whitelist, httponly sessions, rate limiting."""
import os
import json
import re
import time
import secrets
import hmac
import logging

log = logging.getLogger("ioe.auth")

SESSION_TTL = 86400
RATE_LIMIT = 5
RATE_WINDOW = 60
_CLEANUP_INTERVAL = 60

_whitelist = {}
_whitelist_path = ""
_sessions = {}
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


def _normalize_phone(phone):
    phone = re.sub(r"[\s\-()]", "", phone)
    if not phone.startswith("+"):
        phone = "+" + phone
    return phone


def is_whitelisted(phone):
    return _normalize_phone(phone) in _whitelist


def create_session(user_id):
    sid = secrets.token_hex(32)
    _sessions[sid] = {"user_id": user_id, "created": time.time(), "last_seen": time.time()}
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
            if time.time() - data["created"] > SESSION_TTL:
                _sessions.pop(stored_sid, None)
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
            _sessions.pop(sid, None)
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
    expired = [s for s, d in _sessions.items() if now - d["created"] > SESSION_TTL]
    for s in expired:
        _sessions.pop(s, None)
    old_ips = [ip for ip, ts in _rate.items() if all(now - t > RATE_WINDOW for t in ts)]
    for ip in old_ips:
        _rate.pop(ip, None)
