import sys
import os
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webui"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
if "imapclient" not in sys.modules:
    sys.modules["imapclient"] = types.ModuleType("imapclient")
    sys.modules["imapclient"].IMAPClient = type("IMAPClient", (), {})
os.environ.setdefault("EMAIL", "t@t")
os.environ.setdefault("IMAP_PASSWORD", "t")
os.environ.setdefault("IOE_SECRET", "s")

from transport import rewrite_links


class TestRewriteLinksScheme:
    def test_javascript_scheme_blocked(self):
        html = '<a href="javascript:alert(1)">x</a>'
        result = rewrite_links(html)
        assert "javascript:" not in result
        assert "alert" not in result

    def test_data_scheme_blocked(self):
        html = '<a href="data:text/html,<script>alert(1)</script>">x</a>'
        result = rewrite_links(html)
        assert "data:" not in result

    def test_vbscript_scheme_blocked(self):
        html = "<a href='vbscript:msgbox(1)'>x</a>"
        result = rewrite_links(html)
        assert "vbscript:" not in result

    def test_https_url_rewritten(self):
        html = '<a href="https://example.com/p">x</a>'
        result = rewrite_links(html)
        assert "/get?url=https://example.com/p" in result

    def test_relative_url_untouched(self):
        html = '<a href="/local/path">x</a>'
        result = rewrite_links(html)
        assert "/local/path" in result
        assert "/get?url=" not in result


class TestGzipBombGuard:
    def test_decompress_rejects_oversize(self):
        import gzip
        import os as _os
        import base64 as _b64
        import pytest
        from Crypto.Cipher import AES
        from ioe_crypto import derive_key, MAX_DECOMPRESSED, decrypt_decompress

        key = derive_key("secret")
        huge = b"A" * (MAX_DECOMPRESSED + 1024)
        compressed = gzip.compress(huge)
        nonce = _os.urandom(12)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        ct, tag = cipher.encrypt_and_digest(compressed)
        blob = _b64.b64encode(nonce + ct + tag).decode()
        with pytest.raises(ValueError, match="too large"):
            decrypt_decompress(key, blob)

    def test_decompress_normal_payload_works(self):
        from ioe_crypto import derive_key, compress_encrypt, decrypt_decompress

        key = derive_key("secret")
        plaintext = "hello world " * 100
        blob = compress_encrypt(key, plaintext)
        assert decrypt_decompress(key, blob) == plaintext


class TestCSPNoUnsafeInline:
    def test_csp_does_not_contain_unsafe_inline(self):
        import ioe_web
        from handler import Handler

        assert hasattr(ioe_web, "SCRIPT_HASHES")
        assert hasattr(ioe_web, "STYLE_HASHES")
        h = Handler.__new__(Handler)
        captured: dict[str, str] = {}
        h.send_header = lambda k, v: captured.setdefault(k, v)  # type: ignore[method-assign]
        h._add_security_headers()
        csp = captured.get("Content-Security-Policy", "")
        assert "unsafe-inline" not in csp
        assert "sha256-" in csp
        assert "'self'" in csp
