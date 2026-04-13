"""IoE Server v2: folder-based, steganographic, AES-256-GCM."""

from __future__ import annotations
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
import fcntl
from collections import deque
import email as email_mod
import email.utils
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import Any
from urllib.parse import urljoin, urlparse

import truststore

truststore.inject_into_ssl()

from imapclient import IMAPClient
from bs4 import BeautifulSoup, Tag
from readability import Document
from PIL import Image
import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from ioe_crypto import (
    derive_key,
    decrypt,
    compress_encrypt,
    decrypt_decompress,
)

try:
    from browser_handler import handle_browser_request

    BROWSER_AVAILABLE = True
except ImportError:
    BROWSER_AVAILABLE = False

    def handle_browser_request(request: dict[str, Any]) -> dict[str, Any]:
        return {"status": 503, "error": "browser handler not available"}


try:
    from telegram_adapter import TelegramAdapter

    _tg_adapter = None

    def _get_telegram_adapter() -> Any:
        global _tg_adapter
        if _tg_adapter is None:
            _tg_adapter = TelegramAdapter()
            _tg_adapter.start()
        return _tg_adapter
except ImportError:
    _tg_adapter = None

    def _get_telegram_adapter() -> Any:
        return None


try:
    from claude_chat import ClaudeChat

    _claude_chat = ClaudeChat()
except ImportError:
    _claude_chat = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("ioe")

_tg_listeners_started: set[str] = set()


def _send_tg_notification(notification: dict[str, Any]) -> None:
    try:
        client = IMAPClient(IMAP_HOST, ssl=True)
        client.login(EMAIL, PASSWORD)
        append_response(client, notification)
        client.logout()
    except Exception as e:
        log.error("Failed to send TG notification: %s", e)


def _start_telegram_listener(adapter: Any, user_id: str) -> None:
    if user_id in _tg_listeners_started:
        return
    _tg_listeners_started.add(user_id)
    adapter.start_listener(user_id, _send_tg_notification)


EMAIL = os.environ["EMAIL"]
PASSWORD = os.environ["IMAP_PASSWORD"]
IOE_KEY = derive_key(os.environ["IOE_SECRET"])

IMAP_HOST = "imap.yandex.ru"
QUEUE_FOLDER = "IoE"
FETCH_TIMEOUT = 30
MAX_BODY = 50_000
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"

SUBJECTS = [
    "Отчёт за неделю",
    "Re: Протокол совещания",
    "ТЗ на доработку",
    "Коммерческое предложение",
    "Fw: Акт выполненных работ",
    "Re: Согласование бюджета",
    "Счёт на оплату",
    "Fw: Заявка на отпуск",
    "Служебная записка",
    "Re: План на квартал",
    "Табель учёта",
    "Fw: Приказ",
    "Заключение",
    "Re: Реестр документов",
    "Fw: Справка",
    "Протокол",
    "Re: Командировочное удостоверение",
    "Фото с дня рождения",
    "Re: Рецепт шарлотки",
    "Билеты на поезд",
    "Fw: Фотографии из отпуска",
    "Расписание тренировок",
    "Re: Адреса гостиниц",
    "Список покупок",
    "Заказ подтверждён",
    "Fw: Чек об оплате",
    "Статус доставки",
    "Re: Бронирование отеля",
    "Электронный билет",
    "Fw: Возврат товара",
    "Re: Трек-номер посылки",
    "Гарантийный талон",
    "Подтверждение регистрации",
    "Напоминание о записи",
    "Re: Уведомление",
    "Fw: Подтверждение оплаты",
    "Напоминание о встрече",
    "Re: Смена пароля",
    "Fw: Код подтверждения",
    "Уведомление о начислении",
    "Re: Квитанция",
    "Fw: Выписка по счёту",
    "Акт сверки",
    "Re: Дополнительное соглашение",
    "Fw: Техническое задание",
    "Накладная",
    "Re: График дежурств",
    "Fw: Инструкция",
    "Резюме",
    "Re: Приглашение на собеседование",
    "Fw: Результаты аттестации",
    "Расчётный лист",
]
FILENAMES = [
    "scan_001.pdf",
    "receipt.pdf",
    "document.pdf",
    "invoice.pdf",
    "report.pdf",
    "contract.pdf",
    "act.pdf",
    "photo.pdf",
    "statement.pdf",
    "form.pdf",
    "application.pdf",
    "letter.pdf",
    "schedule.pdf",
    "ticket.pdf",
    "confirmation.pdf",
    "order.pdf",
    "memo.pdf",
    "summary.pdf",
    "certificate.pdf",
    "reference.pdf",
]
BODIES = [
    "",
    "см. вложение",
    "Документ во вложении",
    "Пересылаю",
    "Как договаривались",
    "Подтверждение",
    "Во вложении",
    "Прошу ознакомиться",
    "К сведению",
    "Высылаю",
    "В приложении файл",
    "Документ",
    "Направляю",
    "По вашему запросу",
    "Для согласования",
]

