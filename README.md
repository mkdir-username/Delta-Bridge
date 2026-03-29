# Delta-Bridge (IoE)

Internet-over-Email tunnel. Browse the web through IMAP email transport — designed for networks with whitelist-only access where only email protocols are allowed.

## Quick Start

```bash
git clone https://github.com/mkdir-username/Delta-Bridge.git
cd Delta-Bridge
./setup.sh   # install deps, create .env, add 'ioe' alias
./start.sh   # open http://localhost:8080
```

After setup, just type `ioe` anywhere to launch.

## Architecture

```
[Browser] → [WebUI :8080] → IMAP APPEND → [VPS Server] → fetch URL → IMAP APPEND → [WebUI polls] → [Browser]
     localhost                  IoE folder                                              INBOX
```

## Components

### `server/` — VPS server (systemd service)
- `server.py` — IMAP IDLE monitor, fetches URLs via markdown.new (fallback: readability-lxml), DuckDuckGo search
- `crypto.py` — AES-256-GCM encryption (pycryptodome on Termux, cryptography on VPS)

### `client/` — Termux CLI + WebUI
- `client.py` — CLI: `python client.py search <query>`, `python client.py get <url>`, `python client.py update`
- `ioe_web.py` — local HTTP server with browser UI on `localhost:8080`
- `crypto.py` — shared encryption module

### `webui/` — standalone WebUI (same as client/ioe_web.py)
- `ioe_web.py` — run on any machine with Python 3 + pycryptodome

### `tests/` — pytest suite
- `test_ioe_server.py` — server: search format, markdown.new + fallback
- `test_ioe_web.py` — webui: design, endpoints, demo mode, marked.js

## Setup

### VPS
```bash
pip install imapclient requests readability-lxml beautifulsoup4 Pillow pycryptodome duckduckgo-search truststore
cp server/* /opt/ioe/
# Configure .env: EMAIL, IMAP_PASSWORD, IOE_SECRET
systemctl start ioe-server
```

### Client (Termux / macOS)
```bash
pip install pycryptodome imapclient beautifulsoup4
# Configure .ioe.env: EMAIL, IMAP_PASSWORD, IOE_SECRET
source .ioe.env && export EMAIL IMAP_PASSWORD IOE_SECRET
python ioe_web.py  # opens on :8080
```

### Demo mode (no IMAP needed)
```bash
EMAIL=x IMAP_PASSWORD=x IOE_SECRET=x python ioe_web.py 8090 --demo
```

## Tests
```bash
cd tests && python -m pytest -v
```

## Features
- DuckDuckGo search with structured results
- Reader mode via markdown.new (fallback: readability-lxml)
- marked.js client-side markdown rendering
- Auto-paragraph formatting for raw text
- Cmd+Click opens original URL in new tab
- IMAP IDLE with 5s check interval
- Debug logging with timestamps
- Self-update via `client.py update`
