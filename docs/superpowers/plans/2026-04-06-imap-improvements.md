# Delta-Bridge IMAP Transport Improvements Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce IoE request latency from ~13s to 3-5s by migrating to imapclient, adding IMAP IDLE, persistent connections, and LITERAL+.

**Architecture:** Three-phase approach: (1) migrate webui/transport.py from imaplib to imapclient, (2) add IMAP IDLE to both client and server, (3) add persistent connection pool. Each phase is independently deployable and testable.

**Tech Stack:** Python 3.11+, imapclient (already a dependency on server side), pytest, mypy --strict

## Already Completed (this session)

- [x] **B6:** `compress_encrypt` on all send paths, `decrypt_decompress` on all receive paths
- [x] **B4:** MIME variance (3 subtypes, 3 attachment types, optional headers, body padding)
- [x] **A4:** Latency telemetry module (`ioe_telemetry.py`) with Timer, RequestTiming, TelemetryCollector
- [x] **B3:** Batch fetch/delete in server main loop (single `client.fetch(messages, ...)` + single `expunge()`)

## File Structure

| File | Role | Tasks |
|------|------|-------|
| `webui/transport.py` | IMAP transport for WebUI | 1, 2, 3 |
| `webui/ioe_web.py` | Global state, connection pool | 2 |
| `server/server.py` | Server main loop | 3 |
| `tests/test_transport_imapclient.py` | **NEW** — tests for migrated transport | 1 |
| `tests/test_idle.py` | **NEW** — IDLE tests for client + server | 3 |
| `tests/test_connection_pool.py` | **NEW** — connection pool tests | 2 |
| `tests/fake_imap.py` | FakeIMAPClient (already exists) | 1, 2, 3 |

---

### Task 1: Migrate webui/transport.py from imaplib to imapclient

**Files:**
- Modify: `webui/transport.py:1-50` (imports, `imap_conn()`)
- Modify: `webui/transport.py:90-220` (`poll_response()`)
- Modify: `webui/transport.py:51-80` (`send_request()`)
- Modify: `tests/fake_imap.py` (add imaplib-compatible shims if needed)
- Create: `tests/test_transport_imapclient.py`

**Context:** Currently `webui/transport.py` uses `imaplib.IMAP4_SSL` while `server/server.py` uses `imapclient.IMAPClient`. This blocks IDLE support (imaplib has no IDLE). imapclient is already installed (server dependency).

**Key API differences:**

| imaplib | imapclient |
|---------|-----------|
| `imaplib.IMAP4_SSL(host, 993)` | `IMAPClient(host, ssl=True)` |
| `m.login(user, pw)` | `client.login(user, pw)` |
| `m.select("INBOX")` | `client.select_folder("INBOX")` |
| `m.search(None, "ALL")` → `("OK", [b"1 2 3"])` | `client.search(["ALL"])` → `[1, 2, 3]` |
| `m.fetch(uid, "(RFC822)")` → `("OK", [(b"1 (RFC822 {n}", bytes)])` | `client.fetch([uid], ["RFC822"])` → `{uid: {b"RFC822": bytes}}` |
| `m.store(uid, "+FLAGS", "\\Deleted")` | `client.set_flags([uid], [b"\\Deleted"])` |
| `m.expunge()` | `client.expunge()` |
| `m.noop()` | `client.noop()` |
| `m.append(folder, None, None, data)` | `client.append(folder, data)` |
| `m.logout()` | `client.logout()` |

- [ ] **Step 1: Write failing test for imapclient-based `imap_conn`**

```python
# tests/test_transport_imapclient.py
import os
import sys
import types
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webui"))
os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IOE_SECRET", "secret123")

import ioe_web


class TestImapConn:
    def test_returns_imapclient_instance(self):
        """imap_conn should return IMAPClient, not imaplib.IMAP4_SSL."""
        import transport

        mock_client = MagicMock()
        mock_client.login.return_value = b"OK"
        with patch("transport.IMAPClient", return_value=mock_client) as mock_cls:
            result = transport.imap_conn()
        mock_cls.assert_called_once_with(ioe_web.IMAP_HOST, ssl=True)
        mock_client.login.assert_called_once_with(ioe_web.EMAIL, ioe_web.IMAP_PASSWORD)
        assert result is mock_client
```

