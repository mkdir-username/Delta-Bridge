from __future__ import annotations

from css import login_css


def login_page(error: str = "") -> str:
    return f"""<!DOCTYPE html>
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
body {{ font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Helvetica,Arial,sans-serif; height:100%; }}
.hidden {{ display: none; }}
{login_css()}
</style>
</head>
<body>
<div class="login-wrap">
  <div class="login-logo">&#9889;</div>
  <div class="login-title">IoE</div>
  <div class="login-subtitle">internet over email</div>

  <div id="step-phone" class="login-form">
    <div class="login-hint">\u041a\u043e\u0434 \u043f\u0440\u0438\u0434\u0451\u0442 \u043d\u0430 \u043f\u0440\u0438\u0432\u044f\u0437\u0430\u043d\u043d\u044b\u0439 email</div>
    <input type="tel" id="phone" placeholder="+7XXXXXXXXXX" value="+7"
           data-enter="login-auth-start">
    <button data-action="login-auth-start">\u041f\u043e\u043b\u0443\u0447\u0438\u0442\u044c \u043a\u043e\u0434</button>
    <div id="phone-error" class="login-error"></div>
  </div>

  <div id="step-code" class="login-form hidden">
    <div class="login-hint" id="code-hint">\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043a\u043e\u0434 \u0438\u0437 email</div>
    <input type="text" id="code" placeholder="123456" maxlength="6" inputmode="numeric"
           data-enter="login-auth-code">
    <button data-action="login-auth-code">\u0412\u043e\u0439\u0442\u0438</button>
    <div id="code-error" class="login-error"></div>
  </div>
</div>

<script>
var currentPhone = \'\';

function showStep(name) {{
  [\'phone\',\'code\'].forEach(function(s) {{
    var el = document.getElementById(\'step-\'+s);
    if (s===name) el.classList.remove(\'hidden\'); else el.classList.add(\'hidden\');
  }});
}}

function authStart() {{
  var phone = document.getElementById(\'phone\').value.trim();
  if (!phone) return;
  document.getElementById(\'phone-error\').textContent = \'\';
  currentPhone = phone;
  var btn = document.querySelector(\'#step-phone button\');
  btn.textContent = \'\u041e\u0442\u043f\u0440\u0430\u0432\u043a\u0430...\';
  btn.disabled = true;
  fetch(\'/login/email\', {{method:\'POST\', headers:{{\'Content-Type\':\'application/json\'}}, body:JSON.stringify({{action:\'send_code\', phone:phone}})}})
    .then(function(r) {{ return r.json(); }})
    .then(function(d) {{
      btn.textContent = \'\u041f\u043e\u043b\u0443\u0447\u0438\u0442\u044c \u043a\u043e\u0434\';
      btn.disabled = false;
      if (d.status === \'error\') {{
        document.getElementById(\'phone-error\').textContent = d.error;
        return;
      }}
      if (d.email) document.getElementById(\'code-hint\').textContent = \'\u041a\u043e\u0434 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d \u043d\u0430 \' + d.email;
      showStep(\'code\');
      document.getElementById(\'code\').focus();
    }})
    .catch(function() {{
      btn.textContent = \'\u041f\u043e\u043b\u0443\u0447\u0438\u0442\u044c \u043a\u043e\u0434\';
      btn.disabled = false;
      document.getElementById(\'phone-error\').textContent = \'\u041d\u0435\u0442 \u0441\u0432\u044f\u0437\u0438 \u0441 \u0441\u0435\u0440\u0432\u0435\u0440\u043e\u043c\';
    }});
}}

function authCode() {{
  var code = document.getElementById(\'code\').value.trim();
  if (!code) return;
  document.getElementById(\'code-error\').textContent = \'\';
  var btn = document.querySelector(\'#step-code button\');
  btn.textContent = \'\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430...\';
  btn.disabled = true;
  fetch(\'/login/email\', {{method:\'POST\', headers:{{\'Content-Type\':\'application/json\'}}, body:JSON.stringify({{action:\'verify_code\', phone:currentPhone, code:code}})}})
    .then(function(r) {{ return r.json(); }})
    .then(function(d) {{
      btn.textContent = \'\u0412\u043e\u0439\u0442\u0438\';
      btn.disabled = false;
      if (d.status === \'authorized\') {{
        window.location.href = \'/\';
        return;
      }}
      document.getElementById(\'code-error\').textContent = d.error || \'\u041d\u0435\u0432\u0435\u0440\u043d\u044b\u0439 \u043a\u043e\u0434\';
    }})
    .catch(function() {{
      btn.textContent = \'\u0412\u043e\u0439\u0442\u0438\';
      btn.disabled = false;
      document.getElementById(\'code-error\').textContent = \'\u041d\u0435\u0442 \u0441\u0432\u044f\u0437\u0438 \u0441 \u0441\u0435\u0440\u0432\u0435\u0440\u043e\u043c\';
    }});
}}

document.addEventListener(\'click\', function(e) {{
  var t = e.target.closest(\'[data-action]\');
  if (!t) return;
  var a = t.dataset.action;
  if (a === \'login-auth-start\') authStart();
  else if (a === \'login-auth-code\') authCode();
}});
document.addEventListener(\'keydown\', function(e) {{
  if (e.key !== \'Enter\') return;
  var t = e.target.closest(\'[data-enter]\');
  if (!t) return;
  var a = t.dataset.enter;
  if (a === \'login-auth-start\') authStart();
  else if (a === \'login-auth-code\') authCode();
}});
</script>
</body>
</html>"""


