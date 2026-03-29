"""IoE Server v2: folder-based, steganographic, AES-256-GCM."""
import os
import sys
import time
import logging
import json
import uuid
import random
import io
import base64
import ipaddress
import socket
import email as email_mod
import email.utils
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from urllib.parse import urljoin, urlparse

import truststore
truststore.inject_into_ssl()

from imapclient import IMAPClient
from bs4 import BeautifulSoup
from readability import Document
from PIL import Image
import requests

from crypto import derive_key, encrypt, decrypt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("ioe")

EMAIL = os.environ["EMAIL"]
PASSWORD = os.environ["IMAP_PASSWORD"]
IOE_KEY = derive_key(os.environ["IOE_SECRET"])

IMAP_HOST = "imap.yandex.ru"
QUEUE_FOLDER = "IoE"
FETCH_TIMEOUT = 30
MAX_BODY = 50_000
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"

SUBJECTS = [
    "Re: Встреча", "Fw: Документы", "Отчёт", "Заказ",
    "Фото", "Бронирование", "Напоминание", "Чек",
    "Re: Вопрос", "Fw: Счёт", "Расписание", "Доставка",
    "Re: Проект", "Квитанция", "Запись", "Подтверждение",
]
FILENAMES = ["report.pdf", "scan.pdf", "doc.pdf", "invoice.pdf",
             "notes.pdf", "document.pdf", "file.pdf"]
BODIES = ["", "см. вложение", "Документ", "Во вложении", "В приложении"]

BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "metadata.google.internal"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
RATE_LIMIT = 10
RATE_WINDOW = 60
_rate_timestamps = []


def validate_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http/https")
    host = parsed.hostname or ""
    if host in BLOCKED_HOSTS:
        raise ValueError("Blocked host")
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("Private IP")
    except ValueError as e:
        if "Private" in str(e) or "Blocked" in str(e):
            raise
        try:
            resolved = socket.getaddrinfo(host, None, socket.AF_INET)
            for _, _, _, _, addr in resolved:
                ip = ipaddress.ip_address(addr[0])
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    raise ValueError("Resolved to private IP")
        except socket.gaierror:
            pass


def check_rate_limit():
    now = time.time()
    _rate_timestamps[:] = [t for t in _rate_timestamps if now - t < RATE_WINDOW]
    if len(_rate_timestamps) >= RATE_LIMIT:
        raise ValueError("Rate limit exceeded")
    _rate_timestamps.append(now)


def make_envelope(encrypted_bytes):
    msg = MIMEMultipart()
    msg["Subject"] = f"{random.choice(SUBJECTS)} {uuid.uuid4().hex[:8]}"
    msg["From"] = EMAIL
    msg["To"] = EMAIL
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg.attach(MIMEText(random.choice(BODIES), "plain", "utf-8"))
    part = MIMEBase("application", "pdf")
    part.set_payload(encrypted_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment",
                    filename=random.choice(FILENAMES))
    msg.attach(part)
    return msg


def append_response(client, response_dict):
    payload = json.dumps(response_dict, ensure_ascii=False)
    encrypted = encrypt(IOE_KEY, payload).encode("ascii")
    msg = make_envelope(encrypted)
    client.append("INBOX", msg.as_bytes())


def fetch_text(url):
    validate_url(url)
    resp = requests.get(url, timeout=FETCH_TIMEOUT, headers={"User-Agent": UA})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


MIN_READABLE_LEN = 500


def fetch_content(url):
    """Fetch URL content: readability first, fallback to soup if too short."""
    validate_url(url)
    resp = requests.get(url, timeout=FETCH_TIMEOUT, headers={"User-Agent": UA})
    resp.raise_for_status()
    raw_html = resp.text

    try:
        doc = Document(raw_html)
        title = doc.title()
        content = doc.summary()
        content = inline_images(content, url)
        if len(content) > MIN_READABLE_LEN:
            return title, content, "html"
        log.info("readability too short (%d chars), falling back to soup", len(content))
    except Exception as e:
        title = ""
        log.warning("readability failed: %s", e)

    soup = BeautifulSoup(raw_html, "html.parser")
    title = title or (soup.title.string if soup.title else "")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
        tag.decompose()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/"):
            from urllib.parse import urlparse as _up
            base = _up(url)
            a["href"] = "{}://{}{}".format(base.scheme, base.netloc, href)
    body = soup.find("body") or soup
    return title or "", str(body), "html"


def fetch_readable(url):
    validate_url(url)
    resp = requests.get(url, timeout=FETCH_TIMEOUT, headers={"User-Agent": UA})
    resp.raise_for_status()
    doc = Document(resp.text)
    title = doc.title()
    content = doc.summary()
    content = inline_images(content, url)
    return title, content


