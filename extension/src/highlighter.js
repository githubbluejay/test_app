/*
 * highlighter.js — runs on every page, marks player names by league status.
 *
 * Walks text nodes, matches 1-3 word spans against the synced player index from
 * nameMatch.js, and wraps hits in a colored <span> plus a small status chip
 * (echoing RotoWire's inline marker). A debounced MutationObserver re-scans
 * dynamically added content. Reacts to storage changes (new sync / settings).
 */
(function () {
  'use strict';

  if (window.__ofhInjected) return;
  window.__ofhInjected = true;

  var NM = self.OFHNameMatch;
  var MARK = 'ofh-mark';
  var STATUS_LABEL = { mine: 'My roster', freeagent: 'Free agent', taken: 'Taken' };

  var state = {
    index: null,
    settings: null,
    enabled: false,
    observer: null,
    scanScheduled: false
  };

  // Tags whose text we must never touch.
  var SKIP_TAGS = {
    SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEXTAREA: 1, INPUT: 1, SELECT: 1,
    OPTION: 1, CODE: 1, PRE: 1, IFRAME: 1, SVG: 1, CANVAS: 1
  };

  function hostAllowed(settings) {
    var host = location.hostname;
    var inList = (settings.siteList || []).some(function (h) {
      return host === h || host.endsWith('.' + h);
    });
    // 'all' mode: highlight everywhere except listed hosts (deny list).
    // 'none' mode: highlight only on listed hosts (allow list).
    return settings.siteMode === 'none' ? inList : !inList;
  }

  function buildIndexFromStore(playersMap) {
    var arr = Object.keys(playersMap || {}).map(function (k) {
      var p = playersMap[k];
      return { name: p.display, display: p.display, team: p.team, pos: p.pos, status: p.status, owner: p.owner };
    });
    return NM.buildIndex(arr);
  }

  function applyColors(colors) {
    var root = document.documentElement;
    root.style.setProperty('--ofh-mine', colors.mine);
    root.style.setProperty('--ofh-freeagent', colors.freeagent);
    root.style.setProperty('--ofh-taken', colors.taken);
  }

  // Try to find a team abbreviation near a text node, to disambiguate last-name hits.
  function nearbyTeam(node) {
    var row = node.parentElement;
    var hops = 0;
    while (row && hops < 4 && row.tagName !== 'TR') { row = row.parentElement; hops++; }
    if (!row || row.tagName !== 'TR') return '';
    var text = row.textContent || '';
    var m = text.match(/\b([A-Z]{2,3})\b/);
    return m ? m[1] : '';
  }

  // Build a chip element to append after a marked name.
  function makeChip(status) {
    var chip = document.createElement('span');
    chip.className = 'ofh-chip ofh-chip-' + status;
    chip.setAttribute('aria-hidden', 'true');
    return chip;
  }

  // Examine one text node; if it contains a matching name, replace it with marked spans.
  function processTextNode(textNode) {
    var text = textNode.nodeValue;
    if (!text || text.length < 3 || !/[a-z]/i.test(text)) return;

    // Candidate windows: tokens of length up to 3 words, scanning left to right.
    // Names are "Firstname Lastname" so we test 2- and 3-word windows first, then
    // fall back to single-word (last name) windows guarded by a nearby team.
    var wordRe = /[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ.'-]*/g;
    var words = [];
    var wm;
    while ((wm = wordRe.exec(text)) !== null) {
      words.push({ text: wm[0], start: wm.index, end: wm.index + wm[0].length });
    }
    if (!words.length) return;

    var team = null; // computed lazily
    var segments = [];   // ordered list of { type:'text'|'mark', ... }
    var cursor = 0;
    var i = 0;
    while (i < words.length) {
      var matched = null;
      var span = 0;
      for (var w = Math.min(3, words.length - i); w >= 1; w--) {
        var phrase = text.slice(words[i].start, words[i + w - 1].end);
        var opts = null;
        if (w === 1) {
          if (team === null) team = nearbyTeam(textNode);
          if (!team) continue; // never match bare single words without a team hint
          opts = { team: team };
        }
        var rec = NM.findMatch(phrase, state.index, opts);
        if (rec) { matched = rec; span = w; break; }
      }

      if (matched) {
        var startIdx = words[i].start;
        var endIdx = words[i + span - 1].end;
        if (startIdx > cursor) segments.push({ type: 'text', value: text.slice(cursor, startIdx) });
        segments.push({ type: 'mark', value: text.slice(startIdx, endIdx), rec: matched });
        cursor = endIdx;
        i += span;
      } else {
        i += 1;
      }
    }

    if (!segments.length) return; // no match in this node
    if (cursor < text.length) segments.push({ type: 'text', value: text.slice(cursor) });

    var frag = document.createDocumentFragment();
    segments.forEach(function (seg) {
      if (seg.type === 'text') {
        frag.appendChild(document.createTextNode(seg.value));
      } else {
        var span = document.createElement('span');
        span.className = MARK + ' ' + MARK + '-' + seg.rec.status;
        span.textContent = seg.value;
        var tip = (STATUS_LABEL[seg.rec.status] || seg.rec.status);
        var extra = [seg.rec.pos, seg.rec.team, seg.rec.owner].filter(Boolean).join(' · ');
        span.title = extra ? tip + ' — ' + extra : tip;
        span.appendChild(makeChip(seg.rec.status));
        frag.appendChild(span);
      }
    });

    textNode.parentNode.replaceChild(frag, textNode);
  }

  function shouldSkip(el) {
    if (!el) return true;
    if (SKIP_TAGS[el.tagName]) return true;
    if (el.isContentEditable) return true;
    if (el.classList && (el.classList.contains(MARK) || el.classList.contains('ofh-chip'))) return true;
    return false;
  }

  function scan(rootNode) {
    if (!state.index) return;
    var walker = document.createTreeWalker(rootNode, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        var p = node.parentElement;
        while (p) {
          if (shouldSkip(p)) return NodeFilter.FILTER_REJECT;
          p = p.parentElement;
        }
        return node.nodeValue && node.nodeValue.trim().length >= 3
          ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });
    var nodes = [];
    var n;
    while ((n = walker.nextNode())) nodes.push(n);
    // Mutate after collecting to avoid invalidating the walker.
    nodes.forEach(processTextNode);
  }

  function scheduleScan() {
    if (state.scanScheduled) return;
    state.scanScheduled = true;
    (window.requestIdleCallback || window.setTimeout)(function () {
      state.scanScheduled = false;
      if (state.enabled && state.index) scan(document.body);
    }, 300);
  }

  function startObserver() {
    if (state.observer) return;
    state.observer = new MutationObserver(function (mutations) {
      for (var i = 0; i < mutations.length; i++) {
        if (mutations[i].addedNodes && mutations[i].addedNodes.length) { scheduleScan(); return; }
      }
    });
    state.observer.observe(document.body, { childList: true, subtree: true });
  }

  function teardown() {
    if (state.observer) { state.observer.disconnect(); state.observer = null; }
    document.querySelectorAll('.' + MARK).forEach(function (el) {
      var text = el.textContent.replace(/\s*$/, '');
      // chip is empty text, so textContent already excludes it
      el.replaceWith(document.createTextNode(el.firstChild ? el.childNodes[0].nodeValue : text));
    });
  }

  function refresh() {
    self.OFHStorageLite.getAll().then(function (data) {
      state.settings = data.settings;
      applyColors(data.settings.colors);
      state.index = buildIndexFromStore(data.players);
      var on = data.settings.enabled && hostAllowed(data.settings) && Object.keys(data.players || {}).length > 0;
      if (on) {
        state.enabled = true;
        scan(document.body);
        startObserver();
      } else {
        state.enabled = false;
        teardown();
      }
    });
  }

  // Minimal storage reader (the full OFHStorage wrapper isn't injected here to
  // keep the all-sites bundle small; we only need a read + change listener).
  self.OFHStorageLite = {
    getAll: function () {
      return new Promise(function (resolve) {
        chrome.storage.local.get(['players', 'meta', 'settings'], function (res) {
          var d = res || {};
          var defaults = { enabled: true, colors: { mine: '#1b7f4b', freeagent: '#f6c343', taken: '#9aa7b4' }, siteMode: 'all', siteList: [] };
          var settings = Object.assign({}, defaults, d.settings || {});
          settings.colors = Object.assign({}, defaults.colors, (d.settings || {}).colors || {});
          resolve({ players: d.players || {}, meta: d.meta || {}, settings: settings });
        });
      });
    }
  };

  chrome.storage.onChanged.addListener(function (changes, area) {
    if (area !== 'local') return;
    if (changes.players || changes.settings) {
      teardown();
      refresh();
    }
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', refresh);
  } else {
    refresh();
  }
})();
