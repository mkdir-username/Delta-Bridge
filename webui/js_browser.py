JS_BROWSER = r"""var busy = false, pollTimer = null, loadTimer = null, t0 = 0;
var lastResults = null;
var lastMarkdown = '';
var browserMode = false;
function toggleBrowserMode() {
  browserMode = !browserMode;
  $('btnBrowser').classList.toggle('active', browserMode);
}

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
  var endpoint = browserMode
    ? '/browser?url=' + encodeURIComponent(url)
    : '/get?url=' + encodeURIComponent(url);
  fetch(endpoint)
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

var kitData = [];
function loadKits() {
  fetch('/kit').then(function(r){return r.json()}).then(function(d) {
    kitData = d.kits || [];
    var sel = $('kit-select');
    sel.innerHTML = '<option value="">Kit...</option>';
    for (var i = 0; i < kitData.length; i++) {
      var o = document.createElement('option');
      o.value = i;
      o.textContent = kitData[i].service;
      sel.appendChild(o);
    }
    if (kitData.length > 0) $('kit-select').style.display = '';
  }).catch(function(){});
}
function loadKitActions() {
  var idx = $('kit-select').value;
  var actSel = $('kit-action');
  var btn = $('kit-run');
  if (idx === '') { actSel.style.display = 'none'; btn.style.display = 'none'; return; }
  var kit = kitData[parseInt(idx)];
  actSel.innerHTML = '<option value="">Action...</option>';
  for (var j = 0; j < kit.actions.length; j++) {
    var o = document.createElement('option');
    o.value = kit.actions[j];
    o.textContent = kit.actions[j];
    actSel.appendChild(o);
  }
  actSel.style.display = '';
  btn.style.display = '';
}
function runKit() {
  var idx = $('kit-select').value;
  var action = $('kit-action').value;
  if (idx === '' || !action) return;
  var kit = kitData[parseInt(idx)];
  content.innerHTML = '<div class="loading"><div class="spinner"></div><div>Running ' + escHtml(kit.service) + '.' + escHtml(action) + '...</div></div>';
}
loadKits();
"""
