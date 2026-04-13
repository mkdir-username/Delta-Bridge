import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webui"))

from html_templates import login_page
from css import login_css


class TestLoginPage:
    def test_contains_step_divs(self):
        html = login_page()
        for step in ["step-phone", "step-setup"]:
            assert step in html

    def test_contains_auth_js_functions(self):
        html = login_page()
        for fn in ["authCode", "verifySetup"]:
            assert fn in html

    def test_contains_login_email_endpoint(self):
        html = login_page()
        assert "/login/email" in html

    def test_login_css_inlined(self):
        html = login_page()
        css = login_css()
        assert css[:50] in html
