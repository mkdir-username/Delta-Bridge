from css import login_css


def login_page(error=""):
    error_html = '<div class="login-error">{}</div>'.format(error) if error else ""
    return """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IoE — Login</title>
<style>
:root {{
  --bg-base:#0a0e14; --bg-surface:#161b22; --accent:#4a8fe7;
  --text-main:#c9d1d9; --text-dim:#545d6e;
}}
*, *::before, *::after {{ box-sizing:border-box; margin:0; padding:0; }}
html {{ background:var(--bg-base); color:var(--text-main); height:100%; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif; height:100%; }}
{css}
</style>
</head>
<body>
<div class="login-wrap">
  <div class="login-logo">&#9889;</div>
  <div class="login-title">IoE</div>
  <div class="login-subtitle">internet over email</div>
  <form class="login-form" method="POST" action="/login">
    <input type="text" name="username" placeholder="Username" autocomplete="username" required>
    <input type="password" name="password" placeholder="Password" autocomplete="current-password" required>
    <button type="submit">Войти</button>
  </form>
  {error}
</div>
</body>
</html>""".format(css=login_css(), error=error_html)


HTML_TAB_BAR = """<div class="tab-bar">
  <button class="tab active" onclick="switchTab('browser')" id="tab-browser">Browser</button>
  <button class="tab" onclick="switchTab('telegram')" id="tab-telegram">Telegram<span class="notif-badge" id="notif-badge" style="display:none"></span></button>
</div>
"""

HTML_BROWSER = """<div id="browser-view">
<div class="toolbar">
  <input type="text" id="url" placeholder="URL или поисковый запрос..."
         autocomplete="off" autocapitalize="off" spellcheck="false" value="">
  <button id="btnBrowser" class="toolbar-toggle" onclick="toggleBrowserMode()" title="Browser mode">&#127760;</button>
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
      <div id="tg-auth" style="display:none">
        <div id="auth-step-phone" class="auth-step">
          <div class="auth-title">Telegram</div>
          <div class="auth-hint">Код придёт в SMS, доступ к TG не нужен</div>
          <input type="tel" id="auth-phone" placeholder="+7XXXXXXXXXX" class="tg-search"
                 onkeydown="if(event.key==='Enter')authStart()">
          <button onclick="authStart()" class="auth-btn">Отправить код</button>
          <div id="auth-phone-error" class="auth-error"></div>
        </div>
        <div id="auth-step-code" class="auth-step" style="display:none">
          <div class="auth-title">Код из SMS</div>
          <input type="text" id="auth-code" placeholder="12345" class="tg-search"
                 maxlength="6" inputmode="numeric" onkeydown="if(event.key==='Enter')authCode()">
          <button onclick="authCode()" class="auth-btn">Подтвердить</button>
          <div id="auth-code-error" class="auth-error"></div>
        </div>
        <div id="auth-step-2fa" class="auth-step" style="display:none">
          <div class="auth-title">Двухфакторный пароль</div>
          <input type="password" id="auth-password" placeholder="Пароль" class="tg-search"
                 onkeydown="if(event.key==='Enter')auth2FA()">
          <button onclick="auth2FA()" class="auth-btn">Войти</button>
          <div id="auth-2fa-error" class="auth-error"></div>
        </div>
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
