"""IoE transport layer: IMAP connection, send/receive, link rewriting."""
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

from crypto import encrypt, decrypt

log = logging.getLogger("ioe-web")


def imap_conn():
    import ioe_web
    m = imaplib.IMAP4_SSL(ioe_web.IMAP_HOST, 993)
    m.login(ioe_web.EMAIL, ioe_web.IMAP_PASSWORD)
    return m


def send_request(m, request_dict):
    import ioe_web
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
    m.append(ioe_web.QUEUE_FOLDER, None, None, msg.as_bytes())


def extract_attachment(raw):
    parsed = email_mod.message_from_bytes(raw)
    for part in parsed.walk():
        if part.get_content_disposition() == "attachment":
            return part.get_payload(decode=True)
    return None


def poll_response(user_id, req_id):
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
                time.sleep(1)
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
                        with ioe_web.lock:
                            ioe_web.notification_queues.setdefault(user_id, []).append(response)
                        continue
                    rid = response.get("id", "")
                    if rid == req_id:
                        elapsed = time.time() - t0
                        log.info("[%s] poll: FOUND response (%.1fs, status=%s)", req_id, elapsed, response.get("status"))
                        with ioe_web.lock:
                            ioe_web.pending[(user_id, req_id)] = response
                        m.logout()
                        return
                except Exception as e:
                    log.debug("[%s] poll: decrypt/parse skip uid=%s: %s", req_id, uid, e)
                    continue
            if cycle % 5 == 4:
                log.debug("[%s] poll: cycle %d, %.0fs elapsed, %d uids checked", req_id, cycle, time.time() - t0, len(seen_uids))
        elapsed = time.time() - t0
        log.warning("[%s] poll: TIMEOUT after %.0fs", req_id, elapsed)
        with ioe_web.lock:
            ioe_web.pending[(user_id, req_id)] = {"id": req_id, "status": 504, "error": "timeout ({}s)".format(int(elapsed))}
        m.logout()
    except Exception as e:
        elapsed = time.time() - t0
        log.error("[%s] poll: ERROR after %.0fs: %s", req_id, elapsed, e)
        with ioe_web.lock:
            ioe_web.pending[(user_id, req_id)] = {"id": req_id, "status": 500, "error": str(e)}


def rewrite_links(html):
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
