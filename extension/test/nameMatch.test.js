'use strict';
const test = require('node:test');
const assert = require('node:assert');
const NM = require('../src/nameMatch.js');

test('normalizeName: lowercase + collapse', () => {
  assert.equal(NM.normalizeName('Aaron Judge'), 'aaron judge');
  assert.equal(NM.normalizeName('  Aaron   Judge '), 'aaron judge');
});

test('normalizeName: strips accents', () => {
  assert.equal(NM.normalizeName('José Ramírez'), 'jose ramirez');
  assert.equal(NM.normalizeName('Emilio Pagán'), 'emilio pagan');
});

test('normalizeName: periods/initials', () => {
  assert.equal(NM.normalizeName('A.J. Minter'), 'aj minter');
  assert.equal(NM.normalizeName('A. J. Minter'), 'aj minter');
});

test('normalizeName: Last, First ordering', () => {
  assert.equal(NM.normalizeName('Greene, Hunter'), 'hunter greene');
  assert.equal(NM.normalizeName('Ramírez, José'), 'jose ramirez');
});

test('normalizeName: drops generational suffix', () => {
  assert.equal(NM.normalizeName('Ronald Acuna Jr.'), 'ronald acuna');
  assert.equal(NM.normalizeName('Cal Ripken III'), 'cal ripken');
});

const PLAYERS = [
  { name: 'Aaron Judge', team: 'NYY', pos: 'OF', status: 'mine' },
  { name: 'José Ramírez', team: 'CLE', pos: '3B', status: 'mine' },
  { name: 'A.J. Minter', team: 'NYM', pos: 'RP', status: 'taken' },
  { name: 'Walker Buehler', team: 'SD', pos: 'SP', status: 'freeagent' },
  { name: 'Anthony Rizzo', team: 'NYY', pos: '1B', status: 'taken' }
];

test('findMatch: exact full name across name variants', () => {
  const idx = NM.buildIndex(PLAYERS);
  assert.equal(NM.findMatch('Aaron Judge', idx).status, 'mine');
  assert.equal(NM.findMatch('AARON JUDGE', idx).status, 'mine');
  assert.equal(NM.findMatch('Jose Ramirez', idx).status, 'mine'); // accent-insensitive
  assert.equal(NM.findMatch('AJ Minter', idx).status, 'taken');
  assert.equal(NM.findMatch('Minter, A.J.', idx).status, 'taken');
});

test('findMatch: initial form "A. Rizzo"', () => {
  const idx = NM.buildIndex(PLAYERS);
  assert.equal(NM.findMatch('A. Rizzo', idx).display, 'Anthony Rizzo');
});

test('findMatch: last-name only needs a team hint', () => {
  const idx = NM.buildIndex(PLAYERS);
  assert.equal(NM.findMatch('Judge', idx), null); // no team -> no match
  assert.equal(NM.findMatch('Judge', idx, { team: 'NYY' }).status, 'mine');
  assert.equal(NM.findMatch('Judge', idx, { team: 'LAD' }), null); // wrong team
});

test('findMatch: unrelated text does not match', () => {
  const idx = NM.buildIndex(PLAYERS);
  assert.equal(NM.findMatch('Happy Fathers', idx), null);
  assert.equal(NM.findMatch('Book Now', idx), null);
});

test('normalizeTeam: collapses abbreviation variants', () => {
  assert.equal(NM.normalizeTeam('AZ'), NM.normalizeTeam('ARI'));
  assert.equal(NM.normalizeTeam('LA'), NM.normalizeTeam('LAD'));
});
