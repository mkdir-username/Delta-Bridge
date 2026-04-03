# Claude-over-IoE: HTTP Proxy Design

## Context

При whitelist-режиме (чебурнет) единственный доступный протокол — email (IMAP).
IoE уже туннелирует HTTP через IMAP. Задача: дать Claude Code CLI работать через IoE,
сохранив полный функционал (tool use, file editing, conversation).

Пользователь имеет подписку Claude (OAuth, не API key).

## Architecture

```
Claude Code CLI
    │ HTTP (ANTHROPIC_BASE_URL=http://localhost:8090)
    ▼
claude_proxy.py (localhost:8090)
    │ serialize HTTP request → JSON → gzip → AES-256-GCM → IMAP APPEND
    ▼
Yandex Mail (encrypted PDF attachment, steganographic envelope)
    │
    ▼
VPS server.py (Amsterdam) — IMAP FETCH → decrypt → gunzip → deserialize
    │ HTTP request to api.anthropic.com / console.anthropic.com / any target
    ▼
Anthropic API (stream collected into single response)
    │
    ▼
VPS → gzip → encrypt → IMAP APPEND → Yandex → claude_proxy.py → Claude Code CLI
```

## Components

### 1. `client/claude_proxy.py` — Local HTTP Proxy

Python `http.server.HTTPServer` on `localhost:8090`.

**Responsibilities:**
- Accept ANY HTTP request from Claude Code CLI (POST, GET, etc.)
- Serialize full HTTP request: method, path, headers (incl. Authorization), body
- gzip the serialized JSON before encryption
- Encrypt via `crypto.py` → IMAP APPEND to `IoE` folder
- Poll INBOX for response (extended timeout: 300 cycles × 1s)
- Deserialize HTTP response → return to CLI with original status code + headers

**Threading:** Each incoming HTTP request spawns a thread with its own IMAP connection.
Claude Code makes parallel API calls (tool use), so proxy must handle concurrent requests.

**Request serialization format:**
```json
{
  "type": "claude_proxy",
  "id": "<uuid>",
  "user_id": "claude",
  "http_request": {
    "method": "POST",
    "path": "/v1/messages",
    "headers": {"authorization": "Bearer sk-ant-oat01-...", "content-type": "application/json", ...},
    "body": "<raw body string>"
  }
}
```

**Response deserialization:**
```json
{
  "id": "<same uuid>",
  "type": "claude_proxy_response",
  "http_response": {
    "status_code": 200,
    "headers": {"content-type": "application/json", ...},
    "body": "<raw body string>"
  }
}
```

### 2. `server/server.py` — New handler `handle_claude_proxy()`

Added to `dispatch_request()` for `type=claude_proxy`.

**Responsibilities:**
- Reconstruct HTTP request from serialized JSON
- Forward to target host (extracted from `Host` header or path)
- Target: primarily `api.anthropic.com`, but also `console.anthropic.com` (OAuth refresh)
- **Force `stream: false`** in JSON body if present (Claude Messages API)
- If API uses SSE despite stream=false being impossible to set (non-Messages endpoints),
  collect full SSE stream into buffered response
- Return full HTTP response (status, headers, body) via IMAP
- **No `validate_url` / `check_rate_limit`** — trusted internal traffic
- **No `MAX_BODY` truncation** — full response returned

**Timeout:** `requests.request(..., timeout=300)` for Claude API calls.

### 3. Compression

**gzip applied BEFORE encryption, AFTER serialization.**

Rationale: JSON compresses 5-10x. A 1MB Claude response → ~100-200KB compressed → ~150-300KB after base64+AES overhead. Well within Yandex Mail limits (~30MB).

Applied in both directions (request and response).

### 4. Proxy Target Resolution

Claude Code CLI sends requests to `http://localhost:8090/v1/messages`.
Proxy must reconstruct the real target URL:
- Base: `https://api.anthropic.com`
- Path: from the incoming request path (`/v1/messages`)
- Full URL: `https://api.anthropic.com/v1/messages`

