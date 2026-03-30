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
                if not data or not data[0] or data[0] is None:
                    continue
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
  padding-bottom: var(--footer-height);
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
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
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

/* === Tab bar === */
.tab-bar { display:flex; gap:0; background:var(--bg-surface); border-bottom:1px solid var(--border); }
.tab-bar button { background:none; border:none; color:var(--text-muted); padding:8px 16px; cursor:pointer; font-size:14px; font-family:var(--font-ui); }
.tab-bar button.active { color:var(--text); border-bottom:2px solid var(--accent); }

/* === Telegram === */
.tg-layout { display:flex; height:calc(100vh - 38px); }
.tg-sidebar { width:30%; min-width:220px; max-width:320px; border-right:1px solid var(--border); display:flex; flex-direction:column; flex-shrink:0; }
.tg-sidebar-top { padding:8px; border-bottom:1px solid var(--border); }
.tg-search { width:100%; padding:8px 10px; background:var(--bg); border:1px solid var(--border); color:var(--text); border-radius:6px; font-family:var(--font-ui); font-size:13px; outline:none; box-sizing:border-box; }
.tg-search:focus { border-color:var(--accent); }
.tg-search::placeholder { color:var(--text-dim); }
.tg-folders { display:flex; gap:0; border-bottom:1px solid var(--border); overflow-x:auto; scrollbar-width:none; }
.tg-folders::-webkit-scrollbar { display:none; }
.tg-folder { padding:8px 12px; font-size:12px; color:var(--text-muted); cursor:pointer; white-space:nowrap; border-bottom:2px solid transparent; background:none; border-top:none; border-left:none; border-right:none; font-family:var(--font-ui); }
.tg-folder:hover { color:var(--text); }
.tg-folder.active { color:var(--accent); border-bottom-color:var(--accent); }
.tg-folder .tg-folder-badge { background:var(--accent); color:#fff; border-radius:8px; padding:0 5px; font-size:10px; margin-left:4px; }
.tg-chatlist { flex:1; overflow-y:auto; display:flex; flex-direction:column; }
.tg-main { flex:1; display:flex; flex-direction:column; min-width:0; }
.tg-header { padding:12px; font-weight:bold; border-bottom:1px solid var(--border); display:flex; align-items:center; justify-content:space-between; }
.tg-messages { flex:1; overflow-y:auto; overflow-x:hidden; padding:12px 16px; min-width:0; display:flex; flex-direction:column; gap:2px; }
.tg-compose { display:flex; padding:8px; gap:8px; border-top:1px solid var(--border); flex-shrink:0; }
.tg-compose input { flex:1; padding:8px; background:var(--bg); border:1px solid var(--border); color:var(--text); border-radius:6px; font-family:var(--font-ui); font-size:13px; outline:none; }
.tg-compose input:focus { border-color:var(--accent); }
.tg-compose button { padding:8px 16px; background:var(--accent); border:none; color:#fff; border-radius:6px; cursor:pointer; font-family:var(--font-ui); }
.tg-chat { padding:10px 12px; border-bottom:1px solid var(--border); cursor:pointer; display:flex; align-items:center; gap:10px; }
.tg-chat:hover { background:var(--bg-hover); }
.tg-chat.active { background:var(--bg-hover); }
.tg-chat-avatar { width:36px; height:36px; border-radius:50%; color:#fff; display:flex; align-items:center; justify-content:center; font-size:14px; font-weight:bold; flex-shrink:0; }
.tg-chat-info { flex:1; min-width:0; }
.tg-chat-row { display:flex; justify-content:space-between; align-items:center; }
.tg-chat-name { font-weight:bold; font-size:13px; }
.tg-chat-date { color:var(--text-dim); font-size:11px; flex-shrink:0; }
.tg-badge { background:var(--accent); color:#fff; border-radius:10px; padding:1px 6px; font-size:11px; flex-shrink:0; }
.tg-last-msg { color:var(--text-muted); font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-top:2px; }
.tg-bubble { max-width:70%; padding:8px 12px; border-radius:12px; font-size:13px; line-height:1.4; word-wrap:break-word; overflow-wrap:break-word; word-break:break-all; white-space:pre-wrap; }
.tg-bubble-out { align-self:flex-end; background:#1a3a5c; border-bottom-right-radius:4px; }
.tg-bubble-in { align-self:flex-start; background:var(--bg-surface); border-bottom-left-radius:4px; }
.tg-bubble .tg-sender { color:var(--accent); font-weight:bold; font-size:12px; display:block; margin-bottom:2px; }
.tg-bubble-out .tg-sender { display:none; }
.tg-bubble .tg-meta { display:flex; justify-content:flex-end; align-items:center; gap:4px; margin-top:4px; }
.tg-bubble .tg-time { color:var(--text-dim); font-size:10px; }
.tg-bubble .tg-check { color:var(--accent); font-size:10px; }
.tg-bubble .tg-reply-quote { background:rgba(255,255,255,0.05); border-left:2px solid var(--accent); padding:4px 8px; margin-bottom:4px; border-radius:0 4px 4px 0; font-size:12px; color:var(--text-muted); }
.tg-date-sep { text-align:center; padding:8px 0; }
.tg-date-sep span { background:var(--bg-surface); color:var(--text-dim); font-size:11px; padding:4px 12px; border-radius:12px; }
.tg-reply-bar { padding:4px 12px; background:var(--bg-surface); border-top:1px solid var(--border); display:flex; align-items:center; gap:8px; font-size:13px; color:var(--text-muted); }
.tg-loading { padding:20px; color:var(--text-dim); text-align:center; }
.tg-empty { display:flex; align-items:center; justify-content:center; flex:1; color:var(--text-dim); font-size:14px; }

</style>
<script>
/**
 * marked v15.0.12 - a markdown parser
 * Copyright (c) 2011-2025, Christopher Jeffrey. (MIT Licensed)
 * https://github.com/markedjs/marked
 */

/**
 * DO NOT EDIT THIS FILE
 * The code in this file is generated from files in ./src/
 */
(function(g,f){if(typeof exports=="object"&&typeof module<"u"){module.exports=f()}else if("function"==typeof define && define.amd){define("marked",f)}else {g["marked"]=f()}}(typeof globalThis < "u" ? globalThis : typeof self < "u" ? self : this,function(){var exports={};var __exports=exports;var module={exports};
"use strict";var H=Object.defineProperty;var be=Object.getOwnPropertyDescriptor;var Te=Object.getOwnPropertyNames;var we=Object.prototype.hasOwnProperty;var ye=(l,e)=>{for(var t in e)H(l,t,{get:e[t],enumerable:!0})},Re=(l,e,t,n)=>{if(e&&typeof e=="object"||typeof e=="function")for(let s of Te(e))!we.call(l,s)&&s!==t&&H(l,s,{get:()=>e[s],enumerable:!(n=be(e,s))||n.enumerable});return l};var Se=l=>Re(H({},"__esModule",{value:!0}),l);var kt={};ye(kt,{Hooks:()=>L,Lexer:()=>x,Marked:()=>E,Parser:()=>b,Renderer:()=>$,TextRenderer:()=>_,Tokenizer:()=>S,defaults:()=>w,getDefaults:()=>z,lexer:()=>ht,marked:()=>k,options:()=>it,parse:()=>pt,parseInline:()=>ct,parser:()=>ut,setOptions:()=>ot,use:()=>lt,walkTokens:()=>at});module.exports=Se(kt);function z(){return{async:!1,breaks:!1,extensions:null,gfm:!0,hooks:null,pedantic:!1,renderer:null,silent:!1,tokenizer:null,walkTokens:null}}var w=z();function N(l){w=l}var I={exec:()=>null};function h(l,e=""){let t=typeof l=="string"?l:l.source,n={replace:(s,i)=>{let r=typeof i=="string"?i:i.source;return r=r.replace(m.caret,"$1"),t=t.replace(s,r),n},getRegex:()=>new RegExp(t,e)};return n}var m={codeRemoveIndent:/^(?: {1,4}| {0,3}\t)/gm,outputLinkReplace:/\\([\[\]])/g,indentCodeCompensation:/^(\s+)(?:```)/,beginningSpace:/^\s+/,endingHash:/#$/,startingSpaceChar:/^ /,endingSpaceChar:/ $/,nonSpaceChar:/[^ ]/,newLineCharGlobal:/\n/g,tabCharGlobal:/\t/g,multipleSpaceGlobal:/\s+/g,blankLine:/^[ \t]*$/,doubleBlankLine:/\n[ \t]*\n[ \t]*$/,blockquoteStart:/^ {0,3}>/,blockquoteSetextReplace:/\n {0,3}((?:=+|-+) *)(?=\n|$)/g,blockquoteSetextReplace2:/^ {0,3}>[ \t]?/gm,listReplaceTabs:/^\t+/,listReplaceNesting:/^ {1,4}(?=( {4})*[^ ])/g,listIsTask:/^\[[ xX]\] /,listReplaceTask:/^\[[ xX]\] +/,anyLine:/\n.*\n/,hrefBrackets:/^<(.*)>$/,tableDelimiter:/[:|]/,tableAlignChars:/^\||\| *$/g,tableRowBlankLine:/\n[ \t]*$/,tableAlignRight:/^ *-+: *$/,tableAlignCenter:/^ *:-+: *$/,tableAlignLeft:/^ *:-+ *$/,startATag:/^<a /i,endATag:/^<\/a>/i,startPreScriptTag:/^<(pre|code|kbd|script)(\s|>)/i,endPreScriptTag:/^<\/(pre|code|kbd|script)(\s|>)/i,startAngleBracket:/^</,endAngleBracket:/>$/,pedanticHrefTitle:/^([^'"]*[^\s])\s+(['"])(.*)\2/,unicodeAlphaNumeric:/[\p{L}\p{N}]/u,escapeTest:/[&<>"']/,escapeReplace:/[&<>"']/g,escapeTestNoEncode:/[<>"']|&(?!(#\d{1,7}|#[Xx][a-fA-F0-9]{1,6}|\w+);)/,escapeReplaceNoEncode:/[<>"']|&(?!(#\d{1,7}|#[Xx][a-fA-F0-9]{1,6}|\w+);)/g,unescapeTest:/&(#(?:\d+)|(?:#x[0-9A-Fa-f]+)|(?:\w+));?/ig,caret:/(^|[^\[])\^/g,percentDecode:/%25/g,findPipe:/\|/g,splitPipe:/ \|/,slashPipe:/\\\|/g,carriageReturn:/\r\n|\r/g,spaceLine:/^ +$/gm,notSpaceStart:/^\S*/,endingNewline:/\n$/,listItemRegex:l=>new RegExp(`^( {0,3}${l})((?:[	 ][^\\n]*)?(?:\\n|$))`),nextBulletRegex:l=>new RegExp(`^ {0,${Math.min(3,l-1)}}(?:[*+-]|\\d{1,9}[.)])((?:[ 	][^\\n]*)?(?:\\n|$))`),hrRegex:l=>new RegExp(`^ {0,${Math.min(3,l-1)}}((?:- *){3,}|(?:_ *){3,}|(?:\\* *){3,})(?:\\n+|$)`),fencesBeginRegex:l=>new RegExp(`^ {0,${Math.min(3,l-1)}}(?:\`\`\`|~~~)`),headingBeginRegex:l=>new RegExp(`^ {0,${Math.min(3,l-1)}}#`),htmlBeginRegex:l=>new RegExp(`^ {0,${Math.min(3,l-1)}}<(?:[a-z].*>|!--)`,"i")},$e=/^(?:[ \t]*(?:\n|$))+/,_e=/^((?: {4}| {0,3}\t)[^\n]+(?:\n(?:[ \t]*(?:\n|$))*)?)+/,Le=/^ {0,3}(`{3,}(?=[^`\n]*(?:\n|$))|~{3,})([^\n]*)(?:\n|$)(?:|([\s\S]*?)(?:\n|$))(?: {0,3}\1[~`]* *(?=\n|$)|$)/,O=/^ {0,3}((?:-[\t ]*){3,}|(?:_[ \t]*){3,}|(?:\*[ \t]*){3,})(?:\n+|$)/,ze=/^ {0,3}(#{1,6})(?=\s|$)(.*)(?:\n+|$)/,F=/(?:[*+-]|\d{1,9}[.)])/,ie=/^(?!bull |blockCode|fences|blockquote|heading|html|table)((?:.|\n(?!\s*?\n|bull |blockCode|fences|blockquote|heading|html|table))+?)\n {0,3}(=+|-+) *(?:\n+|$)/,oe=h(ie).replace(/bull/g,F).replace(/blockCode/g,/(?: {4}| {0,3}\t)/).replace(/fences/g,/ {0,3}(?:`{3,}|~{3,})/).replace(/blockquote/g,/ {0,3}>/).replace(/heading/g,/ {0,3}#{1,6}/).replace(/html/g,/ {0,3}<[^\n>]+>\n/).replace(/\|table/g,"").getRegex(),Me=h(ie).replace(/bull/g,F).replace(/blockCode/g,/(?: {4}| {0,3}\t)/).replace(/fences/g,/ {0,3}(?:`{3,}|~{3,})/).replace(/blockquote/g,/ {0,3}>/).replace(/heading/g,/ {0,3}#{1,6}/).replace(/html/g,/ {0,3}<[^\n>]+>\n/).replace(/table/g,/ {0,3}\|?(?:[:\- ]*\|)+[\:\- ]*\n/).getRegex(),Q=/^([^\n]+(?:\n(?!hr|heading|lheading|blockquote|fences|list|html|table| +\n)[^\n]+)*)/,Pe=/^[^\n]+/,U=/(?!\s*\])(?:\\.|[^\[\]\\])+/,Ae=h(/^ {0,3}\[(label)\]: *(?:\n[ \t]*)?([^<\s][^\s]*|<.*?>)(?:(?: +(?:\n[ \t]*)?| *\n[ \t]*)(title))? *(?:\n+|$)/).replace("label",U).replace("title",/(?:"(?:\\"?|[^"\\])*"|'[^'\n]*(?:\n[^'\n]+)*\n?'|\([^()]*\))/).getRegex(),Ee=h(/^( {0,3}bull)([ \t][^\n]+?)?(?:\n|$)/).replace(/bull/g,F).getRegex(),v="address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|meta|nav|noframes|ol|optgroup|option|p|param|search|section|summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul",K=/<!--(?:-?>|[\s\S]*?(?:-->|$))/,Ce=h("^ {0,3}(?:<(script|pre|style|textarea)[\\s>][\\s\\S]*?(?:</\\1>[^\\n]*\\n+|$)|comment[^\\n]*(\\n+|$)|<\\?[\\s\\S]*?(?:\\?>\\n*|$)|<![A-Z][\\s\\S]*?(?:>\\n*|$)|<!\\[CDATA\\[[\\s\\S]*?(?:\\]\\]>\\n*|$)|</?(tag)(?: +|\\n|/?>)[\\s\\S]*?(?:(?:\\n[ 	]*)+\\n|$)|<(?!script|pre|style|textarea)([a-z][\\w-]*)(?:attribute)*? */?>(?=[ \\t]*(?:\\n|$))[\\s\\S]*?(?:(?:\\n[ 	]*)+\\n|$)|</(?!script|pre|style|textarea)[a-z][\\w-]*\\s*>(?=[ \\t]*(?:\\n|$))[\\s\\S]*?(?:(?:\\n[ 	]*)+\\n|$))","i").replace("comment",K).replace("tag",v).replace("attribute",/ +[a-zA-Z:_][\w.:-]*(?: *= *"[^"\n]*"| *= *'[^'\n]*'| *= *[^\s"'=<>`]+)?/).getRegex(),le=h(Q).replace("hr",O).replace("heading"," {0,3}#{1,6}(?:\\s|$)").replace("|lheading","").replace("|table","").replace("blockquote"," {0,3}>").replace("fences"," {0,3}(?:`{3,}(?=[^`\\n]*\\n)|~{3,})[^\\n]*\\n").replace("list"," {0,3}(?:[*+-]|1[.)]) ").replace("html","</?(?:tag)(?: +|\\n|/?>)|<(?:script|pre|style|textarea|!--)").replace("tag",v).getRegex(),Ie=h(/^( {0,3}> ?(paragraph|[^\n]*)(?:\n|$))+/).replace("paragraph",le).getRegex(),X={blockquote:Ie,code:_e,def:Ae,fences:Le,heading:ze,hr:O,html:Ce,lheading:oe,list:Ee,newline:$e,paragraph:le,table:I,text:Pe},re=h("^ *([^\\n ].*)\\n {0,3}((?:\\| *)?:?-+:? *(?:\\| *:?-+:? *)*(?:\\| *)?)(?:\\n((?:(?! *\\n|hr|heading|blockquote|code|fences|list|html).*(?:\\n|$))*)\\n*|$)").replace("hr",O).replace("heading"," {0,3}#{1,6}(?:\\s|$)").replace("blockquote"," {0,3}>").replace("code","(?: {4}| {0,3}	)[^\\n]").replace("fences"," {0,3}(?:`{3,}(?=[^`\\n]*\\n)|~{3,})[^\\n]*\\n").replace("list"," {0,3}(?:[*+-]|1[.)]) ").replace("html","</?(?:tag)(?: +|\\n|/?>)|<(?:script|pre|style|textarea|!--)").replace("tag",v).getRegex(),Oe={...X,lheading:Me,table:re,paragraph:h(Q).replace("hr",O).replace("heading"," {0,3}#{1,6}(?:\\s|$)").replace("|lheading","").replace("table",re).replace("blockquote"," {0,3}>").replace("fences"," {0,3}(?:`{3,}(?=[^`\\n]*\\n)|~{3,})[^\\n]*\\n").replace("list"," {0,3}(?:[*+-]|1[.)]) ").replace("html","</?(?:tag)(?: +|\\n|/?>)|<(?:script|pre|style|textarea|!--)").replace("tag",v).getRegex()},Be={...X,html:h(`^ *(?:comment *(?:\\n|\\s*$)|<(tag)[\\s\\S]+?</\\1> *(?:\\n{2,}|\\s*$)|<tag(?:"[^"]*"|'[^']*'|\\s[^'"/>\\s]*)*?/?> *(?:\\n{2,}|\\s*$))`).replace("comment",K).replace(/tag/g,"(?!(?:a|em|strong|small|s|cite|q|dfn|abbr|data|time|code|var|samp|kbd|sub|sup|i|b|u|mark|ruby|rt|rp|bdi|bdo|span|br|wbr|ins|del|img)\\b)\\w+(?!:|[^\\w\\s@]*@)\\b").getRegex(),def:/^ *\[([^\]]+)\]: *<?([^\s>]+)>?(?: +(["(][^\n]+[")]))? *(?:\n+|$)/,heading:/^(#{1,6})(.*)(?:\n+|$)/,fences:I,lheading:/^(.+?)\n {0,3}(=+|-+) *(?:\n+|$)/,paragraph:h(Q).replace("hr",O).replace("heading",` *#{1,6} *[^
]`).replace("lheading",oe).replace("|table","").replace("blockquote"," {0,3}>").replace("|fences","").replace("|list","").replace("|html","").replace("|tag","").getRegex()},qe=/^\\([!"#$%&'()*+,\-./:;<=>?@\[\]\\^_`{|}~])/,ve=/^(`+)([^`]|[^`][\s\S]*?[^`])\1(?!`)/,ae=/^( {2,}|\\)\n(?!\s*$)/,De=/^(`+|[^`])(?:(?= {2,}\n)|[\s\S]*?(?:(?=[\\<!\[`*_]|\b_|$)|[^ ](?= {2,}\n)))/,D=/[\p{P}\p{S}]/u,W=/[\s\p{P}\p{S}]/u,ce=/[^\s\p{P}\p{S}]/u,Ze=h(/^((?![*_])punctSpace)/,"u").replace(/punctSpace/g,W).getRegex(),pe=/(?!~)[\p{P}\p{S}]/u,Ge=/(?!~)[\s\p{P}\p{S}]/u,He=/(?:[^\s\p{P}\p{S}]|~)/u,Ne=/\[[^[\]]*?\]\((?:\\.|[^\\\(\)]|\((?:\\.|[^\\\(\)])*\))*\)|`[^`]*?`|<[^<>]*?>/g,ue=/^(?:\*+(?:((?!\*)punct)|[^\s*]))|^_+(?:((?!_)punct)|([^\s_]))/,je=h(ue,"u").replace(/punct/g,D).getRegex(),Fe=h(ue,"u").replace(/punct/g,pe).getRegex(),he="^[^_*]*?__[^_*]*?\\*[^_*]*?(?=__)|[^*]+(?=[^*])|(?!\\*)punct(\\*+)(?=[\\s]|$)|notPunctSpace(\\*+)(?!\\*)(?=punctSpace|$)|(?!\\*)punctSpace(\\*+)(?=notPunctSpace)|[\\s](\\*+)(?!\\*)(?=punct)|(?!\\*)punct(\\*+)(?!\\*)(?=punct)|notPunctSpace(\\*+)(?=notPunctSpace)",Qe=h(he,"gu").replace(/notPunctSpace/g,ce).replace(/punctSpace/g,W).replace(/punct/g,D).getRegex(),Ue=h(he,"gu").replace(/notPunctSpace/g,He).replace(/punctSpace/g,Ge).replace(/punct/g,pe).getRegex(),Ke=h("^[^_*]*?\\*\\*[^_*]*?_[^_*]*?(?=\\*\\*)|[^_]+(?=[^_])|(?!_)punct(_+)(?=[\\s]|$)|notPunctSpace(_+)(?!_)(?=punctSpace|$)|(?!_)punctSpace(_+)(?=notPunctSpace)|[\\s](_+)(?!_)(?=punct)|(?!_)punct(_+)(?!_)(?=punct)","gu").replace(/notPunctSpace/g,ce).replace(/punctSpace/g,W).replace(/punct/g,D).getRegex(),Xe=h(/\\(punct)/,"gu").replace(/punct/g,D).getRegex(),We=h(/^<(scheme:[^\s\x00-\x1f<>]*|email)>/).replace("scheme",/[a-zA-Z][a-zA-Z0-9+.-]{1,31}/).replace("email",/[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+(@)[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+(?![-_])/).getRegex(),Je=h(K).replace("(?:-->|$)","-->").getRegex(),Ve=h("^comment|^</[a-zA-Z][\\w:-]*\\s*>|^<[a-zA-Z][\\w-]*(?:attribute)*?\\s*/?>|^<\\?[\\s\\S]*?\\?>|^<![a-zA-Z]+\\s[\\s\\S]*?>|^<!\\[CDATA\\[[\\s\\S]*?\\]\\]>").replace("comment",Je).replace("attribute",/\s+[a-zA-Z:_][\w.:-]*(?:\s*=\s*"[^"]*"|\s*=\s*'[^']*'|\s*=\s*[^\s"'=<>`]+)?/).getRegex(),q=/(?:\[(?:\\.|[^\[\]\\])*\]|\\.|`[^`]*`|[^\[\]\\`])*?/,Ye=h(/^!?\[(label)\]\(\s*(href)(?:(?:[ \t]*(?:\n[ \t]*)?)(title))?\s*\)/).replace("label",q).replace("href",/<(?:\\.|[^\n<>\\])+>|[^ \t\n\x00-\x1f]*/).replace("title",/"(?:\\"?|[^"\\])*"|'(?:\\'?|[^'\\])*'|\((?:\\\)?|[^)\\])*\)/).getRegex(),ke=h(/^!?\[(label)\]\[(ref)\]/).replace("label",q).replace("ref",U).getRegex(),ge=h(/^!?\[(ref)\](?:\[\])?/).replace("ref",U).getRegex(),et=h("reflink|nolink(?!\\()","g").replace("reflink",ke).replace("nolink",ge).getRegex(),J={_backpedal:I,anyPunctuation:Xe,autolink:We,blockSkip:Ne,br:ae,code:ve,del:I,emStrongLDelim:je,emStrongRDelimAst:Qe,emStrongRDelimUnd:Ke,escape:qe,link:Ye,nolink:ge,punctuation:Ze,reflink:ke,reflinkSearch:et,tag:Ve,text:De,url:I},tt={...J,link:h(/^!?\[(label)\]\((.*?)\)/).replace("label",q).getRegex(),reflink:h(/^!?\[(label)\]\s*\[([^\]]*)\]/).replace("label",q).getRegex()},j={...J,emStrongRDelimAst:Ue,emStrongLDelim:Fe,url:h(/^((?:ftp|https?):\/\/|www\.)(?:[a-zA-Z0-9\-]+\.?)+[^\s<]*|^email/,"i").replace("email",/[A-Za-z0-9._+-]+(@)[a-zA-Z0-9-_]+(?:\.[a-zA-Z0-9-_]*[a-zA-Z0-9])+(?![-_])/).getRegex(),_backpedal:/(?:[^?!.,:;*_'"~()&]+|\([^)]*\)|&(?![a-zA-Z0-9]+;$)|[?!.,:;*_'"~)]+(?!$))+/,del:/^(~~?)(?=[^\s~])((?:\\.|[^\\])*?(?:\\.|[^\s~\\]))\1(?=[^~]|$)/,text:/^([`~]+|[^`~])(?:(?= {2,}\n)|(?=[a-zA-Z0-9.!#$%&'*+\/=?_`{\|}~-]+@)|[\s\S]*?(?:(?=[\\<!\[`*~_]|\b_|https?:\/\/|ftp:\/\/|www\.|$)|[^ ](?= {2,}\n)|[^a-zA-Z0-9.!#$%&'*+\/=?_`{\|}~-](?=[a-zA-Z0-9.!#$%&'*+\/=?_`{\|}~-]+@)))/},nt={...j,br:h(ae).replace("{2,}","*").getRegex(),text:h(j.text).replace("\\b_","\\b_| {2,}\\n").replace(/\{2,\}/g,"*").getRegex()},B={normal:X,gfm:Oe,pedantic:Be},P={normal:J,gfm:j,breaks:nt,pedantic:tt};var st={"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"},fe=l=>st[l];function R(l,e){if(e){if(m.escapeTest.test(l))return l.replace(m.escapeReplace,fe)}else if(m.escapeTestNoEncode.test(l))return l.replace(m.escapeReplaceNoEncode,fe);return l}function V(l){try{l=encodeURI(l).replace(m.percentDecode,"%")}catch{return null}return l}function Y(l,e){let t=l.replace(m.findPipe,(i,r,o)=>{let a=!1,c=r;for(;--c>=0&&o[c]==="\\";)a=!a;return a?"|":" |"}),n=t.split(m.splitPipe),s=0;if(n[0].trim()||n.shift(),n.length>0&&!n.at(-1)?.trim()&&n.pop(),e)if(n.length>e)n.splice(e);else for(;n.length<e;)n.push("");for(;s<n.length;s++)n[s]=n[s].trim().replace(m.slashPipe,"|");return n}function A(l,e,t){let n=l.length;if(n===0)return"";let s=0;for(;s<n;){let i=l.charAt(n-s-1);if(i===e&&!t)s++;else if(i!==e&&t)s++;else break}return l.slice(0,n-s)}function de(l,e){if(l.indexOf(e[1])===-1)return-1;let t=0;for(let n=0;n<l.length;n++)if(l[n]==="\\")n++;else if(l[n]===e[0])t++;else if(l[n]===e[1]&&(t--,t<0))return n;return t>0?-2:-1}function me(l,e,t,n,s){let i=e.href,r=e.title||null,o=l[1].replace(s.other.outputLinkReplace,"$1");n.state.inLink=!0;let a={type:l[0].charAt(0)==="!"?"image":"link",raw:t,href:i,title:r,text:o,tokens:n.inlineTokens(o)};return n.state.inLink=!1,a}function rt(l,e,t){let n=l.match(t.other.indentCodeCompensation);if(n===null)return e;let s=n[1];return e.split(`
`).map(i=>{let r=i.match(t.other.beginningSpace);if(r===null)return i;let[o]=r;return o.length>=s.length?i.slice(s.length):i}).join(`
`)}var S=class{options;rules;lexer;constructor(e){this.options=e||w}space(e){let t=this.rules.block.newline.exec(e);if(t&&t[0].length>0)return{type:"space",raw:t[0]}}code(e){let t=this.rules.block.code.exec(e);if(t){let n=t[0].replace(this.rules.other.codeRemoveIndent,"");return{type:"code",raw:t[0],codeBlockStyle:"indented",text:this.options.pedantic?n:A(n,`
`)}}}fences(e){let t=this.rules.block.fences.exec(e);if(t){let n=t[0],s=rt(n,t[3]||"",this.rules);return{type:"code",raw:n,lang:t[2]?t[2].trim().replace(this.rules.inline.anyPunctuation,"$1"):t[2],text:s}}}heading(e){let t=this.rules.block.heading.exec(e);if(t){let n=t[2].trim();if(this.rules.other.endingHash.test(n)){let s=A(n,"#");(this.options.pedantic||!s||this.rules.other.endingSpaceChar.test(s))&&(n=s.trim())}return{type:"heading",raw:t[0],depth:t[1].length,text:n,tokens:this.lexer.inline(n)}}}hr(e){let t=this.rules.block.hr.exec(e);if(t)return{type:"hr",raw:A(t[0],`
`)}}blockquote(e){let t=this.rules.block.blockquote.exec(e);if(t){let n=A(t[0],`
`).split(`
`),s="",i="",r=[];for(;n.length>0;){let o=!1,a=[],c;for(c=0;c<n.length;c++)if(this.rules.other.blockquoteStart.test(n[c]))a.push(n[c]),o=!0;else if(!o)a.push(n[c]);else break;n=n.slice(c);let p=a.join(`
`),u=p.replace(this.rules.other.blockquoteSetextReplace,`
    $1`).replace(this.rules.other.blockquoteSetextReplace2,"");s=s?`${s}
${p}`:p,i=i?`${i}
${u}`:u;let d=this.lexer.state.top;if(this.lexer.state.top=!0,this.lexer.blockTokens(u,r,!0),this.lexer.state.top=d,n.length===0)break;let g=r.at(-1);if(g?.type==="code")break;if(g?.type==="blockquote"){let T=g,f=T.raw+`
`+n.join(`
`),y=this.blockquote(f);r[r.length-1]=y,s=s.substring(0,s.length-T.raw.length)+y.raw,i=i.substring(0,i.length-T.text.length)+y.text;break}else if(g?.type==="list"){let T=g,f=T.raw+`
`+n.join(`
`),y=this.list(f);r[r.length-1]=y,s=s.substring(0,s.length-g.raw.length)+y.raw,i=i.substring(0,i.length-T.raw.length)+y.raw,n=f.substring(r.at(-1).raw.length).split(`
`);continue}}return{type:"blockquote",raw:s,tokens:r,text:i}}}list(e){let t=this.rules.block.list.exec(e);if(t){let n=t[1].trim(),s=n.length>1,i={type:"list",raw:"",ordered:s,start:s?+n.slice(0,-1):"",loose:!1,items:[]};n=s?`\\d{1,9}\\${n.slice(-1)}`:`\\${n}`,this.options.pedantic&&(n=s?n:"[*+-]");let r=this.rules.other.listItemRegex(n),o=!1;for(;e;){let c=!1,p="",u="";if(!(t=r.exec(e))||this.rules.block.hr.test(e))break;p=t[0],e=e.substring(p.length);let d=t[2].split(`
`,1)[0].replace(this.rules.other.listReplaceTabs,Z=>" ".repeat(3*Z.length)),g=e.split(`
`,1)[0],T=!d.trim(),f=0;if(this.options.pedantic?(f=2,u=d.trimStart()):T?f=t[1].length+1:(f=t[2].search(this.rules.other.nonSpaceChar),f=f>4?1:f,u=d.slice(f),f+=t[1].length),T&&this.rules.other.blankLine.test(g)&&(p+=g+`
`,e=e.substring(g.length+1),c=!0),!c){let Z=this.rules.other.nextBulletRegex(f),te=this.rules.other.hrRegex(f),ne=this.rules.other.fencesBeginRegex(f),se=this.rules.other.headingBeginRegex(f),xe=this.rules.other.htmlBeginRegex(f);for(;e;){let G=e.split(`
`,1)[0],C;if(g=G,this.options.pedantic?(g=g.replace(this.rules.other.listReplaceNesting,"  "),C=g):C=g.replace(this.rules.other.tabCharGlobal,"    "),ne.test(g)||se.test(g)||xe.test(g)||Z.test(g)||te.test(g))break;if(C.search(this.rules.other.nonSpaceChar)>=f||!g.trim())u+=`
`+C.slice(f);else{if(T||d.replace(this.rules.other.tabCharGlobal,"    ").search(this.rules.other.nonSpaceChar)>=4||ne.test(d)||se.test(d)||te.test(d))break;u+=`
`+g}!T&&!g.trim()&&(T=!0),p+=G+`
`,e=e.substring(G.length+1),d=C.slice(f)}}i.loose||(o?i.loose=!0:this.rules.other.doubleBlankLine.test(p)&&(o=!0));let y=null,ee;this.options.gfm&&(y=this.rules.other.listIsTask.exec(u),y&&(ee=y[0]!=="[ ] ",u=u.replace(this.rules.other.listReplaceTask,""))),i.items.push({type:"list_item",raw:p,task:!!y,checked:ee,loose:!1,text:u,tokens:[]}),i.raw+=p}let a=i.items.at(-1);if(a)a.raw=a.raw.trimEnd(),a.text=a.text.trimEnd();else return;i.raw=i.raw.trimEnd();for(let c=0;c<i.items.length;c++)if(this.lexer.state.top=!1,i.items[c].tokens=this.lexer.blockTokens(i.items[c].text,[]),!i.loose){let p=i.items[c].tokens.filter(d=>d.type==="space"),u=p.length>0&&p.some(d=>this.rules.other.anyLine.test(d.raw));i.loose=u}if(i.loose)for(let c=0;c<i.items.length;c++)i.items[c].loose=!0;return i}}html(e){let t=this.rules.block.html.exec(e);if(t)return{type:"html",block:!0,raw:t[0],pre:t[1]==="pre"||t[1]==="script"||t[1]==="style",text:t[0]}}def(e){let t=this.rules.block.def.exec(e);if(t){let n=t[1].toLowerCase().replace(this.rules.other.multipleSpaceGlobal," "),s=t[2]?t[2].replace(this.rules.other.hrefBrackets,"$1").replace(this.rules.inline.anyPunctuation,"$1"):"",i=t[3]?t[3].substring(1,t[3].length-1).replace(this.rules.inline.anyPunctuation,"$1"):t[3];return{type:"def",tag:n,raw:t[0],href:s,title:i}}}table(e){let t=this.rules.block.table.exec(e);if(!t||!this.rules.other.tableDelimiter.test(t[2]))return;let n=Y(t[1]),s=t[2].replace(this.rules.other.tableAlignChars,"").split("|"),i=t[3]?.trim()?t[3].replace(this.rules.other.tableRowBlankLine,"").split(`
`):[],r={type:"table",raw:t[0],header:[],align:[],rows:[]};if(n.length===s.length){for(let o of s)this.rules.other.tableAlignRight.test(o)?r.align.push("right"):this.rules.other.tableAlignCenter.test(o)?r.align.push("center"):this.rules.other.tableAlignLeft.test(o)?r.align.push("left"):r.align.push(null);for(let o=0;o<n.length;o++)r.header.push({text:n[o],tokens:this.lexer.inline(n[o]),header:!0,align:r.align[o]});for(let o of i)r.rows.push(Y(o,r.header.length).map((a,c)=>({text:a,tokens:this.lexer.inline(a),header:!1,align:r.align[c]})));return r}}lheading(e){let t=this.rules.block.lheading.exec(e);if(t)return{type:"heading",raw:t[0],depth:t[2].charAt(0)==="="?1:2,text:t[1],tokens:this.lexer.inline(t[1])}}paragraph(e){let t=this.rules.block.paragraph.exec(e);if(t){let n=t[1].charAt(t[1].length-1)===`
`?t[1].slice(0,-1):t[1];return{type:"paragraph",raw:t[0],text:n,tokens:this.lexer.inline(n)}}}text(e){let t=this.rules.block.text.exec(e);if(t)return{type:"text",raw:t[0],text:t[0],tokens:this.lexer.inline(t[0])}}escape(e){let t=this.rules.inline.escape.exec(e);if(t)return{type:"escape",raw:t[0],text:t[1]}}tag(e){let t=this.rules.inline.tag.exec(e);if(t)return!this.lexer.state.inLink&&this.rules.other.startATag.test(t[0])?this.lexer.state.inLink=!0:this.lexer.state.inLink&&this.rules.other.endATag.test(t[0])&&(this.lexer.state.inLink=!1),!this.lexer.state.inRawBlock&&this.rules.other.startPreScriptTag.test(t[0])?this.lexer.state.inRawBlock=!0:this.lexer.state.inRawBlock&&this.rules.other.endPreScriptTag.test(t[0])&&(this.lexer.state.inRawBlock=!1),{type:"html",raw:t[0],inLink:this.lexer.state.inLink,inRawBlock:this.lexer.state.inRawBlock,block:!1,text:t[0]}}link(e){let t=this.rules.inline.link.exec(e);if(t){let n=t[2].trim();if(!this.options.pedantic&&this.rules.other.startAngleBracket.test(n)){if(!this.rules.other.endAngleBracket.test(n))return;let r=A(n.slice(0,-1),"\\");if((n.length-r.length)%2===0)return}else{let r=de(t[2],"()");if(r===-2)return;if(r>-1){let a=(t[0].indexOf("!")===0?5:4)+t[1].length+r;t[2]=t[2].substring(0,r),t[0]=t[0].substring(0,a).trim(),t[3]=""}}let s=t[2],i="";if(this.options.pedantic){let r=this.rules.other.pedanticHrefTitle.exec(s);r&&(s=r[1],i=r[3])}else i=t[3]?t[3].slice(1,-1):"";return s=s.trim(),this.rules.other.startAngleBracket.test(s)&&(this.options.pedantic&&!this.rules.other.endAngleBracket.test(n)?s=s.slice(1):s=s.slice(1,-1)),me(t,{href:s&&s.replace(this.rules.inline.anyPunctuation,"$1"),title:i&&i.replace(this.rules.inline.anyPunctuation,"$1")},t[0],this.lexer,this.rules)}}reflink(e,t){let n;if((n=this.rules.inline.reflink.exec(e))||(n=this.rules.inline.nolink.exec(e))){let s=(n[2]||n[1]).replace(this.rules.other.multipleSpaceGlobal," "),i=t[s.toLowerCase()];if(!i){let r=n[0].charAt(0);return{type:"text",raw:r,text:r}}return me(n,i,n[0],this.lexer,this.rules)}}emStrong(e,t,n=""){let s=this.rules.inline.emStrongLDelim.exec(e);if(!s||s[3]&&n.match(this.rules.other.unicodeAlphaNumeric))return;if(!(s[1]||s[2]||"")||!n||this.rules.inline.punctuation.exec(n)){let r=[...s[0]].length-1,o,a,c=r,p=0,u=s[0][0]==="*"?this.rules.inline.emStrongRDelimAst:this.rules.inline.emStrongRDelimUnd;for(u.lastIndex=0,t=t.slice(-1*e.length+r);(s=u.exec(t))!=null;){if(o=s[1]||s[2]||s[3]||s[4]||s[5]||s[6],!o)continue;if(a=[...o].length,s[3]||s[4]){c+=a;continue}else if((s[5]||s[6])&&r%3&&!((r+a)%3)){p+=a;continue}if(c-=a,c>0)continue;a=Math.min(a,a+c+p);let d=[...s[0]][0].length,g=e.slice(0,r+s.index+d+a);if(Math.min(r,a)%2){let f=g.slice(1,-1);return{type:"em",raw:g,text:f,tokens:this.lexer.inlineTokens(f)}}let T=g.slice(2,-2);return{type:"strong",raw:g,text:T,tokens:this.lexer.inlineTokens(T)}}}}codespan(e){let t=this.rules.inline.code.exec(e);if(t){let n=t[2].replace(this.rules.other.newLineCharGlobal," "),s=this.rules.other.nonSpaceChar.test(n),i=this.rules.other.startingSpaceChar.test(n)&&this.rules.other.endingSpaceChar.test(n);return s&&i&&(n=n.substring(1,n.length-1)),{type:"codespan",raw:t[0],text:n}}}br(e){let t=this.rules.inline.br.exec(e);if(t)return{type:"br",raw:t[0]}}del(e){let t=this.rules.inline.del.exec(e);if(t)return{type:"del",raw:t[0],text:t[2],tokens:this.lexer.inlineTokens(t[2])}}autolink(e){let t=this.rules.inline.autolink.exec(e);if(t){let n,s;return t[2]==="@"?(n=t[1],s="mailto:"+n):(n=t[1],s=n),{type:"link",raw:t[0],text:n,href:s,tokens:[{type:"text",raw:n,text:n}]}}}url(e){let t;if(t=this.rules.inline.url.exec(e)){let n,s;if(t[2]==="@")n=t[0],s="mailto:"+n;else{let i;do i=t[0],t[0]=this.rules.inline._backpedal.exec(t[0])?.[0]??"";while(i!==t[0]);n=t[0],t[1]==="www."?s="http://"+t[0]:s=t[0]}return{type:"link",raw:t[0],text:n,href:s,tokens:[{type:"text",raw:n,text:n}]}}}inlineText(e){let t=this.rules.inline.text.exec(e);if(t){let n=this.lexer.state.inRawBlock;return{type:"text",raw:t[0],text:t[0],escaped:n}}}};var x=class l{tokens;options;state;tokenizer;inlineQueue;constructor(e){this.tokens=[],this.tokens.links=Object.create(null),this.options=e||w,this.options.tokenizer=this.options.tokenizer||new S,this.tokenizer=this.options.tokenizer,this.tokenizer.options=this.options,this.tokenizer.lexer=this,this.inlineQueue=[],this.state={inLink:!1,inRawBlock:!1,top:!0};let t={other:m,block:B.normal,inline:P.normal};this.options.pedantic?(t.block=B.pedantic,t.inline=P.pedantic):this.options.gfm&&(t.block=B.gfm,this.options.breaks?t.inline=P.breaks:t.inline=P.gfm),this.tokenizer.rules=t}static get rules(){return{block:B,inline:P}}static lex(e,t){return new l(t).lex(e)}static lexInline(e,t){return new l(t).inlineTokens(e)}lex(e){e=e.replace(m.carriageReturn,`
`),this.blockTokens(e,this.tokens);for(let t=0;t<this.inlineQueue.length;t++){let n=this.inlineQueue[t];this.inlineTokens(n.src,n.tokens)}return this.inlineQueue=[],this.tokens}blockTokens(e,t=[],n=!1){for(this.options.pedantic&&(e=e.replace(m.tabCharGlobal,"    ").replace(m.spaceLine,""));e;){let s;if(this.options.extensions?.block?.some(r=>(s=r.call({lexer:this},e,t))?(e=e.substring(s.raw.length),t.push(s),!0):!1))continue;if(s=this.tokenizer.space(e)){e=e.substring(s.raw.length);let r=t.at(-1);s.raw.length===1&&r!==void 0?r.raw+=`
`:t.push(s);continue}if(s=this.tokenizer.code(e)){e=e.substring(s.raw.length);let r=t.at(-1);r?.type==="paragraph"||r?.type==="text"?(r.raw+=`
`+s.raw,r.text+=`
`+s.text,this.inlineQueue.at(-1).src=r.text):t.push(s);continue}if(s=this.tokenizer.fences(e)){e=e.substring(s.raw.length),t.push(s);continue}if(s=this.tokenizer.heading(e)){e=e.substring(s.raw.length),t.push(s);continue}if(s=this.tokenizer.hr(e)){e=e.substring(s.raw.length),t.push(s);continue}if(s=this.tokenizer.blockquote(e)){e=e.substring(s.raw.length),t.push(s);continue}if(s=this.tokenizer.list(e)){e=e.substring(s.raw.length),t.push(s);continue}if(s=this.tokenizer.html(e)){e=e.substring(s.raw.length),t.push(s);continue}if(s=this.tokenizer.def(e)){e=e.substring(s.raw.length);let r=t.at(-1);r?.type==="paragraph"||r?.type==="text"?(r.raw+=`
`+s.raw,r.text+=`
`+s.raw,this.inlineQueue.at(-1).src=r.text):this.tokens.links[s.tag]||(this.tokens.links[s.tag]={href:s.href,title:s.title});continue}if(s=this.tokenizer.table(e)){e=e.substring(s.raw.length),t.push(s);continue}if(s=this.tokenizer.lheading(e)){e=e.substring(s.raw.length),t.push(s);continue}let i=e;if(this.options.extensions?.startBlock){let r=1/0,o=e.slice(1),a;this.options.extensions.startBlock.forEach(c=>{a=c.call({lexer:this},o),typeof a=="number"&&a>=0&&(r=Math.min(r,a))}),r<1/0&&r>=0&&(i=e.substring(0,r+1))}if(this.state.top&&(s=this.tokenizer.paragraph(i))){let r=t.at(-1);n&&r?.type==="paragraph"?(r.raw+=`
`+s.raw,r.text+=`
`+s.text,this.inlineQueue.pop(),this.inlineQueue.at(-1).src=r.text):t.push(s),n=i.length!==e.length,e=e.substring(s.raw.length);continue}if(s=this.tokenizer.text(e)){e=e.substring(s.raw.length);let r=t.at(-1);r?.type==="text"?(r.raw+=`
`+s.raw,r.text+=`
`+s.text,this.inlineQueue.pop(),this.inlineQueue.at(-1).src=r.text):t.push(s);continue}if(e){let r="Infinite loop on byte: "+e.charCodeAt(0);if(this.options.silent){console.error(r);break}else throw new Error(r)}}return this.state.top=!0,t}inline(e,t=[]){return this.inlineQueue.push({src:e,tokens:t}),t}inlineTokens(e,t=[]){let n=e,s=null;if(this.tokens.links){let o=Object.keys(this.tokens.links);if(o.length>0)for(;(s=this.tokenizer.rules.inline.reflinkSearch.exec(n))!=null;)o.includes(s[0].slice(s[0].lastIndexOf("[")+1,-1))&&(n=n.slice(0,s.index)+"["+"a".repeat(s[0].length-2)+"]"+n.slice(this.tokenizer.rules.inline.reflinkSearch.lastIndex))}for(;(s=this.tokenizer.rules.inline.anyPunctuation.exec(n))!=null;)n=n.slice(0,s.index)+"++"+n.slice(this.tokenizer.rules.inline.anyPunctuation.lastIndex);for(;(s=this.tokenizer.rules.inline.blockSkip.exec(n))!=null;)n=n.slice(0,s.index)+"["+"a".repeat(s[0].length-2)+"]"+n.slice(this.tokenizer.rules.inline.blockSkip.lastIndex);let i=!1,r="";for(;e;){i||(r=""),i=!1;let o;if(this.options.extensions?.inline?.some(c=>(o=c.call({lexer:this},e,t))?(e=e.substring(o.raw.length),t.push(o),!0):!1))continue;if(o=this.tokenizer.escape(e)){e=e.substring(o.raw.length),t.push(o);continue}if(o=this.tokenizer.tag(e)){e=e.substring(o.raw.length),t.push(o);continue}if(o=this.tokenizer.link(e)){e=e.substring(o.raw.length),t.push(o);continue}if(o=this.tokenizer.reflink(e,this.tokens.links)){e=e.substring(o.raw.length);let c=t.at(-1);o.type==="text"&&c?.type==="text"?(c.raw+=o.raw,c.text+=o.text):t.push(o);continue}if(o=this.tokenizer.emStrong(e,n,r)){e=e.substring(o.raw.length),t.push(o);continue}if(o=this.tokenizer.codespan(e)){e=e.substring(o.raw.length),t.push(o);continue}if(o=this.tokenizer.br(e)){e=e.substring(o.raw.length),t.push(o);continue}if(o=this.tokenizer.del(e)){e=e.substring(o.raw.length),t.push(o);continue}if(o=this.tokenizer.autolink(e)){e=e.substring(o.raw.length),t.push(o);continue}if(!this.state.inLink&&(o=this.tokenizer.url(e))){e=e.substring(o.raw.length),t.push(o);continue}let a=e;if(this.options.extensions?.startInline){let c=1/0,p=e.slice(1),u;this.options.extensions.startInline.forEach(d=>{u=d.call({lexer:this},p),typeof u=="number"&&u>=0&&(c=Math.min(c,u))}),c<1/0&&c>=0&&(a=e.substring(0,c+1))}if(o=this.tokenizer.inlineText(a)){e=e.substring(o.raw.length),o.raw.slice(-1)!=="_"&&(r=o.raw.slice(-1)),i=!0;let c=t.at(-1);c?.type==="text"?(c.raw+=o.raw,c.text+=o.text):t.push(o);continue}if(e){let c="Infinite loop on byte: "+e.charCodeAt(0);if(this.options.silent){console.error(c);break}else throw new Error(c)}}return t}};var $=class{options;parser;constructor(e){this.options=e||w}space(e){return""}code({text:e,lang:t,escaped:n}){let s=(t||"").match(m.notSpaceStart)?.[0],i=e.replace(m.endingNewline,"")+`
`;return s?'<pre><code class="language-'+R(s)+'">'+(n?i:R(i,!0))+`</code></pre>
`:"<pre><code>"+(n?i:R(i,!0))+`</code></pre>
`}blockquote({tokens:e}){return`<blockquote>
${this.parser.parse(e)}</blockquote>
`}html({text:e}){return e}heading({tokens:e,depth:t}){return`<h${t}>${this.parser.parseInline(e)}</h${t}>
`}hr(e){return`<hr>
`}list(e){let t=e.ordered,n=e.start,s="";for(let o=0;o<e.items.length;o++){let a=e.items[o];s+=this.listitem(a)}let i=t?"ol":"ul",r=t&&n!==1?' start="'+n+'"':"";return"<"+i+r+`>
`+s+"</"+i+`>
`}listitem(e){let t="";if(e.task){let n=this.checkbox({checked:!!e.checked});e.loose?e.tokens[0]?.type==="paragraph"?(e.tokens[0].text=n+" "+e.tokens[0].text,e.tokens[0].tokens&&e.tokens[0].tokens.length>0&&e.tokens[0].tokens[0].type==="text"&&(e.tokens[0].tokens[0].text=n+" "+R(e.tokens[0].tokens[0].text),e.tokens[0].tokens[0].escaped=!0)):e.tokens.unshift({type:"text",raw:n+" ",text:n+" ",escaped:!0}):t+=n+" "}return t+=this.parser.parse(e.tokens,!!e.loose),`<li>${t}</li>
`}checkbox({checked:e}){return"<input "+(e?'checked="" ':"")+'disabled="" type="checkbox">'}paragraph({tokens:e}){return`<p>${this.parser.parseInline(e)}</p>
`}table(e){let t="",n="";for(let i=0;i<e.header.length;i++)n+=this.tablecell(e.header[i]);t+=this.tablerow({text:n});let s="";for(let i=0;i<e.rows.length;i++){let r=e.rows[i];n="";for(let o=0;o<r.length;o++)n+=this.tablecell(r[o]);s+=this.tablerow({text:n})}return s&&(s=`<tbody>${s}</tbody>`),`<table>
<thead>
`+t+`</thead>
`+s+`</table>
`}tablerow({text:e}){return`<tr>
${e}</tr>
`}tablecell(e){let t=this.parser.parseInline(e.tokens),n=e.header?"th":"td";return(e.align?`<${n} align="${e.align}">`:`<${n}>`)+t+`</${n}>
`}strong({tokens:e}){return`<strong>${this.parser.parseInline(e)}</strong>`}em({tokens:e}){return`<em>${this.parser.parseInline(e)}</em>`}codespan({text:e}){return`<code>${R(e,!0)}</code>`}br(e){return"<br>"}del({tokens:e}){return`<del>${this.parser.parseInline(e)}</del>`}link({href:e,title:t,tokens:n}){let s=this.parser.parseInline(n),i=V(e);if(i===null)return s;e=i;let r='<a href="'+e+'"';return t&&(r+=' title="'+R(t)+'"'),r+=">"+s+"</a>",r}image({href:e,title:t,text:n,tokens:s}){s&&(n=this.parser.parseInline(s,this.parser.textRenderer));let i=V(e);if(i===null)return R(n);e=i;let r=`<img src="${e}" alt="${n}"`;return t&&(r+=` title="${R(t)}"`),r+=">",r}text(e){return"tokens"in e&&e.tokens?this.parser.parseInline(e.tokens):"escaped"in e&&e.escaped?e.text:R(e.text)}};var _=class{strong({text:e}){return e}em({text:e}){return e}codespan({text:e}){return e}del({text:e}){return e}html({text:e}){return e}text({text:e}){return e}link({text:e}){return""+e}image({text:e}){return""+e}br(){return""}};var b=class l{options;renderer;textRenderer;constructor(e){this.options=e||w,this.options.renderer=this.options.renderer||new $,this.renderer=this.options.renderer,this.renderer.options=this.options,this.renderer.parser=this,this.textRenderer=new _}static parse(e,t){return new l(t).parse(e)}static parseInline(e,t){return new l(t).parseInline(e)}parse(e,t=!0){let n="";for(let s=0;s<e.length;s++){let i=e[s];if(this.options.extensions?.renderers?.[i.type]){let o=i,a=this.options.extensions.renderers[o.type].call({parser:this},o);if(a!==!1||!["space","hr","heading","code","table","blockquote","list","html","paragraph","text"].includes(o.type)){n+=a||"";continue}}let r=i;switch(r.type){case"space":{n+=this.renderer.space(r);continue}case"hr":{n+=this.renderer.hr(r);continue}case"heading":{n+=this.renderer.heading(r);continue}case"code":{n+=this.renderer.code(r);continue}case"table":{n+=this.renderer.table(r);continue}case"blockquote":{n+=this.renderer.blockquote(r);continue}case"list":{n+=this.renderer.list(r);continue}case"html":{n+=this.renderer.html(r);continue}case"paragraph":{n+=this.renderer.paragraph(r);continue}case"text":{let o=r,a=this.renderer.text(o);for(;s+1<e.length&&e[s+1].type==="text";)o=e[++s],a+=`
`+this.renderer.text(o);t?n+=this.renderer.paragraph({type:"paragraph",raw:a,text:a,tokens:[{type:"text",raw:a,text:a,escaped:!0}]}):n+=a;continue}default:{let o='Token with "'+r.type+'" type was not found.';if(this.options.silent)return console.error(o),"";throw new Error(o)}}}return n}parseInline(e,t=this.renderer){let n="";for(let s=0;s<e.length;s++){let i=e[s];if(this.options.extensions?.renderers?.[i.type]){let o=this.options.extensions.renderers[i.type].call({parser:this},i);if(o!==!1||!["escape","html","link","image","strong","em","codespan","br","del","text"].includes(i.type)){n+=o||"";continue}}let r=i;switch(r.type){case"escape":{n+=t.text(r);break}case"html":{n+=t.html(r);break}case"link":{n+=t.link(r);break}case"image":{n+=t.image(r);break}case"strong":{n+=t.strong(r);break}case"em":{n+=t.em(r);break}case"codespan":{n+=t.codespan(r);break}case"br":{n+=t.br(r);break}case"del":{n+=t.del(r);break}case"text":{n+=t.text(r);break}default:{let o='Token with "'+r.type+'" type was not found.';if(this.options.silent)return console.error(o),"";throw new Error(o)}}}return n}};var L=class{options;block;constructor(e){this.options=e||w}static passThroughHooks=new Set(["preprocess","postprocess","processAllTokens"]);preprocess(e){return e}postprocess(e){return e}processAllTokens(e){return e}provideLexer(){return this.block?x.lex:x.lexInline}provideParser(){return this.block?b.parse:b.parseInline}};var E=class{defaults=z();options=this.setOptions;parse=this.parseMarkdown(!0);parseInline=this.parseMarkdown(!1);Parser=b;Renderer=$;TextRenderer=_;Lexer=x;Tokenizer=S;Hooks=L;constructor(...e){this.use(...e)}walkTokens(e,t){let n=[];for(let s of e)switch(n=n.concat(t.call(this,s)),s.type){case"table":{let i=s;for(let r of i.header)n=n.concat(this.walkTokens(r.tokens,t));for(let r of i.rows)for(let o of r)n=n.concat(this.walkTokens(o.tokens,t));break}case"list":{let i=s;n=n.concat(this.walkTokens(i.items,t));break}default:{let i=s;this.defaults.extensions?.childTokens?.[i.type]?this.defaults.extensions.childTokens[i.type].forEach(r=>{let o=i[r].flat(1/0);n=n.concat(this.walkTokens(o,t))}):i.tokens&&(n=n.concat(this.walkTokens(i.tokens,t)))}}return n}use(...e){let t=this.defaults.extensions||{renderers:{},childTokens:{}};return e.forEach(n=>{let s={...n};if(s.async=this.defaults.async||s.async||!1,n.extensions&&(n.extensions.forEach(i=>{if(!i.name)throw new Error("extension name required");if("renderer"in i){let r=t.renderers[i.name];r?t.renderers[i.name]=function(...o){let a=i.renderer.apply(this,o);return a===!1&&(a=r.apply(this,o)),a}:t.renderers[i.name]=i.renderer}if("tokenizer"in i){if(!i.level||i.level!=="block"&&i.level!=="inline")throw new Error("extension level must be 'block' or 'inline'");let r=t[i.level];r?r.unshift(i.tokenizer):t[i.level]=[i.tokenizer],i.start&&(i.level==="block"?t.startBlock?t.startBlock.push(i.start):t.startBlock=[i.start]:i.level==="inline"&&(t.startInline?t.startInline.push(i.start):t.startInline=[i.start]))}"childTokens"in i&&i.childTokens&&(t.childTokens[i.name]=i.childTokens)}),s.extensions=t),n.renderer){let i=this.defaults.renderer||new $(this.defaults);for(let r in n.renderer){if(!(r in i))throw new Error(`renderer '${r}' does not exist`);if(["options","parser"].includes(r))continue;let o=r,a=n.renderer[o],c=i[o];i[o]=(...p)=>{let u=a.apply(i,p);return u===!1&&(u=c.apply(i,p)),u||""}}s.renderer=i}if(n.tokenizer){let i=this.defaults.tokenizer||new S(this.defaults);for(let r in n.tokenizer){if(!(r in i))throw new Error(`tokenizer '${r}' does not exist`);if(["options","rules","lexer"].includes(r))continue;let o=r,a=n.tokenizer[o],c=i[o];i[o]=(...p)=>{let u=a.apply(i,p);return u===!1&&(u=c.apply(i,p)),u}}s.tokenizer=i}if(n.hooks){let i=this.defaults.hooks||new L;for(let r in n.hooks){if(!(r in i))throw new Error(`hook '${r}' does not exist`);if(["options","block"].includes(r))continue;let o=r,a=n.hooks[o],c=i[o];L.passThroughHooks.has(r)?i[o]=p=>{if(this.defaults.async)return Promise.resolve(a.call(i,p)).then(d=>c.call(i,d));let u=a.call(i,p);return c.call(i,u)}:i[o]=(...p)=>{let u=a.apply(i,p);return u===!1&&(u=c.apply(i,p)),u}}s.hooks=i}if(n.walkTokens){let i=this.defaults.walkTokens,r=n.walkTokens;s.walkTokens=function(o){let a=[];return a.push(r.call(this,o)),i&&(a=a.concat(i.call(this,o))),a}}this.defaults={...this.defaults,...s}}),this}setOptions(e){return this.defaults={...this.defaults,...e},this}lexer(e,t){return x.lex(e,t??this.defaults)}parser(e,t){return b.parse(e,t??this.defaults)}parseMarkdown(e){return(n,s)=>{let i={...s},r={...this.defaults,...i},o=this.onError(!!r.silent,!!r.async);if(this.defaults.async===!0&&i.async===!1)return o(new Error("marked(): The async option was set to true by an extension. Remove async: false from the parse options object to return a Promise."));if(typeof n>"u"||n===null)return o(new Error("marked(): input parameter is undefined or null"));if(typeof n!="string")return o(new Error("marked(): input parameter is of type "+Object.prototype.toString.call(n)+", string expected"));r.hooks&&(r.hooks.options=r,r.hooks.block=e);let a=r.hooks?r.hooks.provideLexer():e?x.lex:x.lexInline,c=r.hooks?r.hooks.provideParser():e?b.parse:b.parseInline;if(r.async)return Promise.resolve(r.hooks?r.hooks.preprocess(n):n).then(p=>a(p,r)).then(p=>r.hooks?r.hooks.processAllTokens(p):p).then(p=>r.walkTokens?Promise.all(this.walkTokens(p,r.walkTokens)).then(()=>p):p).then(p=>c(p,r)).then(p=>r.hooks?r.hooks.postprocess(p):p).catch(o);try{r.hooks&&(n=r.hooks.preprocess(n));let p=a(n,r);r.hooks&&(p=r.hooks.processAllTokens(p)),r.walkTokens&&this.walkTokens(p,r.walkTokens);let u=c(p,r);return r.hooks&&(u=r.hooks.postprocess(u)),u}catch(p){return o(p)}}}onError(e,t){return n=>{if(n.message+=`
Please report this to https://github.com/markedjs/marked.`,e){let s="<p>An error occurred:</p><pre>"+R(n.message+"",!0)+"</pre>";return t?Promise.resolve(s):s}if(t)return Promise.reject(n);throw n}}};var M=new E;function k(l,e){return M.parse(l,e)}k.options=k.setOptions=function(l){return M.setOptions(l),k.defaults=M.defaults,N(k.defaults),k};k.getDefaults=z;k.defaults=w;k.use=function(...l){return M.use(...l),k.defaults=M.defaults,N(k.defaults),k};k.walkTokens=function(l,e){return M.walkTokens(l,e)};k.parseInline=M.parseInline;k.Parser=b;k.parser=b.parse;k.Renderer=$;k.TextRenderer=_;k.Lexer=x;k.lexer=x.lex;k.Tokenizer=S;k.Hooks=L;k.parse=k;var it=k.options,ot=k.setOptions,lt=k.use,at=k.walkTokens,ct=k.parseInline,pt=k,ut=b.parse,ht=x.lex;

if(__exports != exports)module.exports = exports;return module.exports}));

