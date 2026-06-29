# OnRoto Fantasy Highlighter

A Chrome extension (Manifest V3) that highlights MLB player names on **any** website
according to their status in your **OnRoto** fantasy baseball league:

- 🟩 **My roster**
- 🟨 **Free agent / available**
- ⬜ **Taken by another team**

Names not in your league pool are left untouched. Each marked name gets a small
lightning chip (à la RotoWire) with a tooltip showing position / team / owner.

## How it works

OnRoto has no public API and gates its pages behind an in-URL session, so the
extension reads roster and free-agent data **from OnRoto's own pages while you're
logged in** — no passwords or OAuth. That data is cached locally and used to
highlight names everywhere else you browse.

```
src/nameMatch.js     Name normalization + matching (accents, initials, "Last, First")
src/storage.js       chrome.storage.local wrapper (players, meta, settings)
src/onrotoScraper.js Content script on *.onroto.com — parses rosters / available pages
src/highlighter.js   Content script on all sites — finds + marks player names
src/background.js    Service worker — merges scraped data, "Sync now", toolbar badge
popup/               Toggle, per-category counts, "Sync now"
options/             Your team name, colors, per-site allow/deny, manual overrides
```

## Install (developer / unpacked)

1. `chrome://extensions` → enable **Developer mode**.
2. **Load unpacked** → select this `extension/` folder.
3. Open **Settings** (from the popup) and enter **your team / owner name** exactly as
   it appears on OnRoto — this is how your roster is told apart from rivals' teams.

## Sync your league

1. Log into OnRoto and open your **Rosters/Standings** page and the **Available
   Players** page (visiting them is enough — the extension harvests passively).
2. Or click **Sync now** in the popup to pull from any open OnRoto tab.
3. The popup shows counts for My roster / Free agents / Taken and the last sync time.

Now browse RotoWire, ESPN, MLB.com, etc. — matching players are highlighted.

## Tests

Pure logic (name matching + page parsing) is covered by Node's test runner:

```
node --test extension/test/*.test.js
```

## Pinning the OnRoto parser

The parser uses header/heading heuristics because OnRoto's exact markup is behind a
login. If a page doesn't sync cleanly, save its page source into
`extension/test/fixtures/` and adjust the column/heading heuristics in
`src/onrotoScraper.js` (the only file that needs to change) — the fixtures lock the
behavior in tests.
