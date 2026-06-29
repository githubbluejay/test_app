'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const OR = require('../src/onrotoScraper.js');

const rostersHtml = fs.readFileSync(path.join(__dirname, 'fixtures', 'rosters.html'), 'utf8');
const availableHtml = fs.readFileSync(path.join(__dirname, 'fixtures', 'available.html'), 'utf8');

test('detectPageType classifies pages', () => {
  assert.equal(OR.detectPageType('https://x.onroto.com/rosters.pl', 'Rosters', 'Bronx Bombers'), 'roster');
  assert.equal(OR.detectPageType('https://x.onroto.com/avail.pl', 'Available Players', 'Free agent'), 'available');
  assert.equal(OR.detectPageType('https://x.onroto.com/news', 'News', 'hello'), null);
});

test('classifyColumns finds name/team/pos by header', () => {
  const cols = OR.classifyColumns(['Player', 'Team', 'Pos']);
  assert.equal(cols.name, 0);
  assert.equal(cols.team, 1);
  assert.equal(cols.pos, 2);
});

test('roster parsing: owner from section heading + mine/taken split', () => {
  const sections = OR.extractSectionsFromHtml(rostersHtml);
  const rows = OR.parseRosterSections(sections, { myTeam: 'Bronx Bombers' });
  const byName = Object.fromEntries(rows.map(r => [r.name.toLowerCase(), r]));

  assert.equal(rows.length, 5);
  assert.equal(byName['aaron judge'].status, 'mine');
  assert.equal(byName['aaron judge'].owner, 'Bronx Bombers');
  assert.equal(byName['aaron judge'].team, 'NYY');
  // Comma-form name is preserved as displayed; normalization happens at match time.
  assert.ok(byName['greene, hunter'] || byName['hunter greene']);
  // Other team -> taken
  assert.equal(byName['shohei ohtani'].status, 'taken');
  assert.equal(byName['shohei ohtani'].owner, 'River Sharks');
});

test('available parsing: all freeagent', () => {
  const sections = OR.extractSectionsFromHtml(availableHtml);
  const rows = OR.parseAvailableSections(sections);
  assert.equal(rows.length, 3);
  assert.ok(rows.every(r => r.status === 'freeagent'));
  assert.equal(rows.find(r => /buehler/i.test(r.name)).team, 'SD');
});

test('end-to-end: scraped names match via nameMatch index', () => {
  const NM = require('../src/nameMatch.js');
  const sections = OR.extractSectionsFromHtml(rostersHtml);
  const rows = OR.parseRosterSections(sections, { myTeam: 'Bronx Bombers' });
  const idx = NM.buildIndex(rows.map(r => ({ name: r.name, team: r.team, pos: r.pos, status: r.status })));
  // A page elsewhere referring to "Hunter Greene" (scraped as "Greene, Hunter") matches.
  assert.equal(NM.findMatch('Hunter Greene', idx).status, 'mine');
  assert.equal(NM.findMatch('A.J. Minter', idx).status, 'taken');
});
