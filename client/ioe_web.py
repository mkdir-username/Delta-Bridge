"""IoE WebUI: local web-based browser over IoE transport."""
import os
import sys
import json
import uuid
import time
import random
import imaplib
import email as email_mod
import threading
import re
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from crypto import derive_key, encrypt, decrypt

log = logging.getLogger("ioe-web")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

EMAIL = os.environ["EMAIL"]
IMAP_PASSWORD = os.environ["IMAP_PASSWORD"]
IOE_KEY = derive_key(os.environ["IOE_SECRET"])
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


def imap_conn():
    m = imaplib.IMAP4_SSL(IMAP_HOST, 993)
    m.login(EMAIL, IMAP_PASSWORD)
    return m


def send_request(m, request_dict):
    payload = json.dumps(request_dict)
    encrypted = encrypt(IOE_KEY, payload).encode("ascii")
    msg = MIMEMultipart()
    msg["Subject"] = "{} {}".format(random.choice(SUBJECTS), uuid.uuid4().hex[:8])
    msg["From"] = EMAIL
    msg["To"] = EMAIL
    msg.attach(MIMEText(random.choice(BODIES), "plain", "utf-8"))
    part = MIMEBase("application", "pdf")
    part.set_payload(encrypted)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment",
                    filename=random.choice(FILENAMES))
    msg.attach(part)
    m.append(QUEUE_FOLDER, None, None, msg.as_bytes())


def extract_attachment(raw):
    parsed = email_mod.message_from_bytes(raw)
    for part in parsed.walk():
        if part.get_content_disposition() == "attachment":
            return part.get_payload(decode=True)
    return None


def poll_response(req_id):
    t0 = time.time()
    try:
        log.info("[%s] poll: connecting IMAP...", req_id)
        m = imap_conn()
        log.info("[%s] poll: connected (%.1fs)", req_id, time.time() - t0)
        m.select("INBOX")
        seen_uids = set()
        for cycle in range(30):
            time.sleep(2)
            m.noop()
            _, msgs = m.search(None, "ALL")
            if not msgs[0]:
                continue
            uids = msgs[0].split()
            new_uids = [u for u in uids[-20:] if u not in seen_uids]
            if not new_uids and cycle > 0:
                continue
            for uid in reversed(new_uids):
                seen_uids.add(uid)
                _, data = m.fetch(uid, "(RFC822)")
                raw = data[0][1]
                if not isinstance(raw, bytes):
                    continue
                att = extract_attachment(raw)
                if att is None:
                    continue
                try:
                    decrypted = decrypt(IOE_KEY, att.decode("ascii").strip())
                    response = json.loads(decrypted)
                    rid = response.get("id", "")
                    if rid == req_id:
                        elapsed = time.time() - t0
                        log.info("[%s] poll: FOUND response (%.1fs, status=%s)", req_id, elapsed, response.get("status"))
                        with lock:
                            pending[req_id] = response
                        m.logout()
                        return
                except Exception as e:
                    log.debug("[%s] poll: decrypt/parse skip uid=%s: %s", req_id, uid, e)
                    continue
            if cycle % 5 == 4:
                log.debug("[%s] poll: cycle %d, %.0fs elapsed, %d uids checked", req_id, cycle, time.time() - t0, len(seen_uids))
        elapsed = time.time() - t0
        log.warning("[%s] poll: TIMEOUT after %.0fs", req_id, elapsed)
        with lock:
            pending[req_id] = {"id": req_id, "status": 504, "error": "timeout ({}s)".format(int(elapsed))}
        m.logout()
    except Exception as e:
        elapsed = time.time() - t0
        log.error("[%s] poll: ERROR after %.0fs: %s", req_id, elapsed, e)
        with lock:
            pending[req_id] = {"id": req_id, "status": 500, "error": str(e)}