BLOCKED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "169.254.169.254",
    "metadata.google.internal",
}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
RATE_LIMIT = 10
RATE_WINDOW = 60
_rate_timestamps: dict[str, list[float]] = {}
_processed_uids: set[int] = set()
_processed_uids_deque: deque[int] = deque()
_MAX_PROCESSED = 1000

_sessions: dict[str, dict[str, Any]] = {}
SESSION_TTL = 3600


def validate_url(url: str) -> None:
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
        for family in (socket.AF_INET, socket.AF_INET6):
            try:
                resolved = socket.getaddrinfo(host, None, family)
                for _, _, _, _, addr in resolved:
                    ip = ipaddress.ip_address(addr[0])
                    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                        raise ValueError("Resolved to private IP")
            except socket.gaierror:
                pass


def check_rate_limit(user_id: str = "default") -> None:
    now = time.time()
    if user_id not in _rate_timestamps:
        _rate_timestamps[user_id] = []
    ts = _rate_timestamps[user_id]
    ts[:] = [t for t in ts if now - t < RATE_WINDOW]
    if len(ts) >= RATE_LIMIT:
        raise ValueError("Rate limit exceeded")
    ts.append(now)


MIME_SUBTYPES = ["mixed", "alternative", "related"]
ATTACHMENT_TYPES = [
    ("application", "pdf"),
    ("application", "octet-stream"),
    ("application", "x-compressed"),
]
OPTIONAL_HEADERS: list[tuple[str, str]] = [
    ("CC", EMAIL),
    ("Reply-To", EMAIL),
    ("In-Reply-To", f"<{uuid.uuid4().hex[:12]}@yandex.ru>"),
    ("References", f"<{uuid.uuid4().hex[:12]}@yandex.ru>"),
]


def make_envelope(encrypted_bytes: bytes) -> MIMEMultipart:
    subtype = random.choice(MIME_SUBTYPES)
    msg = MIMEMultipart(subtype)
    msg["Subject"] = f"{random.choice(SUBJECTS)} {uuid.uuid4().hex[:8]}"
    msg["From"] = EMAIL
    msg["To"] = EMAIL
    msg["Date"] = email.utils.formatdate(localtime=True)
    for hdr, val in OPTIONAL_HEADERS:
        if random.random() < 0.3:
            if hdr in ("In-Reply-To", "References"):
                val = f"<{uuid.uuid4().hex[:12]}@yandex.ru>"
            msg[hdr] = val
    body_text = random.choice(BODIES)
    if body_text:
        body_text += " " * random.randint(0, 200)
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    app_type, app_subtype = random.choice(ATTACHMENT_TYPES)
    part = MIMEBase(app_type, app_subtype)
    part.set_payload(encrypted_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=random.choice(FILENAMES))
    msg.attach(part)
    return msg


def append_response(client: Any, response_dict: dict[str, Any]) -> None:
    from ioe_telemetry import Timer

    rid = response_dict.get("id", "?")
    log.debug("append_response: id=%s status=%s", rid, response_dict.get("status", "?"))
    payload = json.dumps(response_dict, ensure_ascii=False)
    encrypted = compress_encrypt(IOE_KEY, payload).encode("ascii")
    msg = make_envelope(encrypted)
    with Timer() as t_append:
        client.append("INBOX", msg.as_bytes())
    log.info("append_response: APPEND OK id=%s (%.0fms, %d bytes)", rid, t_append.elapsed_ms, len(encrypted))


def fetch_text(url: str) -> str:
    validate_url(url)
    resp = requests.get(url, timeout=FETCH_TIMEOUT, headers={"User-Agent": UA})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


import trafilatura
import re as _re

MIN_EXTRACT_LEN = 200