- [ ] **Step 2: Run test — verify it FAILS**

Run: `python -m pytest tests/test_transport_imapclient.py::TestImapConn::test_returns_imapclient_instance -xvs`
Expected: FAIL — `transport` has no `IMAPClient`

- [ ] **Step 3: Migrate `imap_conn()` to imapclient**

Replace in `webui/transport.py`:

```python
# Old imports to remove:
import imaplib

# New import:
from imapclient import IMAPClient

# Replace imap_conn():
def imap_conn() -> IMAPClient:
    import ioe_web

    last_err = None
    delays = [2, 5, 10, 20, 30]
    for attempt in range(len(delays) + 1):
        try:
            client = IMAPClient(ioe_web.IMAP_HOST, ssl=True)
            client.login(ioe_web.EMAIL, ioe_web.IMAP_PASSWORD)
            return client
        except Exception as e:
            last_err = e
            if attempt < len(delays):
                delay = delays[attempt] + random.random() * delays[attempt] * 0.3
                log.warning(
                    "IMAP login attempt %d failed: %s (retry in %.0fs)",
                    attempt + 1,
                    e,
                    delay,
                )
                time.sleep(delay)
    raise last_err  # type: ignore[misc]
```

- [ ] **Step 4: Run test — verify it passes**

Run: `python -m pytest tests/test_transport_imapclient.py::TestImapConn -xvs`
Expected: PASS

- [ ] **Step 5: Write failing test for migrated `send_request`**

```python
class TestSendRequest:
    def test_send_request_appends_to_queue(self):
        import transport

        mock_client = MagicMock()
        transport.send_request(mock_client, {"id": "r1", "cmd": "SEARCH", "query": "test"})
        mock_client.append.assert_called_once()
        folder, msg_bytes = mock_client.append.call_args[0]
        assert folder == ioe_web.QUEUE_FOLDER
        assert isinstance(msg_bytes, bytes)
```

- [ ] **Step 6: Run test — verify it FAILS**

Run: `python -m pytest tests/test_transport_imapclient.py::TestSendRequest -xvs`
Expected: FAIL — `append` called with wrong signature (imaplib uses 4 args, imapclient uses 2)

- [ ] **Step 7: Migrate `send_request()` to imapclient API**

In `webui/transport.py`, change the append call:

```python
# Old:
m.append(ioe_web.QUEUE_FOLDER, None, None, msg.as_bytes())

# New:
m.append(ioe_web.QUEUE_FOLDER, msg.as_bytes())
```

- [ ] **Step 8: Run test — verify it passes**

- [ ] **Step 9: Write failing test for migrated `poll_response` search/fetch**

```python
class TestPollResponse:
    def setup_method(self):
        ioe_web.pending.clear()

    def test_poll_finds_response_via_imapclient_api(self):
        import transport
        from ioe_crypto import compress_encrypt

        req_id = "test-poll-1"
        resp = {"id": req_id, "status": 200, "body": "ok"}
        encrypted = compress_encrypt(ioe_web.IOE_KEY, __import__("json").dumps(resp))

        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email import encoders

        msg = MIMEMultipart()
        msg.attach(__import__("email").mime.text.MIMEText("body"))
        part = MIMEBase("application", "pdf")
        part.set_payload(encrypted.encode("ascii"))
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename="doc.pdf")
        msg.attach(part)
        raw = msg.as_bytes()

        mock_client = MagicMock()
        mock_client.select_folder.return_value = {}
        mock_client.noop.return_value = None
        # imapclient search returns list of ints
        mock_client.search.return_value = [1]
        # imapclient fetch returns dict[int, dict[bytes, bytes]]
        mock_client.fetch.return_value = {1: {b"RFC822": raw}}
        mock_client.set_flags.return_value = {}
        mock_client.expunge.return_value = None
        mock_client.logout.return_value = None

        with (
            patch.object(transport, "imap_conn", return_value=mock_client),
            patch("time.sleep"),
            patch("time.time", side_effect=[0.0] * 200),
        ):
            transport.poll_response("user1", req_id)

        key = ("user1", req_id)
        assert key in ioe_web.pending
        assert ioe_web.pending[key]["status"] == 200
```