</script>
</head>
<body>

<div class="tab-bar">
  <button class="tab active" onclick="switchTab('browser')" id="tab-browser">Browser</button>
  <button class="tab" onclick="switchTab('telegram')" id="tab-telegram">Telegram</button>
</div>

<div id="browser-view">
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
</div>

<div id="telegram-view" style="display:none">
  <div class="tg-layout">
    <div class="tg-sidebar">
      <div class="tg-sidebar-top">
        <input type="text" class="tg-search" id="tg-search" placeholder="Search chats..." oninput="filterChats()">
      </div>
      <div class="tg-folders" id="tg-folders">
        <button class="tg-folder active" data-folder="user" onclick="setFolder('user')">Private</button>
        <button class="tg-folder" data-folder="group" onclick="setFolder('group')">Groups</button>
        <button class="tg-folder" data-folder="channel" onclick="setFolder('channel')">Channels</button>
        <button class="tg-folder" data-folder="all" onclick="setFolder('all')">All</button>
        <button class="tg-folder" data-folder="unread" onclick="setFolder('unread')">Unread</button>
      </div>
      <div class="tg-chatlist" id="tg-chats">
        <div class="loading"><div class="spinner"></div><div>Loading chats...</div><div class="timer">0.0s</div></div>
      </div>
    </div>
    <div class="tg-main">
      <div class="tg-header">
        <span id="tg-chat-title">Select a chat</span>
      </div>
      <div class="tg-messages" id="tg-messages">
        <div class="tg-empty">Select a chat to start messaging</div>
      </div>
      <div class="tg-reply-bar" id="tg-reply-bar" style="display:none">
        Replying to <span id="tg-reply-to"></span>
        <button onclick="cancelReply()" style="background:none;border:none;color:var(--text-muted);cursor:pointer">&#10005;</button>
      </div>
      <div class="tg-compose">
        <input type="text" id="tg-input" placeholder="Message..." onkeydown="if(event.key==='Enter')sendTgMessage()">
        <button onclick="sendTgMessage()">Send</button>
      </div>
    </div>
  </div>
