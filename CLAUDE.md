# Delta-Bridge (IoE — Internet over Email)

IMAP-туннель для веб-трафика в ограниченных сетях. Клиент шифрует запрос AES-256-GCM, кладёт как PDF-аттач в IMAP-папку `IoE`, сервер забирает, исполняет, отвечает через INBOX.

## Stack

Python 3, без фреймворков. Фронтенд — Python string literals (CSS/JS/HTML), сборки нет.

| Зависимость | Роль |
|-------------|------|
| imapclient / imaplib | IMAP транспорт |
| pycryptodome | AES-256-GCM |
| playwright | Headless Chromium (server) |
| telethon | Telegram MTProto (server) |
| requests | HTTP проксирование |
| beautifulsoup4 / trafilatura / readability | Извлечение контента |
| duckduckgo-search | Веб-поиск |

## Structure

```
server/
  server.py              # VPS daemon — IMAP poll + dispatch_request()
  browser_handler.py     # Playwright BrowserPool, 6 browser actions
  telegram_adapter.py    # Telethon multi-user Telegram
  crypto.py              # AES-256-GCM (canonical source)
client/
  client.py              # CLI: get/text/search/update
  kit_runner.py          # JSON-рецепты (Service Kits)
  ioe_web.py             # Legacy WebUI (deprecated → webui/)
  crypto.py
webui/
  ioe_web.py             # Entry: HTTPServer :8080
  handler.py             # HTTP routes (do_GET)
  transport.py           # IMAP send/poll
  html_templates.py      # HTML (табы, панели)
  css.py                 # CSS
  js_browser.py          # JS браузер-таба
  js_telegram.py         # JS Telegram-таба
  js_vendor.py           # Bundled marked.js
  crypto.py
kits/
  hackernews.json        # HN recipe
  _template_auth.json    # Шаблон auth-рецепта
tests/                   # pytest
docs/
  SERVICE_KIT_SPEC.md    # Спека JSON-рецептов
```

## Commands

| Команда | Назначение |
|---------|-----------|
| `bash start.sh` | Запуск WebUI |
| `python server/server.py` | Серверный daemon |
| `python client/client.py get <url>` | CLI fetch |
| `pytest tests/` | Тесты |

## Entry Points

| Точка входа | Файл | Функция |
|-------------|------|---------|
| Server daemon | `server/server.py` | `main()` |
| WebUI | `webui/ioe_web.py` | `main()` |
| CLI | `client/client.py` | `main()` |
| Request dispatch | `server/server.py` | `dispatch_request()` |
| HTTP routing | `webui/handler.py` | `do_GET()` |
| Kit execution | `client/kit_runner.py` | `KitRunner.run()` |

## HTTP Routes (webui/handler.py)

| Route | Назначение |
|-------|-----------|
| `GET /` | SPA |
| `GET /status?id=` | Poll pending response |
| `GET /get?url=` | Reader mode fetch |
| `GET /text?url=` | Plain text fetch |
| `GET /search?q=` | DuckDuckGo search |
| `GET /proxy?method=&url=&body=` | Raw HTTP proxy |
| `GET /tg?action=` | Telegram relay |
| `GET /browser?url=` | Headless browser |
| `GET /notifications` | Telegram push queue |
| `GET /kit?kit=` | List kits |

## Request Types (server/server.py)

| type/cmd | Handler |
|----------|---------|
| `type=http` | `handle_http_proxy()` |
| `type=browser` | `handle_browser_request()` (Playwright) |
| `type=command, service=telegram` | `TelegramAdapter.handle()` |
| `type=session_start/end` | requests.Session management |
| `cmd=SEARCH` | `do_search()` (DuckDuckGo) |
| `cmd=TEXT` | Plain text fetch |
| `cmd=GET` | `smart_extract()` (trafilatura → BS4) |
| `cmd=UPDATE` | Self-update |

## Architecture

- Async message queue over IMAP — нет прямого TCP между клиентом и сервером
- Все write-endpoints async: возвращают `{"id", "status": "pending"}`, фронт поллит `/status`
- Threading: `pending` dict + `threading.Lock`
- crypto.py дублируется в server/, client/, webui/, tests/ — идентичный код

## Coder Navigation

| Задача | Куда |
|--------|------|
| Новый HTTP endpoint | `webui/handler.py` → `do_GET()` |
| Новая серверная команда | `server/server.py` → `dispatch_request()` |
| Browser action | `server/browser_handler.py` → `handle_browser_request()` |
| Telegram функция | `server/telegram_adapter.py` → `handle()` |
| Новый Service Kit | `kits/*.json` по `docs/SERVICE_KIT_SPEC.md` |
| UI таб/компонент | `webui/html_templates.py` + `webui/js_*.py` + `webui/css.py` |
| Шифрование | `server/crypto.py` (canonical) |
| Тесты | `tests/test_*.py` |

## Config

`.env`: `EMAIL`, `IMAP_PASSWORD`, `IOE_SECRET`
