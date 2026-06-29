/*
 * background.js — MV3 service worker.
 *
 * - Merges scraped rows into storage (OFH_SCRAPED from the OnRoto scraper).
 * - Orchestrates "Sync now" from the popup by triggering scrapes in OnRoto tabs.
 * - Keeps the toolbar badge showing sync staleness.
 */
importScripts('nameMatch.js', 'storage.js');

var ONROTO_MATCH = ['*://*.onroto.com/*', '*://onroto.fangraphs.com/*'];

function findOnRotoTabs() {
  return new Promise(function (resolve) {
    chrome.tabs.query({ url: ONROTO_MATCH }, function (tabs) { resolve(tabs || []); });
  });
}

function sendScrape(tabId) {
  return new Promise(function (resolve) {
    chrome.tabs.sendMessage(tabId, { type: 'OFH_SCRAPE' }, function (resp) {
      // chrome.runtime.lastError is read to avoid "unchecked error" noise when a
      // tab has no content script (e.g. a non-page URL).
      void chrome.runtime.lastError;
      resolve(resp || { ok: false });
    });
  });
}

function applyScraped(payload) {
  return self.OFHStorage.mergePlayers(payload.rows, payload.replaceStatuses, {})
    .then(function (res) { updateBadge(); return res; });
}

function updateBadge() {
  self.OFHStorage.getAll().then(function (data) {
    var n = Object.keys(data.players || {}).length;
    var last = data.meta && data.meta.lastSync;
    if (!n || !last) {
      chrome.action.setBadgeText({ text: '' });
      return;
    }
    var days = Math.floor((Date.now() - last) / 86400000);
    chrome.action.setBadgeBackgroundColor({ color: days > 3 ? '#c0392b' : '#1b7f4b' });
    chrome.action.setBadgeText({ text: days > 0 ? days + 'd' : 'ok' });
  });
}

chrome.runtime.onMessage.addListener(function (msg, sender, sendResponse) {
  if (!msg || !msg.type) return;

  if (msg.type === 'OFH_SCRAPED') {
    applyScraped(msg.payload).then(function (res) { sendResponse({ ok: true, res: res }); });
    return true;
  }

  if (msg.type === 'OFH_SYNC_NOW') {
    findOnRotoTabs().then(function (tabs) {
      if (!tabs.length) {
        sendResponse({ ok: false, reason: 'no-onroto-tab' });
        return;
      }
      Promise.all(tabs.map(function (t) { return sendScrape(t.id); })).then(function (results) {
        var synced = results.filter(function (r) { return r && r.ok; });
        sendResponse({ ok: synced.length > 0, pages: synced.map(function (r) { return r.label; }) });
      });
    });
    return true;
  }

  if (msg.type === 'OFH_GET_STATE') {
    self.OFHStorage.getAll().then(function (data) {
      var counts = { mine: 0, freeagent: 0, taken: 0 };
      Object.keys(data.players).forEach(function (k) {
        var s = data.players[k].status;
        if (counts[s] !== undefined) counts[s]++;
      });
      sendResponse({ ok: true, counts: counts, meta: data.meta, settings: data.settings });
    });
    return true;
  }
});

chrome.runtime.onInstalled.addListener(updateBadge);
chrome.runtime.onStartup.addListener(updateBadge);
updateBadge();