- [ ] **Step 10: Run test — verify it FAILS** (poll_response still uses imaplib API)

- [ ] **Step 11: Migrate `poll_response()` to imapclient API**

Key changes in `webui/transport.py:poll_response()`:

```python
# Old: m.select("INBOX")
# New: m.select_folder("INBOX")

# Old: _, msgs = m.search(None, "ALL")
#      uids = msgs[0].split()  # bytes
# New: uids = m.search(["ALL"])  # list[int]

# Old: _, data = m.fetch(uid, "(RFC822)")
#      raw = data[0][1]
# New: data = m.fetch([uid], ["RFC822"])
#      raw = data[uid][b"RFC822"]

# Old: m.store(uid, "+FLAGS", "\\Deleted")
# New: m.set_flags([uid], [b"\\Deleted"])

# Old: seen_uids = set() of bytes
# New: seen_uids = set() of ints
```

Full replacement of poll_response body — see `webui/transport.py` for the current code. Replace the search/fetch/store/delete operations with imapclient equivalents.

- [ ] **Step 12: Run test — verify it passes**

Run: `python -m pytest tests/test_transport_imapclient.py -xvs`
Expected: ALL PASS

- [ ] **Step 13: Update existing transport tests**

Update `tests/test_transport_timeout.py` and `tests/test_transport_retry.py` — they mock `imaplib.IMAP4_SSL`, switch to mock `IMAPClient`.

- [ ] **Step 14: Run full suite**

Run: `make check`
Expected: lint ✅, typecheck ✅, 535+ passed, coverage ≥90%

- [ ] **Step 15: Commit**

```bash
git add webui/transport.py tests/test_transport_imapclient.py \
  tests/test_transport_timeout.py tests/test_transport_retry.py &&
git commit -m "refactor(transport): миграция webui/transport.py с imaplib на imapclient"
```

---

### Task 2: Persistent IMAP Connection Pool

**Files:**
- Modify: `webui/ioe_web.py:145-156` (add connection pool globals)
- Modify: `webui/transport.py:27-48` (`imap_conn()` → pool-based)
- Create: `tests/test_connection_pool.py`

**Context:** Every request creates a new IMAP connection (SSL handshake + LOGIN = 300-500ms). A persistent connection pool eliminates this overhead for subsequent requests. Two connections needed: one for QUEUE_FOLDER (sending), one for INBOX (polling).

- [ ] **Step 1: Write failing test for connection pool**

```python
# tests/test_connection_pool.py
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "webui"))
os.environ.setdefault("EMAIL", "test@test.com")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IOE_SECRET", "secret123")

import ioe_web
import transport


class TestConnectionPool:
    def setup_method(self):
        # Reset pool state
        if hasattr(transport, "_pool"):
            transport._pool.clear()

    def test_second_call_reuses_connection(self):
        mock1 = MagicMock()
        mock1.noop.return_value = None
        call_count = 0

        def factory(*a, **kw):
            nonlocal call_count
            call_count += 1
            return mock1

        with patch("transport.IMAPClient", side_effect=factory):
            c1 = transport.imap_conn()
            c2 = transport.imap_conn()
        assert call_count == 1, "Should reuse existing connection"
        assert c1 is c2

    def test_creates_new_after_noop_fails(self):
        mock_stale = MagicMock()
        mock_stale.noop.side_effect = Exception("dead")
        mock_fresh = MagicMock()
        mock_fresh.noop.return_value = None

        clients = [mock_stale, mock_fresh]
        with patch("transport.IMAPClient", side_effect=clients):
            c1 = transport.imap_conn()  # gets mock_stale
            # Simulate stale detection on next call
            c2 = transport.imap_conn()  # mock_stale.noop fails → creates mock_fresh
        assert c2 is mock_fresh
```

- [ ] **Step 2: Run test — verify it FAILS**

- [ ] **Step 3: Implement connection pool**

In `webui/transport.py`:

