import os
import sys
import types
from unittest.mock import patch, MagicMock

_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "server"))
sys.path.insert(0, os.path.dirname(__file__))

for _mod in ["truststore", "imapclient", "readability", "PIL", "PIL.Image",
             "requests", "trafilatura"]:
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)
sys.modules["truststore"].inject_into_ssl = lambda: None
sys.modules["imapclient"].IMAPClient = type("IMAPClient", (), {})
sys.modules["readability"].Document = type("Document", (), {
    "__init__": lambda self, html="": None, "title": lambda self: "", "summary": lambda self: ""})
sys.modules["PIL.Image"] = sys.modules["PIL"]
sys.modules["PIL"].Image = sys.modules["PIL"]
sys.modules["requests"].get = lambda *a, **kw: None
sys.modules["requests"].request = lambda *a, **kw: None
sys.modules["requests"].Session = type("Session", (), {
    "request": lambda *a, **kw: None, "close": lambda self: None})
sys.modules["trafilatura"].extract = lambda html, **kw: None

os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IOE_SECRET", "test-secret-key")

import browser_handler


class TestBrowserActions:
    def _make_pool_and_page(self):
        mock_page = MagicMock()
        mock_page.title.return_value = "Test Page"
        mock_page.url = "http://example.com"
        mock_page.content.return_value = "<html></html>"
        mock_page.mouse = MagicMock()
        mock_pool = MagicMock()
        mock_pool.get_page.return_value = mock_page
        return mock_pool, mock_page

    def test_type_action_calls_fill(self):
        pool, page = self._make_pool_and_page()
        with patch("browser_handler.PLAYWRIGHT_AVAILABLE", True), \
             patch("browser_handler.get_pool", return_value=pool):
            result = browser_handler.handle_browser_request({
                "session_id": "s1",
                "actions": [{"action": "type", "selector": "#input", "text": "hello"}]
            })
        page.fill.assert_called_once_with("#input", "hello", timeout=5000)

    def test_scroll_action_calls_wheel(self):
        pool, page = self._make_pool_and_page()
        with patch("browser_handler.PLAYWRIGHT_AVAILABLE", True), \
             patch("browser_handler.get_pool", return_value=pool):
            result = browser_handler.handle_browser_request({
                "session_id": "s2",
                "actions": [{"action": "scroll", "amount": 500}]
            })
        page.mouse.wheel.assert_called_once_with(0, 500)

    def test_wait_action_calls_wait_for_selector(self):
        pool, page = self._make_pool_and_page()
        with patch("browser_handler.PLAYWRIGHT_AVAILABLE", True), \
             patch("browser_handler.get_pool", return_value=pool):
            result = browser_handler.handle_browser_request({
                "session_id": "s3",
                "actions": [{"action": "wait", "selector": ".loaded", "timeout": 5000}]
            })
        page.wait_for_selector.assert_called_once()
