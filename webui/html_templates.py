from css import login_css


def login_page(error=""):
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
body {{ font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Helvetica,Arial,sans-serif; height:100%; }}
{css}
</style>
</head>
<body>
<div class="login-wrap">
  <div class="login-logo">&#9889;</div>
  <div class="login-title">IoE</div>
  <div class="login-subtitle">internet over email</div>

  <div id="step-phone" class="login-form">
    <div class="login-hint">Авторизация через Telegram</div>
    <input type="tel" id="phone" placeholder="+7XXXXXXXXXX" value="+7"
           onkeydown="if(event.key===\'Enter\')authStart()">
    <button onclick="authStart()">Войти через Telegram</button>
    <div id="phone-error" class="login-error"></div>
  </div>

  <div id="step-code" class="login-form" style="display:none">
    <div class="login-hint">Код из Telegram</div>
    <input type="text" id="code" placeholder="12345" maxlength="6" inputmode="numeric"
           onkeydown="if(event.key===\'Enter\')authCode()">
    <button onclick="authCode()">Подтвердить</button>
    <div id="code-error" class="login-error"></div>
  </div>

  <div id="step-2fa" class="login-form" style="display:none">
    <div class="login-hint">Двухфакторный пароль</div>
    <input type="password" id="password2fa" placeholder="Пароль"
           onkeydown="if(event.key===\'Enter\')auth2FA()">
    <button onclick="auth2FA()">Войти</button>
    <div id="2fa-error" class="login-error"></div>
  </div>

  <div id="step-loading" class="login-form" style="display:none">
    <div class="login-hint" id="loading-text">Отправка кода...</div>
    <div class="login-timer" id="loading-timer">0s</div>
    <div id="early-code" style="display:none;margin-top:16px">
      <div class="login-hint">Код пришёл в Telegram? Введите:</div>
      <input type="text" id="early-code-input" placeholder="12345" maxlength="6" inputmode="numeric"
             onkeydown="if(event.key===\'Enter\')earlyCodeSubmit()">
      <button id="early-code-btn" onclick="earlyCodeSubmit()" disabled>Ожидание сервера...</button>
    </div>
  </div>
</div>

<script>
var currentPhone = \'\';
var currentReqId = \'\';
var pollCount = 0;
var pollTimer = null;
var loadingSeconds = 0;
var loadingTimer = null;
var earlyCodeTimer = null;
var serverReady = false;
var earlyCode = \'\';

function showStep(name) {{
  [\'phone\',\'code\',\'2fa\',\'loading\'].forEach(function(s) {{
    document.getElementById(\'step-\'+s).style.display = s===name ? \'\' : \'none\';
  }});
}}

