"""IoE WebUI: local web-based browser over IoE transport."""
import os
import sys
import logging
import threading
from http.server import HTTPServer

from crypto import derive_key

from css import CSS
from js_vendor import MARKED_JS
from js_browser import JS_BROWSER
from js_telegram import JS_TELEGRAM
from html_templates import HTML_TAB_BAR, HTML_BROWSER, HTML_TELEGRAM
from handler import Handler

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

HTML_PAGE = (
    r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IoE</title>
<style>
"""
    + CSS
    + """
</style>
<script>
"""
    + MARKED_JS
    + """
</script>
"""
    + HTML_TAB_BAR
    + HTML_BROWSER
    + HTML_TELEGRAM
    + """
<script>
"""
    + JS_BROWSER
    + JS_TELEGRAM
    + """
</script>
</body>
</html>"""
)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8080
    for i, arg in enumerate(sys.argv):
        if arg == "--demo" and i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
            port = int(sys.argv[i + 1])
            break
    from auth import load_whitelist, _whitelist
    load_whitelist()
    if not _whitelist:
        print("\n" + "=" * 60)
        print("WARNING: WHITELIST EMPTY — no users can log in!")
        print("Add phones to users.json and restart.")
        print("=" * 60 + "\n")
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
