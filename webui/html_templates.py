HTML_TAB_BAR = """<div class="tab-bar">
  <button class="tab active" onclick="switchTab('browser')" id="tab-browser">Browser</button>
  <button class="tab" onclick="switchTab('telegram')" id="tab-telegram">Telegram<span class="notif-badge" id="notif-badge" style="display:none"></span></button>
</div>
"""

HTML_BROWSER = """<div id="browser-view">
<div class="toolbar">
  <input type="text" id="url" placeholder="URL или поисковый запрос..."
         autocomplete="off" autocapitalize="off" spellcheck="false" value="">
  <button id="btnGo" onclick="go()">&rarr;</button>
  <label class="browser-toggle" title="Headless browser mode">
    <input type="checkbox" id="browserMode" onchange="toggleBrowserMode()">
    <span class="toggle-label">Browser</span>
  </label>
</div>
<div class="kit-bar" id="kit-bar" style="display:none">
  <select id="kit-select" onchange="loadKitActions()"><option value="">Kit...</option></select>
  <select id="kit-action" style="display:none"><option value="">Action...</option></select>
  <button id="kit-run" onclick="runKit()" style="display:none">Run</button>
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
  <span class="user-id" id="userId" onclick="promptUserId()" title="Click to change"></span>
  <span class="channel" id="channelInfo">IMAP</span>
</footer>
</div>
"""

HTML_TELEGRAM = """<div id="telegram-view" style="display:none">
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

"""
