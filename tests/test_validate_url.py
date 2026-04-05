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
import socket as _socket


class TestValidateUrl:
    def test_http_https_pass(self):
        with patch.object(
            _socket,
            "getaddrinfo",
            return_value=[(_socket.AF_INET, 0, 0, "", ("93.184.216.34", 0))],
        ):
            server.validate_url("http://example.com")
            server.validate_url("https://example.com")

    def test_ftp_scheme_rejected(self):
        with pytest.raises(ValueError, match="http/https"):
            server.validate_url("ftp://evil.com/file")

    def test_file_scheme_rejected(self):
        with pytest.raises(ValueError, match="http/https"):
            server.validate_url("file:///etc/passwd")

    def test_localhost_blocked(self):
        with pytest.raises(ValueError):
            server.validate_url("http://localhost/admin")

    def test_loopback_blocked(self):
        with pytest.raises(ValueError):
            server.validate_url("http://127.0.0.1/admin")

    def test_aws_metadata_blocked(self):
        with pytest.raises(ValueError):
            server.validate_url("http://169.254.169.254/latest/meta-data/")

    def test_private_ip_rejected(self):
        for ip in ["10.0.0.1", "172.16.0.1", "192.168.1.1"]:
            with pytest.raises(ValueError):
                server.validate_url(f"http://{ip}/")

    def test_dns_resolving_to_private_blocked(self):
        with (
            patch.object(
                _socket,
                "getaddrinfo",
                return_value=[(_socket.AF_INET, 0, 0, "", ("127.0.0.1", 0))],
            ),
            pytest.raises(ValueError, match="private|Private"),
        ):
            server.validate_url("http://evil.com/")
