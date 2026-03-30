import time
import base64
import logging
import threading

log = logging.getLogger("ioe.browser")

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class BrowserPool:
    def __init__(self, max_browsers=2, page_ttl=300):
        self.max_browsers = max_browsers
        self.page_ttl = page_ttl
        self.pages = {}
        self.lock = threading.Lock()
        self._pw = None
        self._browser = None

    def _ensure_browser(self):
        if self._pw is None:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
        return self._browser

    def get_page(self, session_id=None):
        with self.lock:
            self._cleanup_expired()
            if session_id and session_id in self.pages:
                entry = self.pages[session_id]
                entry["last_used"] = time.time()
                return entry["page"]
            if len(self.pages) >= self.max_browsers:
                return None
            browser = self._ensure_browser()
            page = browser.new_page()
            sid = session_id or "page_{}".format(len(self.pages))
            self.pages[sid] = {"page": page, "last_used": time.time()}
            return page

    def release(self, session_id):
        with self.lock:
            if session_id in self.pages:
                try:
                    self.pages[session_id]["page"].close()
                except Exception:
                    pass
                del self.pages[session_id]

    def _cleanup_expired(self):
        now = time.time()
        expired = [k for k, v in self.pages.items() if now - v["last_used"] > self.page_ttl]
        for k in expired:
            try:
                self.pages[k]["page"].close()
            except Exception:
                pass
            del self.pages[k]

    def shutdown(self):
        with self.lock:
            for entry in self.pages.values():
                try:
                    entry["page"].close()
                except Exception:
                    pass
            self.pages.clear()
            if self._browser:
                try:
                    self._browser.close()
                except Exception:
                    pass
            if self._pw:
                try:
                    self._pw.stop()
                except Exception:
                    pass


_pool = None

def get_pool():
    global _pool
    if _pool is None:
        _pool = BrowserPool()
    return _pool


def handle_browser_request(request):
    if not PLAYWRIGHT_AVAILABLE:
        return {"status": 503, "error": "playwright not installed"}

    url = request.get("url", "")
    actions = request.get("actions", ["goto"])
    session_id = request.get("session_id")
    timeout_ms = request.get("timeout", 30000)

    pool = get_pool()
    page = pool.get_page(session_id)
    if page is None:
        return {"status": 429, "error": "browser pool exhausted", "retry_after": 30}

    try:
        results = []
        for action in actions:
            if isinstance(action, str):
                action = {"action": action}
            act = action.get("action", "goto")

            if act == "goto":
                page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                screenshot = _take_screenshot(page)
                clickable = _get_clickable_elements(page)
                results.append({
                    "action": "goto",
                    "title": page.title(),
                    "url": page.url,
                    "text_content": page.inner_text("body")[:10000],
                    "screenshot_base64": screenshot,
                    "clickable_elements": clickable,
                })

            elif act == "click":
                selector = action.get("selector", "")
                page.click(selector, timeout=5000)
                page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
                screenshot = _take_screenshot(page)
                results.append({"action": "click", "selector": selector, "screenshot_base64": screenshot})

            elif act == "type":
                selector = action.get("selector", "")
                text = action.get("text", "")
                page.fill(selector, text, timeout=5000)
                results.append({"action": "type", "selector": selector})

            elif act == "scroll":
                amount = action.get("amount", 500)
                direction = action.get("direction", "down")
                delta = amount if direction == "down" else -amount
                page.mouse.wheel(0, delta)
                page.wait_for_timeout(500)
                screenshot = _take_screenshot(page)
                results.append({"action": "scroll", "screenshot_base64": screenshot})

            elif act == "extract":
                selector = action.get("selector", "body")
                elements = page.query_selector_all(selector)
                texts = [el.inner_text() for el in elements[:50]]
                results.append({"action": "extract", "selector": selector, "texts": texts})

            elif act == "wait":
                selector = action.get("selector", "")
                wait_timeout = action.get("timeout", 5000)
                page.wait_for_selector(selector, timeout=wait_timeout)
                results.append({"action": "wait", "selector": selector})

        return {"status": 200, "results": results}

    except Exception as e:
        log.error("Browser action failed: %s", e)
        return {"status": 500, "error": str(e)}
    finally:
        if not session_id:
            pool.release(session_id or "page_0")


def _take_screenshot(page):
    png_bytes = page.screenshot(type="jpeg", quality=50, full_page=False)
    return base64.b64encode(png_bytes).decode("ascii")


def _get_clickable_elements(page, max_elements=50):
    elements = page.query_selector_all("a, button, input, textarea, select")
    result = []
    for el in elements[:max_elements]:
        try:
            bbox = el.bounding_box()
            if not bbox or bbox["width"] == 0 or bbox["height"] == 0:
                continue
            result.append({
                "tag": el.evaluate("e => e.tagName.toLowerCase()"),
                "text": (el.inner_text() or "")[:100],
                "href": el.get_attribute("href") or "",
                "bbox": bbox,
            })
        except Exception:
            continue
    return result