</div>

<script>
var busy = false, pollTimer = null, loadTimer = null, t0 = 0;
var lastResults = null;
var lastMarkdown = '';

if (typeof marked !== 'undefined') {
  var ioeRenderer = new marked.Renderer();
  ioeRenderer.link = function(token) {
    var href = token.href || '';
    var text = token.text || '';
    if (href.indexOf('http') === 0) {
      return '<a data-ioe-url="' + escHtml(href) + '" href="javascript:void(0)" title="' + escHtml(href) + '" style="color:var(--link);cursor:pointer">' + text + '</a>';
    }
    return '<a href="' + escHtml(href) + '">' + text + '</a>';
  };
  ioeRenderer.image = function(token) {
    var href = token.href || '';
    var text = token.text || '';
    return '<img loading="lazy" src="' + href + '" alt="' + escHtml(text) + '" style="max-width:100%;border-radius:6px;margin:12px 0">';
  };
  marked.setOptions({ renderer: ioeRenderer, breaks: true, gfm: true });
}

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
  var isUrl = q.indexOf('http') === 0 || (q.indexOf('.') > -1 && q.indexOf(' ') === -1 && /\.[a-zA-Z]{2,}/.test(q));
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
  lastMarkdown = '';
  if (fmt === 'markdown' && typeof marked !== 'undefined') {
    bodyContent = marked.parse(body);
    lastMarkdown = body;
  } else if (body.indexOf('<') > -1 && body.indexOf('>') > -1) {
    bodyContent = body;
  } else {
    bodyContent = formatRawText(body);
  }

  var wc = data.word_count || 0;
  var readTime = wc > 0 ? Math.ceil(wc / 200) : 0;
  var metaLine = escHtml(domain) + ' \u00b7 ' + elapsed + 's';
  if (wc > 0) metaLine += ' \u00b7 ' + wc + ' \u0441\u043b\u043e\u0432 \u00b7 ~' + readTime + ' \u043c\u0438\u043d';
  var copyBtn = lastMarkdown ? ' <button onclick="copyMd()" style="background:none;border:1px solid var(--border);color:var(--text-dim);border-radius:4px;padding:2px 8px;font-size:11px;cursor:pointer;font-family:var(--font-ui)">\u{1f4cb} Copy MD</button>' : '';

  content.innerHTML = '<div class="reader">' + backHtml +
    '<div class="reader-meta"><div class="source">' + metaLine + copyBtn + '</div>' +
    (title ? '<h1>' + escHtml(title) + '</h1>' : '') +
    '</div><div class="reader-body" id="readerBody"></div></div>';

  $('readerBody').innerHTML = bodyContent;

  if (fmt !== 'markdown') {
    $('readerBody').querySelectorAll('a[href]').forEach(function(a) {
      var href = a.getAttribute('href');
      if (href && (href.indexOf('http://') === 0 || href.indexOf('https://') === 0)) {
        a.setAttribute('data-ioe-url', href);
        a.setAttribute('href', 'javascript:void(0)');
        a.style.color = 'var(--link)';
        a.style.cursor = 'pointer';
      }
    });
  }

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