def detect_type(url: str, html: str) -> str:
    if _re.search(r"/article|/post|/blog|/news/\d", url):
        return "article"
    if _re.search(r"/feed|/hub|/flows|/all$|/top$", url):
        return "feed"
    if _re.search(r"/search|[?&]q=", url):
        return "search"
    soup = BeautifulSoup(html, "html.parser")
    articles = soup.find_all("article")
    if len(articles) > 3:
        return "feed"
    if len(articles) == 1:
        return "article"
    return "page"


_page_cache: dict[str, dict[str, Any]] = {}
PAGE_CACHE_MAX = 100


def smart_extract(url: str) -> dict[str, Any]:
    cache_key = url.split("?")[0]
    if cache_key in _page_cache:
        log.info("cache HIT: %s", url)
        return _page_cache[cache_key]
    result = _smart_extract_impl(url)
    if len(_page_cache) >= PAGE_CACHE_MAX:
        oldest = next(iter(_page_cache))
        del _page_cache[oldest]
    _page_cache[cache_key] = result
    return result


def _smart_extract_impl(url: str) -> dict[str, Any]:
    validate_url(url)
    resp = requests.get(url, timeout=FETCH_TIMEOUT, headers={"User-Agent": UA})
    resp.raise_for_status()
    raw_html = resp.text
    parsed_url = urlparse(url)
    domain = parsed_url.hostname or ""
    page_type = detect_type(url, raw_html)

    # Feed pages: skip trafilatura (extracts only 1 article), use soup directly
    if page_type == "feed":
        log.info("feed page detected, using soup directly")
        soup = BeautifulSoup(raw_html, "html.parser")
        title = soup.title.string if soup.title else ""
        for tag in soup(
            [
                "script",
                "style",
                "nav",
                "footer",
                "header",
                "aside",
                "iframe",
                "form",
                "input",
                "select",
                "fieldset",
                "legend",
                "label",
                "button",
            ]
        ):
            tag.decompose()
        for a in soup.find_all("a", href=True):
            if not isinstance(a, Tag):
                continue
            href = str(a["href"])
            if href.startswith("/"):
                a["href"] = f"{parsed_url.scheme}://{parsed_url.netloc}{href}"
        body = soup.find("body") or soup
        html_content = str(body)
        return {
            "format": "html",
            "type": page_type,
            "title": title or "",
            "body": html_content,
            "domain": domain,
            "word_count": len(BeautifulSoup(html_content, "html.parser").get_text().split()),
        }

    # Tier 1: trafilatura markdown
    md = trafilatura.extract(
        raw_html,
        output_format="markdown",
        include_links=True,
        include_images=True,
        include_tables=True,
        url=url,
    )
    if md and len(md) > MIN_EXTRACT_LEN:
        title = ""
        for line in md.split("\n"):
            if line.startswith("# "):
                title = line[2:].strip()
                break
        return {
            "format": "markdown",
            "type": page_type,
            "title": title,
            "body": md,
            "domain": domain,
            "word_count": len(md.split()),
        }

    # Tier 2: trafilatura with favor_recall
    md = trafilatura.extract(
        raw_html,
        output_format="markdown",
        include_links=True,
        include_images=True,
        favor_recall=True,
        url=url,
    )
    if md and len(md) > MIN_EXTRACT_LEN:
        title = md.split("\n")[0].lstrip("# ").strip()[:100]
        return {
            "format": "markdown",
            "type": page_type,
            "title": title,
            "body": md,
            "domain": domain,
            "word_count": len(md.split()),
        }

    log.info("trafilatura insufficient (%d chars), soup fallback", len(md or ""))

    # Tier 3: soup cleanup
    soup = BeautifulSoup(raw_html, "html.parser")
    title = soup.title.string if soup.title else ""
    for tag in soup(
        [
            "script",
            "style",
            "nav",
            "footer",
            "header",
            "aside",
            "iframe",
            "form",
            "input",
            "select",
            "fieldset",
            "legend",
            "label",
            "button",
        ]
    ):
        tag.decompose()
    for a in soup.find_all("a", href=True):
        if not isinstance(a, Tag):
            continue
        href = str(a["href"])
        if href.startswith("/"):
            a["href"] = f"{parsed_url.scheme}://{parsed_url.netloc}{href}"
    body = soup.find("body") or soup
    html_content = str(body)
    return {
        "format": "html",
        "type": page_type,
        "title": title or "",
        "body": html_content,
        "domain": domain,
        "word_count": len(BeautifulSoup(html_content, "html.parser").get_text().split()),
    }