def inline_images(html, base_url, max_images=10, max_kb=80):
    soup = BeautifulSoup(html, "html.parser")
    count = 0
    for img in soup.find_all("img", src=True):
        if count >= max_images:
            img.decompose()
            continue
        try:
            img_url = urljoin(base_url, img["src"])
            try:
                validate_url(img_url)
            except ValueError:
                img.decompose()
                continue
            resp = requests.get(img_url, timeout=10, headers={"User-Agent": UA}, stream=True)
            content_len = int(resp.headers.get("Content-Length", 0))
            if content_len > MAX_IMAGE_BYTES:
                img.decompose()
                continue
            img_data = resp.content
            if len(img_data) > MAX_IMAGE_BYTES:
                img.decompose()
                continue
            pil_img = Image.open(io.BytesIO(img_data))
            if pil_img.width > 800:
                ratio = 800 / pil_img.width
                pil_img = pil_img.resize((800, int(pil_img.height * ratio)))
            buf = io.BytesIO()
            pil_img.convert("RGB").save(buf, "JPEG", quality=60)
            if buf.tell() > max_kb * 1024:
                buf = io.BytesIO()
                pil_img.convert("RGB").save(buf, "JPEG", quality=40)
            b64 = base64.b64encode(buf.getvalue()).decode()
            img["src"] = f"data:image/jpeg;base64,{b64}"
            count += 1
        except Exception:
            img.decompose()
    return str(soup)


def do_search(query):
    try:
        from ddgs import DDGS
        results = DDGS().text(query, max_results=10)
        return [
            {"title": r.get("title", ""), "href": r.get("href", ""), "snippet": r.get("body", "")}
            for r in results
        ]
    except Exception as e:
        return [{"title": "Search error", "href": "", "snippet": str(e)}]


def extract_attachment(raw):
    parsed = email_mod.message_from_bytes(raw)
    for part in parsed.walk():
        if part.get_content_disposition() == "attachment":
            return part.get_payload(decode=True)
    return None


def process_message(client, uid, raw):
    payload = extract_attachment(raw)
    if payload is None:
        log.warning("uid=%s: no attachment, skipping", uid)
        return False

    try:
        decrypted = decrypt(IOE_KEY, payload.decode("ascii").strip())
        request = json.loads(decrypted)
    except Exception:
        log.warning("uid=%s: decrypt failed, skipping", uid)
        return False

    cmd = request.get("cmd", "GET").upper()
    req_id = request.get("id", "")
    log.info("Processing uid=%s", uid)

    try:
        check_rate_limit()
        if cmd == "SEARCH":
            query = request.get("query", "")
            results = do_search(query)
            append_response(client, {"id": req_id, "status": 200, "results": results})
        elif cmd == "TEXT":
            url = request.get("url", "")
            text = fetch_text(url)
            if len(text) > MAX_BODY:
                text = text[:MAX_BODY] + "\n\n[truncated]"
            append_response(client, {"id": req_id, "status": 200, "body": text})
        elif cmd == "UPDATE":
            files = {}
            base_dir = os.path.dirname(os.path.abspath(__file__))
            for fname in ["client.py", "crypto.py", "ioe_web.py"]:
                fpath = os.path.join(base_dir, fname)
                if os.path.exists(fpath):
                    with open(fpath, "r") as f:
                        files[fname] = f.read()
            append_response(client, {
                "id": req_id, "status": 200, "cmd": "UPDATE", "files": files,
            })
        else:
            url = request.get("url", "")
            title, content, fmt = fetch_content(url)
            if len(content) > MAX_BODY:
                content = content[:MAX_BODY]
            append_response(client, {
                "id": req_id, "status": 200, "title": title,
                "body": content, "format": fmt,
            })
        log.info("Done uid=%s", uid)
    except Exception as e:
        append_response(client, {"id": req_id, "status": 500, "error": type(e).__name__})
        log.error("Failed uid=%s: %s: %s", uid, type(e).__name__, e)

    return True


def main():
    log.info("IoE server v2 starting")
    while True:
        try:
            with IMAPClient(IMAP_HOST, ssl=True) as client:
                client.login(EMAIL, PASSWORD)
                client.select_folder(QUEUE_FOLDER)
                log.info("Connected, monitoring folder '%s'", QUEUE_FOLDER)
                while True:
                    messages = client.search(["ALL"])
                    for uid in messages:
                        data = client.fetch([uid], ["RFC822"])
                        raw = data[uid][b"RFC822"]
                        processed = process_message(client, uid, raw)
                        if processed:
                            client.delete_messages([uid])
                            client.expunge()
                            log.info("Deleted uid=%s from queue", uid)
                    client.idle()
                    client.idle_check(timeout=5)
                    client.idle_done()
        except Exception as e:
            log.error("Connection error: %s, reconnecting in 5s", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
