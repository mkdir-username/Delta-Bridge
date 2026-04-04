"""IoE WebUI: local web-based browser over IoE transport."""
import os
import sys
import logging
import threading
import importlib
from http.server import HTTPServer

from crypto import derive_key

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
    "Отчёт за неделю", "Re: Протокол совещания", "ТЗ на доработку",
    "Коммерческое предложение", "Fw: Акт выполненных работ",
    "Re: Согласование бюджета", "Счёт на оплату", "Fw: Заявка на отпуск",
    "Служебная записка", "Re: План на квартал", "Табель учёта",
    "Fw: Приказ", "Заключение", "Re: Реестр документов",
    "Fw: Справка", "Протокол", "Re: Командировочное удостоверение",
    "Фото с дня рождения", "Re: Рецепт шарлотки", "Билеты на поезд",
    "Fw: Фотографии из отпуска", "Расписание тренировок",
    "Re: Адреса гостиниц", "Список покупок",
    "Заказ подтверждён", "Fw: Чек об оплате", "Статус доставки",
    "Re: Бронирование отеля", "Электронный билет",
    "Fw: Возврат товара", "Re: Трек-номер посылки", "Гарантийный талон",
    "Подтверждение регистрации", "Напоминание о записи",
    "Re: Уведомление", "Fw: Подтверждение оплаты",
    "Напоминание о встрече", "Re: Смена пароля",
    "Fw: Код подтверждения", "Уведомление о начислении",
    "Re: Квитанция", "Fw: Выписка по счёту",
    "Акт сверки", "Re: Дополнительное соглашение",
    "Fw: Техническое задание", "Накладная",
    "Re: График дежурств", "Fw: Инструкция",
    "Резюме", "Re: Приглашение на собеседование",
    "Fw: Результаты аттестации", "Расчётный лист",
]
FILENAMES = [
    "scan_001.pdf", "receipt.pdf", "document.pdf", "invoice.pdf",
    "report.pdf", "contract.pdf", "act.pdf", "photo.pdf",
    "statement.pdf", "form.pdf", "application.pdf", "letter.pdf",
    "schedule.pdf", "ticket.pdf", "confirmation.pdf", "order.pdf",
    "memo.pdf", "summary.pdf", "certificate.pdf", "reference.pdf",
]
BODIES = [
    "", "см. вложение", "Документ во вложении", "Пересылаю",
    "Как договаривались", "Подтверждение", "Во вложении",
    "Прошу ознакомиться", "К сведению", "Высылаю",
    "В приложении файл", "Документ", "Направляю",
    "По вашему запросу", "Для согласования",
]

DEMO_MODE = "--demo" in sys.argv

pending = {}
lock = threading.Lock()
notification_queues = {}

import hashlib as _hashlib
_device_seed = os.environ.get("IOE_DEVICE_ID", "") or "{}@{}".format(
    os.environ.get("USER", ""), __import__("socket").gethostname())
DEVICE_ID = _hashlib.sha256(_device_seed.encode()).hexdigest()[:4]

seen_notification_uids = set()

_ui_modules = [css, js_browser, js_telegram, js_claude, html_templates]


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
    global HTML_PAGE
    for mod in _ui_modules:
        importlib.reload(mod)
    HTML_PAGE = _build_html()
    return HTML_PAGE


HTML_PAGE = _build_html()


def main():
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
    print("IoE WebUI{}: http://localhost:{}".format(mode, port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