function copyMd() {
  if (lastMarkdown && navigator.clipboard) {
    navigator.clipboard.writeText(lastMarkdown).then(function() {
      setStatus('Copied!', 'ok');
    });
  }
}

urlInput.focus();

var currentChatId = null;
var replyToId = null;
var allDialogs = [];
var currentFolder = 'user';
var tgTimers = {};

function makeLoadingHtml(msg) {
  var id = 'lt' + Date.now();
  return {id: id, html: '<div class="loading"><div class="spinner"></div><div>' + escHtml(msg) + '</div><div class="timer" id="' + id + '">0.0s</div></div>'};
}

function startLoadingTimer(timerId) {
  var t = Date.now();
  var iv = setInterval(function() {
    var el = document.getElementById(timerId);
    if (!el) { clearInterval(iv); return; }
    el.textContent = ((Date.now() - t) / 1000).toFixed(1) + 's';
  }, 100);
  tgTimers[timerId] = iv;
  return iv;
}

function switchTab(tab) {
  document.getElementById('browser-view').style.display = tab === 'browser' ? '' : 'none';
  document.getElementById('telegram-view').style.display = tab === 'telegram' ? '' : 'none';
  document.getElementById('tab-browser').className = tab === 'browser' ? 'tab active' : 'tab';
  document.getElementById('tab-telegram').className = tab === 'telegram' ? 'tab active' : 'tab';
  if (tab === 'telegram') loadDialogs();
}

