JS_CLAUDE = r"""
var claudeAuthorized = false;
var claudeSessionActive = false;

document.getElementById('claude-login-btn').onclick = claudeLogin;
document.getElementById('claude-new-btn').onclick = newClaudeConversation;
document.getElementById('claude-send-btn').onclick = sendClaudeMessage;
document.getElementById('claude-input').onkeydown = function(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendClaudeMessage(); }
};
document.getElementById('claude-model').onchange = updateClaudeModelLabel;

function checkClaudeAuth() {
  document.getElementById('claude-auth').style.display = '';
  document.getElementById('claude-chat').style.display = 'none';
  document.getElementById('claude-login-btn').style.display = 'none';
  document.querySelector('.claude-auth-desc').textContent = 'Checking authorization...';

  fetch('/claude?action=check_auth')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.status === 'pending') {
        pollClaudeStatus(data.id, function(resp) { handleAuthResult(resp); });
      } else {
        handleAuthResult(data);
      }
    })
    .catch(function() {
      document.querySelector('.claude-auth-desc').textContent = 'Connection error';
    });
}

function handleAuthResult(data) {
  if (data.status === 'authorized') {
    claudeAuthorized = true;
    document.getElementById('claude-auth').style.display = 'none';
    document.getElementById('claude-chat').style.display = '';
    updateClaudeModelLabel();
  } else {
    var errText = data.error || data.message || 'Not authorized';
    document.querySelector('.claude-auth-desc').textContent = errText;
    document.getElementById('claude-login-btn').style.display = '';
  }
}

function claudeLogin() {
  document.querySelector('.claude-auth-desc').textContent = 'Starting login...';
  document.getElementById('claude-login-btn').style.display = 'none';
  var urlBox = document.getElementById('claude-auth-url');
  urlBox.style.display = 'none';
  urlBox.textContent = '';

  fetch('/claude?action=login')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.status === 'pending') {
        pollClaudeStatus(data.id, function(resp) { handleLoginResult(resp); });
      } else {
        handleLoginResult(data);
      }
    });
}

function handleLoginResult(data) {
  if (data.status === 'authorized') {
    checkClaudeAuth();
  } else if (data.login_url || data.url) {
    var url = data.login_url || data.url;
    document.querySelector('.claude-auth-desc').textContent = 'Open this link to authorize:';
    var urlBox = document.getElementById('claude-auth-url');
    urlBox.style.display = '';
    var a = document.createElement('a');
    a.href = url;
    a.target = '_blank';
    a.textContent = url;
    urlBox.textContent = '';
    urlBox.appendChild(a);
    document.getElementById('claude-login-btn').textContent = 'Check again';
    document.getElementById('claude-login-btn').style.display = '';
    document.getElementById('claude-login-btn').onclick = checkClaudeAuth;
  } else {
    var loginErr = data.error || data.message || 'Login failed';
    if (data.raw_error) loginErr += '\n(' + data.raw_error + ')';
    document.querySelector('.claude-auth-desc').textContent = loginErr;
    document.getElementById('claude-login-btn').style.display = '';
  }
}

function sendClaudeMessage() {
  var input = document.getElementById('claude-input');
  var text = input.value.trim();
  if (!text) return;

  var sendBtn = document.getElementById('claude-send-btn');
  sendBtn.disabled = true;
  input.disabled = true;

  renderClaudeMessage('user', text);
  input.value = '';

  var model = document.getElementById('claude-model').value;
  var loading = renderClaudeLoading();

  fetch('/claude?action=send&text=' + encodeURIComponent(text) + '&model=' + model)
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.status === 'pending') {
        pollClaudeStatus(data.id, function(resp) {
          removeClaudeLoading(loading);
          handleClaudeResponse(resp);
          sendBtn.disabled = false;
          input.disabled = false;
          input.focus();
        });
      } else if (data.error) {
        removeClaudeLoading(loading);
        renderClaudeMessage('error', data.error);
        sendBtn.disabled = false;
        input.disabled = false;
      }
    })
    .catch(function(e) {
      removeClaudeLoading(loading);
      renderClaudeMessage('error', 'Network error: ' + e.message);
      sendBtn.disabled = false;
      input.disabled = false;
    });
}

function handleClaudeResponse(data) {
  if (data.error) {
    renderClaudeMessage('error', data.error);
    return;
  }
  var text = data.response || data.result || '';
  renderClaudeMessage('assistant', text);

  var meta = [];
  if (data.model) meta.push(data.model);
  if (data.duration) meta.push((data.duration / 1000).toFixed(1) + 's');
  if (data.cost) meta.push('$' + data.cost.toFixed(4));
  if (meta.length) {
    var msgs = document.getElementById('claude-messages');
    var metaEl = document.createElement('div');
    metaEl.className = 'claude-meta';
    metaEl.textContent = meta.join(' \u00b7 ');
    msgs.appendChild(metaEl);
  }

  claudeSessionActive = true;
}

function renderClaudeMessage(role, text) {
  var msgs = document.getElementById('claude-messages');
  var div = document.createElement('div');
  div.className = 'claude-msg ' + role;

  if (role === 'assistant') {
    try {
      var container = document.createElement('div');
      container.innerHTML = marked.parse(text);
      while (container.firstChild) div.appendChild(container.firstChild);
    } catch(e) { div.textContent = text; }
  } else {
    div.textContent = text;
  }

  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return div;
}

function renderClaudeLoading() {
  var msgs = document.getElementById('claude-messages');
  var div = document.createElement('div');
  div.className = 'claude-msg assistant claude-loading';
  var spinner = document.createElement('span');
  spinner.className = 'claude-spinner';
  var timer = document.createElement('span');
  timer.className = 'claude-timer-text';
  timer.textContent = '0.0s';
  div.appendChild(spinner);
  div.appendChild(document.createTextNode(' '));
  div.appendChild(timer);
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;

  var start = Date.now();
  div._interval = setInterval(function() {
    timer.textContent = ((Date.now() - start) / 1000).toFixed(1) + 's';
  }, 100);

  return div;
}

function removeClaudeLoading(div) {
  if (div && div._interval) clearInterval(div._interval);
  if (div && div.parentNode) div.parentNode.removeChild(div);
}

function newClaudeConversation() {
  fetch('/claude?action=new_conversation')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.status === 'pending') {
        pollClaudeStatus(data.id, function() { clearClaudeMessages(); });
      } else {
        clearClaudeMessages();
      }
    });
}

function clearClaudeMessages() {
  document.getElementById('claude-messages').textContent = '';
  claudeSessionActive = false;
}

function pollClaudeStatus(id, callback) {
  var attempts = 0;
  var poll = setInterval(function() {
    fetch('/status?id=' + id)
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.status === 'ready') {
          clearInterval(poll);
          callback(data);
        } else if (data.status === 'error') {
          clearInterval(poll);
          callback(data);
        }
        if (++attempts > 150) {
          clearInterval(poll);
          callback({error: 'timeout waiting for response'});
        }
      })
      .catch(function() {
        if (++attempts > 150) {
          clearInterval(poll);
          callback({error: 'connection lost'});
        }
      });
  }, 2000);
}

function updateClaudeModelLabel() {
  var sel = document.getElementById('claude-model');
  var label = document.getElementById('claude-model-label');
  if (label) label.textContent = sel.options[sel.selectedIndex].text;
}
"""
