/*
 * nameMatch.js — player-name normalization + matching engine.
 *
 * Pure, dependency-free functions shared by the OnRoto scraper, the highlighter
 * content script, and the Node unit tests. No DOM, no chrome.* access here.
 *
 * Loaded two ways:
 *   - As a Chrome content script: defines `self.OFHNameMatch`.
 *   - As a Node module (tests): `module.exports`.
 */
(function (root) {
  'use strict';

  // Generational / honorific suffixes that vary across sites and should be dropped.
  var SUFFIXES = { jr: 1, sr: 1, ii: 1, iii: 1, iv: 1, v: 1 };

  // Map common MLB team abbreviation variants to a single canonical token so that
  // last-name + team disambiguation works across sites that spell teams differently.
  var TEAM_ALIASES = {
    az: 'ari', ari: 'ari', sd: 'sd', sdp: 'sd', sf: 'sf', sfg: 'sf',
    tb: 'tb', tbr: 'tb', kc: 'kc', kcr: 'kc', cws: 'chw', chw: 'chw',
    wsh: 'was', was: 'was', wsn: 'was', nyy: 'nyy', nym: 'nym',
    laa: 'laa', lad: 'lad', la: 'lad'
  };

  function normalizeTeam(team) {
    if (!team) return '';
    var t = String(team).toLowerCase().replace(/[^a-z]/g, '');
    return TEAM_ALIASES[t] || t;
  }

  // Strip accents/diacritics. NFKD splits letters from combining marks, which we remove.
  function stripAccents(s) {
    if (typeof s.normalize === 'function') {
      return s.normalize('NFKD').replace(/[̀-ͯ]/g, '');
    }
    return s;
  }

  // Turn a raw name into canonical tokens.
  // Handles "Last, First" ordering, accents, punctuation, and suffixes.
  // Returns an array of word tokens, e.g. ["aj", "minter"] or ["jose", "ramirez"].
  function tokenize(name) {
    if (!name) return [];
    var s = stripAccents(String(name)).toLowerCase();

    // "Ramirez, Jose" -> "Jose Ramirez"
    var comma = s.indexOf(',');
    if (comma !== -1) {
      var last = s.slice(0, comma);
      var first = s.slice(comma + 1);
      s = first + ' ' + last;
    }

    // Drop periods so "A.J." -> "aj"; replace other punctuation with spaces.
    s = s.replace(/\./g, '').replace(/[^a-z0-9]+/g, ' ');

    var split = s.split(/\s+/).filter(Boolean);

    // Merge consecutive single-letter tokens (spaced initials): "a j minter" -> "aj minter".
    var tokens = [];
    split.forEach(function (t) {
      if (t.length === 1 && tokens.length && tokens[tokens.length - 1].length === 1) {
        tokens[tokens.length - 1] += t;
      } else {
        tokens.push(t);
      }
    });

    // Remove trailing generational suffixes.
    while (tokens.length > 2 && SUFFIXES[tokens[tokens.length - 1]]) {
      tokens.pop();
    }
    if (tokens.length > 1 && SUFFIXES[tokens[tokens.length - 1]]) {
      tokens.pop();
    }
    return tokens;
  }

  // Canonical full-name key, e.g. "aj minter", "jose ramirez".
  function normalizeName(name) {
    return tokenize(name).join(' ');
  }

  // Variant key collapsing a multi-letter first name to its initial:
  // "aj minter" stays "aj minter"; "anthony rizzo" -> "a rizzo".
  // Helps match "A. Rizzo" style abbreviations seen on some sites.
  function initialKey(tokens) {
    if (tokens.length < 2) return '';
    var first = tokens[0];
    var rest = tokens.slice(1).join(' ');
    return first.charAt(0) + ' ' + rest;
  }

  /*
   * buildIndex(players)
   *   players: array of { name|display, team, pos, status, owner }
   *   returns an index object consumed by findMatch.
   *
   * Index keys:
   *   byFull:    canonical "first last" -> record (primary, highest confidence)
   *   byInitial: "f last" -> record (only kept when unambiguous)
   *   byLast:    "last" -> [records] (fallback, needs team to disambiguate)
   */
  function buildIndex(players) {
    var byFull = Object.create(null);
    var byInitial = Object.create(null);
    var initialDupes = Object.create(null);
    var byLast = Object.create(null);

    (players || []).forEach(function (p) {
      var raw = p.name || p.display;
      var tokens = tokenize(raw);
      if (!tokens.length) return;

      var rec = {
        display: p.display || raw,
        team: p.team || '',
        teamKey: normalizeTeam(p.team),
        pos: p.pos || '',
        status: p.status,
        owner: p.owner || '',
        tokens: tokens
      };

      var full = tokens.join(' ');
      // First write wins for an exact full-name key; this keeps the result stable.
      if (!byFull[full]) byFull[full] = rec;

      var ik = initialKey(tokens);
      if (ik) {
        if (byInitial[ik] && byInitial[ik] !== rec) initialDupes[ik] = 1;
        byInitial[ik] = rec;
      }

      var last = tokens[tokens.length - 1];
      (byLast[last] || (byLast[last] = [])).push(rec);
    });

    // Drop ambiguous initial keys so "A. Smith" never silently picks one of several.
    Object.keys(initialDupes).forEach(function (k) { delete byInitial[k]; });

    return { byFull: byFull, byInitial: byInitial, byLast: byLast };
  }

  /*
   * findMatch(text, index, opts)
   *   text: a candidate name string (already extracted from the page).
   *   opts.team: optional team abbreviation seen near the name, used to
   *              disambiguate last-name-only matches.
   *   returns the matched record or null.
   */
  function findMatch(text, index, opts) {
    if (!index) return null;
    opts = opts || {};
    var tokens = tokenize(text);
    if (!tokens.length) return null;

    var full = tokens.join(' ');
    if (index.byFull[full]) return index.byFull[full];

    // "A. Rizzo" / "A Rizzo" style — only matches when first token is a single letter.
    if (tokens.length >= 2 && tokens[0].length === 1) {
      var ik = tokens.join(' ');
      if (index.byInitial[ik]) return index.byInitial[ik];
    }

    // Last-name-only: require a team hint to avoid false positives.
    if (tokens.length === 1 && opts.team) {
      var bucket = index.byLast[tokens[0]];
      if (bucket) {
        var wantTeam = normalizeTeam(opts.team);
        for (var i = 0; i < bucket.length; i++) {
          if (bucket[i].teamKey && bucket[i].teamKey === wantTeam) return bucket[i];
        }
      }
    }

    return null;
  }

  var api = {
    normalizeName: normalizeName,
    normalizeTeam: normalizeTeam,
    tokenize: tokenize,
    buildIndex: buildIndex,
    findMatch: findMatch
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  root.OFHNameMatch = api;
})(typeof self !== 'undefined' ? self : this);