function loadDialogs() {
  var ld = makeLoadingHtml('Loading chats...');
  document.getElementById('tg-chats').innerHTML = ld.html;
  startLoadingTimer(ld.id);
  fetch('/tg?action=get_dialogs&limit=30')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.status === 'pending') {
        pollTgStatus(data.id, function(d) { allDialogs = d.dialogs || []; renderFilteredDialogs(); });
      } else if (data.dialogs) {
        allDialogs = data.dialogs;
        renderFilteredDialogs();
      } else if (data.error) {
        document.getElementById('tg-chats').innerHTML = '<div class="tg-loading">' + escHtml(data.error) + '</div>';
      }
    })
    .catch(function(e) {
      document.getElementById('tg-chats').innerHTML = '<div class="tg-loading">Error: ' + escHtml(String(e)) + '</div>';
    });
}

function pollTgStatus(id, callback) {
  var attempts = 0;
  var poll = setInterval(function() {
    fetch('/status?id=' + id)
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.status === 'ready') { clearInterval(poll); callback(data); }
        else if (data.status === 'error') { clearInterval(poll); alert('Error: ' + (data.error || 'unknown')); }
        if (++attempts > 30) clearInterval(poll);
      });
  }, 2000);
}

function setFolder(folder) {
  currentFolder = folder;
  var btns = document.querySelectorAll('.tg-folder');
  btns.forEach(function(b) { b.className = b.getAttribute('data-folder') === folder ? 'tg-folder active' : 'tg-folder'; });
  renderFilteredDialogs();
}

