"""IoE WebUI: local web-based browser over IoE transport."""

import os
import sys
import logging
import threading
import importlib
import webbrowser
from http.server import HTTPServer

import sys as _sys
import os as _os

_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".."))
from ioe_crypto import derive_key

import css
import js_vendor
import js_browser
import js_telegram
import js_claude
import html_templates
from handler import Handler

CSS = css.CSS
MARKED_JS = js_vendor.MARKED_JS
JS_BROWSER = js_browser.JS_BROWSER
JS_TELEGRAM = js_telegram.JS_TELEGRAM
JS_CLAUDE = js_claude.JS_CLAUDE
HTML_TAB_BAR = html_templates.HTML_TAB_BAR
HTML_BROWSER = html_templates.HTML_BROWSER
HTML_TELEGRAM = html_templates.HTML_TELEGRAM
HTML_CLAUDE = html_templates.HTML_CLAUDE

log = logging.getLogger("ioe-web")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

EMAIL = os.environ.get("EMAIL", "demo@example.com")
IMAP_PASSWORD = os.environ.get("IMAP_PASSWORD", "")
IOE_KEY = derive_key(os.environ.get("IOE_SECRET", "demo"))
IMAP_HOST = "imap.yandex.ru"
QUEUE_FOLDER = "IoE"

SUBJECTS = [
    "Отчёт за неделю",
    "Re: Протокол совещания",
    "ТЗ на доработку",
    "Коммерческое предложение",
    "Fw: Акт выполненных работ",
    "Re: Согласование бюджета",
    "Счёт на оплату",
    "Fw: Заявка на отпуск",
    "Служебная записка",
    "Re: План на квартал",
    "Табель учёта",
    "Fw: Приказ",
    "Заключение",
    "Re: Реестр документов",
    "Fw: Справка",
    "Протокол",
    "Re: Командировочное удостоверение",
    "Фото с дня рождения",
    "Re: Рецепт шарлотки",
    "Билеты на поезд",
    "Fw: Фотографии из отпуска",
    "Расписание тренировок",
    "Re: Адреса гостиниц",
    "Список покупок",
    "Заказ подтверждён",
    "Fw: Чек об оплате",
    "Статус доставки",
    "Re: Бронирование отеля",
    "Электронный билет",
    "Fw: Возврат товара",
    "Re: Трек-номер посылки",
    "Гарантийный талон",
    "Подтверждение регистрации",
    "Напоминание о записи",
    "Re: Уведомление",
    "Fw: Подтверждение оплаты",
    "Напоминание о встрече",
    "Re: Смена пароля",
    "Fw: Код подтверждения",
    "Уведомление о начислении",
    "Re: Квитанция",
    "Fw: Выписка по счёту",
    "Акт сверки",
    "Re: Дополнительное соглашение",
    "Fw: Техническое задание",
    "Накладная",
    "Re: График дежурств",
    "Fw: Инструкция",
    "Резюме",
    "Re: Приглашение на собеседование",
    "Fw: Результаты аттестации",
    "Расчётный лист",
]
FILENAMES = [
    "scan_001.pdf",
    "receipt.pdf",
    "document.pdf",
    "invoice.pdf",
    "report.pdf",
    "contract.pdf",
    "act.pdf",
    "photo.pdf",
    "statement.pdf",
    "form.pdf",
    "application.pdf",
    "letter.pdf",
    "schedule.pdf",
    "ticket.pdf",
    "confirmation.pdf",
    "order.pdf",
    "memo.pdf",
    "summary.pdf",
    "certificate.pdf",
    "reference.pdf",
]
BODIES = [
    "",
    "см. вложение",
    "Документ во вложении",
    "Пересылаю",
    "Как договаривались",
    "Подтверждение",
    "Во вложении",
    "Прошу ознакомиться",
    "К сведению",
    "Высылаю",
    "В приложении файл",
    "Документ",
    "Направляю",
    "По вашему запросу",
    "Для согласования",
]

DEMO_MODE = "--demo" in sys.argv

pending = {}
lock = threading.Lock()
notification_queues = {}

import hashlib as _hashlib

_device_seed = os.environ.get("IOE_DEVICE_ID", "") or "{}@{}".format(
    os.environ.get("USER", ""), __import__("socket").gethostname()
)
DEVICE_ID = _hashlib.sha256(_device_seed.encode()).hexdigest()[:4]

