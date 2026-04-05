import os
import sys
import types
import pytest
from unittest.mock import patch

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
sys.modules["PIL.Image"] = sys.modules["PIL"]
sys.modules["PIL"].Image = sys.modules["PIL"]
sys.modules["requests"].get = lambda *a, **kw: None
sys.modules["requests"].request = lambda *a, **kw: None
sys.modules["requests"].Session = type("Session", (), {"request": lambda *a, **kw: None, "close": lambda self: None})
sys.modules["trafilatura"].extract = lambda html, **kw: None

os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IOE_SECRET", "test-secret-key")

import server


class TestRateLimit:
    def setup_method(self):
        server._rate_timestamps.clear()

    def test_allows_up_to_10_requests(self):
        for _ in range(10):
            server.check_rate_limit("user1")

    def test_11th_request_raises(self):
        for _ in range(10):
            server.check_rate_limit("user1")
        with pytest.raises(ValueError, match="Rate limit"):
            server.check_rate_limit("user1")

    def test_different_users_independent(self):
        for _ in range(10):
            server.check_rate_limit("alice")
        server.check_rate_limit("bob")

    def test_window_expiry_resets(self):
        import time

        for _ in range(10):
            server.check_rate_limit("user1")
        with patch("time.time", return_value=time.time() + 61):
            server.check_rate_limit("user1")