def rewrite_links(html):
    html = re.sub(
        r'href="(https?://[^"]+)"',
        lambda m: 'href="/get?url={}"'.format(m.group(1)),
        html
    )
    html = re.sub(
        r"href='(https?://[^']+)'",
        lambda m: "href='/get?url={}'".format(m.group(1)),
        html
    )
    return html


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IoE</title>
<style>

/* === Reset & Base === */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #0e1117;
  --bg-surface: #161b22;
  --bg-hover: #1c2330;
  --border: #2a3140;
  --text: #c9d1d9;
  --text-muted: #7a8394;
  --text-dim: #545d6e;
  --accent: #58a6ff;
  --accent-dim: #1f3a5f;
  --link: #58a6ff;
  --link-visited: #a78bfa;
  --green: #3fb950;
  --orange: #d29922;
  --red: #f85149;
  --font-ui: 'SF Mono', 'Cascadia Code', 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  --font-read: 'Georgia', 'Charter', 'Bitstream Charter', 'Noto Serif', serif;
  --font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  --content-width: 720px;
  --toolbar-height: 52px;
  --footer-height: 28px;
}

html { 
  font-size: 16px;
  background: var(--bg);
  color: var(--text);
  height: 100%;
}

body {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  font-family: var(--font-sans);
  line-height: 1.5;
}

/* === Toolbar === */
.toolbar {
  position: sticky;
  top: 0;
  z-index: 100;
  height: var(--toolbar-height);
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 0 16px;
  gap: 8px;
}

.toolbar input[type="text"] {
  flex: 1;
  height: 34px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text);
  font-family: var(--font-ui);
  font-size: 13px;
  padding: 0 12px;
  outline: none;
  transition: border-color 0.15s;
}

.toolbar input[type="text"]:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-dim);
}

.toolbar input[type="text"]::placeholder {
  color: var(--text-dim);
}

.toolbar button {
  height: 34px;
  padding: 0 14px;
  background: var(--accent-dim);
  color: var(--accent);
  border: 1px solid var(--accent);
  border-radius: 6px;
  font-family: var(--font-ui);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s;
}

.toolbar button:hover {
  background: var(--accent);
  color: var(--bg);
}

.toolbar button:active {
  transform: scale(0.97);
}

/* === Main content area === */
main {
  flex: 1;
  padding: 24px 16px 40px;
  display: flex;
  flex-direction: column;
  align-items: center;
}

/* === Empty state === */
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  color: var(--text-dim);
  font-family: var(--font-ui);
  gap: 8px;
  user-select: none;
}

.empty .logo { font-size: 32px; opacity: 0.5; }
.empty .title { font-size: 15px; letter-spacing: 2px; text-transform: uppercase; }
.empty .sub { font-size: 11px; }

/* === Loading === */
.loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  gap: 12px;
  color: var(--text-muted);
  font-family: var(--font-ui);
  font-size: 13px;
}