function showLoading(text) {{
  document.getElementById(\'loading-text\').textContent = text;
  loadingSeconds = 0;
  document.getElementById(\'loading-timer\').textContent = \'0s\';
  showStep(\'loading\');
  if (loadingTimer) clearInterval(loadingTimer);
  loadingTimer = setInterval(function() {{
    loadingSeconds++;
    document.getElementById(\'loading-timer\').textContent = loadingSeconds + \'s\';
  }}, 1000);
}}

function stopLoading() {{
  if (loadingTimer) {{ clearInterval(loadingTimer); loadingTimer = null; }}
  if (earlyCodeTimer) {{ clearTimeout(earlyCodeTimer); earlyCodeTimer = null; }}
  document.getElementById(\'early-code\').style.display = \'none\';
}}

function earlyCodeSubmit() {{
  var code = document.getElementById(\'early-code-input\').value.trim();
  if (!code) return;
  if (serverReady) {{
    document.getElementById(\'code\').value = code;
    stopLoading();
    showStep(\'code\');
    authCode();
  }} else {{
    earlyCode = code;
    document.getElementById(\'early-code-btn\').textContent = \'Код сохранён, ожидание...\';
  }}
}}

function authStart() {{
  var phone = document.getElementById(\'phone\').value.trim();
  if (!phone) return;
  document.getElementById(\'phone-error\').textContent = \'\';
  currentPhone = phone;
  serverReady = false;
  earlyCode = \'\';
  showLoading(\'Отправка кода...\');
  earlyCodeTimer = setTimeout(function() {{
    document.getElementById(\'early-code\').style.display = \'\';
    document.getElementById(\'early-code-input\').focus();
  }}, 5000);
  fetch(\'/login/tg\', {{method:\'POST\', headers:{{\'Content-Type\':\'application/json\'}}, body:JSON.stringify({{action:\'auth_start\', phone:phone}})}})
    .then(function(r) {{ return r.json(); }})
    .then(function(d) {{
      if (d.status === \'error\') {{
        stopLoading();
        showStep(\'phone\');
        document.getElementById(\'phone-error\').textContent = d.error;
        return;
      }}
      currentReqId = d.id;
      pollCount = 0;
      pollStatus(function(resp) {{
        stopLoading();
        if (resp.auth_status === \'code_required\' || resp.status === \'ready\') {{
          serverReady = true;
          var ecBtn = document.getElementById(\'early-code-btn\');
          ecBtn.disabled = false;
          ecBtn.textContent = \'Подтвердить\';
          if (earlyCode) {{
            document.getElementById(\'code\').value = earlyCode;
            showStep(\'code\');
            authCode();
            return;
          }}
          showStep(\'code\');
          document.getElementById(\'code\').focus();
        }} else if (resp.auth_status === \'flood_wait\') {{
          showStep(\'phone\');
          var mins = Math.ceil((resp.seconds || 60) / 60);
          document.getElementById(\'phone-error\').textContent = \'Подождите \' + mins + \' мин\';
        }} else {{
          showStep(\'phone\');
          document.getElementById(\'phone-error\').textContent = resp.error || \'Ошибка\';
        }}
      }});
    }})
    .catch(function() {{
      stopLoading();
      showStep(\'phone\');
      document.getElementById(\'phone-error\').textContent = \'Нет связи с сервером\';
    }});
}}

function authCode() {{
  var code = document.getElementById(\'code\').value.trim();
  if (!code) return;
  document.getElementById(\'code-error\').textContent = \'\';
  showLoading(\'Проверка кода...\');
  fetch(\'/login/tg\', {{method:\'POST\', headers:{{\'Content-Type\':\'application/json\'}}, body:JSON.stringify({{action:\'auth_code\', code:code, phone:currentPhone}})}})
    .then(function(r) {{ return r.json(); }})
    .then(function(d) {{
      if (d.status === \'error\') {{
        stopLoading();
        showStep(\'code\');
        document.getElementById(\'code-error\').textContent = d.error;
        return;
      }}
      currentReqId = d.id;
      pollCount = 0;
      pollStatus(function(resp) {{
        stopLoading();
        if (resp.auth_status === \'authorized\' && resp.set_session) {{
          window.location.href = \'/\';
        }} else if (resp.auth_status === \'2fa_required\') {{
          showStep(\'2fa\');
          document.getElementById(\'password2fa\').focus();
        }} else {{
          showStep(\'code\');
          document.getElementById(\'code-error\').textContent = resp.error || \'Неверный код\';
        }}
      }});
    }})
    .catch(function() {{
      stopLoading();
      showStep(\'code\');
      document.getElementById(\'code-error\').textContent = \'Нет связи с сервером\';
    }});
}}

function auth2FA() {{
  var pw = document.getElementById(\'password2fa\').value.trim();
  if (!pw) return;
  document.getElementById(\'2fa-error\').textContent = \'\';
  showLoading(\'Проверка пароля...\');
  fetch(\'/login/tg\', {{method:\'POST\', headers:{{\'Content-Type\':\'application/json\'}}, body:JSON.stringify({{action:\'auth_code\', password:pw, phone:currentPhone}})}})
    .then(function(r) {{ return r.json(); }})
    .then(function(d) {{
      if (d.status === \'error\') {{
        stopLoading();
        showStep(\'2fa\');
        document.getElementById(\'2fa-error\').textContent = d.error;
        return;
      }}
      currentReqId = d.id;
      pollCount = 0;
      pollStatus(function(resp) {{
        stopLoading();
        if (resp.auth_status === \'authorized\' && resp.set_session) {{
          window.location.href = \'/\';
        }} else {{
          showStep(\'2fa\');
          document.getElementById(\'2fa-error\').textContent = resp.error || \'Неверный пароль\';
        }}
      }});
    }})
    .catch(function() {{
      stopLoading();
      showStep(\'2fa\');
      document.getElementById(\'2fa-error\').textContent = \'Нет связи с сервером\';
    }});
}}

function pollStatus(callback) {{
  if (pollTimer) clearTimeout(pollTimer);
  pollCount++;
  if (pollCount > 60) {{
    stopLoading();
    showStep(\'phone\');
    document.getElementById(\'phone-error\').textContent = \'Таймаут ожидания\';
    return;
  }}
  fetch(\'/login/status?id=\'+encodeURIComponent(currentReqId))
    .then(function(r) {{ return r.json(); }})
    .then(function(d) {{
      if (d.status === \'pending\') {{
        pollTimer = setTimeout(function() {{ pollStatus(callback); }}, 2000);
      }} else {{
        callback(d);
      }}
    }})
    .catch(function() {{
      pollTimer = setTimeout(function() {{ pollStatus(callback); }}, 2000);
    }});
}}
</script>
</body>
</html>""".format(css=login_css())


HTML_TAB_BAR = """<div class="tab-bar">
  <button class="tab active" onclick="switchTab('browser')" id="tab-browser">Browser</button>
  <button class="tab" onclick="switchTab('telegram')" id="tab-telegram">Telegram<span class="notif-badge" id="notif-badge" style="display:none"></span></button>
  <button class="tab" onclick="switchTab('claude')" id="tab-claude">Claude</button>
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
          <input type="tel" id="auth-phone" placeholder="+7XXXXXXXXXX" value="+7" class="tg-search"
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

HTML_CLAUDE = """<div id="claude-view" style="display:none">
  <div class="claude-layout">
    <div class="claude-auth" id="claude-auth" style="display:none">
      <div class="claude-auth-box">
        <div class="claude-auth-title">Claude Chat</div>
        <div class="claude-auth-desc">Checking authorization...</div>
        <button class="claude-auth-btn" id="claude-login-btn" style="display:none">Login</button>
        <div id="claude-auth-url" style="display:none"></div>
      </div>
    </div>
    <div class="claude-chat" id="claude-chat" style="display:none">
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
