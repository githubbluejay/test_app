/*
 * storage.js — thin async wrapper over chrome.storage.local.
 *
 * Holds the synced player pool, league metadata, and user settings. Exposed as
 * `self.OFHStorage` for content scripts and imported by the background worker.
 */
(function (root) {
  'use strict';

  var DEFAULTS = {
    players: {},            // normalizedKey -> { display, team, pos, status, owner }
    meta: {
      lastSync: 0,
      leagueName: '',
      myTeam: '',
      source: 'onroto'
    },
    settings: {
      enabled: true,
      colors: { mine: '#1b7f4b', freeagent: '#f6c343', taken: '#9aa7b4' },
      siteMode: 'all',       // 'all' = highlight everywhere except siteList; 'none' = only on siteList
      siteList: []           // hostnames (deny list in 'all' mode, allow list in 'none' mode)
    }
  };

  function get(keys) {
    return new Promise(function (resolve) {
      chrome.storage.local.get(keys, function (res) { resolve(res || {}); });
    });
  }

  function set(obj) {
    return new Promise(function (resolve) {
      chrome.storage.local.set(obj, function () { resolve(); });
    });
  }

  // Deep-ish merge of defaults so newly added settings keys appear for old installs.
  function withDefaults(stored) {
    var out = {};
    out.players = stored.players || {};
    out.meta = Object.assign({}, DEFAULTS.meta, stored.meta || {});
    out.settings = Object.assign({}, DEFAULTS.settings, stored.settings || {});
    out.settings.colors = Object.assign({}, DEFAULTS.settings.colors, (stored.settings || {}).colors || {});
    return out;
  }

  var api = {
    DEFAULTS: DEFAULTS,

    getAll: function () {
      return get(['players', 'meta', 'settings']).then(withDefaults);
    },

    getSettings: function () {
      return get(['settings']).then(function (s) {
        return Object.assign({}, DEFAULTS.settings, s.settings || {}, {
          colors: Object.assign({}, DEFAULTS.settings.colors, (s.settings || {}).colors || {})
        });
      });
    },

    setSettings: function (settings) {
      return set({ settings: settings });
    },

    // Replace the players belonging to a given status set, then merge.
    // Used by the scraper: a rosters-page sync replaces all mine/taken records,
    // an available-page sync replaces all freeagent records.
    mergePlayers: function (rows, replaceStatuses, metaPatch) {
      return get(['players', 'meta']).then(function (cur) {
        var players = {};
        var prev = cur.players || {};
        var drop = {};
        (replaceStatuses || []).forEach(function (s) { drop[s] = 1; });

        // Keep existing records whose status is NOT being replaced.
        Object.keys(prev).forEach(function (k) {
          if (!drop[prev[k].status]) players[k] = prev[k];
        });

        // Add the freshly scraped rows.
        rows.forEach(function (r) {
          var key = root.OFHNameMatch.normalizeName(r.name || r.display);
          if (!key) return;
          players[key] = {
            display: r.display || r.name,
            team: r.team || '',
            pos: r.pos || '',
            status: r.status,
            owner: r.owner || ''
          };
        });

        var meta = Object.assign({}, DEFAULTS.meta, cur.meta || {}, metaPatch || {}, {
          lastSync: Date.now()
        });
        return set({ players: players, meta: meta }).then(function () {
          return { count: rows.length, total: Object.keys(players).length };
        });
      });
    },

    clearPlayers: function () {
      return set({ players: {}, meta: Object.assign({}, DEFAULTS.meta) });
    }
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  root.OFHStorage = api;
})(typeof self !== 'undefined' ? self : this);
