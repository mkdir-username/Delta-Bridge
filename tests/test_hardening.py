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
