"""Local HTTP proxy that tunnels Claude Code CLI traffic through IoE IMAP transport."""
from __future__ import annotations
import json
import os
import sys
import time
import uuid
import random
import logging
import imaplib
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import Any
import email as email_mod

from crypto import derive_key, compress_encrypt, decrypt_decompress

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
log = logging.getLogger("claude-proxy")

EMAIL: str = os.environ.get("EMAIL", "")
IMAP_PASSWORD: str = os.environ.get("IMAP_PASSWORD", "")
IOE_SECRET: str = os.environ.get("IOE_SECRET", "")
IOE_KEY: bytes = derive_key(IOE_SECRET) if IOE_SECRET else b""

IMAP_HOST: str = "imap.yandex.ru"
QUEUE_FOLDER: str = "IoE"
PROXY_PORT: int = int(os.environ.get("IOE_CLAUDE_PORT", "8090"))
POLL_CYCLES: int = 300

SUBJECTS: list[str] = [
    "Re: Протокол совещания", "Отчёт за неделю", "ТЗ на доработку",
    "Коммерческое предложение", "Fw: Акт выполненных работ",
    "Re: Согласование бюджета", "Счёт на оплату", "Fw: Заявка на отпуск",
    "Фото с дня рождения", "Re: Рецепт шарлотки", "Билеты на поезд",
    "Заказ подтверждён", "Fw: Чек об оплате", "Статус доставки",
]
FILENAMES: list[str] = [
    "scan_001.pdf", "receipt.pdf", "document.pdf", "invoice.pdf",
    "report.pdf", "contract.pdf", "act.pdf", "statement.pdf",
]
BODIES: list[str] = [
    "см. вложение", "Документ во вложении", "Пересылаю",
    "Как договаривались", "Подтверждение", "Во вложении",
]


_send_lock: threading.Lock = threading.Lock()
_send_conn: imaplib.IMAP4_SSL | None = None


def _imap_connect() -> imaplib.IMAP4_SSL:
    m = imaplib.IMAP4_SSL(IMAP_HOST, 993)
    m.login(EMAIL, IMAP_PASSWORD)
    return m


def _get_send_conn() -> imaplib.IMAP4_SSL:
    global _send_conn
    if _send_conn is not None:
        try:
            _send_conn.noop()
            return _send_conn
        except Exception:
            try:
                _send_conn.logout()
            except Exception:
                pass
            _send_conn = None
    _send_conn = _imap_connect()
    return _send_conn


def _send_via_imap(payload_b64: bytes) -> None:
    msg = MIMEMultipart()
    msg["Subject"] = "{} {}".format(random.choice(SUBJECTS), uuid.uuid4().hex[:8])
    msg["From"] = EMAIL
    msg["To"] = EMAIL
    msg.attach(MIMEText(random.choice(BODIES), "plain", "utf-8"))
    part = MIMEBase("application", "pdf")
    part.set_payload(payload_b64)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=random.choice(FILENAMES))
    msg.attach(part)
    with _send_lock:
        conn = _get_send_conn()
        conn.append(QUEUE_FOLDER, None, None, msg.as_bytes())  # type: ignore[arg-type]  # RFC 3501: NIL valid


def _extract_attachment(raw: bytes) -> bytes | None:
    parsed = email_mod.message_from_bytes(raw)
    for part in parsed.walk():
        if part.get_content_disposition() == "attachment":
            payload = part.get_payload(decode=True)
            return payload if isinstance(payload, bytes) else None
    return None


def _poll_response(req_id: str) -> dict[str, Any] | None:
    t0 = time.time()
    m = None
    try:
        m = _imap_connect()
        m.select("INBOX")
        seen_uids = set()
        for cycle in range(POLL_CYCLES):
            if cycle > 0:
                interval = 0.3 if cycle < 10 else (0.5 if cycle < 30 else 1.0)
                time.sleep(interval)
            try:
                m.noop()
            except Exception:
                m = _imap_connect()
                m.select("INBOX")
            _, msgs = m.search(None, "UNSEEN")
            if not msgs[0]:
                if cycle > 5:
                    _, msgs = m.search(None, "ALL")
                    if not msgs[0]:
                        continue
                else:
                    continue
            uids = msgs[0].split()
            new_uids = [u for u in uids if u not in seen_uids]
            for uid in reversed(new_uids):
                seen_uids.add(uid)
                _, data = m.fetch(uid, "(RFC822)")
                if not data or not data[0] or data[0] is None:
                    continue
                raw = data[0][1]
                if not isinstance(raw, bytes):
                    continue
                att = _extract_attachment(raw)
                if att is None:
                    continue
                try:
                    decrypted = decrypt_decompress(IOE_KEY, att.decode("ascii").strip())
                    response = json.loads(decrypted)
                    if response.get("id") == req_id:
                        elapsed = time.time() - t0
                        log.info("[%s] response (%.1fs, cycle %d)", req_id, elapsed, cycle)
                        try:
                            m.store(uid, "+FLAGS", "\\Deleted")
                            m.expunge()
                        except Exception:
                            pass
                        m.logout()
                        return response
                except Exception:
                    continue
        elapsed = time.time() - t0
        log.warning("[%s] poll timeout after %.0fs", req_id, elapsed)
        if m:
            m.logout()
        return None
    except Exception as e:
        log.error("[%s] poll error: %s", req_id, e)
        if m:
            try:
                m.logout()
            except Exception:
                pass
        return None


