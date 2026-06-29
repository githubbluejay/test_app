'use strict';

var NM = self.OFHNameMatch;
var DEFAULTS = {
  colors: { mine: '#1b7f4b', freeagent: '#f6c343', taken: '#9aa7b4' },
  siteMode: 'all',
  siteList: []
};

function get(keys) {
  return new Promise(function (r) { chrome.storage.local.get(keys, function (res) { r(res || {}); }); });
}
function set(obj) {
  return new Promise(function (r) { chrome.storage.local.set(obj, function () { r(); }); });
}

function load() {
  get(['settings', 'meta', 'players']).then(function (res) {
    var s = Object.assign({}, DEFAULTS, res.settings || {});
    s.colors = Object.assign({}, DEFAULTS.colors, (res.settings || {}).colors || {});
    document.getElementById('myTeam').value = (res.meta && res.meta.myTeam) || '';
    document.getElementById('col-mine').value = s.colors.mine;
    document.getElementById('col-freeagent').value = s.colors.freeagent;
    document.getElementById('col-taken').value = s.colors.taken;
    document.querySelector('input[name="siteMode"][value="' + s.siteMode + '"]').checked = true;
    document.getElementById('siteList').value = (s.siteList || []).join('\n');
    renderOverrides(res.players || {});
  });
}

// Manual-override players are tagged so they survive a re-sync of other statuses
// only when their status isn't replaced; we mark them with owner "(manual)".
function renderOverrides(players) {
  var ul = document.getElementById('overrides');
  ul.innerHTML = '';
  Object.keys(players).forEach(function (key) {
    var p = players[key];
    if (p.owner !== '(manual)') return;
    var li = document.createElement('li');
    var label = document.createElement('span');
    label.textContent = p.display + ' — ' + p.status + (p.team ? ' · ' + p.team : '');
    var del = document.createElement('button');
    del.textContent = 'remove';
    del.addEventListener('click', function () {
      get(['players']).then(function (res) {
        var pl = res.players || {};
        delete pl[key];
        set({ players: pl }).then(load);
      });
    });
    li.appendChild(label);
    li.appendChild(del);
    ul.appendChild(li);
  });
}

document.getElementById('m-add').addEventListener('click', function () {
  var name = document.getElementById('m-name').value.trim();
  if (!name) return;
  var key = NM.normalizeName(name);
  if (!key) return;
  var rec = {
    display: name,
    team: document.getElementById('m-team').value.trim(),
    pos: document.getElementById('m-pos').value.trim(),
    status: document.getElementById('m-status').value,
    owner: '(manual)'
  };
  get(['players']).then(function (res) {
    var pl = res.players || {};
    pl[key] = rec;
    set({ players: pl }).then(function () {
      document.getElementById('m-name').value = '';
      document.getElementById('m-team').value = '';
      document.getElementById('m-pos').value = '';
      load();
    });
  });
});

document.getElementById('save').addEventListener('click', function () {
  var settings = {
    enabled: true,
    colors: {
      mine: document.getElementById('col-mine').value,
      freeagent: document.getElementById('col-freeagent').value,
      taken: document.getElementById('col-taken').value
    },
    siteMode: document.querySelector('input[name="siteMode"]:checked').value,
    siteList: document.getElementById('siteList').value.split('\n')
      .map(function (l) { return l.trim().toLowerCase(); }).filter(Boolean)
  };
  get(['settings', 'meta']).then(function (res) {
    var merged = Object.assign({}, res.settings || {}, settings);
    var meta = Object.assign({}, res.meta || {}, { myTeam: document.getElementById('myTeam').value.trim() });
    return set({ settings: merged, meta: meta });
  }).then(function () {
    var el = document.getElementById('saved');
    el.textContent = 'Saved ✓';
    setTimeout(function () { el.textContent = ''; }, 1500);
  });
});

document.getElementById('clear').addEventListener('click', function () {
  if (!confirm('Remove all synced players? Manual overrides are removed too.')) return;
  get(['meta']).then(function (res) {
    var meta = Object.assign({}, res.meta || {}, { lastSync: 0 });
    set({ players: {}, meta: meta }).then(load);
  });
});

load();
