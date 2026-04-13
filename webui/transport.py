"""IoE transport layer: IMAP connection, send/receive, link rewriting."""

from __future__ import annotations
from typing import Any
import imaplib
import json
import uuid
import time
import random
import email as email_mod
import re
from urllib.parse import quote as _url_quote
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

import sys as _sys
import os as _os

_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".."))
from ioe_crypto import compress_encrypt, decrypt_decompress

from imapclient import IMAPClient

log = logging.getLogger("ioe-web")

import threading

_pool: dict[str, IMAPClient] = {}
_pool_lock = threading.Lock()

_poll_pool: dict[str, tuple[Any, float]] = {}
_poll_pool_lock = threading.Lock()
_POLL_TTL = 120.0


def _acquire_poll_conn(user_id: str) -> Any:
    with _poll_pool_lock:
        entry = _poll_pool.pop(user_id, None)
    if entry is not None:
        conn, ts = entry
        if time.time() - ts < _POLL_TTL:
            try:
                conn.noop()
                return conn
            except Exception:
                try:
                    conn.logout()
                except Exception:
                    pass
        else:
            try:
                conn.logout()
            except Exception:
                pass
    return _create_conn()


def _release_poll_conn(user_id: str, conn: Any, healthy: bool) -> None:
    if conn is None:
        return
    if healthy:
        with _poll_pool_lock:
            _poll_pool[user_id] = (conn, time.time())
    else:
        try:
            conn.logout()
        except Exception:
            pass


def _create_conn() -> IMAPClient:
    import ioe_web

    last_err = None
    delays = [2, 5, 10, 20, 30]
    for attempt in range(len(delays) + 1):
        try:
            client = IMAPClient(ioe_web.IMAP_HOST, ssl=True)
            client.login(ioe_web.EMAIL, ioe_web.IMAP_PASSWORD)
            return client
        except Exception as e:
            last_err = e
            if attempt < len(delays):
                delay = delays[attempt] + random.random() * delays[attempt] * 0.3
                log.warning(
                    "IMAP login attempt %d failed: %s (retry in %.0fs)",
                    attempt + 1,
                    e,
                    delay,
                )
                time.sleep(delay)
    raise last_err  # type: ignore[misc]  # always set after len(delays)+1 attempts


def imap_conn() -> IMAPClient:
    import ioe_web

    with _pool_lock:
        key = f"{ioe_web.EMAIL}@{ioe_web.IMAP_HOST}"
        if key in _pool:
            client = _pool[key]
            try:
                client.noop()
                return client
            except Exception:
                log.info("Stale pooled connection, reconnecting")
                try:
                    client.logout()
                except Exception:
                    pass
                del _pool[key]
        client = _create_conn()
        _pool[key] = client
        return client


def send_request(m: Any, request_dict: dict[str, Any]) -> None:
    import ioe_web

    rid = request_dict.get("id", "?")
    log.info("[%s] send_request: APPEND to %s", rid, ioe_web.QUEUE_FOLDER)
    payload = json.dumps(request_dict)
    encrypted = compress_encrypt(ioe_web.IOE_KEY, payload).encode("ascii")
    subtype = random.choice(["mixed", "alternative", "related"])
    msg = MIMEMultipart(subtype)
    msg["Subject"] = f"{random.choice(ioe_web.SUBJECTS)} {uuid.uuid4().hex[:8]}"
    msg["From"] = ioe_web.EMAIL
    msg["To"] = ioe_web.EMAIL
    if random.random() < 0.3:
        msg["Reply-To"] = ioe_web.EMAIL
    if random.random() < 0.3:
        msg["In-Reply-To"] = f"<{uuid.uuid4().hex[:12]}@yandex.ru>"
    body_text = random.choice(ioe_web.BODIES)
    if body_text:
        body_text += " " * random.randint(0, 200)
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    app_type = random.choice([("application", "pdf"), ("application", "octet-stream"), ("application", "x-compressed")])
    part = MIMEBase(app_type[0], app_type[1])
    part.set_payload(encrypted)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=random.choice(ioe_web.FILENAMES))
    msg.attach(part)
    from ioe_telemetry import Timer

    with Timer() as t_append:
        m.append(ioe_web.QUEUE_FOLDER, msg.as_bytes())
    log.info("[%s] send_request: APPEND OK (%.0fms, %d bytes)", rid, t_append.elapsed_ms, len(encrypted))


def extract_attachment(raw: bytes) -> bytes | None:
    parsed = email_mod.message_from_bytes(raw)
    for part in parsed.walk():
        if part.get_content_disposition() == "attachment":
            payload = part.get_payload(decode=True)
            return payload if isinstance(payload, bytes) else None
    return None


_IDLE_SCHEDULE = [2, 2, 3, 3, 5, 5, 10, 10]


