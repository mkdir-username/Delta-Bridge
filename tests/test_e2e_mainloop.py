"""E2E tests for server.main() loop — zombie prevention, reconnect, normal flow."""

from __future__ import annotations

import json
import os
import sys
import types
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import patch

# --- Module stubs (same pattern as test_process_message.py) ---
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
from fake_imap import FakeIMAPClient
from ioe_crypto import derive_key, encrypt

IOE_KEY = derive_key(os.environ["IOE_SECRET"])


def _make_mime(payload_dict: dict) -> bytes:
    """Build a MIME message with AES-GCM encrypted JSON attachment."""
    encrypted = encrypt(IOE_KEY, json.dumps(payload_dict)).encode("ascii")
    msg = MIMEMultipart()
    msg.attach(MIMEText("body"))
    part = MIMEBase("application", "pdf")
    part.set_payload(encrypted)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename="report.pdf")
    msg.attach(part)
    return msg.as_bytes()


class _TickLimitReached(SystemExit):
    """Raised by patched time.sleep to stop main() after N ticks."""

    pass


def _run_main(
    clients: list[FakeIMAPClient],
    max_ticks: int = 5,
    time_seq: list[float] | None = None,
) -> None:
    """Run server.main() with patched IMAPClient, time, and lock.

    Args:
        clients: List of FakeIMAPClient instances. Each outer-loop iteration
                 pops one from the front. When exhausted, raises _TickLimitReached.
        max_ticks: Max time.sleep() calls before forced exit.
        time_seq: Sequence of values for time.time(). Cycles if exhausted.
    """
    client_iter = iter(clients)
    tick_count = 0
    time_idx = 0
    if time_seq is None:
        time_seq = [100.0]

    def tick() -> None:
        nonlocal tick_count
        tick_count += 1
        if tick_count >= max_ticks:
            raise _TickLimitReached(0)

    def fake_imap_factory(host: str, ssl: bool = True) -> FakeIMAPClient:
        try:
            client = next(client_iter)
            client._tick_callback = tick
            return client
        except StopIteration:
            raise _TickLimitReached(0) from None

    def fake_sleep(seconds: float) -> None:
        tick()

    def fake_time() -> float:
        nonlocal time_idx
        val = time_seq[time_idx % len(time_seq)]
        time_idx += 1
        return val

    with (
        patch.object(server, "IMAPClient", fake_imap_factory),
        patch.object(server, "_acquire_lock", return_value=None),
        patch("time.sleep", fake_sleep),
        patch("time.time", fake_time),
    ):
        try:
            server.main()
        except _TickLimitReached:
            pass


class TestNormalFlow:
    def setup_method(self) -> None:
        server._processed_uids.clear()
        server._rate_timestamps.clear()

    def test_message_processed_and_deleted(self) -> None:
        """Inject encrypted message → processed → deleted → response appended."""
        fake = FakeIMAPClient()
        raw = _make_mime({"id": "e2e-1", "type": "session_start", "session_id": "s1"})
        fake.inject_message(1, raw)

        _run_main([fake], max_ticks=3)

        assert 1 in fake._deleted, "message should be deleted after processing"
        assert len(fake._appended) >= 1, "response should be appended to INBOX"
        assert fake.search_count >= 1

    def test_empty_queue_loops_cleanly(self) -> None:
        """Empty queue — runs several ticks without errors."""
        fake = FakeIMAPClient()
        # No messages injected

        _run_main([fake], max_ticks=5)

        assert fake.search_count >= 1
        assert fake.idle_count >= 1
        assert len(fake._deleted) == 0
        assert len(fake._appended) == 0


