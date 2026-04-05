import os
import sys
import types
from unittest.mock import patch, MagicMock

_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "server"))
sys.path.insert(0, os.path.dirname(__file__))

for _mod in [
    "truststore",
    "imapclient",
    "readability",
    "PIL",
    "PIL.Image",
    "requests",
    "trafilatura",
]:
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)
sys.modules["truststore"].inject_into_ssl = lambda: None
sys.modules["imapclient"].IMAPClient = type("IMAPClient", (), {})
sys.modules["readability"].Document = type(
    "Document",
    (),
    {
        "__init__": lambda self, html="": None,
        "title": lambda self: "",
        "summary": lambda self: "",
    },
)

_mock_img = MagicMock()
_mock_img.size = (400, 300)
_mock_img.width = 400
_mock_img.height = 300
_mock_img.convert.return_value = _mock_img
_mock_img.resize.return_value = _mock_img


def _mock_save(buf, format="JPEG", quality=60):
    buf.write(b"\xff\xd8\xff\xe0tiny-jpeg")


_mock_img.save = _mock_save

_pil_mod = types.ModuleType("PIL")
_pil_image_mod = types.ModuleType("PIL.Image")
_pil_image_mod.open = lambda buf: _mock_img
_pil_mod.Image = _pil_image_mod
sys.modules["PIL"] = _pil_mod
sys.modules["PIL.Image"] = _pil_image_mod

_mock_requests = types.ModuleType("requests")
_mock_resp = MagicMock()
_mock_resp.headers = {"Content-Length": "1000"}
_mock_resp.content = b"\xff\xd8\xff\xe0fake-jpeg-data"
_mock_resp.raise_for_status = lambda: None
_mock_requests.get = MagicMock(return_value=_mock_resp)
_mock_requests.request = MagicMock(return_value=_mock_resp)
_mock_requests.Session = type("Session", (), {"request": lambda *a, **kw: None, "close": lambda self: None})
sys.modules["requests"] = _mock_requests

sys.modules["trafilatura"] = types.ModuleType("trafilatura")
sys.modules["trafilatura"].extract = lambda html, **kw: None

os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IOE_SECRET", "test-secret-key")

import server


def _img_open(buf):
    return _mock_img


def _patches(*extra):
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(patch.object(server, "Image", type("Image", (), {"open": staticmethod(_img_open)})))
    for p in extra:
        stack.enter_context(p)
    return stack


class TestInlineImages:
    def test_image_replaced_with_data_uri(self):
        html = '<html><body><img src="http://example.com/photo.jpg"></body></html>'
        with _patches(
            patch.object(server, "validate_url"),
            patch.object(server.requests, "get", return_value=_mock_resp),
        ):
            result = server.inline_images(html, "http://example.com")
        assert "data:image/jpeg;base64," in result

    def test_over_max_images_decomposed(self):
        imgs = "".join(f'<img src="http://example.com/{i}.jpg">' for i in range(15))
        html = f"<html><body>{imgs}</body></html>"
        with _patches(
            patch.object(server, "validate_url"),
            patch.object(server.requests, "get", return_value=_mock_resp),
        ):
            result = server.inline_images(html, "http://example.com", max_images=10)
        assert result.count("data:image") <= 10

    def test_large_content_length_decomposed(self):
        html = '<html><body><img src="http://example.com/huge.jpg"></body></html>'
        big_resp = MagicMock()
        big_resp.headers = {"Content-Length": str(20 * 1024 * 1024)}
        big_resp.content = b"x" * 100
        big_resp.raise_for_status = lambda: None
        with _patches(
            patch.object(server, "validate_url"),
            patch.object(server.requests, "get", return_value=big_resp),
        ):
            result = server.inline_images(html, "http://example.com")
        assert "data:image" not in result
        assert "<img" not in result

    def test_validate_url_called_per_image(self):
        html = '<html><body><img src="http://evil.com/x.jpg"><img src="http://good.com/y.jpg"></body></html>'

        def mock_validate(url):
            if "evil" in url:
                raise ValueError("Blocked")

        with _patches(
            patch.object(server, "validate_url", side_effect=mock_validate),
            patch.object(server.requests, "get", return_value=_mock_resp),
        ):
            result = server.inline_images(html, "http://example.com")
        assert result.count("data:image") <= 1

    def test_exception_doesnt_break_others(self):
        html = '<html><body><img src="http://fail.com/a.jpg"><img src="http://ok.com/b.jpg"></body></html>'
        call_count = [0]

        def side_effect(url, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("fail")
            return _mock_resp

        with _patches(
            patch.object(server, "validate_url"),
            patch.object(server.requests, "get", side_effect=side_effect),
        ):
            result = server.inline_images(html, "http://example.com")
        assert "data:image" in result
