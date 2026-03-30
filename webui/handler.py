"""IoE HTTP request handler."""
import json
import os
import uuid
import time
import threading
import logging
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import auth
from transport import imap_conn, send_request, poll_response

log = logging.getLogger("ioe-web")

_TG_ALLOWED_KEYS = {"phone", "code", "password", "chat_id", "text", "limit",
                     "offset_id", "reply_to_id", "message_id", "folder", "query"}

_auth_attempts = {}
_AUTH_LIMIT = 3
_AUTH_WINDOW = 300


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def respond_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_demo(self, cmd, qs, req_id):
        if cmd == "SEARCH":
            q = qs.get("q", [""])[0]
            results = [
                {"title": "\u041f\u043e\u0433\u043e\u0434\u0430 \u0432 \u0421\u0430\u043d\u043a\u0442-\u041f\u0435\u0442\u0435\u0440\u0431\u0443\u0440\u0433\u0435 \u2014 \u042f\u043d\u0434\u0435\u043a\u0441", "href": "https://yandex.ru/pogoda/saint-petersburg", "snippet": "\u0421\u0435\u0433\u043e\u0434\u043d\u044f +4\u00b0, \u043e\u0431\u043b\u0430\u0447\u043d\u043e. \u0417\u0430\u0432\u0442\u0440\u0430 +6\u00b0, \u0432\u043e\u0437\u043c\u043e\u0436\u0435\u043d \u0434\u043e\u0436\u0434\u044c."},
                {"title": "\u041f\u043e\u0433\u043e\u0434\u0430 \u0421\u041f\u0431 \u2014 Gismeteo", "href": "https://www.gismeteo.ru/weather-saint-petersburg/", "snippet": "\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u044b\u0439 \u043f\u0440\u043e\u0433\u043d\u043e\u0437 \u043f\u043e\u0433\u043e\u0434\u044b \u043d\u0430 \u0441\u0435\u0433\u043e\u0434\u043d\u044f, \u0437\u0430\u0432\u0442\u0440\u0430, \u043d\u0435\u0434\u0435\u043b\u044e."},
                {"title": "\u041f\u043e\u0433\u043e\u0434\u0430 \u0432 \u041f\u0438\u0442\u0435\u0440\u0435 \u0441\u0435\u0439\u0447\u0430\u0441 \u2014 rp5.ru", "href": "https://rp5.ru/spb", "snippet": "\u0422\u0435\u043a\u0443\u0449\u0430\u044f \u0442\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 +3\u00b0C, \u0432\u0435\u0442\u0435\u0440 5 \u043c/\u0441, \u0432\u043b\u0430\u0436\u043d\u043e\u0441\u0442\u044c 78%."},
                {"title": "\u041a\u043b\u0438\u043c\u0430\u0442 \u0421\u0430\u043d\u043a\u0442-\u041f\u0435\u0442\u0435\u0440\u0431\u0443\u0440\u0433\u0430 \u2014 \u0412\u0438\u043a\u0438\u043f\u0435\u0434\u0438\u044f", "href": "https://ru.wikipedia.org/wiki/\u041a\u043b\u0438\u043c\u0430\u0442_\u0421\u0430\u043d\u043a\u0442-\u041f\u0435\u0442\u0435\u0440\u0431\u0443\u0440\u0433\u0430", "snippet": "\u041a\u043b\u0438\u043c\u0430\u0442 \u0443\u043c\u0435\u0440\u0435\u043d\u043d\u044b\u0439. \u0421\u0440\u0435\u0434\u043d\u044f\u044f \u0442\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 \u043c\u0430\u0440\u0442\u0430 \u2212\u2060\u0031\u2026+4\u00b0C."},
            ]
            self.respond_json({"status": "ready", "results": results})
        elif cmd in ("GET", "TEXT"):
            url = qs.get("url", [""])[0]
            self.respond_json({
                "status": "ready",
                "title": "\u041f\u043e\u0433\u043e\u0434\u0430 \u0432 \u0421\u0430\u043d\u043a\u0442-\u041f\u0435\u0442\u0435\u0440\u0431\u0443\u0440\u0433\u0435 \u043d\u0430 \u0441\u0435\u0433\u043e\u0434\u043d\u044f",
                "body": "# \u041f\u043e\u0433\u043e\u0434\u0430\n\n\u0421\u0435\u0433\u043e\u0434\u043d\u044f +5\u00b0C, \u043e\u0431\u043b\u0430\u0447\u043d\u043e.\n\n## \u041f\u0440\u043e\u0433\u043d\u043e\u0437\n\n- \u041f\u043d +4\u00b0 \u0434\u043e\u0436\u0434\u044c\n- \u0412\u0442 +6\u00b0 \u043e\u0431\u043b\u0430\u0447\u043d\u043e\n- \u0421\u0440 +7\u00b0 \u0441\u043e\u043b\u043d\u0435\u0447\u043d\u043e",
                "format": "markdown",
            })
        else:
            self.respond_json({"status": "error", "error": "unknown cmd"})

    def do_GET(self):
        import ioe_web

        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path == "/login":
            self._serve_login()
            return
        if parsed.path == "/login/check_phone":
            phone = qs.get("phone", [""])[0]
            ip = self.client_address[0]
            if not auth.check_rate_limit(ip):
                self.respond_json({"allowed": False, "error": "rate_limit"})
                return
            self.respond_json({"allowed": auth.is_whitelisted(phone)})
            return
        if parsed.path.startswith("/login/tg"):
            action = qs.get("action", [""])[0]
            if action not in ("auth_start", "auth_code", "check_auth"):
                self.respond_json({"status": "error", "error": "forbidden action"})
                return
            phone = qs.get("phone", [""])[0]
            if action == "auth_start" and not auth.is_whitelisted(phone):
                self.respond_json({"status": "error", "error": "not allowed"})
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
            req_id = uuid.uuid4().hex[:8]
            login_user_id = phone or "login"
            req = {"id": req_id, "type": "command", "service": "telegram", "action": action, "user_id": login_user_id}
            for key in qs:
                if key in _TG_ALLOWED_KEYS:
                    req[key] = qs[key][0]
            try:
                m = imap_conn()
                send_request(m, req)
                m.logout()
            except Exception as e:
                self.respond_json({"status": "error", "error": str(e)})
                return
            t = threading.Thread(target=poll_response, args=(login_user_id, req_id), daemon=True)
            t.start()
            self.respond_json({"id": req_id, "status": "pending"})
            return
        if parsed.path == "/login/status":
            req_id = qs.get("id", [""])[0]
            phone = qs.get("phone", [""])[0]
            login_user_id = phone or "login"
            with ioe_web.lock:
                if (login_user_id, req_id) in ioe_web.pending:
                    resp = ioe_web.pending.pop((login_user_id, req_id))
                    result = {"status": "ready"}
                    for key in resp:
                        if key != "id":
                            result[key] = resp[key]
                    if result.get("auth_status") == "authorized":
                        sid = auth.create_session(login_user_id)
                        result["set_session"] = True
                        body = json.dumps(result, ensure_ascii=False).encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.send_header("Set-Cookie", "sid={}; HttpOnly; SameSite=Strict; Path=/".format(sid))
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
            self.end_headers()
            return

        user_id = auth.get_authenticated_user(self.headers.get("Cookie", ""))
        if not user_id:
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
            return

        if parsed.path == "/":
            body = ioe_web.HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
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
                        elif resp.get("type") == "command" or "dialogs" in resp or "messages" in resp or "unread_chats" in resp or "message_id" in resp or "auth_status" in resp or "results" not in resp and "body" not in resp:
                            for key in resp:
                                if key not in ("id", "status"):
                                    result[key] = resp[key]
                        else:
                            result["title"] = resp.get("title", "")
                            result["body"] = resp.get("body", "")
                            result["format"] = resp.get("format", "html")
                        self.respond_json(result)
                    else:
                        self.respond_json({
                            "status": "error",
                            "error": resp.get("error", "unknown"),
                        })
                    return
            self.respond_json({"status": "pending"})
            return

        if parsed.path in ("/get", "/text", "/search"):
            req_id = uuid.uuid4().hex[:8]
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
                log.info("[%s] send: %s %s", req_id, cmd, req.get("query", req.get("url", "")))
                m = imap_conn()
                send_request(m, req)
                m.logout()
                log.info("[%s] send: done (%.1fs)", req_id, time.time() - t0)
            except Exception as e:
                log.error("[%s] send: FAILED: %s", req_id, e)
                self.respond_json({"status": "error", "error": str(e)})
                return
            t = threading.Thread(target=poll_response, args=(user_id, req_id), daemon=True)
            t.start()
            self.respond_json({"id": req_id, "status": "pending"})
            return

        if parsed.path == "/proxy":
            req_id = uuid.uuid4().hex[:8]

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
                log.info("[%s] proxy: %s %s", req_id, method, url)
                m = imap_conn()
                send_request(m, req)
                m.logout()
            except Exception as e:
                log.error("[%s] proxy send FAILED: %s", req_id, e)
                self.respond_json({"status": "error", "error": str(e)})
                return

            t = threading.Thread(target=poll_response, args=(user_id, req_id), daemon=True)
            t.start()
            self.respond_json({"id": req_id, "status": "pending"})
            return

        if parsed.path == "/tg":
            req_id = uuid.uuid4().hex[:8]
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
                m.logout()
            except Exception as e:
                log.error("[%s] tg send FAILED: %s", req_id, e)
                self.respond_json({"status": "error", "error": str(e)})
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
                            kits.append({"file": os.path.basename(f), "service": k.get("service", ""), "description": k.get("description", ""), "actions": list(k.get("actions", {}).keys())})
                    except Exception:
                        continue
                self.respond_json({"kits": kits})
                return
            self.respond_json({"status": "error", "error": "kit execution via WebUI not yet supported"})
            return

        if parsed.path == "/browser":
            req_id = uuid.uuid4().hex[:8]
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
                log.info("[%s] browser: %s", req_id, url)
                m = imap_conn()
                send_request(m, req)
                m.logout()
            except Exception as e:
                log.error("[%s] browser send FAILED: %s", req_id, e)
                self.respond_json({"status": "error", "error": str(e)})
                return

            t = threading.Thread(target=poll_response, args=(user_id, req_id), daemon=True)
            t.start()
            self.respond_json({"id": req_id, "status": "pending"})
            return

        self.send_error(404)

    def _serve_login(self, error="", status=200):
        from html_templates import login_page
        body = login_page(error).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        import ioe_web
        from transport import imap_conn, send_request, poll_response

        parsed = urlparse(self.path)

        user_id = auth.get_authenticated_user(self.headers.get("Cookie", ""))
        if not user_id:
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
            return

        if parsed.path != "/tg":
            self.send_error(404)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length) if content_length else b"{}"
        try:
            body = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            self.respond_json({"status": "error", "error": "invalid JSON"}, 400)
            return

        req_id = uuid.uuid4().hex[:8]
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
            m.logout()
        except Exception as e:
            log.error("[%s] tg POST send FAILED: %s", req_id, e)
            self.respond_json({"status": "error", "error": str(e)})
            return

        t = threading.Thread(target=poll_response, args=(user_id, req_id), daemon=True)
        t.start()
        self.respond_json({"id": req_id, "status": "pending"})