function filterChats() {
  renderFilteredDialogs();
}

function renderFilteredDialogs() {
  var query = (document.getElementById('tg-search').value || '').toLowerCase();
  var filtered = allDialogs.filter(function(d) {
    if (d.archived && currentFolder !== 'all') return false;
    if (currentFolder === 'unread' && d.unread <= 0) return false;
    if (currentFolder !== 'all' && currentFolder !== 'unread' && d.type !== currentFolder) return false;
    if (query && (d.name || '').toLowerCase().indexOf(query) === -1) return false;
    return true;
  });
  renderDialogs(filtered);
  updateFolderBadges();
}

function updateFolderBadges() {
  var counts = { all: 0, unread: 0, user: 0, group: 0, channel: 0 };
  allDialogs.forEach(function(d) {
    if (d.unread > 0) {
      counts.all += d.unread;
      counts.unread += d.unread;
      if (counts[d.type] !== undefined) counts[d.type] += d.unread;
    }
  });
  document.querySelectorAll('.tg-folder').forEach(function(btn) {
    var f = btn.getAttribute('data-folder');
    var badge = btn.querySelector('.tg-folder-badge');
    var c = counts[f] || 0;
    if (c > 0) {
      if (!badge) { badge = document.createElement('span'); badge.className = 'tg-folder-badge'; btn.appendChild(badge); }
      badge.textContent = c > 99 ? '99+' : c;
    } else if (badge) { badge.remove(); }
  });
}

