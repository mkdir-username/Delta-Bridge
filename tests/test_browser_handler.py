import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
from unittest.mock import MagicMock, patch


class TestBrowserPool:
    def test_pool_creation(self):
        from browser_handler import BrowserPool

        pool = BrowserPool(max_browsers=2, page_ttl=300)
        assert pool.max_browsers == 2
        assert pool.page_ttl == 300
        assert len(pool.pages) == 0

    def test_cleanup_expired(self):
        from browser_handler import BrowserPool
        import time

        pool = BrowserPool(max_browsers=2, page_ttl=1)
        mock_page = MagicMock()
        pool.pages["test"] = {"page": mock_page, "last_used": time.time() - 10}
        pool._cleanup_expired()
        assert "test" not in pool.pages
        mock_page.close.assert_called_once()

    def test_release_page(self):
        from browser_handler import BrowserPool

        pool = BrowserPool()
        mock_page = MagicMock()
        pool.pages["s1"] = {"page": mock_page, "last_used": 0}
        pool.release("s1")
        assert "s1" not in pool.pages
        mock_page.close.assert_called_once()

    def test_pool_exhausted(self):
        from browser_handler import BrowserPool

        pool = BrowserPool(max_browsers=1)
        pool.pages["existing"] = {"page": MagicMock(), "last_used": 99999999999}
        result = pool.get_page()
        assert result is None


class TestHandleBrowserRequest:
    def test_playwright_not_available(self):
        from browser_handler import handle_browser_request

        with patch("browser_handler.PLAYWRIGHT_AVAILABLE", False):
            result = handle_browser_request({"url": "https://example.com"})
            assert result["status"] == 503

    def test_pool_exhausted_returns_429(self):
        from browser_handler import handle_browser_request

        with (
            patch("browser_handler.PLAYWRIGHT_AVAILABLE", True),
            patch("browser_handler.get_pool") as mock_pool,
        ):
            mock_pool.return_value.get_page.return_value = None
            result = handle_browser_request({"url": "https://example.com"})
            assert result["status"] == 429
            assert "retry_after" in result

    def test_goto_action(self):
        from browser_handler import handle_browser_request

        mock_page = MagicMock()
        mock_page.title.return_value = "Example"
        mock_page.url = "https://example.com"
        mock_page.inner_text.return_value = "Example Domain"
        mock_page.screenshot.return_value = b"fake_png"
        mock_page.query_selector_all.return_value = []

        with (
            patch("browser_handler.PLAYWRIGHT_AVAILABLE", True),
            patch("browser_handler.get_pool") as mock_pool,
        ):
            mock_pool.return_value.get_page.return_value = mock_page
            result = handle_browser_request({"url": "https://example.com", "actions": ["goto"]})
            assert result["status"] == 200
            assert len(result["results"]) == 1
            assert result["results"][0]["title"] == "Example"
            mock_page.goto.assert_called_once()

    def test_click_action(self):
        from browser_handler import handle_browser_request

        mock_page = MagicMock()
        mock_page.screenshot.return_value = b"fake"

        with (
            patch("browser_handler.PLAYWRIGHT_AVAILABLE", True),
            patch("browser_handler.get_pool") as mock_pool,
        ):
            mock_pool.return_value.get_page.return_value = mock_page
            result = handle_browser_request(
                {
                    "url": "https://example.com",
                    "actions": [{"action": "click", "selector": "#btn"}],
                }
            )
            assert result["status"] == 200
            mock_page.click.assert_called_once_with("#btn", timeout=5000)

    def test_extract_action(self):
        from browser_handler import handle_browser_request

        mock_page = MagicMock()
        mock_el = MagicMock()
        mock_el.inner_text.return_value = "Link text"
        mock_page.query_selector_all.return_value = [mock_el]

        with (
            patch("browser_handler.PLAYWRIGHT_AVAILABLE", True),
            patch("browser_handler.get_pool") as mock_pool,
        ):
            mock_pool.return_value.get_page.return_value = mock_page
            result = handle_browser_request(
                {
                    "url": "https://example.com",
                    "actions": [{"action": "extract", "selector": "a"}],
                }
            )
            assert result["status"] == 200
            assert result["results"][0]["texts"] == ["Link text"]

    def test_exception_returns_500(self):
        from browser_handler import handle_browser_request

        mock_page = MagicMock()
        mock_page.goto.side_effect = Exception("timeout")

        with (
            patch("browser_handler.PLAYWRIGHT_AVAILABLE", True),
            patch("browser_handler.get_pool") as mock_pool,
        ):
            mock_pool.return_value.get_page.return_value = mock_page
            result = handle_browser_request({"url": "https://example.com"})
            assert result["status"] == 500
            assert "timeout" in result["error"]