def fetch_readable(url: str) -> tuple[str, str]:
    validate_url(url)
    resp = requests.get(url, timeout=FETCH_TIMEOUT, headers={"User-Agent": UA})
    resp.raise_for_status()
    doc = Document(resp.text)
    title = doc.title()
    content = doc.summary()
    content = inline_images(content, url)
    return title, content


def inline_images(html: str, base_url: str, max_images: int = 10, max_kb: int = 80) -> str:
    soup = BeautifulSoup(html, "html.parser")
    count = 0
    for img in soup.find_all("img", src=True):
        if not isinstance(img, Tag):
            continue
        if count >= max_images:
            img.decompose()
            continue
        try:
            img_url = urljoin(base_url, str(img["src"]))
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
                pil_img = pil_img.resize((800, int(pil_img.height * ratio)))  # type: ignore[assignment]  # PIL typeshed
            buf = io.BytesIO()
            pil_img.convert("RGB").save(buf, "JPEG", quality=60)
            if buf.tell() > max_kb * 1024:
                buf = io.BytesIO()
                pil_img.convert("RGB").save(buf, "JPEG", quality=40)
            b64 = base64.b64encode(buf.getvalue()).decode()
            img["src"] = f"data:image/jpeg;base64,{b64}"
            count += 1
        except Exception as e:
            log.debug("Image inline failed: %s", e)
            img.decompose()
    return str(soup)


def do_search(query: str) -> list[dict[str, str]]:
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS
            results = DDGS().text(query, max_results=10)
            return [
                {
                    "title": r.get("title", ""),
                    "href": r.get("href", ""),
                    "snippet": r.get("body", ""),
                }
                for r in results
            ]
        except Exception as e:
            last_exc = e
            if attempt < 2:
                time.sleep(1.5**attempt)
            log.warning("DDGS attempt %d failed: %s", attempt + 1, e)
    if BROWSER_AVAILABLE:
        try:
            return do_browser_search(query)
        except Exception as e:
            return [{"title": "Search error", "href": "", "snippet": str(e)}]
    return [{"title": "Search error", "href": "", "snippet": str(last_exc)}]


def do_browser_search(query: str) -> list[dict[str, str]]:
    from urllib.parse import quote_plus

    try:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        browser_req: dict[str, Any] = {
            "url": url,
            "actions": [
                {"action": "goto"},
                {"action": "extract", "selector": ".result__a"},
                {"action": "extract", "selector": ".result__snippet"},
            ],
            "timeout": 30000,
        }
        resp = handle_browser_request(browser_req)
        if resp.get("status") != 200:
            return [
                {
                    "title": "Browser search error",
                    "href": "",
                    "snippet": resp.get("error", "unknown"),
                }
            ]
        links = []
        snippets = []
        for r in resp.get("results", []):
            if r.get("action") == "extract":
                sel = r.get("selector", "")
                if sel == ".result__a":
                    links = r.get("elements", [])
                elif sel == ".result__snippet":
                    snippets = r.get("elements", [])
        results = []
        for i, el in enumerate(links[:10]):
            text = el.get("text", "").strip()
            if not text:
                continue
            snip = snippets[i].get("text", "").strip() if i < len(snippets) else ""
            results.append({"title": text, "href": el.get("href", ""), "snippet": snip})
        if results:
            return results
        return [
            {
                "title": "No results",
                "href": "",
                "snippet": f"No results for: {query}",
            }
        ]
    except Exception as e:
        return [{"title": "Browser search error", "href": "", "snippet": str(e)}]


def extract_attachment(raw: bytes) -> bytes | None:
    parsed = email_mod.message_from_bytes(raw)
    for part in parsed.walk():
        if part.get_content_disposition() == "attachment":
            payload = part.get_payload(decode=True)
            return payload if isinstance(payload, bytes) else None
    return None


def _cleanup_sessions() -> None:
    now = time.time()
    expired = [k for k, v in _sessions.items() if now - v["created"] > SESSION_TTL]
    for k in expired:
        _sessions[k]["session"].close()
        del _sessions[k]


