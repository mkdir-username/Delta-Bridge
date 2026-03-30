# Delta-Bridge (IoE — Internet over Email)

IMAP-туннель для веб-трафика в ограниченных сетях. Клиент шифрует запрос AES-256-GCM, кладёт как PDF-аттач в IMAP-папку `IoE`, сервер забирает, исполняет, отвечает через INBOX.

## Threat Model — ЧИТАЙ ПЕРВЫМ

Проект работает в условиях государственной цензуры (РФ). Это определяет ВСЕ архитектурные решения.

- **Противник:** РКН + ТСПУ (DPI на всех магистралях) + ФСБ (доступ к данным российских сервисов) + ISP (логирование соединений)
- **Yandex Mail** = транспорт, НЕ доверенный сервис. Payload зашифрован E2E, Yandex видит только метаданные.
- **VPS** в Нидерландах (Амстердам). Ноль компонентов на российских серверах.
- **Цель:** Работать при whitelist-режиме (когда разрешён только email-протокол)

## Security Decision Rules — НЕ СПРАШИВАЙ, ВЫБИРАЙ

При выборе между вариантами реализации — ВСЕГДА выбирай более безопасный. Не предлагай "простой (без защиты)" как вариант.

| Развилка | ВСЕГДА выбирай | НИКОГДА не предлагай |
|----------|----------------|---------------------|
| С паролем / без пароля | С паролем | "Простой вариант без пароля" |
| Шифровать / не шифровать | Шифровать | "Можно без шифрования для простоты" |
| Хранить на сервере / на клиенте | На клиенте (если возможно) | "Храним credentials на VPS в plaintext" |
| Логировать / не логировать PII | Не логировать | "Запишем user_id в лог для отладки" |
| Российский сервис / зарубежный | Зарубежный (для хранения/обработки) | "Можно через Mail.ru — там проще API" |
| Plausible deniability / нет | С plausible deniability | "Назовём endpoint /vpn-bypass" |
| Минимум метаданных / больше метаданных | Минимум | "Добавим User-Agent с версией IoE" |
| Изоляция пользователей / shared state | Изоляция | "Общий session для всех пользователей" |

**Правило:** Если вопрос имеет очевидный ответ с точки зрения безопасности/анонимности — не спрашивай, делай. Спрашивай только когда trade-off неочевиден (производительность vs безопасность при конкретных ограничениях).

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

## Naming & Steganography

Всё что видно снаружи (email subjects, filenames, endpoint names, error messages) — должно выглядеть безобидно.

| Компонент | Правильно | Неправильно |
|-----------|-----------|-------------|
| Email subject | "Re: Встреча 4f8a2b1c" | "IoE Request #42" |
| Attachment | "report.pdf" | "encrypted_payload.bin" |
| Email body | "см. вложение" | "" (пустое = подозрительно) |
| Endpoint path | `/get?url=` | `/bypass-censorship?target=` |
| Error в логах | "decrypt failed, skipping" | "censorship bypass error" |
| Имя проекта в коде | Нейтральные имена функций | `class CensorshipBypass` |

## Config

`.env`: `EMAIL`, `IMAP_PASSWORD`, `IOE_SECRET`

## Anti-Patterns — НЕ ДЕЛАЙ

| ❌ Не делай | ✅ Делай вместо |
|------------|----------------|
| Предлагать варианты с разным уровнем безопасности | Выбирать безопасный вариант, объяснить trade-off если есть |
| Спрашивать "с паролем или без?" | Реализовывать с паролем |
| Хранить секреты в коде | `.env` + `os.environ` |
| Логировать содержимое запросов | Логировать только req_id, тип, статус, тайминг |
| Добавлять идентифицирующие заголовки | Минимальные generic headers |
| Называть вещи своими именами в коде | Нейтральная терминология |
| Спрашивать "нужна ли аутентификация?" | Аутентификация нужна всегда |
| Предлагать отправку данных на российские серверы | Все данные — только через зашифрованный канал на VPS в НЛ |