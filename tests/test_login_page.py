import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webui"))

from html_templates import login_page
from css import login_css


class TestLoginPage:
    def test_contains_step_divs(self):
        html = login_page()
        assert "step-phone" in html
        assert "step-setup" not in html

    def test_contains_auth_js_functions(self):
        html = login_page()
        assert "authCode" in html
        assert "verifySetup" not in html
        assert "setupCheck" not in html

    def test_contains_login_email_endpoint(self):
        html = login_page()
        assert "/login/email" in html

    def test_login_css_inlined(self):
        html = login_page()
        css = login_css()
        assert css[:50] in html