def handle_http_proxy(request: dict[str, Any]) -> dict[str, Any]:
    method = request.get("method", "GET").upper()
    url = request.get("url", "")
    headers = request.get("headers", {})
    cookies = request.get("cookies")
    body = request.get("body")
    content_type = request.get("content_type", "json")
    session_id = request.get("session_id")

    try:
        validate_url(url)
        check_rate_limit(request.get("user_id", "default"))
    except ValueError as e:
        return {"type": "http_response", "status_code": 403, "error": str(e)}

    try:
        _cleanup_sessions()

        req_headers = {**{"User-Agent": UA}, **headers}
        kwargs = {
            "headers": req_headers,
            "cookies": cookies,
            "timeout": FETCH_TIMEOUT,
            "allow_redirects": False,
        }

        if body and method in ("POST", "PUT", "PATCH"):
            if content_type == "form":
                kwargs["data"] = body
            else:
                kwargs["json"] = body

        if session_id and session_id in _sessions:
            requester = _sessions[session_id]["session"]
        else:
            requester = requests

        resp = requester.request(method, url, **kwargs)

        redirect_count = 0
        while resp.status_code in (301, 302, 303, 307, 308) and redirect_count < 5:
            location = resp.headers.get("Location", "")
            if not location:
                break
            from urllib.parse import urljoin

            location = urljoin(str(resp.url), location)
            validate_url(location)
            resp = requester.request(
                "GET",
                location,
                headers=req_headers,
                cookies=cookies,
                timeout=FETCH_TIMEOUT,
                allow_redirects=False,
            )
            redirect_count += 1

        result = {
            "type": "http_response",
            "status_code": resp.status_code,
            "headers": dict(resp.headers),
            "body": resp.text[:MAX_BODY],
            "url": str(resp.url),
        }

        ct = resp.headers.get("Content-Type", "")
        if "text/html" in ct and request.get("extract", True):
            try:
                extracted = smart_extract(url)
                result["extracted"] = extracted
                result["page_type"] = extracted.get("type", "page")
            except Exception as e:
                log.debug("smart_extract failed for %s: %s", url, e)

        return result
    except Exception as e:
        return {"type": "http_response", "status_code": 502, "error": str(e)}


CLAUDE_PROXY_TIMEOUT = 300
CLAUDE_DEFAULT_HOST = "api.anthropic.com"
CLAUDE_ALLOWED_HOSTS = {"api.anthropic.com"}

_claude_session: requests.Session | None = None


def _get_claude_session() -> requests.Session:
    global _claude_session
    if _claude_session is None:
        _claude_session = requests.Session()
    return _claude_session


def handle_claude_proxy(request: dict[str, Any]) -> dict[str, Any]:
    http_req = request.get("http_request", {})
    method = http_req.get("method", "GET").upper()
    path = http_req.get("path", "/")
    headers = http_req.get("headers", {})
    body = http_req.get("body")

    host = headers.get("host", CLAUDE_DEFAULT_HOST)
    if host in ("localhost", "127.0.0.1") or host.startswith("localhost:"):
        host = CLAUDE_DEFAULT_HOST
    if host not in CLAUDE_ALLOWED_HOSTS:
        return {
            "type": "claude_proxy_response",
            "http_response": {"status_code": 403, "headers": {}, "body": "forbidden host"},
        }
    url = f"https://{host}{path}"

    req_headers = {k: v for k, v in headers.items() if k.lower() != "host"}

    try:
        kwargs = {
            "headers": req_headers,
            "timeout": CLAUDE_PROXY_TIMEOUT,
            "allow_redirects": True,
        }
        if body and method in ("POST", "PUT", "PATCH"):
            kwargs["data"] = body.encode("utf-8") if isinstance(body, str) else body
        resp = _get_claude_session().request(method, url, **kwargs)
        return {
            "type": "claude_proxy_response",
            "http_response": {
                "status_code": resp.status_code,
                "headers": dict(resp.headers),
                "body": resp.text,
            },
        }
    except (requests.Timeout, TimeoutError):
        return {
            "type": "claude_proxy_response",
            "http_response": {
                "status_code": 504,
                "headers": {},
                "body": "upstream timeout",
            },
        }
    except Exception as e:
        return {
            "type": "claude_proxy_response",
            "http_response": {"status_code": 502, "headers": {}, "body": str(e)},
        }