For OAuth refresh and other non-API calls, Claude Code may hit different hosts.
Proxy approach: **transparent forwarding** — the CLI sets `Host` header, proxy uses it.
If `Host` header is missing or `localhost`, default to `api.anthropic.com`.

Alternative: environment variable `IOE_CLAUDE_TARGET=api.anthropic.com` on proxy side.

### 5. OAuth Token Handling

- Token stored in macOS Keychain (existing Claude Code behavior, unchanged)
- Token travels in `Authorization` header inside encrypted IMAP payload
- VPS sees token only in memory during request forwarding, never persists
- Token refresh: Claude Code CLI calls `console.anthropic.com` — also tunneled through proxy
- If token expires mid-session: CLI retries with refreshed token, transparent to proxy

### 6. Timeouts & Reliability

| Component | Value | Rationale |
|-----------|-------|-----------|
| Proxy → IMAP send | 30s | Standard IMAP operation |
| Proxy poll cycles | 300 × 1s | 5 min max wait for Claude response |
| VPS → Anthropic API | 300s | Claude can take minutes for complex tasks |
| IMAP reconnect | 3 retries, 2s backoff | Handle transient drops |

### 7. IMAP Optimization

Current `poll_response` fetches ALL messages in INBOX — O(n) per poll cycle.
With heavy Claude usage (50+ messages/session), this degrades.

**Mitigation:** Filter by Subject containing `req_id` prefix:
```python
m.search(None, "SUBJECT", req_id[:8])
```
Or use a dedicated IMAP folder `IoE-Claude` for proxy responses.

### 8. Error Handling

| Error | Proxy behavior |
|-------|---------------|
| IMAP connection failed | Retry 3x, then return 503 to CLI |
| VPS timeout (no response in 300s) | Return 504 to CLI |
| Anthropic API error (4xx/5xx) | Forward original status code + body to CLI |
| Decrypt failure | Log, skip, continue polling |
| gzip decompress failure | Return 502 to CLI |

## Files to Modify

| File | Change |
|------|--------|
| `client/claude_proxy.py` | **NEW.** Localhost HTTP proxy with IMAP transport |
| `server/server.py` | Add `handle_claude_proxy()` + dispatch entry |
| `server/crypto.py` | Add `compress_encrypt()` / `decrypt_decompress()` helpers |
| `start.sh` | Add claude_proxy launch option |
| `.env` | No changes (reuses existing IOE_SECRET, EMAIL, IMAP_PASSWORD) |

## Startup

```bash
# Terminal 1: WebUI (existing)
bash start.sh

# Terminal 2: Claude proxy
python client/claude_proxy.py

# Terminal 3: Claude Code
ANTHROPIC_BASE_URL=http://localhost:8090 claude
```

Or unified: `start.sh` gets a `--claude` flag that starts proxy in background.

## Testing Strategy

1. **Unit:** `tests/test_claude_proxy.py` — serialization/deserialization, gzip, timeout handling
2. **Integration:** Send a real Messages API request through the full chain (proxy → IMAP → VPS → API → back)
3. **Manual verification:** Run `ANTHROPIC_BASE_URL=http://localhost:8090 claude` and execute a simple task

## Pre-implementation Verification

**MUST verify before coding:**
1. Claude Code CLI works with `stream=false` responses (or if it always sends `stream=true`,
   verify VPS can collect SSE and return as non-streaming)
2. Claude Code CLI correctly uses `ANTHROPIC_BASE_URL` for ALL requests (not just Messages API)
3. Yandex Mail accepts ~1MB attachments without issues

## Known Limitations

- Latency: each API call adds ~5-15s IMAP round-trip overhead
- No streaming: user sees no output until full response arrives (can be 30-120s)
- Session with 50+ tool calls = 50+ IMAP round-trips = 4-12 minutes of overhead
- OAuth token refresh requires `console.anthropic.com` also tunneled
