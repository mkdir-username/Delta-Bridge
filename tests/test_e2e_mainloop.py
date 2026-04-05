"""E2E tests for server main loop — zombie detection, reconnect, normal flow.

These tests would have caught the 2-day zombie IMAP bug from 2026-04-03:
server stayed connected but search() returned [] silently.
"""

import json
import os
import sys
import types
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
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
sys.modules["PIL.Image"] = sys.modules["PIL"]
sys.modules["PIL"].Image = sys.modules["PIL"]
sys.modules["requests"].get = lambda *a, **kw: None
sys.modules["requests"].request = lambda *a, **kw: None
sys.modules["requests"].Session = type("Session", (), {"request": lambda *a, **kw: None, "close": lambda self: None})
sys.modules["trafilatura"].extract = lambda html, **kw: None

os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IOE_SECRET", "test-secret-key")

import server as ioe_server
from ioe_crypto import encrypt, derive_key
from fake_imap import FakeIMAPClient

IOE_KEY = derive_key(os.environ["IOE_SECRET"])


def _make_mime(payload_dict: dict) -> bytes:
    encrypted = encrypt(IOE_KEY, json.dumps(payload_dict)).encode("ascii")
    msg = MIMEMultipart()
    msg.attach(MIMEText("body"))
    part = MIMEBase("application", "pdf")
    part.set_payload(encrypted)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename="report.pdf")
    msg.attach(part)
    return msg.as_bytes()


def _run_main_ticks(fake_factory, max_ticks=10, time_values=None):
    """Run server.main() for max_ticks sleep cycles then stop."""
    tick = {"n": 0}

    def counting_sleep(t):
        tick["n"] += 1
        if tick["n"] >= max_ticks:
            raise SystemExit("test stop")

    time_seq = iter(time_values) if time_values else None

    def fake_time():
        if time_seq:
            return next(time_seq)
        return 0.0

    patches = [
        patch.object(ioe_server, "IMAPClient", side_effect=fake_factory),
        patch.object(ioe_server, "_acquire_lock", return_value=MagicMock()),
        patch("server.time.sleep", side_effect=counting_sleep),
        patch("server.time.time", side_effect=fake_time),
    ]
    for p in patches:
        p.start()
    try:
        try:
            ioe_server.main()
        except SystemExit:
            pass
    finally:
        for p in patches:
            p.stop()


class TestNormalFlow:
    def setup_method(self):
        ioe_server._processed_uids.clear()
        ioe_server._rate_timestamps.clear()

    def test_message_is_processed_and_deleted(self):
        fake = FakeIMAPClient()
        raw = _make_mime({"id": "req-1", "cmd": "SEARCH", "query": "test"})
        fake.inject_message(1, raw)

        def factory(*a, **kw):
            return fake

        with patch.object(ioe_server, "do_search", return_value=[{"title": "R"}]):
            _run_main_ticks(factory, max_ticks=3, time_values=[0] * 50)

        assert fake.search_count >= 1
        assert 1 in fake._deleted
        assert len(fake._appended) >= 1

    def test_empty_queue_loops_cleanly(self):
        fake = FakeIMAPClient()

        def factory(*a, **kw):
            return fake

        _run_main_ticks(factory, max_ticks=5, time_values=[0] * 50)

        assert fake.search_count >= 5
        assert fake._deleted == []
        assert fake._appended == []


class TestZombieConnection:
    """Regression tests for the zombie IMAP bug (2026-04-03)."""

    def setup_method(self):
        ioe_server._processed_uids.clear()
        ioe_server._rate_timestamps.clear()

    def test_zombie_starves_messages(self):
        """Zombie search returns [] — message never processed."""
        fake = FakeIMAPClient()
        raw = _make_mime({"id": "req-z1", "cmd": "SEARCH", "query": "test"})
        fake.inject_message(1, raw)
        fake.set_mode("zombie")

        def factory(*a, **kw):
            return fake

        _run_main_ticks(factory, max_ticks=10, time_values=[0] * 100)

        assert fake.search_count >= 10
        assert 1 not in fake._deleted
        assert fake._appended == []

    def test_zombie_after_initial_normal(self):
        """Starts normal, goes zombie after 1 tick — message never processed."""
        fake = FakeIMAPClient()
        raw = _make_mime({"id": "req-z2", "cmd": "SEARCH", "query": "test"})
        fake.inject_message(2, raw)
        fake.set_zombie_after(ticks=1)

        def factory(*a, **kw):
            return fake

        _run_main_ticks(factory, max_ticks=10, time_values=[0] * 100)

        assert fake.search_count >= 5
        assert 2 not in fake._deleted
        assert fake._appended == []

    def test_reconnect_interval_breaks_zombie(self):
        """RECONNECT_INTERVAL forces reconnection, new connection finds messages."""
        fake_zombie = FakeIMAPClient()
        raw = _make_mime({"id": "req-r1", "cmd": "SEARCH", "query": "python"})
        fake_zombie.inject_message(1, raw)
        fake_zombie.set_mode("zombie")

        fake_fresh = FakeIMAPClient()
        fake_fresh.inject_message(1, raw)

        call_count = {"n": 0}

        def factory(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return fake_zombie
            return fake_fresh

        # time values: first few = 0, then jump past RECONNECT_INTERVAL
        times = [0.0] * 6 + [301.0] * 50

        with patch.object(ioe_server, "do_search", return_value=[{"title": "R"}]):
            _run_main_ticks(factory, max_ticks=10, time_values=times)

        assert call_count["n"] >= 2
        assert 1 in fake_fresh._deleted
        assert len(fake_fresh._appended) >= 1


class TestConnectionErrors:
    def setup_method(self):
        ioe_server._processed_uids.clear()
        ioe_server._rate_timestamps.clear()

    def test_timeout_triggers_reconnect(self):
        fake_timeout = FakeIMAPClient()
        fake_timeout.set_mode("timeout")
        fake_ok = FakeIMAPClient()

        call_count = {"n": 0}

        def factory(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return fake_timeout
            return fake_ok

        _run_main_ticks(factory, max_ticks=3, time_values=[0] * 50)

        assert call_count["n"] >= 2

    def test_disconnect_triggers_reconnect(self):
        fake_dc = FakeIMAPClient()
        fake_dc.set_mode("disconnected")
        fake_ok = FakeIMAPClient()

        call_count = {"n": 0}

        def factory(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return fake_dc
            return fake_ok

        _run_main_ticks(factory, max_ticks=3, time_values=[0] * 50)

        assert call_count["n"] >= 2