.loading .spinner {
  width: 24px;
  height: 24px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.loading .timer { font-variant-numeric: tabular-nums; color: var(--text-dim); }

/* === Reader content === */
.reader {
  width: 100%;
  max-width: var(--content-width);
}

.reader-meta {
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
}

.reader-meta .source {
  font-family: var(--font-ui);
  font-size: 12px;
  color: var(--text-dim);
  margin-bottom: 4px;
}

.reader-meta .source a {
  color: var(--green);
  text-decoration: none;
}

.reader-meta h1 {
  font-family: var(--font-read);
  font-size: 28px;
  font-weight: 700;
  line-height: 1.3;
  color: var(--text);
  margin: 8px 0 0;
}

/* Article body — reader-mode typography */
.reader-body {
  font-family: var(--font-read);
  font-size: 18px;
  line-height: 1.75;
  color: var(--text);
  word-wrap: break-word;
  overflow-wrap: break-word;
}

.reader-body p {
  margin-bottom: 1.2em;
}

.reader-body h1, .reader-body h2, .reader-body h3,
.reader-body h4, .reader-body h5, .reader-body h6 {
  font-family: var(--font-sans);
  color: var(--text);
  margin-top: 1.8em;
  margin-bottom: 0.6em;
  line-height: 1.3;
}

.reader-body h2 { font-size: 22px; }
.reader-body h3 { font-size: 19px; }

.reader-body a {
  color: var(--link);
  text-decoration: underline;
  text-decoration-color: var(--accent-dim);
  text-underline-offset: 3px;
  transition: text-decoration-color 0.15s;
}

.reader-body a:visited { color: var(--link-visited); }
.reader-body a:hover { text-decoration-color: var(--accent); }

.reader-body img {
  max-width: 100%;
  height: auto;
  border-radius: 6px;
  margin: 16px 0;
}

.reader-body ul, .reader-body ol {
  padding-left: 1.5em;
  margin-bottom: 1.2em;
}

.reader-body li { margin-bottom: 0.4em; }

.reader-body blockquote {
  border-left: 3px solid var(--accent-dim);
  padding: 4px 0 4px 16px;
  color: var(--text-muted);
  margin: 1em 0;
  font-style: italic;
}

.reader-body pre, .reader-body code {
  font-family: var(--font-ui);
  font-size: 14px;
  background: var(--bg-surface);
  border-radius: 4px;
}

.reader-body code { padding: 2px 6px; }

.reader-body pre {
  padding: 12px 16px;
  overflow-x: auto;
  margin: 1em 0;
}

.reader-body table {
  width: 100%;
  border-collapse: collapse;
  margin: 1em 0;
  font-size: 15px;
}

.reader-body th, .reader-body td {
  padding: 8px 12px;
  border: 1px solid var(--border);
  text-align: left;
}

.reader-body th {
  background: var(--bg-surface);
  font-weight: 600;
}

.reader-body hr {
  border: none;
  border-top: 1px solid var(--border);
  margin: 2em 0;
}

/* === Search results === */
.search-results {
  width: 100%;
  max-width: var(--content-width);
}

.search-results .query-info {
  font-family: var(--font-ui);
  font-size: 12px;
  color: var(--text-dim);
  margin-bottom: 20px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}

.result-card {
  padding: 16px 0;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background 0.1s;
}

.result-card:hover {
  background: var(--bg-hover);
  margin: 0 -12px;
  padding: 16px 12px;
  border-radius: 6px;
}

.result-card .url {
  font-family: var(--font-ui);
  font-size: 12px;
  color: var(--green);
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.result-card .title {
  font-family: var(--font-sans);
  font-size: 17px;
  font-weight: 600;
  color: var(--accent);
  margin-bottom: 6px;
  line-height: 1.3;
}

.result-card .snippet {
  font-family: var(--font-sans);
  font-size: 14px;
  color: var(--text-muted);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* === Raw page content (non-reader) === */
.raw-content {
  width: 100%;
  max-width: var(--content-width);
  font-family: var(--font-sans);
  font-size: 15px;
  line-height: 1.7;
  color: var(--text);
  white-space: pre-wrap;
  word-wrap: break-word;
}

/* === Footer / status bar === */
footer {
  position: sticky;
  bottom: 0;
  height: var(--footer-height);
  background: var(--bg-surface);
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  font-family: var(--font-ui);
  font-size: 11px;
  color: var(--text-dim);
  z-index: 100;
}

footer .status { display: flex; align-items: center; gap: 6px; }
footer .status .dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--green);
}

footer .channel { color: var(--text-dim); }

/* === Back button === */
.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--font-ui);
  font-size: 12px;
  color: var(--accent);
  cursor: pointer;
  background: none;
  border: none;
  padding: 4px 0;
  margin-bottom: 12px;
}

.back-btn:hover { text-decoration: underline; }

/* === Content formatting helper (for text without paragraphs) === */
.auto-format {
  font-family: var(--font-read);
  font-size: 18px;
  line-height: 1.75;
  max-width: var(--content-width);
  width: 100%;
}

