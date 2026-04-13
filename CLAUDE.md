## Bypass Infrastructure — Многослойная архитектура обхода

Delta-Bridge (IoE) — один слой из четырёх. Агент ОБЯЗАН понимать общую архитектуру чтобы не принимать решения в вакууме.

### Слои защиты (defense in depth)

| Слой | Инструмент | Когда работает | Когда ломается |
|------|-----------|---------------|----------------|
| L1 — DPI bypass | zapret2 / tpws | DPI блокирует протоколы, IP доступны | IP-блокировка, whitelist-режим |
| L2 — VPN tunnel | NaiveProxy (primary), VLESS+Reality (backup) | IP VPS доступен | VPS IP заблокирован, whitelist |
| L3 — CDN tunnel | VLESS+WS+TLS через Cloudflare | Cloudflare IP в whitelist | Cloudflare заблокирован (маловероятно) |
| L4 — Email tunnel | **Delta-Bridge (IoE)** | Только IMAP жив | IMAP к Yandex заблокирован |

**Правило:** Каждый слой автономен. Падение L2 не затрагивает L4. Решения в рамках одного слоя НЕ ДОЛЖНЫ создавать зависимость от другого.

### Текущая инфраструктура

| Компонент | Где | Адрес / Домен | Статус |
|-----------|-----|---------------|--------|
| Exit node (VPS) | Amsterdam, Cloudzy | 107.189.26.252 / gazorpazorp.xyz | ✅ Работает |
| Relay (domestic hop) | SPb, Beget | 155.212.218.50 | ✅ Работает |
| DNS + CDN | Cloudflare | gazorpazorp.xyz (orange cloud, Full strict) | ✅ Настроен |
| IMAP transport | Yandex Mail | (see .env) | ✅ Работает |
| DPI bypass | Телефон (Termux) | zapret2/tpws | ✅ Работает |
| NaiveProxy server | Amsterdam VPS | Caddy 2.11.2 + forwardproxy@naive :8443 | ✅ Работает |
| NaiveProxy client (desktop) | Локально | CLI naive v143 → :8443 | ✅ Работает |
| NaiveProxy client (Android) | Телефон | Exclave 0.17.30 + naive plugin v143 | ✅ Работает |
| VLESS+Reality (Android) | Телефон | AmneziaVPN / v2rayNG | ✅ Работает (backup) |
| CDN tunnel (Cloudflare) | — | VLESS+WS+TLS | ⏸ Pending recon |
| IoE Plan B | — | Dual-mailbox Yandex+Gmail | 💤 Dormant |

### Каскад подключения (клиент → интернет)

```
Телефон → [zapret2 DPI bypass] → Beget SPb (relay) → Amsterdam VPS → Internet
                                      ↑ внутренний трафик       ↑ невидим для оператора
```

Двухопный каскад: мобильный оператор видит подключение к российскому IP (Beget). Подключение к голландскому VPS происходит server-side, оператор его не видит.

## Android Proxy Client — Приоритеты и решения

### Почему NaiveProxy > VLESS+Reality

| Критерий | NaiveProxy | VLESS+Reality |
|----------|-----------|---------------|
| TLS fingerprint | **Настоящий** Chromium stack | Эмуляция Chrome (uTLS) |
| Active probing resistance | Caddy = реальный веб-сервер | Xray проксирует чужой TLS |
| IP↔SNI mismatch | Нет (свой домен) | google.com на не-google IP |
| Устойчивость при эскалации DPI | Высокая (нечего детектировать) | Средняя (эмуляция детектируема) |
| Текущий статус на ТСПУ | Проходит | Проходит |

**Вывод:** Оба работают сейчас. NaiveProxy устойчивее при эскалации. VLESS = backup, не мусор.

### Решение для Android: Exclave + naive plugin

**Стандартный sing-box for Android (SFA) НЕ включает naive outbound.** Требуется build tag `with_naive` + libcronet. Кастомная сборка нецелесообразна.

**Рабочий путь:**

