"""IoE transport layer: IMAP connection, send/receive, link rewriting."""
from __future__ import annotations
from typing import Any
import json
import uuid
import time
import random
import imaplib
import email as email_mod
import re
import logging
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".."))
from ioe_crypto import encrypt, decrypt

log = logging.getLogger("ioe-web")


def imap_conn() -> imaplib.IMAP4_SSL:
    import ioe_web
    last_err = None
    delays = [2, 5, 10, 20, 30]
    for attempt in range(len(delays) + 1):
        try:
            m = imaplib.IMAP4_SSL(ioe_web.IMAP_HOST, 993)
            m.login(ioe_web.EMAIL, ioe_web.IMAP_PASSWORD)
            return m
        except Exception as e:
            last_err = e
            if attempt < len(delays):
                delay = delays[attempt] + random.random() * delays[attempt] * 0.3
                log.warning("IMAP login attempt %d failed: %s (retry in %.0fs)", attempt + 1, e, delay)
                time.sleep(delay)
    raise last_err  # type: ignore[misc]  # always set after len(delays)+1 attempts


def send_request(m: imaplib.IMAP4_SSL, request_dict: dict[str, Any]) -> None:
    import ioe_web
    rid = request_dict.get("id", "?")
    log.info("[%s] send_request: APPEND to %s", rid, ioe_web.QUEUE_FOLDER)
    payload = json.dumps(request_dict)
    encrypted = encrypt(ioe_web.IOE_KEY, payload).encode("ascii")
    msg = MIMEMultipart()
    msg["Subject"] = "{} {}".format(random.choice(ioe_web.SUBJECTS), uuid.uuid4().hex[:8])
    msg["From"] = ioe_web.EMAIL
    msg["To"] = ioe_web.EMAIL
    msg.attach(MIMEText(random.choice(ioe_web.BODIES), "plain", "utf-8"))
    part = MIMEBase("application", "pdf")
    part.set_payload(encrypted)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment",
                    filename=random.choice(ioe_web.FILENAMES))
    msg.attach(part)
    m.append(ioe_web.QUEUE_FOLDER, None, None, msg.as_bytes())  # type: ignore[arg-type]  # RFC 3501: NIL valid
    log.info("[%s] send_request: APPEND OK", rid)


def extract_attachment(raw: bytes) -> bytes | None:
    parsed = email_mod.message_from_bytes(raw)
    for part in parsed.walk():
        if part.get_content_disposition() == "attachment":
            payload = part.get_payload(decode=True)
            return payload if isinstance(payload, bytes) else None
    return None


def poll_response(user_id: str, req_id: str) -> None:
    import ioe_web
    t0 = time.time()
    try:
        log.info("[%s] poll: connecting IMAP...", req_id)
        m = imap_conn()
        log.info("[%s] poll: connected (%.1fs)", req_id, time.time() - t0)
        m.select("INBOX")
        seen_uids = set()
        for cycle in range(60):
            if cycle > 0:
                time.sleep(1 + random.random() * 0.6)
            m.noop()
            _, msgs = m.search(None, "ALL")
            if not msgs[0]:
                continue
            uids = msgs[0].split()
            new_uids = [u for u in uids if u not in seen_uids]
            if not new_uids and cycle > 0:
                continue
            for uid in reversed(new_uids):
                seen_uids.add(uid)
                _, data = m.fetch(uid, "(RFC822)")
                if not data or not data[0] or data[0] is None:
                    continue
                raw = data[0][1]
                if not isinstance(raw, bytes):
                    continue
                att = extract_attachment(raw)
                if att is None:
                    continue
                try:
                    decrypted = decrypt(ioe_web.IOE_KEY, att.decode("ascii").strip())
                    response = json.loads(decrypted)
                    if response.get("type") == "notification":
                        uid_key = uid.decode() if isinstance(uid, bytes) else str(uid)
                        with ioe_web.lock:
                            if uid_key in ioe_web.seen_notification_uids:
                                continue
                            ioe_web.seen_notification_uids.add(uid_key)
                            ioe_web.notification_queues.setdefault(user_id, []).append(response)
                        continue
                    rid = response.get("id", "")
                    if rid == req_id:
                        elapsed = time.time() - t0
                        log.info("[%s] poll: FOUND response (%.1fs, status=%s)", req_id, elapsed, response.get("status"))
                        try:
                            m.store(uid, "+FLAGS", "\\Deleted")
                            m.expunge()
                        except Exception as e:
                            log.debug("[%s] poll: cleanup failed: %s", req_id, e)
                        if "error" in response:
                            from handler import _classify_error
                            err_type, err_msg = _classify_error(response["error"])
                            response["error"] = err_msg
                            if "error_type" not in response:
                                response["error_type"] = err_type
                        with ioe_web.lock:
                            ioe_web.pending[(user_id, req_id)] = response
                        m.logout()
                        return
                except Exception as e:
                    log.debug("[%s] poll: decrypt/parse skip uid=%s: %s", req_id, uid, e)
                    continue
            if cycle % 5 == 4:
                log.debug("[%s] poll: cycle %d, %.0fs elapsed, %d uids checked", req_id, cycle, time.time() - t0, len(seen_uids))
            if cycle % 10 == 9:
                from datetime import datetime, timedelta
                cutoff = (datetime.utcnow() - timedelta(minutes=5)).strftime("%d-%b-%Y")
                try:
                    _, old = m.search(None, "BEFORE", cutoff)
                    if old[0]:
                        for old_uid in old[0].split():
                            m.store(old_uid, "+FLAGS", "\\Deleted")
                        m.expunge()
                except Exception as e:
                    log.debug("[%s] poll: old mail cleanup: %s", req_id, e)
        elapsed = time.time() - t0
        log.warning("[%s] poll: TIMEOUT after %.0fs", req_id, elapsed)
        with ioe_web.lock:
            ioe_web.pending[(user_id, req_id)] = {"id": req_id, "status": 504, "error": "timeout ({}s)".format(int(elapsed)), "error_type": "transport"}
        m.logout()
    except Exception as e:
        elapsed = time.time() - t0
        log.error("[%s] poll: ERROR after %.0fs: %s", req_id, elapsed, e)
        from handler import _classify_error
        err_type, err_msg = _classify_error(str(e))
        with ioe_web.lock:
            ioe_web.pending[(user_id, req_id)] = {"id": req_id, "status": 500, "error": err_msg, "error_type": err_type}


def rewrite_links(html: str) -> str:
    html = re.sub(
        r'href="(https?://[^"]+)"',
        lambda m: 'href="/get?url={}"'.format(m.group(1)),
        html
    )
    html = re.sub(
        r"href='(https?://[^']+)'",
        lambda m: "href='/get?url={}'".format(m.group(1)),
        html
    )
    return html