/* === Scroll to top === */
.scroll-top {
  position: fixed;
  bottom: 44px;
  right: 20px;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  color: var(--text-muted);
  cursor: pointer;
  display: none;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  z-index: 90;
  transition: all 0.15s;
}

.scroll-top:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.scroll-top.visible { display: flex; }

/* === Responsive === */
@media (max-width: 768px) {
  :root {
    --content-width: 100%;
  }
  
  .reader-body { font-size: 16px; }
  .reader-meta h1 { font-size: 22px; }
  
  main { padding: 16px 12px 32px; }
}

@media (min-width: 1200px) {
  :root {
    --content-width: 760px;
  }
}

</style>
<script src="https://cdn.jsdelivr.net/npm/marked@15/marked.min.js"></script>
</head>
<body>

<div class="toolbar">
  <input type="text" id="url" placeholder="URL или поисковый запрос..."
         autocomplete="off" autocapitalize="off" spellcheck="false" value="">
  <button id="btnGo" onclick="go()">&rarr;</button>
</div>

<main id="content">
  <div class="empty">
    <div class="logo">&#9889;</div>
    <div class="title">IoE</div>
    <div class="sub">internet over email</div>
  </div>
</main>

<button class="scroll-top" id="scrollTop" onclick="window.scrollTo({top:0,behavior:'smooth'})">&uarr;</button>

<footer>
  <div class="status">
    <span class="dot"></span>
    <span id="statusText">Ready</span>
  </div>
  <span class="channel" id="channelInfo">IMAP</span>
</footer>

<script>
var busy = false, pollTimer = null, loadTimer = null, t0 = 0;
var lastResults = null;

function $(id) { return document.getElementById(id); }
var urlInput = $('url');
var content = $('content');

window.addEventListener('scroll', function() {
  $('scrollTop').classList.toggle('visible', window.scrollY > 400);
});

urlInput.addEventListener('keydown', function(e) {
  if (e.key === 'Enter') { e.preventDefault(); go(); }
});

function go() {
  if (busy) return;
  var q = urlInput.value.trim();
  if (!q) { urlInput.focus(); return; }
  var isUrl = (q.indexOf('.') > -1 && q.indexOf(' ') === -1) || q.indexOf('http') === 0;
  if (isUrl) {
    var url = q.indexOf('http') === 0 ? q : 'https://' + q;
    openPage(url);
  } else {
    doSearch(q);
  }
}

function setStatus(text, type) {
  $('statusText').textContent = text;
  var dot = document.querySelector('.status .dot');
  dot.style.background = type === 'error' ? 'var(--red)' : type === 'loading' ? 'var(--orange)' : 'var(--green)';
}

function showLoading(msg) {
  busy = true;
  $('btnGo').disabled = true;
  t0 = Date.now();
  setStatus('Loading...', 'loading');
  content.innerHTML = '<div class="loading"><div class="spinner"></div><div>' + escHtml(msg) + '</div><div class="timer" id="loadTimer">0.0s</div></div>';
  loadTimer = setInterval(function() {
    var el = $('loadTimer');
    if (el) el.textContent = ((Date.now() - t0) / 1000).toFixed(1) + 's';
  }, 100);
}

function doneLoading() {
  busy = false;
  $('btnGo').disabled = false;
  clearInterval(loadTimer);
  clearInterval(pollTimer);
  var sec = ((Date.now() - t0) / 1000).toFixed(1);
  setStatus('\u2713 ' + sec + 's', 'ok');
}

function showError(msg) {
  doneLoading();
  setStatus('Error', 'error');
  content.innerHTML = '<div class="loading" style="color:var(--red)">' + escHtml(msg) + '</div>';
}

function doSearch(query) {
  showLoading('\u0418\u0449\u0443 \u0447\u0435\u0440\u0435\u0437 IMAP...');
  fetch('/search?q=' + encodeURIComponent(query))
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (d.error) { showError(d.error); return; }
      if (d.status === 'pending') {
        startPoll(d.id, function(resp) { renderResults(query, resp.results || []); });
      } else if (d.results) {
        renderResults(query, d.results);
        doneLoading();
      }
    })
    .catch(function(e) { showError(String(e)); });
}