| Шаг | Действие | Источник |
|-----|----------|---------|
| 1 | Установить Exclave (хост-приложение) | GitHub: `dyhkwong/Exclave/releases` или F-Droid |
| 2 | Установить NaïveProxy plugin APK | GitHub: `klzgrad/naiveproxy/releases` → `naiveproxy-plugin-*-arm64-v8a.apk` |
| 3 | Создать NaïveProxy профиль в Exclave | Server: `gazorpazorp.xyz:8443`, Protocol: HTTPS, auth: из Caddyfile |
| 4 | Проверить: заблокированный сайт открывается | — |

**Exclave** = форк SagerNet (dyhkwong), активно поддерживается (обновления еженедельно), F-Droid + GitHub releases, 1.6k stars. Плагин naive автоматически обнаруживается через `ACTION_NATIVE_PLUGIN` intent.

### Чего НЕ делать

| ❌ Не делай | ✅ Делай вместо | Почему |
|------------|----------------|--------|
| Собирать sing-box с naive из исходников | Использовать Exclave + plugin | Готовое решение, часы vs минуты |
| Писать naive-клиент с нуля | Upstream plugin = настоящий Chromium stack | Месяцы работы на воспроизведение существующего |
| Ломать VLESS конфиг | Держать VLESS параллельно | VLESS = рабочий backup |
| Трогать серверную сторону | Caddy + forwardproxy уже работает | Серверная сторона стабильна (Caddy 2.11.2, forwardproxy@naive) |
| Использовать SagerNet (оригинальный) | Только Exclave | SagerNet archived, не поддерживается |

### Целевая архитектура Android

```
Exclave (единое приложение)
  ├── NaiveProxy profile → gazorpazorp.xyz:8443 (PRIMARY) ✅
  ├── VLESS+Reality profile → gazorpazorp.xyz:443 (BACKUP) ✅
  └── Переключение вручную (один VPN активен)
```

Один клиент, два протокола.

### Caddy forwardproxy — критичные правила конфига

| Правило | Почему |
|---------|--------|
| `:PORT, domain.tld` в адресе серверного блока | Bare `:PORT` = catch-all для CONNECT к любым хостам. Без него forward_proxy не матчит CONNECT |
| `order forward_proxy before file_server` | Без этого file_server перехватывает CONNECT → 405 или пустой ответ |
| `admin off` | VPS без резолва localhost → Caddy падает при старте |
| Сборка: `xcaddy build --with ...forwardproxy=...klzgrad/forwardproxy@naive` | Стандартный forwardproxy НЕ поддерживает naive padding → `padding type: None` → не работает |

Текущий рабочий Caddyfile:
```
{
  admin off
  order forward_proxy before file_server
  http_port 80
  https_port 8443
}

:8443, gazorpazorp.xyz {
  forward_proxy {
    basic_auth user_0 PASSWORD
    hide_ip
    hide_via
    probe_resistance
  }
}
```

## Recon-First Principle

**НЕ строй инфраструктуру на непроверенных предположениях.**

| Компонент | Допущение | Статус верификации | Блокирует |
|-----------|-----------|-------------------|-----------|
| CDN tunnel | Cloudflare IP в whitelist при whitelist-режиме | ⏸ Ждёт `recon.sh` при следующем whitelist-event | Деплой VLESS+WS+TLS |
| IoE Plan B | Yandex начнёт блокировать иностранный IMAP | 💤 Мониторинг | Dual-mailbox migration |
| Exclave + naive | Plugin работает с текущим сервером | ✅ Верифицировано 2026-04-04 | — |

`recon.sh` — 8-фазный POSIX-скрипт, задеплоен на телефон через Termux. Запускать при whitelist-event для сбора данных о доступности Cloudflare/CDN IP.

## Regulatory Threat Monitor

### Аналитический фильтр (применять ВСЕГДА при оценке новостей)

