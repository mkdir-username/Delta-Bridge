CSS = """/* === Reset & Base === */
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
.kit-bar { display: flex; gap: 8px; padding: 4px 12px; background: var(--bg-surface); border-bottom: 1px solid var(--border); }
.kit-bar select { background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 4px 8px; font-size: 13px; }
.kit-bar button { background: var(--accent); color: #fff; border: none; border-radius: 4px; padding: 4px 12px; cursor: pointer; font-size: 13px; }

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
.user-id { font-size: 11px; color: var(--text-muted); opacity: 0.7; cursor: pointer; padding: 2px 6px; border-radius: 4px; }
.user-id:hover { opacity: 1; background: rgba(255,255,255,0.1); }

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
.notif-badge { display:inline-block; background:#e74c3c; color:#fff; border-radius:50%; min-width:18px; height:18px; font-size:11px; line-height:18px; text-align:center; margin-left:6px; vertical-align:middle; }

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
"""