HTML_TAB_BAR = """<div class="tab-bar">
  <button class="tab active" data-action="switch-tab-browser" id="tab-browser">Browser</button>
  <button class="tab" data-action="switch-tab-telegram" id="tab-telegram">Telegram<span class="notif-badge hidden" id="notif-badge"></span></button>
  <button class="tab" data-action="switch-tab-claude" id="tab-claude">Claude</button>
</div>
"""

HTML_BROWSER = """<div id="browser-view">
<div class="toolbar">
  <input type="text" id="url" placeholder="URL или поисковый запрос..."
         autocomplete="off" autocapitalize="off" spellcheck="false" value="">
  <button id="btnBrowser" class="toolbar-toggle" data-action="toggle-browser-mode" title="Browser mode">&#127760;</button>
  <button id="btnGo" data-action="go">&rarr;</button>
</div>

<main id="content">
  <div class="empty">
    <div class="logo">&#9889;</div>
    <div class="title">IoE</div>
    <div class="sub">internet over email</div>
  </div>
</main>

<button class="scroll-top" id="scrollTop" data-action="scroll-top">&uarr;</button>

<footer>
  <div class="status">
    <span class="dot"></span>
    <span id="statusText">Ready</span>
  </div>
  <span class="channel" id="channelInfo">IMAP</span>
</footer>
</div>
"""

HTML_TELEGRAM = """<div id="telegram-view" class="hidden">
  <div class="tg-layout">
    <div class="tg-sidebar">
      <div class="tg-sidebar-top">
        <input type="text" class="tg-search" id="tg-search" placeholder="Search chats..." data-input="filter-chats">
      </div>
      <div class="tg-folders" id="tg-folders">
        <button class="tg-folder active" data-folder="user" data-action="set-folder-user">Private</button>
        <button class="tg-folder" data-folder="group" data-action="set-folder-group">Groups</button>
        <button class="tg-folder" data-folder="channel" data-action="set-folder-channel">Channels</button>
        <button class="tg-folder" data-folder="all" data-action="set-folder-all">All</button>
        <button class="tg-folder" data-folder="unread" data-action="set-folder-unread">Unread</button>
      </div>
      <div id="tg-auth" class="hidden">
        <div id="auth-step-phone" class="auth-step">
          <div class="auth-title">Telegram</div>
          <div class="auth-hint">Код придёт в SMS, доступ к TG не нужен</div>
          <input type="tel" id="auth-phone" placeholder="+7XXXXXXXXXX" value="+7" class="tg-search"
                 data-enter="tg-auth-start">
          <button data-action="tg-auth-start" class="auth-btn">Отправить код</button>
          <div id="auth-phone-error" class="auth-error"></div>
        </div>
        <div id="auth-step-code" class="auth-step hidden">
          <div class="auth-title">Код из SMS</div>
          <input type="text" id="auth-code" placeholder="12345" class="tg-search"
                 maxlength="6" inputmode="numeric" data-enter="tg-auth-code">
          <button data-action="tg-auth-code" class="auth-btn">Подтвердить</button>
          <div id="auth-code-error" class="auth-error"></div>
        </div>
        <div id="auth-step-2fa" class="auth-step hidden">
          <div class="auth-title">Двухфакторный пароль</div>
          <input type="password" id="auth-password" placeholder="Пароль" class="tg-search"
                 data-enter="tg-auth-2fa">
          <button data-action="tg-auth-2fa" class="auth-btn">Войти</button>
          <div id="auth-2fa-error" class="auth-error"></div>
        </div>
      </div>
      <div class="tg-chatlist" id="tg-chats">
        <div class="loading"><div class="spinner"></div><div>Loading chats...</div><div class="timer">0.0s</div></div>
      </div>
      <div class="tg-sidebar-bottom" id="tg-sidebar-bottom">
        <button id="tg-logout-btn" class="tg-logout-btn" data-action="tg-logout">Выйти</button>
      </div>
    </div>
    <div class="tg-main">
      <div class="tg-header">
        <span id="tg-chat-title">Select a chat</span>
      </div>
      <div class="tg-messages" id="tg-messages">
        <div class="tg-empty">Select a chat to start messaging</div>
      </div>
      <div class="tg-reply-bar hidden" id="tg-reply-bar">
        Replying to <span id="tg-reply-to"></span>
        <button data-action="cancel-reply" class="cancel-reply-btn">&#10005;</button>
      </div>
      <div class="tg-compose">
        <input type="text" id="tg-input" placeholder="Message..." data-enter="send-tg-message">
        <button data-action="send-tg-message">Send</button>
      </div>
    </div>
  </div>
</div>

"""

HTML_CLAUDE = """<div id="claude-view" class="hidden">
  <div class="claude-layout">
    <div class="claude-auth hidden" id="claude-auth">
      <div class="claude-auth-box">
        <div class="claude-auth-title">Claude Chat</div>
        <div class="claude-auth-desc">Checking authorization...</div>
        <button class="claude-auth-btn hidden" id="claude-login-btn">Login</button>
        <div class="hidden" id="claude-auth-url"></div>
      </div>
    </div>
    <div class="claude-chat hidden" id="claude-chat">
      <div class="claude-header">
        <span class="claude-title">Claude</span>
        <span class="claude-model-label" id="claude-model-label"></span>
        <button class="claude-new-btn" id="claude-new-btn" title="New conversation">&#x21bb;</button>
      </div>
      <div class="claude-messages" id="claude-messages"></div>
      <div class="claude-compose">
        <textarea id="claude-input" placeholder="Type your message..." rows="2"></textarea>
        <div class="claude-compose-row">
          <select id="claude-model">
            <option value="sonnet" selected>Sonnet</option>
            <option value="opus">Opus</option>
            <option value="haiku">Haiku</option>
          </select>
          <button id="claude-send-btn">Send</button>
        </div>
      </div>
    </div>
  </div>
</div>
"""