function openPage(url) {
  showLoading('\u0417\u0430\u0433\u0440\u0443\u0436\u0430\u044e...');
  urlInput.value = url;
  fetch('/get?url=' + encodeURIComponent(url))
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (d.error) { showError(d.error); return; }
      if (d.status === 'pending') {
        startPoll(d.id, function(resp) { showReader(url, resp); });
      } else {
        showReader(url, d);
        doneLoading();
      }
    })
    .catch(function(e) { showError(String(e)); });
}

function startPoll(id, callback) {
  var pollStart = Date.now();
  pollTimer = setInterval(function() {
    if ((Date.now() - pollStart) > 90000) {
      showError('\u0422\u0430\u0439\u043c\u0430\u0443\u0442 90\u0441\u0435\u043a');
      return;
    }
    fetch('/status?id=' + id)
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d.status !== 'pending') {
          if (d.error) { showError(d.error); return; }
          callback(d);
          doneLoading();
        }
      });
  }, 2000);
}

function renderResults(query, results) {
  lastResults = { query: query, results: results };
  var elapsed = ((Date.now() - t0) / 1000).toFixed(1);
  var h = '<div class="search-results">';
  h += '<div class="query-info">' + results.length + ' \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u043e\u0432 \u00b7 \u00ab' + escHtml(query) + '\u00bb \u00b7 ' + elapsed + 's</div>';
  for (var i = 0; i < results.length; i++) {
    var r = results[i];
    h += '<div class="result-card" data-url="' + escAttr(r.href || r.url || '') + '">' +
      '<div class="url">' + escHtml(r.href || r.url || '') + '</div>' +
      '<div class="title">' + escHtml(r.title) + '</div>' +
      '<div class="snippet">' + escHtml(r.snippet) + '</div>' +
      '</div>';
  }
  h += '</div>';
  content.innerHTML = h;
  urlInput.value = query;
  window.scrollTo(0, 0);
}

function showReader(url, data) {
  var title = data.title || '';
  var body = data.body || '';
  var fmt = data.format || '';
  var elapsed = ((Date.now() - t0) / 1000).toFixed(1);
  var domain = '';
  try { domain = new URL(url).hostname; } catch(e) { domain = url; }
  var backHtml = lastResults
    ? '<button class="back-btn" onclick="renderResults(\'' + escAttr(lastResults.query) + '\', lastResults.results)">\u2190 \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u044b</button>'
    : '<button class="back-btn" onclick="history.back()">\u2190 \u043d\u0430\u0437\u0430\u0434</button>';

  var bodyContent;
  if (fmt === 'markdown' && typeof marked !== 'undefined') {
    bodyContent = marked.parse(body);
  } else if (body.indexOf('<') > -1 && body.indexOf('>') > -1) {
    bodyContent = body;
  } else {
    bodyContent = formatRawText(body);
  }

  content.innerHTML = '<div class="reader">' + backHtml +
    '<div class="reader-meta"><div class="source">' + escHtml(domain) + ' \u00b7 ' + elapsed + 's</div>' +
    (title ? '<h1>' + escHtml(title) + '</h1>' : '') +
    '</div><div class="reader-body" id="readerBody"></div></div>';

  $('readerBody').innerHTML = bodyContent;

  $('readerBody').querySelectorAll('a[href]').forEach(function(a) {
    var href = a.getAttribute('href');
    if (href && (href.indexOf('http://') === 0 || href.indexOf('https://') === 0)) {
      a.setAttribute('data-ioe-url', href);
      a.setAttribute('href', 'javascript:void(0)');
      a.style.color = 'var(--link)';
      a.style.cursor = 'pointer';
    }
  });

  urlInput.value = url;
  window.scrollTo(0, 0);
}