| Сигнал | Интерпретация |
|--------|--------------|
| Тема в публичном дискурсе + официальное отрицание | Процесс запущен. "Не будет" = "объявим позже" |
| Несколько деловых изданий с "неподтверждённой информацией" | Контролируемая утечка / зондирование реакции |
| "Административная ответственность за обход" на совещаниях | Стадия Овертона: "приемлемо" → следующий шаг "разумно" (законопроект) |
| Лимит на международный трафик (>15GB) | Затрагивает L2 (VPN к VPS). НЕ затрагивает L4 (IMAP к Yandex = внутренний) |

### Оценка воздействия новых блокировок

При любой новости о блокировках — прогнать через таблицу:

| Слой | Вопрос | Если "да" — действие |
|------|--------|---------------------|
| L1 zapret2 | Новый DPI-паттерн ломает обход? | Обновить zapret2, проверить tpws конфиг |
| L2 NaiveProxy | VPS IP заблокирован? Протокол заблокирован? | Ротация IP или переход на CDN tunnel (L3) |
| L2 VLESS | Reality fingerprint детектируется? | Переход на NaiveProxy как primary |
| L3 CDN | Cloudflare IP заблокированы? | Активация IoE (L4) |
| L4 IoE | IMAP к Yandex заблокирован? | Активация Plan B (dual-mailbox) |

## Security Evaluation Checklist — Новые решения

При предложении ЛЮБОГО нового инструмента/протокола/подхода — обязательно:

- [ ] **Fingerprint:** Как выглядит на DPI? Отличимо от легитимного трафика?
- [ ] **Метаданные:** Что утекает? Кому?
- [ ] **Юрисдикция:** Где данные? Кто может запросить?
- [ ] **Блокируемость:** Насколько легко РКН заблокировать (IP, протокол, SNI)?
- [ ] **Plausible deniability:** Есть легитимное объяснение?
- [ ] **Распространяемость:** Можно дать нетехническому пользователю?
- [ ] **Resilience:** Что при отказе? Есть fallback?
- [ ] **Слепые зоны РКН:** Канал/протокол ниже порога мониторинга?

## Security Anti-Patterns — БЛОКЕРЫ

Из реальных инцидентов Delta-Bridge. Повторение = критический провал.

| Ситуация | ЗАПРЕЩЕНО | ОБЯЗАТЕЛЬНО | Инцидент |
|----------|-----------|-------------|----------|
| Unauthenticated endpoint (`/login/*`) | Возвращать secret, key, token, QR, provisioning URI | Только error/status/challenge | TOTP secret в JSON на `/login/email` — любой генерил валидный код |
| Provisioning (TOTP setup, user creation, token issuance) | Через WebUI login flow | Только CLI/SSH или authenticated admin-endpoint | `setup_totp` через WebUI = unauthenticated provisioning |
| Pending/intermediate secret | Отдавать client-side "для подтверждения" | Server-side only, secret НИКОГДА не покидает сервер | "Pending TOTP" отданный клиенту = leaked secret |

### Self-Review Checklist (ПЕРЕД коммитом auth-кода)

При изменении файлов с auth/session/crypto/password/token/secret/login/TOTP:

1. Новые endpoints: требуют auth? Если нет — что возвращают?
2. JSON-ответы: есть поля secret/key/token/password?
3. Цепочка атаки: "Я неаутентифицированный. Что получу за 3 HTTP-запроса?"
4. Утечки в транспорте: что видит Yandex (email metadata) / ISP / ТСПУ в этом flow?

### Security Decision Rules

| Развилка | Выбирай | Красный флаг (отвергай немедленно) |
|----------|---------|-------------------------------------|
| Provisioning через WebUI vs CLI | CLI (SSH) | "Добавим setup wizard в web-интерфейс" |
| Secret в HTTP response vs только на сервере | Только на сервере | "Отдадим secret клиенту для подтверждения" |
| Unauthenticated endpoint возвращает данные vs ошибку | Только ошибку | "Покажем QR-код на странице логина" |

При изменении auth/security кода — активируй skill `owasp-security` для полного чеклиста.