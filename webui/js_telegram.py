JS_TELEGRAM = r"""var currentChatId = null;
var replyToId = null;
var allDialogs = [];
var currentFolder = 'user';
var tgTimers = {};
var _tgCheckStarted = false;
var _retryTimer = null;
var _retryAttempt = 0;
var _retryDelays = [5000, 15000, 30000, 60000];
var tgAuthResult = null;
var tgAuthStartTime = null;

function bgCheckTgAuth() {
  tgAuthStartTime = Date.now();
  _tgCheckStarted = true;
  fetch('/tg?action=check_auth')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.status === 'error') {
        tgAuthResult = data.error_type === 'transport' ? 'transport_error' : 'wizard';
        applyTgAuthIfVisible();
        return;
      }
      if (data.status === 'pending') {
        pollTgStatus(data.id, function(d) {
          if (d.error_type === 'transport') { tgAuthResult = 'transport_error'; }
          else if (d.authorized) { tgAuthResult = 'authorized'; }
          else { tgAuthResult = 'wizard'; }
          applyTgAuthIfVisible();
        }, true);
      } else if (data.authorized) {
        tgAuthResult = 'authorized';
        applyTgAuthIfVisible();
      } else {
        tgAuthResult = 'wizard';
        applyTgAuthIfVisible();
      }
    })
    .catch(function() {
      tgAuthResult = 'transport_error';
      applyTgAuthIfVisible();
    });
}

function applyTgAuthIfVisible() {
  if (document.getElementById('telegram-view').style.display === 'none') return;
  _tgCheckStarted = false;
  if (tgAuthResult === 'authorized') { _retryAttempt = 0; showTgMain(); loadDialogs(); }
  else if (tgAuthResult === 'wizard') { showAuthWizard(); }
  else if (tgAuthResult === 'transport_error') { showTransportError('Нет связи с сервером'); }
}

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
  document.getElementById('claude-view').style.display = tab === 'claude' ? '' : 'none';
  document.getElementById('tab-browser').className = tab === 'browser' ? 'tab active' : 'tab';
  document.getElementById('tab-telegram').className = tab === 'telegram' ? 'tab active' : 'tab';
  document.getElementById('tab-claude').className = tab === 'claude' ? 'tab active' : 'tab';
  if (tab === 'telegram') { if (!_tgCheckStarted) checkTgAuth(); notifCount = 0; var b = document.getElementById('notif-badge'); if (b) b.style.display = 'none'; }
  if (tab === 'claude' && !claudeAuthorized) { checkClaudeAuth(); }
}

function loadDialogs() {
  var ld = makeLoadingHtml('Loading chats...');
  document.getElementById('tg-chats').innerHTML = ld.html;
  startLoadingTimer(ld.id);
  fetch('/tg?action=get_dialogs&limit=30')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.status === 'pending') {
        pollTgStatus(data.id, function(d) {
          if (d.error) { showTgError(d.error); }
          else { allDialogs = d.dialogs || []; renderFilteredDialogs(); }
        });
      } else if (data.dialogs) {
        allDialogs = data.dialogs;
        renderFilteredDialogs();
      } else if (data.error_type === 'auth' || data.auth_required || (data.error && data.error.indexOf('not registered') !== -1)) {
        showAuthWizard();
      } else if (data.error_type === 'transport') {
        showTransportError(data.error);
      } else if (data.error) {
        showTgError(data.error);
      }
    })
    .catch(function(e) {
      showTgError(String(e));
    });
}

function pollTgStatus(id, callback, isAuthRequest) {
  var attempts = 0;
  var poll = setInterval(function() {
    fetch('/status?id=' + id)
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.status === 'ready') {
          clearInterval(poll);
          if (data.auth_required || data.error_type === 'auth') { showAuthWizard(); }
          else { callback(data); }
        }
        else if (data.status === 'error') {
          clearInterval(poll);
          if (data.error_type === 'auth') { showAuthWizard(); }
          else { callback({error: data.error || 'unknown', error_type: data.error_type || 'vps'}); }
        }
        if (++attempts > 30) {
          clearInterval(poll);
          callback({error: 'Сервер не отвечает', error_type: 'transport'});
        }
      })
      .catch(function() {
        if (++attempts > 5) {
          clearInterval(poll);
          callback({error: 'Нет связи', error_type: 'transport'});
        }
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
    if (d.archived && currentFolder === 'user') return false;
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
    })
    .catch(function() {
      document.getElementById('tg-messages').textContent = 'Ошибка загрузки сообщений';
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

var notifCount = 0;

function pollNotifications() {
  fetch('/notifications')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.notifications && data.notifications.length > 0) {
        notifCount += data.notifications.length;
        var badge = document.getElementById('notif-badge');
        if (badge) {
          badge.textContent = notifCount;
          badge.style.display = '';
        }
      }
    })
    .catch(function() {});
}

function scheduleNotifPoll() {
  setTimeout(function() { pollNotifications(); scheduleNotifPoll(); }, 4000 + Math.random() * 2000);
}
scheduleNotifPoll();
checkTgAuth();

function _clearTgTimers() {
  Object.keys(tgTimers).forEach(function(k) { clearInterval(tgTimers[k]); delete tgTimers[k]; });
  if (_retryTimer) { clearInterval(_retryTimer); _retryTimer = null; }
}

function showTransportError(msg) {
  _clearTgTimers();
  var delay = _retryDelays[Math.min(_retryAttempt, _retryDelays.length - 1)];
  var secs = Math.ceil(delay / 1000);
  _retryAttempt++;
  var el = document.getElementById('tg-chats');
  el.style.display = '';
  el.textContent = '';
  var wrap = document.createElement('div');
  wrap.style.cssText = 'padding:24px;color:var(--text-dim);text-align:center';
  wrap.appendChild(document.createTextNode(msg || 'Сервер недоступен'));
  var countdown = document.createElement('div');
  countdown.style.cssText = 'margin-top:8px;font-size:12px';
  countdown.textContent = 'Повтор через ' + secs + 's';
  wrap.appendChild(countdown);
  var btn = document.createElement('button');
  btn.className = 'auth-btn';
  btn.style.marginTop = '12px';
  btn.textContent = 'Повторить сейчас';
  btn.onclick = retryTgAuth;
  wrap.appendChild(btn);
  el.appendChild(wrap);
  var remaining = secs;
  _retryTimer = setInterval(function() {
    remaining--;
    countdown.textContent = 'Повтор через ' + remaining + 's';
    if (remaining <= 0) { clearInterval(_retryTimer); _retryTimer = null; checkTgAuth(); }
  }, 1000);
}

function retryTgAuth() {
  if (_retryTimer) { clearInterval(_retryTimer); _retryTimer = null; }
  checkTgAuth();
}

function showTgError(msg) {
  var el = document.getElementById('tg-chats');
  el.textContent = '';
  var wrap = document.createElement('div');
  wrap.style.cssText = 'padding:24px;color:var(--text-dim);text-align:center';
  wrap.appendChild(document.createTextNode(msg || 'Ошибка'));
  wrap.appendChild(document.createElement('br'));
  var btn = document.createElement('button');
  btn.className = 'auth-btn';
  btn.style.marginTop = '12px';
  btn.textContent = 'Повторить';
  btn.onclick = function() { checkTgAuth(); };
  wrap.appendChild(btn);
  el.appendChild(wrap);
}

function checkTgAuth() {
  if (tgAuthResult === 'authorized') { _retryAttempt = 0; showTgMain(); loadDialogs(); return; }
  if (tgAuthResult === 'wizard') { showAuthWizard(); return; }
  if (tgAuthResult === 'transport_error') { showTransportError('Нет связи с сервером'); return; }
  var ld = makeLoadingHtml('Проверка авторизации...');
  document.getElementById('tg-chats').textContent = '';
  var container = document.createElement('div');
  container.className = 'loading';
  var spinner = document.createElement('div');
  spinner.className = 'spinner';
  container.appendChild(spinner);
  var msg = document.createElement('div');
  msg.textContent = 'Проверка авторизации...';
  container.appendChild(msg);
  var timer = document.createElement('div');
  timer.className = 'timer';
  timer.id = ld.id;
  timer.textContent = '0.0s';
  container.appendChild(timer);
  document.getElementById('tg-chats').appendChild(container);
  if (tgAuthStartTime) {
    var offset = tgAuthStartTime;
    var iv = setInterval(function() {
      var el = document.getElementById(ld.id);
      if (!el) { clearInterval(iv); return; }
      el.textContent = ((Date.now() - offset) / 1000).toFixed(1) + 's';
    }, 100);
    tgTimers[ld.id] = iv;
  } else {
    startLoadingTimer(ld.id);
  }
}

function showAuthWizard() {
  _clearTgTimers(); _tgCheckStarted = false;
  document.getElementById('tg-auth').style.display = '';
  document.getElementById('tg-chats').style.display = 'none';
  document.getElementById('tg-folders').style.display = 'none';
  var top = document.querySelector('.tg-sidebar-top');
  if (top) top.style.display = 'none';
  var bot = document.getElementById('tg-sidebar-bottom'); if (bot) bot.style.display = 'none';
  document.getElementById('auth-step-phone').style.display = '';
  document.getElementById('auth-step-code').style.display = 'none';
  document.getElementById('auth-step-2fa').style.display = 'none';
}

function showTgMain() {
  _clearTgTimers(); _tgCheckStarted = false;
  document.getElementById('tg-auth').style.display = 'none';
  document.getElementById('tg-chats').style.display = '';
  document.getElementById('tg-folders').style.display = '';
  var top = document.querySelector('.tg-sidebar-top');
  if (top) top.style.display = '';
  var bot = document.getElementById('tg-sidebar-bottom'); if (bot) bot.style.display = '';
}

function logoutTelegram() {
  if (!confirm('Выйти из Telegram?')) return;
  var btn = document.getElementById('tg-logout-btn');
  if (btn) btn.disabled = true;
  fetch('/tg', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action:'auth_logout'})})
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.status === 'pending') { pollTgStatus(data.id, handleLogoutResult, true); }
      else { handleLogoutResult(data); }
    })
    .catch(function() { handleLogoutResult({}); });
}

function handleLogoutResult() {
  currentChatId = null;
  replyToId = null;
  allDialogs = [];
  document.getElementById('tg-messages').textContent = '';
  var btn = document.getElementById('tg-logout-btn');
  if (btn) btn.disabled = false;
  _tgCheckStarted = false;
  showAuthWizard();
}

function authStart() {
  var phone = document.getElementById('auth-phone').value.trim();
  if (!phone) return;
  var btn = document.querySelector('#auth-step-phone .auth-btn');
  btn.textContent = '...';
  document.getElementById('auth-phone-error').textContent = '';
  fetch('/tg', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action:'auth_start', phone:phone})})
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.status === 'pending') {
        pollTgStatus(data.id, handleAuthStartResult, true);
      } else {
        handleAuthStartResult(data);
      }
    })
    .catch(function(e) {
      btn.textContent = 'Отправить код';
      document.getElementById('auth-phone-error').textContent = 'Сеть недоступна';
    });
}

function handleAuthStartResult(data) {
  document.querySelector('#auth-step-phone .auth-btn').textContent = 'Отправить код';
  if (data.auth_status === 'code_required' || data.status === 200) {
    document.getElementById('auth-step-phone').style.display = 'none';
    document.getElementById('auth-step-code').style.display = '';
    document.getElementById('auth-code').focus();
  } else {
    document.getElementById('auth-phone-error').textContent = data.error || 'Ошибка';
  }
}

function authCode() {
  var code = document.getElementById('auth-code').value.trim();
  if (!code) return;
  var btn = document.querySelector('#auth-step-code .auth-btn');
  btn.textContent = '...';
  document.getElementById('auth-code-error').textContent = '';
  fetch('/tg', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action:'auth_code', code:code})})
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.status === 'pending') {
        pollTgStatus(data.id, handleAuthCodeResult, true);
      } else {
        handleAuthCodeResult(data);
      }
    })
    .catch(function() {
      btn.textContent = 'Подтвердить';
      document.getElementById('auth-code-error').textContent = 'Сеть недоступна';
    });
}

function handleAuthCodeResult(data) {
  document.querySelector('#auth-step-code .auth-btn').textContent = 'Подтвердить';
  if (data.auth_status === 'authorized') {
    tgAuthResult = 'authorized';
    showTgMain(); loadDialogs();
  } else if (data.auth_status === '2fa_required') {
    document.getElementById('auth-step-code').style.display = 'none';
    document.getElementById('auth-step-2fa').style.display = '';
    document.getElementById('auth-password').focus();
  } else if (data.auth_status === 'invalid_code') {
    document.getElementById('auth-code-error').textContent = 'Неверный код';
    document.getElementById('auth-code').value = '';
    document.getElementById('auth-code').focus();
  } else if (data.auth_status === 'flood_wait') {
    document.getElementById('auth-code-error').textContent = 'Подожди ' + (data.seconds || '?') + ' сек';
  } else {
    document.getElementById('auth-code-error').textContent = data.error || 'Ошибка';
  }
}

function auth2FA() {
  var pw = document.getElementById('auth-password').value;
  if (!pw) return;
  var btn = document.querySelector('#auth-step-2fa .auth-btn');
  btn.textContent = '...';
  document.getElementById('auth-2fa-error').textContent = '';
  fetch('/tg', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action:'auth_code', password:pw})})
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.status === 'pending') {
        pollTgStatus(data.id, handleAuth2FAResult, true);
      } else {
        handleAuth2FAResult(data);
      }
    })
    .catch(function() {
      btn.textContent = 'Войти';
      document.getElementById('auth-2fa-error').textContent = 'Сеть недоступна';
    });
}

function handleAuth2FAResult(data) {
  document.querySelector('#auth-step-2fa .auth-btn').textContent = 'Войти';
  if (data.auth_status === 'authorized') {
    tgAuthResult = 'authorized';
    showTgMain(); loadDialogs();
  } else {
    document.getElementById('auth-2fa-error').textContent = data.error || 'Неверный пароль';
  }
}

bgCheckTgAuth();

document.addEventListener('click', function(e) {
  var t = e.target.closest('[data-action]');
  if (!t) return;
  var a = t.dataset.action;
  if (a === 'tg-auth-start') authStart();
  else if (a === 'tg-auth-code') authCode();
  else if (a === 'tg-auth-2fa') auth2FA();
  else if (a === 'tg-logout') logoutTelegram();
  else if (a === 'cancel-reply') cancelReply();
  else if (a === 'send-tg-message') sendTgMessage();
  else if (a.startsWith('set-folder-')) setFolder(a.replace('set-folder-', ''));
});
document.addEventListener('keydown', function(e) {
  if (e.key !== 'Enter') return;
  var t = e.target.closest('[data-enter]');
  if (!t) return;
  var a = t.dataset.enter;
  if (a === 'tg-auth-start') authStart();
  else if (a === 'tg-auth-code') authCode();
  else if (a === 'tg-auth-2fa') auth2FA();
  else if (a === 'send-tg-message') sendTgMessage();
});
document.addEventListener('input', function(e) {
  if (e.target.closest('[data-input="filter-chats"]')) filterChats();
});

"""