```python
import threading

_pool: dict[str, IMAPClient] = {}
_pool_lock = threading.Lock()


def imap_conn() -> IMAPClient:
    """Get or create a persistent IMAP connection."""
    import ioe_web

    with _pool_lock:
        key = f"{ioe_web.EMAIL}@{ioe_web.IMAP_HOST}"
        if key in _pool:
            client = _pool[key]
            try:
                client.noop()
                return client
            except Exception:
                log.info("Stale connection, reconnecting")
                try:
                    client.logout()
                except Exception:
                    pass
                del _pool[key]

        last_err = None
        delays = [2, 5, 10, 20, 30]
        for attempt in range(len(delays) + 1):
            try:
                client = IMAPClient(ioe_web.IMAP_HOST, ssl=True)
                client.login(ioe_web.EMAIL, ioe_web.IMAP_PASSWORD)
                _pool[key] = client
                return client
            except Exception as e:
                last_err = e
                if attempt < len(delays):
                    delay = delays[attempt] + random.random() * delays[attempt] * 0.3
                    log.warning("IMAP attempt %d failed: %s (retry %.0fs)", attempt + 1, e, delay)
                    time.sleep(delay)
        raise last_err  # type: ignore[misc]
```

- [ ] **Step 4: Run test — verify it passes**

- [ ] **Step 5: Update `poll_response` — don't `logout()` the pooled connection**

In `webui/transport.py:poll_response()`, remove `m.logout()` calls — connection stays in pool. Add try/finally to handle errors without killing pool.

- [ ] **Step 6: Run full suite**

Run: `make check`

- [ ] **Step 7: Commit**

```bash
git add webui/transport.py tests/test_connection_pool.py &&
git commit -m "feat(transport): persistent IMAP connection pool"
```

---

### Task 3: IMAP IDLE for Client and Server

**Files:**
- Modify: `webui/transport.py:90-220` (`poll_response()` — replace polling with IDLE)
- Modify: `server/server.py:991-1041` (`main()` — replace 0.5s polling with IDLE)
- Modify: `tests/fake_imap.py` (add IDLE methods)
- Create: `tests/test_idle.py`

**Context:** IMAP IDLE (RFC 2177) enables server-push. Instead of polling every 0.5-1.6s, the server tells us when new messages arrive. Yandex supports IDLE but it's unstable (EOF 1-2 times/hour). Cycle: IDLE(10min) → DONE → NOOP → IDLE.

**Depends on:** Task 1 (imapclient migration)

- [ ] **Step 1: Add IDLE methods to FakeIMAPClient**

In `tests/fake_imap.py`, add:

```python
def idle(self) -> None:
    self._assert_connected()
    self._idle_active = True

def idle_check(self, timeout: int = 30) -> list[tuple[int, bytes]]:
    self._assert_connected()
    if not self._idle_active:
        return []
    if self._messages:
        return [(1, b"EXISTS")]
    return []

def idle_done(self) -> tuple[bytes, list[bytes]]:
    self._assert_connected()
    self._idle_active = False
    return (b"OK", [])
```

- [ ] **Step 2: Write failing test for server IDLE loop**

```python
# tests/test_idle.py
import os
import sys
import types
import json
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import patch

_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "server"))
sys.path.insert(0, os.path.dirname(__file__))

for _mod in ["truststore", "imapclient", "readability", "PIL", "PIL.Image", "requests", "trafilatura"]:
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)
sys.modules["truststore"].inject_into_ssl = lambda: None
sys.modules["imapclient"].IMAPClient = type("IMAPClient", (), {})
sys.modules["readability"].Document = type("Document", (), {"__init__": lambda self, html="": None, "title": lambda self: "", "summary": lambda self: ""})
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


class TestServerIdle:
    def setup_method(self):
        server._processed_uids.clear()
        server._rate_timestamps.clear()

    def test_main_uses_idle_instead_of_polling(self):
        """Server main loop should call idle() instead of time.sleep(0.5)."""
        fake = FakeIMAPClient()
        # Verify idle() is called
        assert hasattr(fake, "idle"), "FakeIMAPClient must support idle()"
        assert hasattr(fake, "idle_check"), "FakeIMAPClient must support idle_check()"
        assert hasattr(fake, "idle_done"), "FakeIMAPClient must support idle_done()"
```