function chatInitial(name) {
  return (name || '?').charAt(0).toUpperCase();
}

function chatColor(id) {
  var colors = ['#e17076','#7bc862','#e5ca77','#65aadd','#a695e7','#ee7aae','#6ec9cb','#faa774'];
  return colors[Math.abs(id) % colors.length];
}

function formatChatDate(iso) {
  if (!iso) return '';
  var d = new Date(iso);
  var now = new Date();
  if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
  var diff = (now - d) / 86400000;
  if (diff < 7) return ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][d.getDay()];
  return d.toLocaleDateString([], {day:'numeric',month:'short'});
}

function renderDialogs(dialogs) {
  var list = document.getElementById('tg-chats');
  if (!dialogs.length) { list.innerHTML = '<div class="tg-loading">No chats</div>'; return; }
  list.innerHTML = dialogs.map(function(d) {
    var active = d.id === currentChatId ? ' active' : '';
    return '<div class="tg-chat' + active + '" onclick="openChat(' + d.id + ', this)" data-name="' + escAttr(d.name) + '">' +
      '<div class="tg-chat-avatar" style="background:' + chatColor(d.id) + '">' + chatInitial(d.name) + '</div>' +
      '<div class="tg-chat-info">' +
        '<div class="tg-chat-row"><span class="tg-chat-name">' + escHtml(d.name) + '</span><span class="tg-chat-date">' + formatChatDate(d.date) + '</span></div>' +
        '<div class="tg-chat-row"><span class="tg-last-msg">' + escHtml((d.last_message || '').substring(0, 50)) + '</span>' +
        (d.unread > 0 ? '<span class="tg-badge">' + d.unread + '</span>' : '') +
      '</div></div></div>';
  }).join('');
}