def handle_claude_chat(request: dict[str, Any]) -> dict[str, Any]:
    if _claude_chat is None:
        return {"status": 503, "error": "claude CLI not available"}
    action = request.get("action", "")
    user_id = request.get("user_id", "default")
    if action == "send":
        result: dict[str, Any] = _claude_chat.send_message(user_id, request.get("text", ""), request.get("model"))
        return result
    elif action == "check_auth":
        result = _claude_chat.check_auth()
        return result
    elif action == "new_conversation":
        result = _claude_chat.new_conversation(user_id)
        return result
    return {"status": 400, "error": f"unknown action: {action}"}


def dispatch_request(request: dict[str, Any]) -> dict[str, Any] | None:
    req_type = request.get("type")
    if req_type is None:
        return None
    user_id = request.get("user_id", "default")
    if req_type == "claude_proxy":
        result = handle_claude_proxy(request)
        result["user_id"] = user_id
        return result
    if req_type == "http":
        result = handle_http_proxy(request)
        result["user_id"] = user_id
        return result
    if req_type == "command":
        service = request.get("service", "")
        if service == "telegram":
            adapter = _get_telegram_adapter()
            if adapter is None:
                return {
                    "status": 503,
                    "error": "telegram not available (telethon not installed)",
                    "user_id": user_id,
                }
            action = request.get("action", "")
            adapter_result: dict[str, Any] = adapter.handle(action, request)
            adapter_result["user_id"] = user_id
            result = adapter_result
            if action == "auth_code" and result.get("auth_status") == "authorized":
                _start_telegram_listener(adapter, user_id)
            return result
        return {
            "status": 400,
            "error": f"unknown service: {service}",
            "user_id": user_id,
        }
    if req_type == "claude_chat":
        result = handle_claude_chat(request)
        result["user_id"] = user_id
        return result
    if req_type == "session_start":
        sid = uuid.uuid4().hex
        _sessions[sid] = {"session": requests.Session(), "created": time.time()}
        return {"status": 200, "session_id": sid, "user_id": user_id}
    if req_type == "session_end":
        sid = request.get("session_id", "")
        if sid in _sessions:
            _sessions[sid]["session"].close()
            del _sessions[sid]
            return {"status": 200, "session_id": sid, "user_id": user_id}
        return {"status": 404, "error": f"session {sid} not found", "user_id": user_id}
    if req_type == "browser_search":
        query = request.get("query", "")
        results = do_browser_search(query)
        return {"status": 200, "results": results, "user_id": user_id}
    if req_type == "browser":
        browser_result: dict[str, Any] = handle_browser_request(request)
        return browser_result
    return {"status": 400, "error": f"unknown type: {req_type}", "user_id": user_id}


