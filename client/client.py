"""IoE CLI client v2: folder-based, steganographic, AES-256-GCM."""

from __future__ import annotations
from typing import Any
import os
import sys
import json
import uuid
import time
import random
import imaplib
import email as email_mod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from ioe_crypto import derive_key, encrypt, decrypt

EMAIL: str = os.environ["EMAIL"]
PASSWORD: str = os.environ["IMAP_PASSWORD"]
IOE_KEY: bytes = derive_key(os.environ["IOE_SECRET"])

IMAP_HOST = "imap.yandex.ru"
QUEUE_FOLDER = "IoE"

SUBJECTS = [
    "Re: Встреча",
    "Fw: Документы",
    "Отчёт",
    "Заказ",
    "Фото",
    "Бронирование",
    "Напоминание",
    "Чек",
    "Re: Вопрос",
    "Fw: Счёт",
    "Расписание",
    "Доставка",
]
FILENAMES = ["report.pdf", "scan.pdf", "doc.pdf", "invoice.pdf", "notes.pdf"]
BODIES = ["", "см. вложение", "Документ", "Во вложении"]


def imap_conn() -> imaplib.IMAP4_SSL:
    m = imaplib.IMAP4_SSL(IMAP_HOST, 993)
    m.login(EMAIL, PASSWORD)
    return m


def send_request(m: imaplib.IMAP4_SSL, request_dict: dict[str, Any]) -> str:
    payload = json.dumps(request_dict)
    encrypted = encrypt(IOE_KEY, payload).encode("ascii")
    msg = MIMEMultipart()
    msg["Subject"] = f"{random.choice(SUBJECTS)} {uuid.uuid4().hex[:8]}"
    msg["From"] = EMAIL
    msg["To"] = EMAIL
    msg.attach(MIMEText(random.choice(BODIES), "plain", "utf-8"))
    part = MIMEBase("application", "pdf")
    part.set_payload(encrypted)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=random.choice(FILENAMES))
    msg.attach(part)
    m.append(QUEUE_FOLDER, None, None, msg.as_bytes())  # type: ignore[arg-type]  # RFC 3501: NIL valid
    return str(request_dict["id"])


def extract_attachment(raw: bytes) -> bytes | None:
    parsed = email_mod.message_from_bytes(raw)
    for part in parsed.walk():
        if part.get_content_disposition() == "attachment":
            payload = part.get_payload(decode=True)
            return payload if isinstance(payload, bytes) else None
    return None


def wait_response(m: imaplib.IMAP4_SSL, req_id: str, timeout: int = 90) -> dict[str, Any] | None:
    m.select("INBOX")
    for _ in range(timeout // 3):
        time.sleep(3)
        m.noop()
        _, msgs = m.search(None, "ALL")
        if not msgs[0]:
            continue
        uids = msgs[0].split()
        for uid in reversed(uids):
            _, data = m.fetch(uid, "(RFC822)")
            item = data[0]
            if not isinstance(item, tuple):
                continue
            raw = item[1]
            if not isinstance(raw, bytes):
                continue
            att = extract_attachment(raw)
            if att is None:
                continue
            try:
                decrypted = decrypt(IOE_KEY, att.decode("ascii").strip())
                response: dict[str, Any] = json.loads(decrypted)
                if response.get("id") == req_id:
                    return response
            except Exception:
                continue
    return None


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: client.py <cmd> <url_or_query>")
        print("  client.py get <url>       - reader mode")
        print("  client.py text <url>      - plain text")
        print("  client.py search <query>  - search")
        print("  client.py update          - self-update from VPS")
        sys.exit(1)

    cmd = sys.argv[1].upper()
    arg = " ".join(sys.argv[2:])
    req_id = uuid.uuid4().hex[:8]

    if cmd == "SEARCH":
        request = {"id": req_id, "cmd": "SEARCH", "query": arg}
    elif cmd == "UPDATE":
        request = {"id": req_id, "cmd": "UPDATE"}
    else:
        request = {"id": req_id, "cmd": cmd, "url": arg}

    m = imap_conn()
    send_request(m, request)
    print(f"Sent (id={req_id})")
    print("Waiting...")

    response = wait_response(m, req_id)
    if response:
        if response.get("status") == 200:
            if response.get("cmd") == "UPDATE":
                import shutil

                files = response.get("files", {})
                for fname, content in files.items():
                    target = os.path.expanduser(f"~/{fname}")
                    if os.path.exists(target):
                        shutil.copy2(target, target + ".bak")
                    with open(target, "w") as f:
                        f.write(content)
                    print(f"Updated: {fname}")
                print(f"Updated {len(files)} files. Restart ioe to apply.")
            else:
                title = response.get("title", "")
                if title:
                    print(f"\n=== {title} ===\n")
                body = response.get("body", "")
                if "<" in body and ">" in body:
                    from bs4 import BeautifulSoup

                    print(BeautifulSoup(body, "html.parser").get_text(separator="\n", strip=True))
                else:
                    print(body)
        else:
            print(f"Error: {response.get('error', 'unknown')}")
    else:
        print("Timeout: no response in 90s")

    m.logout()


if __name__ == "__main__":
    main()
