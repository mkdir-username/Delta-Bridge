"""IoE HTTP request handler."""

from __future__ import annotations
import hashlib
import hmac
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import json
import re as _re
import uuid
import time
import threading
import logging
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Any

import auth
from transport import imap_conn, send_request, poll_response

log = logging.getLogger("ioe-web")

_ERROR_MAP = [
    (
        _re.compile(r"UNAVAILABLE", _re.I),
        "transport",
        "Сервер почты недоступен, попробуйте позже",
    ),
    (_re.compile(r"timeout", _re.I), "transport", None),
    (
        _re.compile(r"Connection refused|Network is unreachable|ConnectionReset", _re.I),
        "transport",
        "Нет соединения с сервером",
    ),
    (
        _re.compile(r"session expired|not registered|auth.*required", _re.I),
        "auth",
        "Сессия истекла, войдите заново",
    ),
    (
        _re.compile(r"all available options.*already used", _re.I),
        "rate_limit",
        "Слишком много попыток. Подождите 10 минут",
    ),
    (_re.compile(r"wait of (\d+) seconds", _re.I), "rate_limit", None),
    (_re.compile(r"phone number is invalid", _re.I), "vps", "Неверный номер телефона"),
]


def _classify_error(raw: object) -> tuple[str, str]:
    s = str(raw)
    for pattern, err_type, msg in _ERROR_MAP:
        m = pattern.search(s)
        if m:
            if msg is None:
                if err_type == "rate_limit":
                    try:
                        secs = int(m.group(1))
                        mins = max(1, secs // 60)
                        return err_type, f"Подождите {mins} мин"
                    except (IndexError, ValueError):
                        pass
                return err_type, s
            return err_type, msg
    return "vps", f"Ошибка сервера: {s}"


def _humanize_error(raw: object) -> str:
    _, msg = _classify_error(raw)
    return msg


_TG_ALLOWED_KEYS: set[str] = {
    "phone",
    "code",
    "password",
    "chat_id",
    "text",
    "limit",
    "offset_id",
    "reply_to_id",
    "message_id",
    "folder",
    "query",
}

MAX_BODY_SIZE = 256 * 1024

_SECRET_QS_RE = _re.compile(
    r"([?&](?:token|password|code|key|sid|auth|api[_-]?key)=)[^&#]*",
    _re.IGNORECASE,
)


def _mask_url(url: str) -> str:
    return _SECRET_QS_RE.sub(lambda m: m.group(1) + "***", url)


_auth_attempts: dict[str, list[float]] = {}
_login_request_owners: dict[str, tuple[str, float]] = {}
_LOGIN_OWNER_TTL: int = 600


def _cleanup_login_owners() -> None:
    cutoff = time.time() - _LOGIN_OWNER_TTL
    stale = [k for k, (_, ts) in _login_request_owners.items() if ts < cutoff]
    for k in stale:
        del _login_request_owners[k]


_code_attempts: dict[str, list[float]] = {}
_CODE_LIMIT: int = 5
_CODE_WINDOW: int = 300
_AUTH_LIMIT: int = 3
_AUTH_WINDOW: int = 300


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def _read_body(self) -> bytes | None:
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400, "Bad Content-Length")
            return None
        if n > MAX_BODY_SIZE:
            self.send_error(413, "Payload too large")
            return None
        return self.rfile.read(n) if n > 0 else b""

    def _add_security_headers(self) -> None:
        import ioe_web

        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        script_src = " ".join(["'self'"] + ioe_web.SCRIPT_HASHES)
        style_src = " ".join(["'self'"] + ioe_web.STYLE_HASHES)
        self.send_header(
            "Content-Security-Policy",
            f"default-src 'self'; script-src {script_src}; style-src {style_src}; img-src 'self' data: https:",
        )

    def respond_json(self, data: Any, code: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._add_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _handle_demo(self, cmd: str, qs: dict[str, list[str]], req_id: str) -> None:
        if cmd == "SEARCH":
            q = qs.get("q", [""])[0]
            results = [
                {
                    "title": "\u041f\u043e\u0433\u043e\u0434\u0430 \u0432 \u0421\u0430\u043d\u043a\u0442-\u041f\u0435\u0442\u0435\u0440\u0431\u0443\u0440\u0433\u0435 \u2014 \u042f\u043d\u0434\u0435\u043a\u0441",
                    "href": "https://yandex.ru/pogoda/saint-petersburg",
                    "snippet": "\u0421\u0435\u0433\u043e\u0434\u043d\u044f +4\u00b0, \u043e\u0431\u043b\u0430\u0447\u043d\u043e. \u0417\u0430\u0432\u0442\u0440\u0430 +6\u00b0, \u0432\u043e\u0437\u043c\u043e\u0436\u0435\u043d \u0434\u043e\u0436\u0434\u044c.",
                },
                {
                    "title": "\u041f\u043e\u0433\u043e\u0434\u0430 \u0421\u041f\u0431 \u2014 Gismeteo",
                    "href": "https://www.gismeteo.ru/weather-saint-petersburg/",
                    "snippet": "\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u044b\u0439 \u043f\u0440\u043e\u0433\u043d\u043e\u0437 \u043f\u043e\u0433\u043e\u0434\u044b \u043d\u0430 \u0441\u0435\u0433\u043e\u0434\u043d\u044f, \u0437\u0430\u0432\u0442\u0440\u0430, \u043d\u0435\u0434\u0435\u043b\u044e.",
                },
                {
                    "title": "\u041f\u043e\u0433\u043e\u0434\u0430 \u0432 \u041f\u0438\u0442\u0435\u0440\u0435 \u0441\u0435\u0439\u0447\u0430\u0441 \u2014 rp5.ru",
                    "href": "https://rp5.ru/spb",
                    "snippet": "\u0422\u0435\u043a\u0443\u0449\u0430\u044f \u0442\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 +3\u00b0C, \u0432\u0435\u0442\u0435\u0440 5 \u043c/\u0441, \u0432\u043b\u0430\u0436\u043d\u043e\u0441\u0442\u044c 78%.",
                },
                {
                    "title": "\u041a\u043b\u0438\u043c\u0430\u0442 \u0421\u0430\u043d\u043a\u0442-\u041f\u0435\u0442\u0435\u0440\u0431\u0443\u0440\u0433\u0430 \u2014 \u0412\u0438\u043a\u0438\u043f\u0435\u0434\u0438\u044f",
                    "href": "https://ru.wikipedia.org/wiki/\u041a\u043b\u0438\u043c\u0430\u0442_\u0421\u0430\u043d\u043a\u0442-\u041f\u0435\u0442\u0435\u0440\u0431\u0443\u0440\u0433\u0430",
                    "snippet": "\u041a\u043b\u0438\u043c\u0430\u0442 \u0443\u043c\u0435\u0440\u0435\u043d\u043d\u044b\u0439. \u0421\u0440\u0435\u0434\u043d\u044f\u044f \u0442\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 \u043c\u0430\u0440\u0442\u0430 \u2212\u2060\u0031\u2026+4\u00b0C.",
                },
            ]
            self.respond_json({"status": "ready", "results": results})
        elif cmd in ("GET", "TEXT"):
            url = qs.get("url", [""])[0]
            self.respond_json(
                {
                    "status": "ready",
                    "title": "\u041f\u043e\u0433\u043e\u0434\u0430 \u0432 \u0421\u0430\u043d\u043a\u0442-\u041f\u0435\u0442\u0435\u0440\u0431\u0443\u0440\u0433\u0435 \u043d\u0430 \u0441\u0435\u0433\u043e\u0434\u043d\u044f",
                    "body": "# \u041f\u043e\u0433\u043e\u0434\u0430\n\n\u0421\u0435\u0433\u043e\u0434\u043d\u044f +5\u00b0C, \u043e\u0431\u043b\u0430\u0447\u043d\u043e.\n\n## \u041f\u0440\u043e\u0433\u043d\u043e\u0437\n\n- \u041f\u043d +4\u00b0 \u0434\u043e\u0436\u0434\u044c\n- \u0412\u0442 +6\u00b0 \u043e\u0431\u043b\u0430\u0447\u043d\u043e\n- \u0421\u0440 +7\u00b0 \u0441\u043e\u043b\u043d\u0435\u0447\u043d\u043e",
                    "format": "markdown",
                }
            )
        else:
            self.respond_json({"status": "error", "error": "unknown cmd"})

    def do_GET(self) -> None:
        import ioe_web

        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path == "/login":
            self._serve_login()
            return
        if parsed.path.startswith("/login/tg"):
            self.respond_json({"status": "error", "error": "use POST"}, 405)
            return
        if parsed.path == "/login/status":
            ip = self.client_address[0]
            if not auth.check_rate_limit(ip):
                self.respond_json({"status": "error", "error": "rate limited"}, 429)
                return
            ioe_web._cleanup_pending()
            req_id = qs.get("id", [""])[0]
            _owner_entry = _login_request_owners.get(req_id)
            login_user_id = _owner_entry[0] if _owner_entry else "login"
            with ioe_web.lock:
                if (login_user_id, req_id) in ioe_web.pending:
                    resp = ioe_web.pending.pop((login_user_id, req_id))
                    result: dict[str, Any] = {"status": "ready"}
                    for key in resp:
                        if key in ("id", "status"):
                            continue
                        result[key] = resp[key]
                    if result.get("auth_status") == "authorized":
                        sid = auth.create_session(login_user_id)
                        result["set_session"] = True
                        body = json.dumps(result, ensure_ascii=False).encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.send_header(
                            "Set-Cookie",
                            f"sid={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age={auth.SESSION_TTL}",
                        )
                        self._add_security_headers()
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    self.respond_json(result)
                    return
            self.respond_json({"status": "pending"})
            return
        if parsed.path == "/logout":
            auth.delete_session(self.headers.get("Cookie", ""))
            self.send_response(302)
            self.send_header("Location", "/login")
            self.send_header("Set-Cookie", "sid=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
            self._add_security_headers()
            self.end_headers()
            return

        user_id = auth.get_authenticated_user(self.headers.get("Cookie", ""))
        if not user_id:
            self.send_response(302)
            self.send_header("Location", "/login")
            self._add_security_headers()
            self.end_headers()
            return

        if parsed.path == "/":
            ioe_web.rebuild_html()
            body = ioe_web.HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self._add_security_headers()
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/status":
            req_id = qs.get("id", [""])[0]
            with ioe_web.lock:
                if (user_id, req_id) in ioe_web.pending:
                    resp = ioe_web.pending.pop((user_id, req_id))
                    if resp.get("status") == 200:
                        result = {"status": "ready"}
                        if "results" in resp:
                            result["results"] = resp["results"]
                        elif (
                            resp.get("type") == "command"
                            or "dialogs" in resp
                            or "messages" in resp
                            or "unread_chats" in resp
                            or "message_id" in resp
                            or "auth_status" in resp
                            or "results" not in resp
                            and "body" not in resp
                        ):
                            for key in resp:
                                if key not in ("id", "status"):
                                    result[key] = resp[key]
                        else:
                            result["title"] = resp.get("title", "")
                            result["body"] = resp.get("body", "")
                            result["format"] = resp.get("format", "html")
                        self.respond_json(result)
                    else:
                        result = {"status": "error"}
                        for key in resp:
                            if key not in ("id", "status"):
                                result[key] = resp[key]
                        if "error" not in result:
                            result["error"] = "unknown"
                        self.respond_json(result)
                    return
            self.respond_json({"status": "pending"})
            return

        if parsed.path in ("/get", "/text", "/search"):
            req_id = f"{ioe_web.DEVICE_ID}-{uuid.uuid4().hex[:6]}"
            cmd = parsed.path.lstrip("/").upper()

            if ioe_web.DEMO_MODE:
                self._handle_demo(cmd, qs, req_id)
                return

            if cmd == "SEARCH":
                q = qs.get("q", [""])[0]
                req = {"id": req_id, "cmd": "SEARCH", "query": q, "user_id": user_id}
            else:
                url = qs.get("url", [""])[0]
                req = {"id": req_id, "cmd": cmd, "url": url, "user_id": user_id}
            try:
                t0 = time.time()
                log.info(
                    "[%s] send: %s %s",
                    req_id,
                    cmd,
                    _mask_url(req.get("query", req.get("url", ""))),
                )
                m = imap_conn()
                send_request(m, req)
                log.info("[%s] send: done (%.1fs)", req_id, time.time() - t0)
            except Exception as e:
                log.error("[%s] send: FAILED: %s", req_id, e)
                err_type, err_msg = _classify_error(str(e))
                self.respond_json({"status": "error", "error": err_msg, "error_type": err_type})
                return
            t = threading.Thread(target=poll_response, args=(user_id, req_id), daemon=True)
            t.start()
            self.respond_json({"id": req_id, "status": "pending"})
            return

        if parsed.path == "/proxy":
            req_id = f"{ioe_web.DEVICE_ID}-{uuid.uuid4().hex[:6]}"

            if ioe_web.DEMO_MODE:
                self.respond_json({"status": "error", "error": "proxy not available in demo"})
                return

            method = qs.get("method", ["GET"])[0].upper()
            url = qs.get("url", [""])[0]
            body_str = qs.get("body", [""])[0]
            session_id = qs.get("session_id", [""])[0]
            extract = qs.get("extract", ["true"])[0] != "false"

            req = {
                "id": req_id,
                "type": "http",
                "method": method,
                "url": url,
                "extract": extract,
                "user_id": user_id,
            }
            if body_str:
                try:
                    req["body"] = json.loads(body_str)
                except (json.JSONDecodeError, ValueError):
                    req["body"] = body_str
            if session_id:
                req["session_id"] = session_id

            try:
                log.info("[%s] proxy: %s %s", req_id, method, _mask_url(url))
                m = imap_conn()
                send_request(m, req)
            except Exception as e:
                log.error("[%s] proxy send FAILED: %s", req_id, e)
                err_type, err_msg = _classify_error(str(e))
                self.respond_json({"status": "error", "error": err_msg, "error_type": err_type})
                return

            t = threading.Thread(target=poll_response, args=(user_id, req_id), daemon=True)
            t.start()
            self.respond_json({"id": req_id, "status": "pending"})
            return

        if parsed.path == "/tg":
            req_id = f"{ioe_web.DEVICE_ID}-{uuid.uuid4().hex[:6]}"
            action = qs.get("action", [""])[0]

            if ioe_web.DEMO_MODE:
                self.respond_json({"status": "error", "error": "telegram not available in demo"})
                return

            req = {
                "id": req_id,
                "type": "command",
                "service": "telegram",
                "action": action,
                "user_id": user_id,
            }
            for key in qs:
                if key in _TG_ALLOWED_KEYS:
                    req[key] = qs[key][0]
            if "chat_id" in req:
                try:
                    req["chat_id"] = int(req["chat_id"])
                except ValueError:
                    pass
            for int_key in ("limit", "reply_to_id", "message_id"):
                if int_key in req:
                    try:
                        req[int_key] = int(req[int_key])
                    except ValueError:
                        pass

            try:
                log.info("[%s] tg: %s", req_id, action)
                m = imap_conn()
                send_request(m, req)
            except Exception as e:
                log.error("[%s] tg send FAILED: %s", req_id, e)
                err_type, err_msg = _classify_error(str(e))
                self.respond_json({"status": "error", "error": err_msg, "error_type": err_type})
                return

            t = threading.Thread(target=poll_response, args=(user_id, req_id), daemon=True)
            t.start()
            self.respond_json({"id": req_id, "status": "pending"})
            return

        if parsed.path == "/claude":
            req_id = f"{ioe_web.DEVICE_ID}-{uuid.uuid4().hex[:6]}"
            action = qs.get("action", [""])[0]
            text = qs.get("text", [""])[0]
            model = qs.get("model", [""])[0]

            req = {
                "id": req_id,
                "type": "claude_chat",
                "action": action,
                "user_id": user_id,
            }
            if text:
                req["text"] = text
            if model:
                req["model"] = model

            try:
                log.info("[%s] claude: %s", req_id, action)
                m = imap_conn()
                send_request(m, req)
            except Exception as e:
                log.error("[%s] claude send FAILED: %s", req_id, e)
                err_type, err_msg = _classify_error(str(e))
                self.respond_json({"status": "error", "error": err_msg, "error_type": err_type})
                return

            t = threading.Thread(target=poll_response, args=(user_id, req_id), daemon=True)
            t.start()
            self.respond_json({"id": req_id, "status": "pending"})
            return

        if parsed.path == "/notifications":
            with ioe_web.lock:
                notifs = list(ioe_web.notification_queues.get(user_id, []))
                if user_id in ioe_web.notification_queues:
                    ioe_web.notification_queues[user_id] = []
            self.respond_json({"notifications": notifs})
            return

        if parsed.path == "/kit":
            import glob as _glob

            kit_name = qs.get("kit", [""])[0]
            kits_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kits")
            if not kit_name:
                kits = []
                for f in sorted(_glob.glob(os.path.join(kits_dir, "*.json"))):
                    if os.path.basename(f).startswith("_"):
                        continue
                    try:
                        with open(f) as fh:
                            k = json.load(fh)
                            kits.append(
                                {
                                    "file": os.path.basename(f),
                                    "service": k.get("service", ""),
                                    "description": k.get("description", ""),
                                    "actions": list(k.get("actions", {}).keys()),
                                }
                            )
                    except Exception as e:
                        log.warning("Kit load failed %s: %s", f, e)
                        continue
                self.respond_json({"kits": kits})
                return
            self.respond_json(
                {
                    "status": "error",
                    "error": "kit execution via WebUI not yet supported",
                }
            )
            return

        if parsed.path == "/browser-search":
            req_id = f"{ioe_web.DEVICE_ID}-{uuid.uuid4().hex[:6]}"
            q = qs.get("q", [""])[0]

            if ioe_web.DEMO_MODE:
                self.respond_json({"status": "error", "error": "browser search not available in demo"})
                return

            req = {
                "id": req_id,
                "type": "browser_search",
                "query": q,
                "user_id": user_id,
            }
            try:
                log.info("[%s] browser-search: %s", req_id, q)
                m = imap_conn()
                send_request(m, req)
            except Exception as e:
                log.error("[%s] browser-search send FAILED: %s", req_id, e)
                err_type, err_msg = _classify_error(str(e))
                self.respond_json({"status": "error", "error": err_msg, "error_type": err_type})
                return

            t = threading.Thread(target=poll_response, args=(user_id, req_id), daemon=True)
            t.start()
            self.respond_json({"id": req_id, "status": "pending"})
            return

        if parsed.path == "/browser":
            req_id = f"{ioe_web.DEVICE_ID}-{uuid.uuid4().hex[:6]}"
            url = qs.get("url", [""])[0]

            if ioe_web.DEMO_MODE:
                self.respond_json({"status": "error", "error": "browser not available in demo"})
                return

            req = {
                "id": req_id,
                "type": "browser",
                "url": url,
                "actions": ["goto"],
                "user_id": user_id,
            }
            try:
                log.info("[%s] browser: %s", req_id, _mask_url(url))
                m = imap_conn()
                send_request(m, req)
            except Exception as e:
                log.error("[%s] browser send FAILED: %s", req_id, e)
                err_type, err_msg = _classify_error(str(e))
                self.respond_json({"status": "error", "error": err_msg, "error_type": err_type})
                return

            t = threading.Thread(target=poll_response, args=(user_id, req_id), daemon=True)
            t.start()
            self.respond_json({"id": req_id, "status": "pending"})
            return

        self.send_error(404)

    def _serve_login(self, error: str = "", status: int = 200) -> None:
        from html_templates import login_page

        body = login_page(error).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._add_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _handle_login_tg_post(self) -> None:
        import ioe_web

        _cleanup_login_owners()
        body_bytes = self._read_body()
        if body_bytes is None:
            return
        raw = body_bytes if body_bytes else b"{}"
        try:
            body = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            self.respond_json({"status": "error", "error": "invalid JSON"}, 400)
            return

        ip = self.client_address[0]
        if not auth.check_rate_limit(ip):
            self.respond_json({"status": "error", "error": "Подождите минуту"})
            return

        action = body.get("action", "")
        if action not in ("auth_start", "auth_code", "check_auth", "auth_logout"):
            self.respond_json({"status": "error", "error": "forbidden action"})
            return

        phone = body.get("phone", "")

        if action == "auth_start" and not auth.is_whitelisted(phone):
            _ = hmac.new(b"honeypot-pad", phone.encode(), hashlib.sha256).digest()
            req_id = f"{ioe_web.DEVICE_ID}-{uuid.uuid4().hex[:6]}"
            login_user_id = phone or "login"
            with ioe_web.lock:
                ioe_web.pending[(login_user_id, req_id)] = {
                    "id": req_id,
                    "status": 200,
                    "auth_status": "error",
                    "error": "authentication failed",
                    "_created": time.time(),
                }
            _login_request_owners[req_id] = (login_user_id, time.time())
            self.respond_json({"id": req_id, "status": "pending"})
            return

        if action == "auth_start":
            now = time.time()
            attempts = _auth_attempts.get(phone, [])
            attempts = [t for t in attempts if now - t < _AUTH_WINDOW]
            if len(attempts) >= _AUTH_LIMIT:
                self.respond_json({"status": "error", "error": "too many attempts, wait 5 min"})
                return
            attempts.append(now)
            _auth_attempts[phone] = attempts

        if action == "auth_code":
            now = time.time()
            attempts = _code_attempts.get(phone, [])
            attempts = [t for t in attempts if now - t < _CODE_WINDOW]
            if len(attempts) >= _CODE_LIMIT:
                self.respond_json({"status": "error", "error": "too many attempts, wait 5 min"})
                return
            attempts.append(now)
            _code_attempts[phone] = attempts

        req_id = f"{ioe_web.DEVICE_ID}-{uuid.uuid4().hex[:6]}"
        login_user_id = phone or "login"
        req = {
            "id": req_id,
            "type": "command",
            "service": "telegram",
            "action": action,
            "user_id": login_user_id,
        }
        for key in ("phone", "code", "password"):
            if key in body:
                req[key] = body[key]

        try:
            m = imap_conn()
            send_request(m, req)
        except Exception as e:
            log.error("[%s] login/tg send FAILED: %s", req_id, e)
            err_type, err_msg = _classify_error(str(e))
            self.respond_json({"status": "error", "error": err_msg, "error_type": err_type})
            return

        _login_request_owners[req_id] = (login_user_id, time.time())
        t = threading.Thread(target=poll_response, args=(login_user_id, req_id), daemon=True)
        t.start()
        self.respond_json({"id": req_id, "status": "pending"})

    def _handle_login_email_post(self) -> None:
        body_bytes = self._read_body()
        if body_bytes is None:
            return
        raw = body_bytes if body_bytes else b"{}"
        try:
            body = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            self.respond_json({"status": "error", "error": "invalid JSON"}, 400)
            return

        action = body.get("action", "")
        phone = body.get("phone", "")

        if action == "send_code":
            if not auth.is_whitelisted(phone):
                _ = hmac.new(b"honeypot-pad", phone.encode(), hashlib.sha256).digest()
                self.respond_json({"status": "code_sent"})
                return
            ip = self.client_address[0]
            if not auth.check_rate_limit(ip):
                self.respond_json({"status": "error", "error": "Подождите минуту"})
                return
            secret = auth.get_user_totp_secret(phone)
            if not secret:
                self.respond_json({"status": "error", "error": "TOTP не настроен. Обратитесь к администратору"})
                return
            self.respond_json({"status": "code_sent"})
            return

        if action == "verify_code":
            code = body.get("code", "")
            if not code or not phone:
                self.respond_json({"status": "error", "error": "Введите код"})
                return
            ip = self.client_address[0]
            if not auth.check_rate_limit(ip):
                self.respond_json({"status": "error", "error": "Подождите минуту"})
                return

            if auth.verify_totp(phone, code):
                sid = auth.create_session(phone)
                result = {"status": "authorized"}
                body_bytes = json.dumps(result, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header(
                    "Set-Cookie",
                    f"sid={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age={auth.SESSION_TTL}",
                )
                self._add_security_headers()
                self.end_headers()
                self.wfile.write(body_bytes)
                return

            self.respond_json({"status": "error", "error": "Неверный код"})
            return

        if action in ("setup_totp", "confirm_totp"):
            self.respond_json({"status": "error", "error": "TOTP setup только через CLI"})
            return

        self.respond_json({"status": "error", "error": "unknown action"})

    def do_POST(self) -> None:
        import ioe_web

        parsed = urlparse(self.path)

        if parsed.path == "/login":
            body_bytes = self._read_body()
            if body_bytes is None:
                return
            body_raw = body_bytes.decode()
            params = parse_qs(body_raw)
            username = params.get("username", [""])[0]
            password_val = params.get("password", [""])[0]
            ip = self.client_address[0]
            if not auth.check_rate_limit(ip):
                self._serve_login("Слишком много попыток. Подожди минуту.", 429)
                return
            if username and password_val and auth.verify_password(username, password_val):
                sid = auth.create_session(username)
                self.send_response(302)
                self.send_header("Location", "/")
                self.send_header(
                    "Set-Cookie",
                    f"sid={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age={auth.SESSION_TTL}",
                )
                self._add_security_headers()
                self.end_headers()
            else:
                self._serve_login("Неверный логин или пароль")
            return

        if parsed.path == "/login/email":
            self._handle_login_email_post()
            return

        if parsed.path == "/login/tg":
            self._handle_login_tg_post()
            return

        user_id = auth.get_authenticated_user(self.headers.get("Cookie", ""))
        if not user_id:
            self.send_response(302)
            self.send_header("Location", "/login")
            self._add_security_headers()
            self.end_headers()
            return

        if parsed.path != "/tg":
            self.send_error(404)
            return

        body_bytes = self._read_body()
        if body_bytes is None:
            return
        raw = body_bytes if body_bytes else b"{}"
        try:
            body = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            self.respond_json({"status": "error", "error": "invalid JSON"}, 400)
            return

        req_id = f"{ioe_web.DEVICE_ID}-{uuid.uuid4().hex[:6]}"
        action = body.get("action", "")

        if ioe_web.DEMO_MODE:
            self.respond_json({"status": "error", "error": "telegram not available in demo"})
            return

        req = {
            "id": req_id,
            "type": "command",
            "service": "telegram",
            "action": action,
            "user_id": user_id,
        }
        for key in body:
            if key in _TG_ALLOWED_KEYS:
                req[key] = body[key]
        if "chat_id" in req:
            try:
                req["chat_id"] = int(req["chat_id"])
            except (ValueError, TypeError):
                pass

        try:
            log.info("[%s] tg POST: %s", req_id, action)
            m = imap_conn()
            send_request(m, req)
        except Exception as e:
            log.error("[%s] tg POST send FAILED: %s", req_id, e)
            err_type, err_msg = _classify_error(str(e))
            self.respond_json({"status": "error", "error": err_msg, "error_type": err_type})
            return

        t = threading.Thread(target=poll_response, args=(user_id, req_id), daemon=True)
        t.start()
        self.respond_json({"id": req_id, "status": "pending"})
