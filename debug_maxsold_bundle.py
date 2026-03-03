"""
Diagnostic script — searches ALL Next.js chunks for Algolia credentials.
Run: python debug_maxsold_bundle.py 2>&1 | tee bundle_debug.txt
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

# ── 1. Collect all script URLs ───────────────────────────────────────────────
print("=" * 70)
print("STEP 1: fetching homepage")
print("=" * 70)
resp = session.get(MAXSOLD_HOME, headers=HEADERS, timeout=15)
resp.raise_for_status()
html = resp.text

srcs = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html)
print(f"Found {len(srcs)} script tags:")
for s in srcs:
    print(f"  {s}")

# Build full URLs, prepend /__ENV.js
all_urls = [MAXSOLD_HOME + "/__ENV.js"] + [
    (s if s.startswith("http") else MAXSOLD_HOME + s) for s in srcs
]

# ── 2. Search every JS file for anything Algolia-related ─────────────────────
print(f"\n{'=' * 70}")
print("STEP 2: scanning all JS files for 'algolia', 'appId', 'apiKey'")
print("=" * 70)

KEYWORDS = ["algolia", "Algolia", "ALGOLIA", "appId", "apiKey", "app_id", "api_key", "NEXT_PUBLIC"]

for url in all_urls:
    print(f"\n── {url}")
    try:
        r = session.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"   SKIP: {e}")
        continue

    js = r.text
    print(f"   size: {len(js):,} chars")

    found_any = False
    for kw in KEYWORDS:
        positions = [m.start() for m in re.finditer(re.escape(kw), js, re.IGNORECASE)]
        if positions:
            found_any = True
            print(f"\n   [{kw}] — {len(positions)} hit(s)")
            for pos in positions[:3]:   # show up to 3 per keyword
                start = max(0, pos - 100)
                end   = min(len(js), pos + 150)
                snippet = js[start:end].replace("\n", " ")
                print(f"     ...{snippet}...")

    if not found_any:
        print("   (no Algolia-related keywords found)")
