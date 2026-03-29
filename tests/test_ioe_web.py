"""Tests for IoE WebUI v4."""
import json
import sys
import os
import threading
from urllib.request import urlopen
from unittest.mock import patch, MagicMock
from http.server import HTTPServer
import socket

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "pass")
os.environ.setdefault("IOE_SECRET", "secret123")


def get_html():
    import ioe_web
    return ioe_web.HTML_PAGE


def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestV4Design:
    def test_has_empty_state(self):
        assert 'class="empty"' in get_html()

    def test_has_toolbar(self):
        assert 'class="toolbar"' in get_html()
        assert 'id="url"' in get_html()
        assert 'id="btnGo"' in get_html()

    def test_has_loading_styles(self):
        html = get_html()
        assert '.loading' in html
        assert '.spinner' in html
        assert '@keyframes spin' in html

    def test_has_result_card_styles(self):
        html = get_html()
        assert '.result-card' in html
        assert '.snippet' in html

    def test_has_reader_styles(self):
        html = get_html()
        assert '.reader-body' in html
        assert '.reader-meta' in html
        assert '.back-btn' in html
        assert 'font-read' in html

    def test_has_footer(self):
        assert 'id="statusText"' in get_html()
        assert '<footer>' in get_html()

    def test_has_scroll_top(self):
        assert 'scroll-top' in get_html()

    def test_button_disabled(self):
        assert 'disabled' in get_html()

    def test_no_pico_css(self):
        assert 'picocss' not in get_html()

    def test_has_format_raw_text(self):
        assert 'formatRawText' in get_html()

    def test_has_marked_js(self):
        html = get_html()
        assert 'marked' in html
        assert 'marked.min.js' in html

    def test_has_markdown_render_logic(self):
        assert 'marked.parse' in get_html()

    def test_cmd_click_support(self):
        assert 'metaKey' in get_html()
        assert 'ctrlKey' in get_html()


class TestRewriteLinks:
    def test_double_quote_href(self):
        import ioe_web
        result = ioe_web.rewrite_links('<a href="https://example.com/page">Link</a>')
        assert '/get?url=https://example.com/page' in result

    def test_relative_links_untouched(self):
        import ioe_web
        result = ioe_web.rewrite_links('<a href="/about">About</a>')
        assert 'href="/about"' in result


class TestEndpoints:
    def test_root_returns_html(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/".format(port), timeout=5)
        body = resp.read().decode()
        assert resp.status == 200
        assert "IoE" in body
        assert 'class="toolbar"' in body
        server.server_close()

    def test_search_returns_pending(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with patch.object(ioe_web, 'imap_conn') as mock:
            mock.return_value = MagicMock()
            t = threading.Thread(target=server.handle_request, daemon=True)
            t.start()
            resp = urlopen("http://127.0.0.1:{}/search?q=test".format(port), timeout=5)
            data = json.loads(resp.read().decode())
            assert data["status"] == "pending"
            assert "id" in data
        server.server_close()

    def test_status_returns_results_for_search(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        test_results = [{"title": "Test", "href": "https://test.com", "snippet": "Desc"}]
        with ioe_web.lock:
            ioe_web.pending["test123"] = {"id": "test123", "status": 200, "results": test_results}
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/status?id=test123".format(port), timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "ready"
        assert data["results"] == test_results
        server.server_close()

    def test_status_returns_body_for_page(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with ioe_web.lock:
            ioe_web.pending["page123"] = {"id": "page123", "status": 200, "title": "Page", "body": "<p>Content</p>"}
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/status?id=page123".format(port), timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "ready"
        assert data["title"] == "Page"
        assert data["body"] == "<p>Content</p>"
        server.server_close()


class TestDemoMode:
    def test_demo_search_returns_results(self):
        import ioe_web
        old = ioe_web.DEMO_MODE
        ioe_web.DEMO_MODE = True
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/search?q=weather".format(port), timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "ready"
        assert isinstance(data["results"], list)
        assert len(data["results"]) >= 3
        server.server_close()
        ioe_web.DEMO_MODE = old

    def test_demo_get_returns_body(self):
        import ioe_web
        old = ioe_web.DEMO_MODE
        ioe_web.DEMO_MODE = True
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/get?url=https://example.com".format(port), timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "ready"
        assert "title" in data
        assert "body" in data
        server.server_close()
        ioe_web.DEMO_MODE = old


class TestStatusEndpoint:
    def test_status_passes_format_field(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with ioe_web.lock:
            ioe_web.pending["fmt123"] = {
                "id": "fmt123", "status": 200,
                "title": "T", "body": "B", "format": "markdown",
            }
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/status?id=fmt123".format(port), timeout=5)
        data = json.loads(resp.read().decode())
        assert data["format"] == "markdown"
        server.server_close()

    def test_status_error_response(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with ioe_web.lock:
            ioe_web.pending["err123"] = {
                "id": "err123", "status": 500, "error": "HTTPError",
            }
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/status?id=err123".format(port), timeout=5)
        data = json.loads(resp.read().decode())
        assert data["status"] == "error"
        assert data["error"] == "HTTPError"
        server.server_close()

    def test_status_default_format_html(self):
        import ioe_web
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        with ioe_web.lock:
            ioe_web.pending["nofmt"] = {
                "id": "nofmt", "status": 200,
                "title": "T", "body": "<p>B</p>",
            }
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/status?id=nofmt".format(port), timeout=5)
        data = json.loads(resp.read().decode())
        assert data["format"] == "html"
        server.server_close()

    def test_404_for_unknown_path(self):
        import ioe_web
        from urllib.error import HTTPError as UrlHTTPError
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        try:
            urlopen("http://127.0.0.1:{}/nonexistent".format(port), timeout=5)
            assert False, "expected 404"
        except UrlHTTPError as e:
            assert e.code == 404
        server.server_close()


class TestDemoFormatField:
    def test_demo_get_has_format(self):
        import ioe_web
        old = ioe_web.DEMO_MODE
        ioe_web.DEMO_MODE = True
        port = get_free_port()
        server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        resp = urlopen("http://127.0.0.1:{}/get?url=https://example.com".format(port), timeout=5)
        data = json.loads(resp.read().decode())
        assert "format" in data
        server.server_close()
        ioe_web.DEMO_MODE = old