class ClaudeProxyHandler(BaseHTTPRequestHandler):
    def _handle_request(self, method: str) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else None

        headers = {k.lower(): v for k, v in self.headers.items()}
        req_id = uuid.uuid4().hex

        request_dict = {
            "type": "claude_proxy",
            "id": req_id,
            "user_id": "claude",
            "http_request": {
                "method": method,
                "path": self.path,
                "headers": headers,
                "body": body,
            },
        }

        t_start = time.time()
        with open("/tmp/cp-trace.log", "a") as _f:
            _f.write(f"{time.strftime('%H:%M:%S')} REQ {method} {self.path}\n")
        log.info("[%s] %s %s", req_id, method, self.path)

        try:
            payload = json.dumps(request_dict)
            encrypted = compress_encrypt(IOE_KEY, payload).encode("ascii")
            _send_via_imap(encrypted)
        except Exception as e:
            log.error("[%s] IMAP send failed: %s", req_id, e)
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "IMAP send failed"}).encode())
            return

        response = _poll_response(req_id)
        if response is None:
            self.send_response(504)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "gateway timeout"}).encode())
            return

        http_resp = response.get("http_response", {})
        status_code = http_resp.get("status_code", 502)
        resp_headers = http_resp.get("headers", {})
        resp_body = http_resp.get("body", "")

        self.send_response(status_code)
        skip_headers = {"transfer-encoding", "content-encoding", "content-length"}
        for k, v in resp_headers.items():
            if k.lower() not in skip_headers:
                self.send_header(k, v)
        body_bytes = resp_body.encode("utf-8") if isinstance(resp_body, str) else resp_body
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

        elapsed = time.time() - t_start
        with open("/tmp/cp-trace.log", "a") as _f:
            _f.write(f"{time.strftime('%H:%M:%S')} RSP {status_code} {len(body_bytes)}b {elapsed:.1f}s {self.path}\n")
        log.info("[%s] ← %d (%d bytes, %.1fs)", req_id, status_code, len(body_bytes), elapsed)

    def do_GET(self) -> None:
        self._handle_request("GET")

    def do_POST(self) -> None:
        self._handle_request("POST")

    def do_PUT(self) -> None:
        self._handle_request("PUT")

    def do_PATCH(self) -> None:
        self._handle_request("PATCH")

    def do_DELETE(self) -> None:
        self._handle_request("DELETE")

    def do_OPTIONS(self) -> None:
        self._handle_request("OPTIONS")

    def do_HEAD(self) -> None:
        self._handle_request("HEAD")

    def log_message(self, format: str, *args: Any) -> None:
        pass


class ThreadedHTTPServer(HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def process_request(self, request: Any, client_address: Any) -> None:
        t = threading.Thread(target=self.process_request_thread, args=(request, client_address))
        t.daemon = True
        t.start()

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


def main() -> None:
    if not all([EMAIL, IMAP_PASSWORD, IOE_SECRET]):
        print("Set EMAIL, IMAP_PASSWORD, IOE_SECRET in environment or .env")
        sys.exit(1)

    log.info("Pre-connecting to IMAP...")
    _get_send_conn()
    log.info("IMAP ready")

    server = ThreadedHTTPServer(("127.0.0.1", PROXY_PORT), ClaudeProxyHandler)
    log.info("Claude IoE proxy on http://127.0.0.1:%d", PROXY_PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down")
        server.shutdown()


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
    except ImportError:
        def load_dotenv(path: Any) -> None:  # type: ignore[misc]  # fallback redefines import
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
        EMAIL = os.environ.get("EMAIL", "")
        IMAP_PASSWORD = os.environ.get("IMAP_PASSWORD", "")
        IOE_SECRET = os.environ.get("IOE_SECRET", "")
        IOE_KEY = derive_key(IOE_SECRET) if IOE_SECRET else b""
    main()