function formatRawText(text) {
  if (!text || !text.trim()) return '';
  var paragraphs = text.split(/\n\s*\n/);
  if (paragraphs.length <= 1) {
    var lines = text.split('\n');
    paragraphs = [];
    var current = '';
    for (var i = 0; i < lines.length; i++) {
      var trimmed = lines[i].trim();
      if (!trimmed) {
        if (current) { paragraphs.push(current); current = ''; }
        continue;
      }
      if (current && /[.!?\u00bb"']\s*$/.test(current) && /^[A-Z\u0410-\u042f\u0401\u00ab"']/.test(trimmed)) {
        paragraphs.push(current);
        current = trimmed;
      } else {
        current += (current ? ' ' : '') + trimmed;
      }
    }
    if (current) paragraphs.push(current);
  }
  return paragraphs
    .map(function(p) { return p.trim(); })
    .filter(function(p) { return p.length > 0; })
    .map(function(p) { return '<p>' + escHtml(p) + '</p>'; })
    .join('\n');
}

function escHtml(s) {
  if (!s) return '';
  var d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function escAttr(s) {
  return escHtml(s).replace(/'/g, "\\'");
}

content.addEventListener('click', function(e) {
  var card = e.target.closest('.result-card[data-url]');
  if (card) {
    if (e.metaKey || e.ctrlKey) {
      window.open(card.getAttribute('data-url'), '_blank');
      return;
    }
    e.preventDefault();
    openPage(card.getAttribute('data-url'));
    return;
  }
  var link = e.target.closest('a[data-ioe-url]');
  if (link) {
    if (e.metaKey || e.ctrlKey) {
      window.open(link.getAttribute('data-ioe-url'), '_blank');
      return;
    }
    e.preventDefault();
    openPage(link.getAttribute('data-ioe-url'));
  }
});

urlInput.focus();
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def respond_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_demo(self, cmd, qs, req_id):
        if cmd == "SEARCH":
            q = qs.get("q", [""])[0]
            results = [
                {"title": "\u041f\u043e\u0433\u043e\u0434\u0430 \u0432 \u0421\u0430\u043d\u043a\u0442-\u041f\u0435\u0442\u0435\u0440\u0431\u0443\u0440\u0433\u0435 \u2014 \u042f\u043d\u0434\u0435\u043a\u0441", "href": "https://yandex.ru/pogoda/saint-petersburg", "snippet": "\u0421\u0435\u0433\u043e\u0434\u043d\u044f +4\u00b0, \u043e\u0431\u043b\u0430\u0447\u043d\u043e. \u0417\u0430\u0432\u0442\u0440\u0430 +6\u00b0, \u0432\u043e\u0437\u043c\u043e\u0436\u0435\u043d \u0434\u043e\u0436\u0434\u044c."},
                {"title": "\u041f\u043e\u0433\u043e\u0434\u0430 \u0421\u041f\u0431 \u2014 Gismeteo", "href": "https://www.gismeteo.ru/weather-saint-petersburg/", "snippet": "\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u044b\u0439 \u043f\u0440\u043e\u0433\u043d\u043e\u0437 \u043f\u043e\u0433\u043e\u0434\u044b \u043d\u0430 \u0441\u0435\u0433\u043e\u0434\u043d\u044f, \u0437\u0430\u0432\u0442\u0440\u0430, \u043d\u0435\u0434\u0435\u043b\u044e."},
                {"title": "\u041f\u043e\u0433\u043e\u0434\u0430 \u0432 \u041f\u0438\u0442\u0435\u0440\u0435 \u0441\u0435\u0439\u0447\u0430\u0441 \u2014 rp5.ru", "href": "https://rp5.ru/spb", "snippet": "\u0422\u0435\u043a\u0443\u0449\u0430\u044f \u0442\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 +3\u00b0C, \u0432\u0435\u0442\u0435\u0440 5 \u043c/\u0441, \u0432\u043b\u0430\u0436\u043d\u043e\u0441\u0442\u044c 78%."},
                {"title": "\u041a\u043b\u0438\u043c\u0430\u0442 \u0421\u0430\u043d\u043a\u0442-\u041f\u0435\u0442\u0435\u0440\u0431\u0443\u0440\u0433\u0430 \u2014 \u0412\u0438\u043a\u0438\u043f\u0435\u0434\u0438\u044f", "href": "https://ru.wikipedia.org/wiki/Климат_Санкт-Петербурга", "snippet": "\u041a\u043b\u0438\u043c\u0430\u0442 \u0443\u043c\u0435\u0440\u0435\u043d\u043d\u044b\u0439. \u0421\u0440\u0435\u0434\u043d\u044f\u044f \u0442\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 \u043c\u0430\u0440\u0442\u0430 \u2212\u2060\u0031\u2026+4\u00b0C."},
            ]
            self.respond_json({"status": "ready", "results": results})
        elif cmd in ("GET", "TEXT"):
            url = qs.get("url", [""])[0]
            self.respond_json({
                "status": "ready",
                "title": "\u041f\u043e\u0433\u043e\u0434\u0430 \u0432 \u0421\u0430\u043d\u043a\u0442-\u041f\u0435\u0442\u0435\u0440\u0431\u0443\u0440\u0433\u0435 \u043d\u0430 \u0441\u0435\u0433\u043e\u0434\u043d\u044f",
                "body": "# \u041f\u043e\u0433\u043e\u0434\u0430\n\n\u0421\u0435\u0433\u043e\u0434\u043d\u044f +5\u00b0C, \u043e\u0431\u043b\u0430\u0447\u043d\u043e.\n\n## \u041f\u0440\u043e\u0433\u043d\u043e\u0437\n\n- \u041f\u043d +4\u00b0 \u0434\u043e\u0436\u0434\u044c\n- \u0412\u0442 +6\u00b0 \u043e\u0431\u043b\u0430\u0447\u043d\u043e\n- \u0421\u0440 +7\u00b0 \u0441\u043e\u043b\u043d\u0435\u0447\u043d\u043e",
                "format": "markdown",
            })
        else:
            self.respond_json({"status": "error", "error": "unknown cmd"})

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path == "/":
            body = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/status":
            req_id = qs.get("id", [""])[0]
            with lock:
                if req_id in pending:
                    resp = pending.pop(req_id)
                    if resp.get("status") == 200:
                        result = {"status": "ready"}
                        if "results" in resp:
                            result["results"] = resp["results"]
                        else:
                            result["title"] = resp.get("title", "")
                            result["body"] = resp.get("body", "")
                            result["format"] = resp.get("format", "html")
                        self.respond_json(result)
                    else:
                        self.respond_json({
                            "status": "error",
                            "error": resp.get("error", "unknown"),
                        })
                    return
            self.respond_json({"status": "pending"})
            return

        if parsed.path in ("/get", "/text", "/search"):
            req_id = uuid.uuid4().hex[:8]
            cmd = parsed.path.lstrip("/").upper()

            if DEMO_MODE:
                self._handle_demo(cmd, qs, req_id)
                return

            if cmd == "SEARCH":
                q = qs.get("q", [""])[0]
                req = {"id": req_id, "cmd": "SEARCH", "query": q}
            else:
                url = qs.get("url", [""])[0]
                req = {"id": req_id, "cmd": cmd, "url": url}
            try:
                t0 = time.time()
                log.info("[%s] send: %s %s", req_id, cmd, req.get("query", req.get("url", "")))
                m = imap_conn()
                send_request(m, req)
                m.logout()
                log.info("[%s] send: done (%.1fs)", req_id, time.time() - t0)
            except Exception as e:
                log.error("[%s] send: FAILED: %s", req_id, e)
                self.respond_json({"status": "error", "error": str(e)})
                return
            t = threading.Thread(target=poll_response, args=(req_id,), daemon=True)
            t.start()
            self.respond_json({"id": req_id, "status": "pending"})
            return

        self.send_error(404)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8080
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
