'use strict';

function send(msg) {
  return new Promise(function (resolve) {
    chrome.runtime.sendMessage(msg, function (resp) {
      void chrome.runtime.lastError;
      resolve(resp);
    });
  });
}

function fmtAgo(ts) {
  if (!ts) return 'never';
  var s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  return Math.floor(s / 86400) + 'd ago';
}

function render(state) {
  if (!state || !state.ok) return;
  document.getElementById('c-mine').textContent = state.counts.mine;
  document.getElementById('c-freeagent').textContent = state.counts.freeagent;
  document.getElementById('c-taken').textContent = state.counts.taken;
  document.getElementById('enabled').checked = !!state.settings.enabled;

  var total = state.counts.mine + state.counts.freeagent + state.counts.taken;
  var status = document.getElementById('status');
  if (!total) {
    status.textContent = 'No players synced yet. Open your OnRoto league and click Sync now.';
  } else {
    status.textContent = total + ' players · last sync ' + fmtAgo(state.meta.lastSync);
  }
}

function refresh() {
  return send({ type: 'OFH_GET_STATE' }).then(render);
}

document.getElementById('enabled').addEventListener('change', function (e) {
  chrome.storage.local.get(['settings'], function (res) {
    var settings = res.settings || {};
    settings.enabled = e.target.checked;
    chrome.storage.local.set({ settings: settings });
  });
});

document.getElementById('sync').addEventListener('click', function () {
  var btn = this;
  var hint = document.getElementById('sync-hint');
  btn.disabled = true;
  hint.textContent = 'Syncing from open OnRoto tabs…';
  send({ type: 'OFH_SYNC_NOW' }).then(function (resp) {
    btn.disabled = false;
    if (resp && resp.ok) {
      hint.textContent = 'Synced: ' + (resp.pages.join(', ') || 'ok');
      refresh();
    } else if (resp && resp.reason === 'no-onroto-tab') {
      hint.textContent = 'Open your OnRoto league in a tab, then Sync.';
    } else {
      hint.textContent = 'Nothing recognizable to sync on the open OnRoto page.';
    }
  });
});

document.getElementById('open-options').addEventListener('click', function (e) {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

refresh();
