import os
import sys
import threading
from http.server import HTTPServer
from urllib.request import urlopen

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webui"))
sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IOE_SECRET", "secret123")

import ioe_web
import auth

_real_get_auth = auth.get_authenticated_user


def _get_response(port, path="/search?q=test"):
    server = HTTPServer(("127.0.0.1", port), ioe_web.Handler)
    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()
    resp = urlopen(f"http://127.0.0.1:{port}{path}", timeout=5)
    server.server_close()
    return resp


class TestSecurityHeaders:
    def setup_method(self):
        auth.get_authenticated_user = lambda cookie_header: "testuser"
        ioe_web.DEMO_MODE = True

    def teardown_method(self):
        auth.get_authenticated_user = _real_get_auth
        ioe_web.DEMO_MODE = False

    def test_nosniff_header(self, free_port):
        resp = _get_response(free_port)
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    def test_frame_options_header(self, free_port):
        resp = _get_response(free_port)
        assert resp.headers.get("X-Frame-Options") == "DENY"

    def test_referrer_policy_header(self, free_port):
        resp = _get_response(free_port)
        assert resp.headers.get("Referrer-Policy") == "no-referrer"
