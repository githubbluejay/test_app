"""
Diagnostic script — finds MaxSold's new search API endpoint.
Algolia has been dropped; credentials now come from /__ENV.js as
NEXT_PUBLIC_X_API_KEY. This script finds the actual search endpoint URL.

Run: python debug_maxsold_bundle.py 2>&1 | tee bundle_debug.txt
"""

import re
import json
import requests

MAXSOLD_HOME = "https://www.maxsold.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

session = requests.Session()

# ── 1. Dump full __ENV.js ────────────────────────────────────────────────────
print("=" * 70)
print("STEP 1: full /__ENV.js content")
print("=" * 70)
env_resp = session.get(MAXSOLD_HOME + "/__ENV.js", headers=HEADERS, timeout=15)
env_resp.raise_for_status()
print(env_resp.text)

# Extract the JSON object
env_match = re.search(r'window\.__ENV\s*=\s*(\{.*?\})\s*;?$', env_resp.text, re.DOTALL)
env_vars = {}
if env_match:
    try:
        env_vars = json.loads(env_match.group(1))
        print("\nParsed env vars:")
        for k, v in env_vars.items():
            print(f"  {k} = {v!r}")
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")

# ── 2. Fetch homepage to get all chunk URLs ──────────────────────────────────
print(f"\n{'=' * 70}")
print("STEP 2: finding API endpoint URLs in JS bundles")
print("=" * 70)
resp = session.get(MAXSOLD_HOME, headers=HEADERS, timeout=15)
resp.raise_for_status()
srcs = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', resp.text)
all_urls = [(s if s.startswith("http") else MAXSOLD_HOME + s) for s in srcs]

# ── 3. Search each bundle for maxsold/search API URLs ───────────────────────
SEARCH_TERMS = [
    "maxsold", "search", "auction", "lot", "x-api-key", "X-Api-Key",
    "NEXT_PUBLIC_MAXSOLD", "auctionMethod", "lotSearch", "auctionSearch",
]

for url in all_urls:
    try:
        r = session.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except Exception as e:
        continue

    js = r.text
    found = {}

    # Find all https:// URLs in this bundle
    api_urls = set(re.findall(r'https?://[a-zA-Z0-9._/-]+', js))
    maxsold_urls = [u for u in api_urls if "maxsold" in u.lower() and len(u) > 20]

    # Also find hardcoded strings near search terms
    snippets = []
    for term in SEARCH_TERMS:
        for m in re.finditer(re.escape(term), js, re.IGNORECASE):
            start = max(0, m.start() - 80)
            end   = min(len(js), m.end() + 120)
            snippet = js[start:end].replace("\n", " ")
            snippets.append((term, snippet))

    if maxsold_urls or snippets:
        print(f"\n── {url.split('maxsold.com')[-1]}")
        if maxsold_urls:
            print("  MaxSold URLs found:")
            for u in sorted(maxsold_urls):
                print(f"    {u}")
        if snippets:
            print("  Keyword context (first 3 per keyword):")
            seen_terms = {}
            for term, snippet in snippets:
                count = seen_terms.get(term, 0)
                if count < 3:
                    print(f"    [{term}] ...{snippet}...")
                    seen_terms[term] = count + 1

# ── 4. Try known MaxSold API endpoints with the X_API_KEY ───────────────────
print(f"\n{'=' * 70}")
print("STEP 3: probing known MaxSold API endpoints")
print("=" * 70)

x_api_key = env_vars.get("NEXT_PUBLIC_X_API_KEY", "")
print(f"X_API_KEY from __ENV.js: {x_api_key!r}")

probe_headers = {**HEADERS, "x-api-key": x_api_key, "Content-Type": "application/json"}

# Known/guessed endpoints to probe
endpoints = [
    ("GET",  "https://maxsold.maxsold.com/api/auctions"),
    ("GET",  "https://maxsold.maxsold.com/api/auction/search"),
    ("POST", "https://maxsold.maxsold.com/api/auction/search"),
    ("GET",  "https://maxsold.maxsold.com/api/lots/search"),
    ("GET",  "https://www.maxsold.com/api/auctions"),
    ("GET",  "https://api.maxsold.com/auctions"),
    ("GET",  "https://api.maxsold.com/search"),
]

for method, endpoint in endpoints:
    try:
        if method == "GET":
            r = session.get(endpoint, headers=probe_headers, timeout=10)
        else:
            r = session.post(endpoint, headers=probe_headers, json={"query": "estate"}, timeout=10)
        print(f"  {method} {endpoint}")
        print(f"    → HTTP {r.status_code}  ({len(r.text)} chars)")
        if r.status_code < 400:
            print(f"    BODY: {r.text[:300]}")
    except Exception as e:
        print(f"  {method} {endpoint}  → ERROR: {e}")