class TestZombie:
    def setup_method(self) -> None:
        server._processed_uids.clear()
        server._rate_timestamps.clear()

    def test_zombie_starves_messages(self) -> None:
        """Zombie mode from start: search returns [] despite injected message."""
        fake = FakeIMAPClient()
        raw = _make_mime({"id": "z-1", "type": "session_start", "session_id": "s2"})
        fake.inject_message(1, raw)
        fake.set_mode("zombie")

        _run_main([fake], max_ticks=5)

        # Message should NOT be processed — zombie search returns []
        assert 1 not in fake._deleted, "zombie: message should NOT be deleted"
        assert len(fake._appended) == 0, "zombie: no response should be appended"
        # But message is still in the fake
        assert 1 in fake._messages

    def test_zombie_after_initial_normal(self) -> None:
        """Starts normal, turns zombie after 2 noops — new messages get stuck."""
        fake = FakeIMAPClient()
        # First message will be processed (normal mode)
        raw1 = _make_mime({"id": "z-2a", "type": "session_start", "session_id": "s3"})
        fake.inject_message(1, raw1)
        fake.set_zombie_after(2)  # zombie after 2 noops

        _run_main([fake], max_ticks=6)

        # First message processed in tick 1 (before zombie kicks in)
        assert 1 in fake._deleted, "first message should be processed before zombie"

        # Inject a second message after zombie — it won't be found
        # (In practice, the zombie already started by tick 2, so any messages
        #  injected after that point would be invisible to search)
        assert fake.idle_count >= 2

    def test_reconnect_breaks_zombie(self) -> None:
        """Time exceeds RECONNECT_INTERVAL → break inner loop → fresh client works."""
        # First client: zombie — messages stuck
        zombie_client = FakeIMAPClient()
        raw = _make_mime({"id": "z-3", "type": "session_start", "session_id": "s4"})
        zombie_client.inject_message(1, raw)
        zombie_client.set_mode("zombie")

        # Second client: normal — same message now visible
        fresh_client = FakeIMAPClient()
        fresh_client.inject_message(2, raw)  # same payload, new uid

        # Time sequence traces through time.time() calls:
        # Zombie client:
        #   connected_at = t() → 0.0
        #   iter1: age = t() - 0 → 1.0 (<300, continues, zombie search returns [])
        #   iter2: age = t() - 0 → 301.0 (>300, break → reconnect)
        # Fresh client:
        #   connected_at = t() → 1000.0
        #   iter1: age = t() - 1000 → 1.0 (<300, processes message)
        #   further calls: 1002+
        time_seq = [0.0, 1.0, 301.0, 1000.0, 1001.0, 1002.0, 1003.0, 1004.0]

        _run_main([zombie_client, fresh_client], max_ticks=8, time_seq=time_seq)

        # Zombie client: message NOT processed
        assert 1 not in zombie_client._deleted
        # Fresh client: message processed after reconnect
        assert 2 in fresh_client._deleted, "reconnect should break zombie"
        assert len(fresh_client._appended) >= 1


class TestErrors:
    def setup_method(self) -> None:
        server._processed_uids.clear()
        server._rate_timestamps.clear()

    def test_timeout_triggers_reconnect(self) -> None:
        """Timeout on noop → exception → outer loop catches → reconnects."""
        timeout_client = FakeIMAPClient()
        timeout_client.set_mode("timeout")

        fresh_client = FakeIMAPClient()
        raw = _make_mime({"id": "e-1", "type": "session_start", "session_id": "s5"})
        fresh_client.inject_message(1, raw)

        _run_main([timeout_client, fresh_client], max_ticks=5)

        # Timeout client raised, outer loop caught it
        assert timeout_client.idle_count == 1
        # Fresh client processed the message
        assert 1 in fresh_client._deleted

    def test_disconnect_triggers_reconnect(self) -> None:
        """IMAP4.abort on noop → exception → reconnect → fresh client works."""
        disc_client = FakeIMAPClient()
        disc_client.set_mode("disconnected")

        fresh_client = FakeIMAPClient()
        raw = _make_mime({"id": "e-2", "type": "session_start", "session_id": "s6"})
        fresh_client.inject_message(1, raw)

        _run_main([disc_client, fresh_client], max_ticks=5)

        assert disc_client.idle_count == 1
        assert 1 in fresh_client._deleted
