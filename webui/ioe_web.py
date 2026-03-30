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
    "Re: Встреча", "Fw: Документы", "Отчёт", "Заказ",
    "Фото", "Бронирование", "Напоминание", "Чек",
]
FILENAMES = ["report.pdf", "scan.pdf", "doc.pdf", "invoice.pdf"]
BODIES = ["", "см. вложение", "Документ"]

DEMO_MODE = "--demo" in sys.argv

pending = {}
lock = threading.Lock()

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