function openChat(chatId, el) {
  currentChatId = chatId;
  var name = el ? el.getAttribute('data-name') : document.getElementById('tg-chat-title').textContent;
  document.getElementById('tg-chat-title').textContent = name || 'Chat';
  var ld = makeLoadingHtml('Loading messages...');
  document.getElementById('tg-messages').innerHTML = ld.html;
  startLoadingTimer(ld.id);
  cancelReply();
  renderFilteredDialogs();
  fetch('/tg?action=get_messages&chat_id=' + chatId + '&limit=30')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.status === 'pending') pollTgStatus(data.id, renderMessages);
      else if (data.messages) renderMessages(data);
    });
  fetch('/tg?action=mark_read&chat_id=' + chatId);
}

function formatMsgDate(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString([], { day:'numeric', month:'long', year:'numeric' });
}

function renderMessages(data) {
  var container = document.getElementById('tg-messages');
  var msgs = (data.messages || []).slice().reverse();
  if (!msgs.length) { container.innerHTML = '<div class="tg-empty">No messages</div>'; return; }

  var html = '';
  var lastDate = '';
  var lastSender = '';

  msgs.forEach(function(m) {
    var msgDate = formatMsgDate(m.date);
    if (msgDate !== lastDate) {
      html += '<div class="tg-date-sep"><span>' + escHtml(msgDate) + '</span></div>';
      lastDate = msgDate;
      lastSender = '';
    }

    var isOut = m.out;
    var cls = isOut ? 'tg-bubble tg-bubble-out' : 'tg-bubble tg-bubble-in';
    var showSender = !isOut && m.sender !== lastSender;
    lastSender = m.sender;

    var time = m.date ? new Date(m.date).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) : '';
    var check = isOut ? ' <span class="tg-check">&#10003;&#10003;</span>' : '';

    html += '<div class="' + cls + '" data-id="' + m.id + '" onclick="setReply(' + m.id + ')">';
    if (showSender) html += '<span class="tg-sender">' + escHtml(m.sender || '') + '</span>';
    if (m.reply_to_id) html += '<div class="tg-reply-quote">&#8617; Reply</div>';
    html += '<div class="tg-text">' + escHtml(m.text || '') + '</div>';
    html += '<div class="tg-meta"><span class="tg-time">' + time + '</span>' + check + '</div>';
    html += '</div>';
  });

  container.innerHTML = html;
  container.scrollTop = container.scrollHeight;
}

function setReply(msgId) {
  replyToId = msgId;
  document.getElementById('tg-reply-bar').style.display = 'flex';
  document.getElementById('tg-reply-to').textContent = '#' + msgId;
  document.getElementById('tg-input').focus();
}

function cancelReply() {
  replyToId = null;
  document.getElementById('tg-reply-bar').style.display = 'none';
}

function sendTgMessage() {
  var input = document.getElementById('tg-input');
  var btn = document.querySelector('.tg-compose button');
  var text = input.value.trim();
  if (!text || !currentChatId) return;

  btn.disabled = true; btn.textContent = 'Sending...'; input.disabled = true;

  var url;
  if (replyToId) {
    url = '/tg?action=reply&chat_id=' + currentChatId + '&text=' + encodeURIComponent(text) + '&reply_to_id=' + replyToId;
  } else {
    url = '/tg?action=send_message&chat_id=' + currentChatId + '&text=' + encodeURIComponent(text);
  }

  fetch(url).then(function(r) { return r.json(); }).then(function(data) {
    var done = function() {
      input.value = ''; input.disabled = false; btn.disabled = false; btn.textContent = 'Send';
      cancelReply();
      openChat(currentChatId, null);
    };
    if (data.status === 'pending') { pollTgStatus(data.id, done); }
    else { done(); }
  }).catch(function() {
    input.disabled = false; btn.disabled = false; btn.textContent = 'Send';
  });
}

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
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
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
                        elif resp.get("type") == "command" or "dialogs" in resp or "messages" in resp or "unread_chats" in resp or "message_id" in resp or "auth_status" in resp or "results" not in resp and "body" not in resp:
                            for key in resp:
                                if key not in ("id", "status"):
                                    result[key] = resp[key]
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

        if parsed.path == "/proxy":
            req_id = uuid.uuid4().hex[:8]

            if DEMO_MODE:
                self.respond_json({"status": "error", "error": "proxy not available in demo"})
                return

            method = qs.get("method", ["GET"])[0].upper()
            url = qs.get("url", [""])[0]
            body_str = qs.get("body", [""])[0]
            session_id = qs.get("session_id", [""])[0]
            extract = qs.get("extract", ["true"])[0] != "false"

            req = {
                "id": req_id,
                "type": "http",
                "method": method,
                "url": url,
                "extract": extract,
            }
            if body_str:
                try:
                    req["body"] = json.loads(body_str)
                except (json.JSONDecodeError, ValueError):
                    req["body"] = body_str
            if session_id:
                req["session_id"] = session_id

            try:
                log.info("[%s] proxy: %s %s", req_id, method, url)
                m = imap_conn()
                send_request(m, req)
                m.logout()
            except Exception as e:
                log.error("[%s] proxy send FAILED: %s", req_id, e)
                self.respond_json({"status": "error", "error": str(e)})
                return

            t = threading.Thread(target=poll_response, args=(req_id,), daemon=True)
            t.start()
            self.respond_json({"id": req_id, "status": "pending"})
            return

        if parsed.path == "/tg":
            req_id = uuid.uuid4().hex[:8]
            action = qs.get("action", [""])[0]

            if DEMO_MODE:
                self.respond_json({"status": "error", "error": "telegram not available in demo"})
                return

            req = {
                "id": req_id,
                "type": "command",
                "service": "telegram",
                "action": action,
            }
            for key in qs:
                if key != "action":
                    req[key] = qs[key][0]
            if "chat_id" in req:
                try:
                    req["chat_id"] = int(req["chat_id"])
                except ValueError:
                    pass
            for int_key in ("limit", "reply_to_id", "message_id"):
                if int_key in req:
                    try:
                        req[int_key] = int(req[int_key])
                    except ValueError:
                        pass

            try:
                log.info("[%s] tg: %s", req_id, action)
                m = imap_conn()
                send_request(m, req)
                m.logout()
            except Exception as e:
                log.error("[%s] tg send FAILED: %s", req_id, e)
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
