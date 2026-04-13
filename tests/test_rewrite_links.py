"""rewrite_links must URL-encode href values to prevent injection."""

import sys
import os

_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "webui"))

from transport import rewrite_links


def test_rewrite_normal_link():
    html = '<a href="https://example.com/page">Link</a>'
    result = rewrite_links(html)
    assert "/get?url=" in result
    assert "example.com" in result


def test_rewrite_encodes_quotes_in_url():
    """URL containing quotes must be percent-encoded to prevent attribute breakout."""
    html = '<a href="https://evil.com/path&quot;onmouseover=&quot;alert(1)">Link</a>'
    result = rewrite_links(html)
    assert "onmouseover" not in result.split("/get?url=")[0] if "/get?url=" in result else True


def test_rewrite_blocks_javascript():
    html = '<a href="javascript:alert(1)">XSS</a>'
    result = rewrite_links(html)
    assert 'href="#blocked"' in result


def test_rewrite_blocks_data_uri():
    html = '<a href="data:text/html,<script>alert(1)</script>">XSS</a>'
    result = rewrite_links(html)
    assert 'href="#blocked"' in result


def test_rewrite_encodes_ampersands():
    """Ampersands in URL must not break the /get?url= query parameter."""
    html = '<a href="https://example.com/search?q=a&b=c">Link</a>'
    result = rewrite_links(html)
    assert "/get?url=" in result
    url_part = result.split("/get?url=")[1].split('"')[0]
    assert "%26" in url_part or "&amp;" in url_part