- [ ] **Step 3: Run test — verify FAIL** (FakeIMAPClient doesn't have idle methods yet)

- [ ] **Step 4: Add idle methods to FakeIMAPClient** (code from Step 1)

- [ ] **Step 5: Run test — verify PASS**

- [ ] **Step 6: Write failing test for server IDLE integration**

```python
    def test_idle_processes_message_on_exists(self):
        """When idle_check returns EXISTS, server should fetch and process."""
        fake = FakeIMAPClient()
        raw = _make_mime({"id": "idle-1", "type": "session_start", "session_id": "s1"})
        fake.inject_message(1, raw)

        # Run main loop with time that triggers reconnect after 1 iteration
        # The loop should: idle() → idle_check() gets EXISTS → idle_done() → search() → process
        time_seq = [0.0, 1.0, 302.0]  # third call triggers reconnect
        _run_main_idle([fake], max_ticks=3, time_seq=time_seq)

        assert 1 in fake._deleted, "Message should be processed via IDLE"
        assert fake.idle_count >= 1, "idle() should be called"
```

(`_make_mime` and `_run_main_idle` helper functions needed — copy from test_e2e_mainloop.py and adapt)

- [ ] **Step 7: Run test — verify FAIL** (server main loop still uses polling)

- [ ] **Step 8: Implement IDLE in server main loop**

Replace in `server/server.py:main()`:

```python
# Replace the inner while loop body:
while True:
    iteration += 1
    age = time.time() - connected_at
    if age > RECONNECT_INTERVAL:
        log.info("Reconnecting (stale prevention, %ds, iter=%d)", RECONNECT_INTERVAL, iteration)
        break
    
    # IDLE-based waiting instead of polling
    client.idle()
    try:
        responses = client.idle_check(timeout=min(600, RECONNECT_INTERVAL - int(age)))
    except Exception:
        log.debug("IDLE interrupted, restarting cycle")
        try:
            client.idle_done()
        except Exception:
            pass
        break
    client.idle_done()
    
    # Process any messages
    messages = client.search(["ALL"])
    if messages:
        log.info("mainloop: search found %d uids (iter=%d)", len(messages), iteration)
        all_data = client.fetch(messages, ["RFC822"])
        processed_uids = []
        for uid in messages:
            raw = all_data.get(uid, {}).get(b"RFC822")
            if raw is None:
                continue
            if process_message(client, uid, raw):
                processed_uids.append(uid)
        if processed_uids:
            client.delete_messages(processed_uids)
            client.expunge()
            log.info("Deleted %d uids from queue", len(processed_uids))
```

- [ ] **Step 9: Run test — verify PASS**

- [ ] **Step 10: Write failing test for client-side IDLE in poll_response**

Similar pattern: `poll_response` should use `m.idle()` + `m.idle_check(timeout=10)` instead of `time.sleep(1)` + `m.search()`.

- [ ] **Step 11: Implement IDLE in poll_response**

Replace the polling loop in `webui/transport.py:poll_response()`:

```python
# Instead of:
#   time.sleep(1 + random.random() * 0.6)
#   m.noop()
#   _, msgs = m.search(None, "ALL")
# Use:
#   m.idle()
#   responses = m.idle_check(timeout=10)
#   m.idle_done()
#   if any EXISTS in responses:
#       uids = m.search(["ALL"])
#   Fallback: if idle_check raises, fall back to noop+search
```

- [ ] **Step 12: Run full suite**

Run: `make check`
Expected: lint ✅, typecheck ✅, all pass, coverage ≥90%

- [ ] **Step 13: Commit**

```bash
git add server/server.py webui/transport.py tests/fake_imap.py tests/test_idle.py &&
git commit -m "feat(transport): IMAP IDLE вместо polling на клиенте и сервере"
```

---

### Task 4: Smoke Test — Rate Limit Probe (A1)

**Files:**
- Create: `scripts/probe_append_rate.py`

**Context:** IMAP APPEND rate limit на Yandex не документирован. Этот скрипт запускается вручную с реальными credentials для эмпирического определения safe rate. Не часть CI.

- [ ] **Step 1: Write the probe script**

```python
#!/usr/bin/env python3
"""Probe Yandex IMAP APPEND rate limits empirically.

Usage: EMAIL=... IMAP_PASSWORD=... python scripts/probe_append_rate.py
"""
import os
import sys
import time
import json
from imapclient import IMAPClient
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ioe_crypto import derive_key, compress_encrypt

EMAIL = os.environ["EMAIL"]
PASSWORD = os.environ["IMAP_PASSWORD"]
KEY = derive_key(os.environ.get("IOE_SECRET", "probe"))
HOST = "imap.yandex.ru"
FOLDER = "IoE-Probe"  # separate folder to avoid interference


def make_probe_msg(seq: int) -> bytes:
    payload = compress_encrypt(KEY, json.dumps({"probe": seq})).encode("ascii")
    msg = MIMEMultipart()
    msg["Subject"] = f"probe {seq}"
    msg["From"] = EMAIL
    msg["To"] = EMAIL
    msg.attach(MIMEText(payload, "plain"))
    return msg.as_bytes()


def probe(rate_per_min: float, count: int = 10) -> list[dict]:
    interval = 60.0 / rate_per_min
    results = []
    client = IMAPClient(HOST, ssl=True)
    client.login(EMAIL, PASSWORD)
    try:
        client.create_folder(FOLDER)
    except Exception:
        pass
    client.select_folder(FOLDER)

    for i in range(count):
        t0 = time.monotonic()
        try:
            client.append(FOLDER, make_probe_msg(i))
            elapsed = (time.monotonic() - t0) * 1000
            results.append({"seq": i, "status": "OK", "ms": round(elapsed, 1)})
            print(f"  [{i+1}/{count}] OK  {elapsed:.0f}ms")
        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            results.append({"seq": i, "status": "ERROR", "error": str(e), "ms": round(elapsed, 1)})
            print(f"  [{i+1}/{count}] ERR {e} ({elapsed:.0f}ms)")
            break
        if i < count - 1:
            time.sleep(max(0, interval - (time.monotonic() - t0)))

    # Cleanup
    try:
        msgs = client.search(["ALL"])
        if msgs:
            client.delete_messages(msgs)
            client.expunge()
    except Exception:
        pass
    client.logout()
    return results


def main():
    rates = [1, 6, 12, 30, 60, 120]  # per minute
    print(f"Probing IMAP APPEND rate limits on {HOST}")
    print(f"Account: {EMAIL}")
    print(f"Folder: {FOLDER}")
    print()

    all_results = {}
    for rate in rates:
        print(f"--- {rate}/min (interval {60/rate:.1f}s) ---")
        results = probe(rate, count=10)
        all_results[f"{rate}/min"] = results
        errors = [r for r in results if r["status"] == "ERROR"]
        if errors:
            print(f"  STOPPED: errors at rate {rate}/min")
            break
        avg_ms = sum(r["ms"] for r in results) / len(results)
        print(f"  avg: {avg_ms:.0f}ms")
        time.sleep(5)  # cooldown between series

    print("\n=== RESULTS ===")
    for rate, results in all_results.items():
        ok = sum(1 for r in results if r["status"] == "OK")
        print(f"{rate}: {ok}/{len(results)} OK")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run manually** (requires real credentials)

```bash
EMAIL=your@yandex.ru IMAP_PASSWORD=... IOE_SECRET=... python scripts/probe_append_rate.py
```

- [ ] **Step 3: Document results in CLAUDE.md**

Add discovered rate limit to `## Yandex IMAP Rate Limits` section.

- [ ] **Step 4: Commit**

```bash
git add scripts/probe_append_rate.py &&
git commit -m "feat(scripts): IMAP APPEND rate limit probe"
```

---

## Verification

After all tasks:

1. `make check` — lint + typecheck + 535+ tests + coverage ≥90%
2. Manual E2E: deploy to VPS, send request via WebUI, verify latency improvement
3. Run `scripts/probe_append_rate.py` to document safe APPEND rate
4. Monitor for 24h: no Yandex anti-spam blocks
