"""
Diagnostic script — run this to figure out the current MaxSold bundle format.
It prints:
  1. All <script> src tags found on the homepage
  2. The first 2 000 chars of the bundle (to see its structure)
  3. Every line/token containing 'algolia' or 'Algolia' (case-insensitive)
  4. Context around 'appId' and 'apiKey' occurrences
"""

import re
import requests

MAXSOLD_HOME = "https://www.maxsold.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

session = requests.Session()

# ── 1. Homepage script tags ──────────────────────────────────────────────────
print("=" * 70)
print("STEP 1: script tags on the MaxSold homepage")
print("=" * 70)
resp = session.get(MAXSOLD_HOME, headers=HEADERS, timeout=15)
resp.raise_for_status()
html = resp.text

scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html)
if scripts:
    for s in scripts:
        print(" ", s)
else:
    print("  (none found — dumping first 3 000 chars of HTML)")
    print(html[:3000])

# ── 2. Pick a bundle to inspect ──────────────────────────────────────────────
# Try to find the largest/most likely JS bundle
bundle_url = None
for s in scripts:
    if re.search(r'\.[a-f0-9]{6,}\.js', s) or 'main' in s or 'index' in s or 'app' in s:
        bundle_url = s if s.startswith("http") else MAXSOLD_HOME + s
        break

if not bundle_url and scripts:
    candidate = scripts[-1]
    bundle_url = candidate if candidate.startswith("http") else MAXSOLD_HOME + candidate

if not bundle_url:
    print("\n[!] Could not pick a bundle URL — check the script tags above.")
    raise SystemExit(1)

print(f"\n{'=' * 70}")
print(f"STEP 2: downloading bundle\n  {bundle_url}")
print("=" * 70)
resp2 = session.get(bundle_url, headers=HEADERS, timeout=30)
resp2.raise_for_status()
js = resp2.text
print(f"Bundle size: {len(js):,} chars")
print("\n-- First 2 000 chars --")
print(js[:2000])

# ── 3. Algolia mentions ───────────────────────────────────────────────────────
print(f"\n{'=' * 70}")
print("STEP 3: all 'algolia' occurrences (±120 chars of context)")
print("=" * 70)
for m in re.finditer(r'algolia', js, re.IGNORECASE):
    start = max(0, m.start() - 120)
    end   = min(len(js), m.end() + 120)
    snippet = js[start:end].replace("\n", " ")
    print(f"\n  ...{snippet}...")

# ── 4. appId / apiKey context ────────────────────────────────────────────────
print(f"\n{'=' * 70}")
print("STEP 4: 'appId' and 'apiKey' occurrences (±80 chars of context)")
print("=" * 70)
for keyword in ("appId", "apiKey", "app_id", "api_key"):
    matches = list(re.finditer(re.escape(keyword), js))
    if matches:
        print(f"\n  [{keyword}] — {len(matches)} occurrence(s)")
        for m in matches[:5]:          # show at most 5
            start = max(0, m.start() - 80)
            end   = min(len(js), m.end() + 80)
            snippet = js[start:end].replace("\n", " ")
            print(f"    ...{snippet}...")
    else:
        print(f"\n  [{keyword}] — NOT FOUND")