def process_message(client: Any, uid: int, raw: bytes) -> bool:
    log.debug("process_message: enter uid=%s", uid)
    if uid in _processed_uids:
        log.info("uid=%s already processed, skipping", uid)
        return True

    payload = extract_attachment(raw)
    if payload is None:
        log.warning("uid=%s: no attachment, skipping", uid)
        return False

    try:
        blob = payload.decode("ascii").strip()
        try:
            decrypted = decrypt_decompress(IOE_KEY, blob)
        except Exception as e:
            log.debug("Primary decrypt failed, trying fallback: %s", e)
            decrypted = decrypt(IOE_KEY, blob)
        request = json.loads(decrypted)
    except Exception:
        log.warning("uid=%s: decrypt failed, skipping", uid)
        return False

    user_id = request.get("user_id", "default")
    req_type = request.get("type")
    dispatch_result = dispatch_request(request)
    if dispatch_result is not None:
        req_id = request.get("id", "")
        response_dict = {"id": req_id, **dispatch_result}
        if req_type == "claude_proxy":
            resp_json = json.dumps(response_dict, ensure_ascii=False)
            encrypted = compress_encrypt(IOE_KEY, resp_json).encode("ascii")
            msg = make_envelope(encrypted)
            client.append("INBOX", msg.as_bytes())
        else:
            append_response(client, response_dict)
        log.info("Done uid=%s (type=%s)", uid, request.get("type"))
        _processed_uids.add(uid)
        _processed_uids_deque.append(uid)
        if len(_processed_uids) > _MAX_PROCESSED:
            while len(_processed_uids) > _MAX_PROCESSED and _processed_uids_deque:
                old = _processed_uids_deque.popleft()
                _processed_uids.discard(old)
        return True

    cmd = request.get("cmd", "GET").upper()
    req_id = request.get("id", "")
    log.info("Processing uid=%s", uid)

    try:
        check_rate_limit(request.get("user_id", "default"))
        if cmd == "SEARCH":
            query = request.get("query", "")
            results = do_search(query)
            append_response(
                client,
                {"id": req_id, "status": 200, "results": results, "user_id": user_id},
            )
        elif cmd == "TEXT":
            url = request.get("url", "")
            text = fetch_text(url)
            if len(text) > MAX_BODY:
                text = text[:MAX_BODY] + "\n\n[truncated]"
            append_response(client, {"id": req_id, "status": 200, "body": text, "user_id": user_id})
        elif cmd == "UPDATE":
            files = {}
            base_dir = os.path.dirname(os.path.abspath(__file__))
            for fname in ["client.py", "crypto.py", "ioe_web.py"]:
                fpath = os.path.join(base_dir, fname)
                if os.path.exists(fpath):
                    with open(fpath) as f:
                        files[fname] = f.read()
            append_response(
                client,
                {
                    "id": req_id,
                    "status": 200,
                    "cmd": "UPDATE",
                    "files": files,
                    "user_id": user_id,
                },
            )
        else:
            url = request.get("url", "")
            result = smart_extract(url)
            body = result["body"]
            if len(body) > MAX_BODY:
                body = body[:MAX_BODY]
            append_response(
                client,
                {
                    "id": req_id,
                    "status": 200,
                    "title": result["title"],
                    "body": body,
                    "format": result["format"],
                    "type": result["type"],
                    "domain": result["domain"],
                    "word_count": result["word_count"],
                    "user_id": user_id,
                },
            )
        log.info("Done uid=%s", uid)
    except Exception as e:
        append_response(
            client,
            {
                "id": req_id,
                "status": 500,
                "error": "internal_error",
                "user_id": user_id,
            },
        )
        log.error("Failed uid=%s: %s: %s", uid, type(e).__name__, e)

    _processed_uids.add(uid)
    _processed_uids_deque.append(uid)
    if len(_processed_uids) > _MAX_PROCESSED:
        while len(_processed_uids) > _MAX_PROCESSED and _processed_uids_deque:
            old = _processed_uids_deque.popleft()
            _processed_uids.discard(old)
    return True


LOCK_FILE = "/tmp/ioe-server.lock"


def _acquire_lock() -> Any:
    fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.error("Another instance is running (lock: %s). Exiting.", LOCK_FILE)
        sys.exit(1)
    fd.write(str(os.getpid()))
    fd.flush()
    return fd


RECONNECT_INTERVAL = 300


def main() -> None:
    _lock_fd = _acquire_lock()  # noqa: F841 — prevent GC releasing the lock
    log.info("IoE server v2 starting")
    while True:
        try:
            with IMAPClient(IMAP_HOST, ssl=True) as client:
                client.login(EMAIL, PASSWORD)
                client.select_folder(QUEUE_FOLDER)
                log.info("Connected, monitoring folder '%s'", QUEUE_FOLDER)
                connected_at = time.time()
                iteration = 0
                while True:
                    iteration += 1
                    age = time.time() - connected_at
                    if age > RECONNECT_INTERVAL:
                        log.info(
                            "Reconnecting (stale prevention, %ds, iter=%d)",
                            RECONNECT_INTERVAL,
                            iteration,
                        )
                        break
                    idle_timeout = max(1, min(600, RECONNECT_INTERVAL - int(age)))
                    client.idle()
                    try:
                        responses = client.idle_check(timeout=idle_timeout)
                    except Exception as e:
                        log.debug("IDLE interrupted: %s", e)
                        try:
                            client.idle_done()
                        except Exception:
                            pass
                        break
                    client.idle_done()

                    messages = client.search(["ALL"])
                    if messages:
                        log.info(
                            "mainloop: search found %d uids: %s (iter=%d)",
                            len(messages),
                            messages[:10],
                            iteration,
                        )
                        all_data = client.fetch(messages, ["RFC822"])
                        processed_uids = []
                        for uid in messages:
                            raw = all_data.get(uid, {}).get(b"RFC822")
                            if raw is None:
                                continue
                            if process_message(client, uid, raw):
                                processed_uids.append(uid)
                        if processed_uids:
                            client.delete_messages(processed_uids)
                            client.expunge()
                            log.info("Deleted %d uids from queue: %s", len(processed_uids), processed_uids)
        except Exception as e:
            log.error("Connection error: %s, reconnecting in 5s", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