from collections import deque

seen_notification_uids: deque[str] = deque()
_seen_set: set[str] = set()
_SEEN_UIDS_MAX = 500
_NOTIF_QUEUE_MAX = 200
_PENDING_TTL = 600


def _trim_seen_uids() -> None:
    while len(_seen_set) > _SEEN_UIDS_MAX and seen_notification_uids:
        old = seen_notification_uids.popleft()
        _seen_set.discard(old)


def enqueue_notification(user_id: str, notif: dict) -> None:
    with lock:
        q = notification_queues.setdefault(user_id, [])
        q.append(notif)
        if len(q) > _NOTIF_QUEUE_MAX:
            del q[: len(q) - _NOTIF_QUEUE_MAX]


def _cleanup_pending() -> None:
    import time as _time

    cutoff = _time.time() - _PENDING_TTL
    with lock:
        stale = [k for k, v in pending.items() if v.get("_created", 0) < cutoff]
        for k in stale:
            del pending[k]


_ui_modules = [css, js_browser, js_telegram, js_claude, html_templates]


import hashlib as _hl
import base64 as _b64
import re as _re


def _inline_hashes(html: str, tag: str) -> list[str]:
    pattern = _re.compile(rf"<{tag}[^>]*>(.*?)</{tag}>", _re.DOTALL)
    result: list[str] = []
    for body in pattern.findall(html):
        digest = _hl.sha256(body.encode("utf-8")).digest()
        result.append("'sha256-" + _b64.b64encode(digest).decode("ascii") + "'")
    return result


SCRIPT_HASHES: list[str] = []
STYLE_HASHES: list[str] = []


def _build_html():
    return (
        r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IoE</title>
<style>
"""
        + css.CSS
        + """
</style>
<script>
"""
        + js_vendor.MARKED_JS
        + """
</script>
"""
        + html_templates.HTML_TAB_BAR
        + html_templates.HTML_BROWSER
        + html_templates.HTML_TELEGRAM
        + html_templates.HTML_CLAUDE
        + """
<script>
"""
        + js_browser.JS_BROWSER
        + js_telegram.JS_TELEGRAM
        + js_claude.JS_CLAUDE
        + """
</script>
</body>
</html>"""
    )


def rebuild_html():
    global HTML_PAGE, SCRIPT_HASHES, STYLE_HASHES
    for mod in _ui_modules:
        importlib.reload(mod)
    HTML_PAGE = _build_html()
    main_s = _inline_hashes(HTML_PAGE, "script")
    main_st = _inline_hashes(HTML_PAGE, "style")
    login_html = html_templates.login_page()
    login_s = _inline_hashes(login_html, "script")
    login_st = _inline_hashes(login_html, "style")
    SCRIPT_HASHES = list(dict.fromkeys(main_s + login_s))
    STYLE_HASHES = list(dict.fromkeys(main_st + login_st))
    return HTML_PAGE


HTML_PAGE = _build_html()
_main_script_h = _inline_hashes(HTML_PAGE, "script")
_main_style_h = _inline_hashes(HTML_PAGE, "style")
_login_html = html_templates.login_page()
_login_script_h = _inline_hashes(_login_html, "script")
_login_style_h = _inline_hashes(_login_html, "style")
SCRIPT_HASHES = list(dict.fromkeys(_main_script_h + _login_script_h))
STYLE_HASHES = list(dict.fromkeys(_main_style_h + _login_style_h))


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8080
    for i, arg in enumerate(sys.argv):
        if arg == "--demo" and i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
            port = int(sys.argv[i + 1])
            break
    import auth

    auth.load_whitelist()
    auth.init_sessions()
    if not auth._whitelist:
        print("\n" + "=" * 60)
        print("WARNING: WHITELIST EMPTY — no users can log in!")
        print("Add phones to users.json and restart.")
        print("=" * 60 + "\n")
    log.info("Device ID: %s", DEVICE_ID)
    HTTPServer.allow_reuse_address = True
    server = HTTPServer(("0.0.0.0", port), Handler)
    mode = " (demo)" if DEMO_MODE else ""
    url = f"http://localhost:{port}"
    print(f"IoE WebUI{mode}: {url}")
    threading.Timer(0.5, webbrowser.open, args=[url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
