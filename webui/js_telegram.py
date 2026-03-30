JS_TELEGRAM = r"""var currentChatId = null;
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
  if (tab === 'telegram') { loadDialogs(); notifCount = 0; var b = document.getElementById('notif-badge'); if (b) b.style.display = 'none'; }
}

function loadDialogs() {
  var ld = makeLoadingHtml('Loading chats...');
  document.getElementById('tg-chats').innerHTML = ld.html;
  startLoadingTimer(ld.id);
  fetch('/tg?action=get_dialogs&limit=30&user_id=' + encodeURIComponent(userId))
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
  fetch('/tg?action=get_messages&chat_id=' + chatId + '&limit=30&user_id=' + encodeURIComponent(userId))
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.status === 'pending') pollTgStatus(data.id, renderMessages);
      else if (data.messages) renderMessages(data);
    });
  fetch('/tg?action=mark_read&chat_id=' + chatId + '&user_id=' + encodeURIComponent(userId));
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
    url = '/tg?action=reply&chat_id=' + currentChatId + '&text=' + encodeURIComponent(text) + '&reply_to_id=' + replyToId + '&user_id=' + encodeURIComponent(userId);
  } else {
    url = '/tg?action=send_message&chat_id=' + currentChatId + '&text=' + encodeURIComponent(text) + '&user_id=' + encodeURIComponent(userId);
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

setInterval(pollNotifications, 5000);

"""