def poll_response(user_id: str, req_id: str, timeout: int = 60) -> None:
    import ioe_web
    from ioe_telemetry import RequestTiming, Timer, collector

    timing = RequestTiming(req_id)
    t0 = time.time()
    m = None
    healthy = True
    try:
        log.info("[%s] poll: connecting IMAP...", req_id)
        with Timer() as t_conn:
            m = _acquire_poll_conn(user_id)
        timing.record("connect", t_conn.elapsed_ms)
        log.info("[%s] poll: connected (%.1fs)", req_id, time.time() - t0)
        m.select_folder("INBOX")
        seen_uids: set[int] = set()
        stale_response_uids: list[int] = []
        deadline = t0 + timeout
        cycle = 0
        while time.time() < deadline:
            cycle += 1
            try:
                if cycle > 0:
                    try:
                        m.idle()
                        idle_timeout = _IDLE_SCHEDULE[min(cycle, len(_IDLE_SCHEDULE) - 1)]
                        m.idle_check(timeout=idle_timeout)
                        m.idle_done()
                    except Exception:
                        time.sleep(1 + random.random() * 0.6)
                        try:
                            m.noop()
                        except Exception:
                            log.info("[%s] poll: reconnecting after IDLE failure", req_id)
                            try:
                                m.logout()
                            except Exception:
                                pass
                            m = _create_conn()
                            m.select_folder("INBOX")
                uids = m.search(["ALL"])
                if not uids:
                    continue
                new_uids = [u for u in uids if u not in seen_uids]
                if not new_uids and cycle > 0:
                    continue
                for uid in reversed(new_uids):
                    seen_uids.add(uid)
                    data = m.fetch([uid], ["RFC822"])
                    if uid not in data:
                        continue
                    raw = data[uid].get(b"RFC822")
                    if not isinstance(raw, bytes):
                        continue
                    att = extract_attachment(raw)
                    if att is None:
                        continue
                    try:
                        decrypted = decrypt_decompress(ioe_web.IOE_KEY, att.decode("ascii").strip())
                        response = json.loads(decrypted)
                        if response.get("type") == "notification":
                            uid_key = str(uid)
                            with ioe_web.lock:
                                if uid_key in ioe_web._seen_set:
                                    continue
                                ioe_web.seen_notification_uids.append(uid_key)
                                ioe_web._seen_set.add(uid_key)
                                ioe_web._trim_seen_uids()
                            ioe_web.enqueue_notification(user_id, response)
                            continue
                        rid = response.get("id", "")
                        if rid != req_id:
                            resp_type = response.get("type", "")
                            resp_user = response.get("user_id", "")
                            if resp_type != "claude_proxy_response" and (not resp_user or resp_user == user_id):
                                stale_response_uids.append(uid)
                        if rid == req_id:
                            elapsed = time.time() - t0
                            timing.record("wait", elapsed * 1000 - t_conn.elapsed_ms)
                            log.info(
                                "[%s] poll: FOUND response (%.1fs, status=%s)",
                                req_id,
                                elapsed,
                                response.get("status"),
                            )
                            try:
                                delete_uids = stale_response_uids + [uid]
                                m.set_flags(delete_uids, [b"\\Deleted"])
                                m.expunge()
                            except Exception as e:
                                log.debug("[%s] poll: cleanup failed: %s", req_id, e)
                            if "error" in response:
                                try:
                                    from handler import _classify_error

                                    err_type, err_msg = _classify_error(response["error"])
                                    response["error"] = err_msg
                                    if "error_type" not in response:
                                        response["error_type"] = err_type
                                except Exception as e:
                                    log.debug("[%s] poll: _classify_error failed: %s", req_id, e)
                            collector.record(timing)
                            log.info("[%s] telemetry: %s", req_id, timing.summary())
                            response["_created"] = time.time()
                            with ioe_web.lock:
                                ioe_web.pending[(user_id, req_id)] = response
                            return
                    except Exception as e:
                        log.debug("[%s] poll: decrypt/parse skip uid=%s: %s", req_id, uid, e)
                        continue
                if cycle % 5 == 4:
                    log.debug(
                        "[%s] poll: cycle %d, %.0fs elapsed, %d uids checked",
                        req_id,
                        cycle,
                        time.time() - t0,
                        len(seen_uids),
                    )
                if cycle % 10 == 9:
                    from datetime import datetime, timedelta

                    cutoff = (datetime.utcnow() - timedelta(minutes=5)).strftime("%d-%b-%Y")
                    try:
                        old = m.search(["BEFORE", cutoff])
                        if old:
                            m.set_flags(old, [b"\\Deleted"])
                            m.expunge()
                    except Exception as e:
                        log.debug("[%s] poll: old mail cleanup: %s", req_id, e)
            except (imaplib.IMAP4.abort, ConnectionError, OSError, BrokenPipeError) as e:
                log.warning("[%s] poll: connection lost at cycle %d: %s, reconnecting", req_id, cycle, e)
                try:
                    m.logout()
                except Exception:
                    pass
                m = _create_conn()
                m.select_folder("INBOX")
                healthy = True
                continue
        elapsed = time.time() - t0
        log.warning("[%s] poll: TIMEOUT after %.0fs", req_id, elapsed)
        with ioe_web.lock:
            ioe_web.pending[(user_id, req_id)] = {
                "id": req_id,
                "status": 504,
                "error": f"timeout ({int(elapsed)}s)",
                "error_type": "transport",
                "_created": time.time(),
            }
    except Exception as e:
        elapsed = time.time() - t0
        log.error("[%s] poll: ERROR after %.0fs: %s", req_id, elapsed, e)
        healthy = False
        from handler import _classify_error

        err_type, err_msg = _classify_error(str(e))
        with ioe_web.lock:
            ioe_web.pending[(user_id, req_id)] = {
                "id": req_id,
                "status": 500,
                "error": err_msg,
                "error_type": err_type,
                "_created": time.time(),
            }
    finally:
        _release_poll_conn(user_id, m, healthy)


_DANGEROUS_HREF_RE = re.compile(
    r"""href=(['"])\s*(?:javascript|data|vbscript|file):[^'"]*\1""",
    re.IGNORECASE,
)


def rewrite_links(html: str) -> str:
    html = _DANGEROUS_HREF_RE.sub('href="#blocked"', html)
    html = re.sub(
        r'href="(https?://[^"]+)"',
        lambda m: f'href="/get?url={_url_quote(m.group(1), safe="")}"',
        html,
    )
    html = re.sub(
        r"href='(https?://[^']+)'",
        lambda m: "href='/get?url=" + _url_quote(m.group(1), safe="") + "'",
        html,
    )
    return html
