/*
 * onrotoScraper.js — runs on *.onroto.com pages, harvests league data.
 *
 * OnRoto has no public API and gates pages behind a URL session, so we read the
 * already-authenticated page the user is viewing. The PURE parsing functions
 * (column classification, table -> player rows) are exported for Node tests and
 * fed string matrices; the DOM-dependent glue builds those matrices from the
 * live page and only runs in the browser.
 *
 * NOTE: exact OnRoto markup is auth-gated and not yet pinned. The heuristics
 * below classify columns by header keywords and pair tables with their nearest
 * heading. Lock these against a real league page (see test/fixtures) — only this
 * file should need to change if the markup differs.
 */
(function (root) {
  'use strict';

  var HEADER_KEYS = {
    name: ['player', 'name', 'batter', 'pitcher', 'hitter'],
    team: ['team', 'tm', 'mlb'],
    pos: ['pos', 'position', 'slot'],
    owner: ['owner', 'franchise', 'fantasy team', 'roster', 'manager']
  };

  function cellText(s) {
    return String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
  }

  function matchHeader(text, keys) {
    var t = cellText(text).toLowerCase();
    if (!t) return false;
    for (var i = 0; i < keys.length; i++) {
      if (t === keys[i] || t.indexOf(keys[i]) !== -1) return true;
    }
    return false;
  }

  // Given a header row (array of strings), return indexes for known columns.
  function classifyColumns(headerRow) {
    var idx = { name: -1, team: -1, pos: -1, owner: -1 };
    (headerRow || []).forEach(function (h, i) {
      Object.keys(HEADER_KEYS).forEach(function (field) {
        if (idx[field] === -1 && matchHeader(h, HEADER_KEYS[field])) idx[field] = i;
      });
    });
    return idx;
  }

  // Heuristic: does a cell value look like a player name (>= 2 alpha words)?
  function looksLikeName(v) {
    var t = cellText(v);
    if (t.length < 3) return false;
    if (/^\d/.test(t)) return false;
    var words = t.replace(/[.,]/g, '').split(/\s+/).filter(function (w) { return /[a-z]/i.test(w); });
    return words.length >= 2 || /,/.test(t); // "Last, First" is one comma-joined token
  }

  /*
   * parseTable(matrix)
   *   matrix: array of rows, each an array of cell strings. Row 0 may be a header.
   *   returns { columns, rows } where rows are { name, team, pos, owner } objects.
   */
  function parseTable(matrix) {
    if (!matrix || !matrix.length) return { columns: {}, rows: [] };

    var header = matrix[0] || [];
    var cols = classifyColumns(header);
    var startRow = 1;

    // If no recognizable name header, treat every row as data and guess the
    // name column as the first cell that looks like a name across the table.
    if (cols.name === -1) {
      startRow = 0;
      var firstData = matrix[0] || [];
      for (var c = 0; c < firstData.length; c++) {
        if (looksLikeName(firstData[c])) { cols.name = c; break; }
      }
    }
    if (cols.name === -1) return { columns: cols, rows: [] };

    var rows = [];
    for (var r = startRow; r < matrix.length; r++) {
      var row = matrix[r] || [];
      var name = cellText(row[cols.name]);
      if (!looksLikeName(name)) continue;
      rows.push({
        name: name,
        team: cols.team !== -1 ? cellText(row[cols.team]) : '',
        pos: cols.pos !== -1 ? cellText(row[cols.pos]) : '',
        owner: cols.owner !== -1 ? cellText(row[cols.owner]) : ''
      });
    }
    return { columns: cols, rows: rows };
  }

  // Normalize a team/owner label for comparison against the user's configured team.
  function labelKey(s) {
    return cellText(s).toLowerCase().replace(/[^a-z0-9]/g, '');
  }

  /*
   * parseRosterSections(sections, opts)
   *   sections: [{ label, matrix }] — label is the nearest heading text.
   *   opts.myTeam: the user's team/owner label (from settings).
   *   Returns player rows with status "mine" (your team) or "taken" (others).
   */
  function parseRosterSections(sections, opts) {
    opts = opts || {};
    var mineKey = labelKey(opts.myTeam);
    var out = [];
    (sections || []).forEach(function (sec) {
      var parsed = parseTable(sec.matrix);
      parsed.rows.forEach(function (row) {
        var owner = row.owner || sec.label || '';
        var isMine = mineKey && labelKey(owner) === mineKey;
        out.push({
          name: row.name,
          team: row.team,
          pos: row.pos,
          owner: cellText(owner),
          status: isMine ? 'mine' : 'taken'
        });
      });
    });
    return out;
  }

  /*
   * parseAvailableSections(sections)
   *   Free-agent / available-player listings -> status "freeagent".
   */
  function parseAvailableSections(sections) {
    var out = [];
    (sections || []).forEach(function (sec) {
      var parsed = parseTable(sec.matrix);
      parsed.rows.forEach(function (row) {
        out.push({
          name: row.name, team: row.team, pos: row.pos, status: 'freeagent'
        });
      });
    });
    return out;
  }

  // Decide what kind of OnRoto page this is from its URL/title/visible text.
  function detectPageType(url, title, bodyText) {
    var hay = ((url || '') + ' ' + (title || '') + ' ' + (bodyText || '')).toLowerCase();
    if (/available|free agent|free-agent|reservoir|unowned|pickup/.test(hay)) return 'available';
    if (/roster|standings|franchise|teams|owners|lineup/.test(hay)) return 'roster';
    return null;
  }

  // --- Regex-based HTML table extractor (used by Node tests / as a fallback) ---
  // The live content script prefers the DOM extractor below; this keeps parsing
  // fully testable in Node without a DOM dependency.
  function extractSectionsFromHtml(html) {
    if (!html) return [];
    var sections = [];
    // Walk the document, tracking the most recent heading as the section label.
    var token = /<h[1-6][^>]*>([\s\S]*?)<\/h[1-6]>|<table[\s\S]*?<\/table>/gi;
    var m;
    var lastLabel = '';
    while ((m = token.exec(html)) !== null) {
      if (m[1] !== undefined) {
        lastLabel = cellText(stripTags(m[1]));
      } else {
        sections.push({ label: lastLabel, matrix: tableToMatrix(m[0]) });
      }
    }
    return sections;
  }

  function stripTags(s) {
    return String(s).replace(/<[^>]*>/g, ' ').replace(/&nbsp;/gi, ' ');
  }

  function tableToMatrix(tableHtml) {
    var rows = [];
    var rowRe = /<tr[\s\S]*?<\/tr>/gi;
    var cellRe = /<t[dh][^>]*>([\s\S]*?)<\/t[dh]>/gi;
    var rm;
    while ((rm = rowRe.exec(tableHtml)) !== null) {
      var cells = [];
      var cm;
      cellRe.lastIndex = 0;
      while ((cm = cellRe.exec(rm[0])) !== null) {
        cells.push(cellText(stripTags(cm[1])));
      }
      if (cells.length) rows.push(cells);
    }
    return rows;
  }

  var api = {
    classifyColumns: classifyColumns,
    looksLikeName: looksLikeName,
    parseTable: parseTable,
    parseRosterSections: parseRosterSections,
    parseAvailableSections: parseAvailableSections,
    detectPageType: detectPageType,
    extractSectionsFromHtml: extractSectionsFromHtml
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  root.OFHOnRoto = api;

  // ---------------------------------------------------------------------------
  // DOM glue — browser only. Builds sections from the live page and reports rows.
  // ---------------------------------------------------------------------------
  if (typeof document === 'undefined' || typeof chrome === 'undefined' || !chrome.runtime) {
    return;
  }

  // Build [{label, matrix}] from live DOM tables, pairing each table with the
  // nearest preceding heading for owner/team context.
  function domSections() {
    var sections = [];
    var tables = document.querySelectorAll('table');
    tables.forEach(function (table) {
      var matrix = [];
      table.querySelectorAll('tr').forEach(function (tr) {
        var cells = [];
        tr.querySelectorAll('th,td').forEach(function (cell) {
          cells.push(cellText(cell.textContent));
        });
        if (cells.length) matrix.push(cells);
      });
      if (matrix.length) sections.push({ label: nearestHeading(table), matrix: matrix });
    });
    return sections;
  }

  function nearestHeading(el) {
    var node = el;
    while (node) {
      var sib = node.previousElementSibling;
      while (sib) {
        if (/^H[1-6]$/.test(sib.tagName) || /caption|title|heading/i.test(sib.className)) {
          return cellText(sib.textContent);
        }
        sib = sib.previousElementSibling;
      }
      node = node.parentElement;
    }
    return '';
  }

  function scrape(settings) {
    var pageType = detectPageType(location.href, document.title, document.body.innerText.slice(0, 4000));
    if (!pageType) return { ok: false, reason: 'unknown-page' };

    var sections = domSections();
    var rows, replaceStatuses, label;
    if (pageType === 'available') {
      rows = parseAvailableSections(sections);
      replaceStatuses = ['freeagent'];
      label = 'available players';
    } else {
      rows = parseRosterSections(sections, { myTeam: (settings && settings.myTeam) || '' });
      replaceStatuses = ['mine', 'taken'];
      label = 'rosters';
    }
    return { ok: rows.length > 0, pageType: pageType, label: label, rows: rows, replaceStatuses: replaceStatuses };
  }

  // Respond to an explicit scrape request from the popup/background ("Sync now").
  chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
    if (msg && msg.type === 'OFH_SCRAPE') {
      chrome.storage.local.get(['meta'], function (res) {
        var result = scrape((res && res.meta) || {});
        if (result.ok) {
          chrome.runtime.sendMessage({ type: 'OFH_SCRAPED', payload: result });
        }
        sendResponse(result);
      });
      return true; // async response
    }
  });

  // Passive harvest: if the user simply browses a recognizable page, sync it.
  chrome.storage.local.get(['meta'], function (res) {
    var result = scrape((res && res.meta) || {});
    if (result.ok) {
      chrome.runtime.sendMessage({ type: 'OFH_SCRAPED', payload: result });
    }
  });
})(typeof self !== 'undefined' ? self : this);
