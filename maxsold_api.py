"""
MaxSold API Connection Script

MaxSold does not have an official public API. This script connects to
MaxSold's backend via the same Algolia search endpoints used by their
web app, with credentials extracted dynamically from their JS bundle.

References:
  - https://github.com/holts-shoe/maxbought-api (unofficial wrapper)
"""

import re
import json
import requests

MAXSOLD_HOME = "https://www.maxsold.com"
ALGOLIA_SEARCH_URL = "https://{app_id}-dsn.algolia.net/1/indexes/*/queries"
MAXSOLD_API_BASE = "https://maxsold.maxsold.com/api"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
}


def get_js_bundle_url(session: requests.Session) -> str:
    """Fetch the MaxSold homepage and extract the main JS bundle URL."""
    resp = session.get(MAXSOLD_HOME, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    html = resp.text

    # CRA-style: src="/main.abc123.js"
    match = re.search(r'src="(/main\.[a-f0-9]+\.js)"', html)
    if not match:
        # Vite-style: src="/assets/index-abc123.js"
        match = re.search(r'src="(/assets/index-[^"]+\.js)"', html)
    if not match:
        # Vite-style with hash in filename: /assets/SomeName-abc12345.js
        match = re.search(r'src="(/assets/[^"]*-[a-f0-9]{8,}\.[^"]*\.js)"', html)
    if not match:
        # Any script tag whose path contains "main"
        match = re.search(r'src="(/[^"]*main[^"]*\.js)"', html)
    if not match:
        # Last resort: any hashed JS bundle referenced in a script tag
        match = re.search(r'src="(/[^"]+\.[a-f0-9]{8,}\.js)"', html)
    if not match:
        raise RuntimeError("Could not locate main JS bundle on MaxSold homepage.")

    path = match.group(1)
    return path if path.startswith("http") else MAXSOLD_HOME + path


def extract_algolia_credentials(session: requests.Session) -> dict:
    """
    Download MaxSold's main JS bundle and parse out the Algolia
    application ID and search API key embedded in the bundle.

    Multiple patterns are tried in order to handle bundle format changes.
    Algolia app IDs are 8-12 uppercase alphanumeric chars; search API keys
    are 32 lowercase hex chars.
    """
    print("[*] Fetching MaxSold homepage to find JS bundle...")
    js_url = get_js_bundle_url(session)
    print(f"[*] Downloading JS bundle: {js_url}")

    resp = session.get(js_url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    js_text = resp.text

    # --- App ID patterns (most-specific to most-general) ---
    APP_ID_PATTERNS = [
        # Named variables (original)
        r'algoliaApplicationId\s*[=:]\s*["\']([^"\']+)["\']',
        r'algoliaAppId\s*[=:]\s*["\']([^"\']+)["\']',
        r'ALGOLIA_APP_ID\s*[=:]\s*["\']([^"\']+)["\']',
        r'"ALGOLIA_APP_ID"\s*:\s*"([^"]+)"',
        # Minified object literal: appId:"ABCDE12345"
        # Algolia app IDs are uppercase alphanumeric, typically 10 chars.
        r'appId\s*:\s*["\']([A-Z0-9]{8,12})["\']',
        r'"appId"\s*:\s*"([A-Z0-9]{8,12})"',
    ]

    # --- API key patterns ---
    API_KEY_PATTERNS = [
        # Named variables (original)
        r'algoliaSearchAPIKey\s*[=:]\s*["\']([^"\']+)["\']',
        r'algoliaApiKey\s*[=:]\s*["\']([^"\']+)["\']',
        r'ALGOLIA_SEARCH_KEY\s*[=:]\s*["\']([^"\']+)["\']',
        r'ALGOLIA_API_KEY\s*[=:]\s*["\']([^"\']+)["\']',
        r'"ALGOLIA_API_KEY"\s*:\s*"([^"]+)"',
        # Minified object literal: apiKey:"abc123..."
        # Algolia search keys are exactly 32 lowercase hex chars.
        r'apiKey\s*:\s*["\']([a-f0-9]{32})["\']',
        r'"apiKey"\s*:\s*"([a-f0-9]{32})"',
    ]

    app_id_match = None
    for pattern in APP_ID_PATTERNS:
        app_id_match = re.search(pattern, js_text)
        if app_id_match:
            print(f"[*] App ID matched with pattern: {pattern}")
            break

    api_key_match = None
    for pattern in API_KEY_PATTERNS:
        api_key_match = re.search(pattern, js_text)
        if api_key_match:
            print(f"[*] API key matched with pattern: {pattern}")
            break

    if not app_id_match or not api_key_match:
        raise RuntimeError(
            "Could not extract Algolia credentials from JS bundle. "
            "MaxSold may have changed their bundle format."
        )

    return {
        "app_id": app_id_match.group(1),
        "api_key": api_key_match.group(1),
    }


def build_algolia_headers(app_id: str, api_key: str) -> dict:
    return {
        **HEADERS,
        "x-algolia-application-id": app_id,
        "x-algolia-api-key": api_key,
    }


def test_connection(session: requests.Session, app_id: str, api_key: str) -> bool:
    """Send a minimal Algolia query to verify credentials work."""
    url = ALGOLIA_SEARCH_URL.format(app_id=app_id)
    payload = {"requests": [{"indexName": "auction", "params": "query=&hitsPerPage=1"}]}
    headers = build_algolia_headers(app_id, api_key)

    print(f"[*] Testing Algolia connection to: {url}")
    resp = session.post(url, headers=headers, json=payload, timeout=15)

    if resp.status_code == 200:
        data = resp.json()
        hits = data.get("results", [{}])[0].get("hits", [])
        print(f"[+] Connection successful! Got {len(hits)} result(s) in test query.")
        return True
    else:
        print(f"[-] Connection failed: HTTP {resp.status_code} — {resp.text[:200]}")
        return False


def search_auctions(
    session: requests.Session,
    app_id: str,
    api_key: str,
    query: str = "",
    location: str = "",
    radius_km: int = 160,
    page: int = 0,
    hits_per_page: int = 5,
) -> list:
    """
    Search for live MaxSold auctions via Algolia.

    Args:
        query:         Free-text search term (e.g. 'furniture', 'estate').
        location:      Lat/lng string, e.g. '43.6532,-79.3832' (Toronto).
        radius_km:     Search radius in kilometres (default 160 km).
        page:          Page number (0-indexed).
        hits_per_page: Results per page.

    Returns:
        List of auction hit dicts.
    """
    params = f"query={requests.utils.quote(query)}&hitsPerPage={hits_per_page}&page={page}"
    if location:
        radius_m = radius_km * 1000
        params += f"&aroundLatLng={requests.utils.quote(location)}&aroundRadius={radius_m}"

    payload = {"requests": [{"indexName": "auction", "params": params}]}
    url = ALGOLIA_SEARCH_URL.format(app_id=app_id)
    headers = build_algolia_headers(app_id, api_key)

    resp = session.post(url, headers=headers, json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json().get("results", [{}])[0].get("hits", [])


def get_auction_items(
    session: requests.Session,
    auction_id: int | str,
    page: int = 1,
) -> dict:
    """Retrieve items listed in a specific auction."""
    url = f"{MAXSOLD_API_BASE}/getitems"
    payload = {"auctionid": auction_id, "page": page}
    resp = session.post(url, headers=HEADERS, json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_item(session: requests.Session, item_id: int | str) -> dict:
    """Retrieve detailed data for a single auction item."""
    url = f"{MAXSOLD_API_BASE}/itemdata"
    payload = {"itemid": item_id}
    resp = session.post(url, headers=HEADERS, json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Demo / quick-test
# ---------------------------------------------------------------------------

def main():
    session = requests.Session()

    # Step 1: Extract Algolia credentials from MaxSold's JS bundle
    try:
        creds = extract_algolia_credentials(session)
    except Exception as exc:
        print(f"[!] Failed to extract credentials: {exc}")
        return

    app_id = creds["app_id"]
    api_key = creds["api_key"]
    print(f"[+] Credentials — app_id={app_id!r}  api_key={api_key[:6]}...{api_key[-4:]!r}")

    # Step 2: Verify the connection
    ok = test_connection(session, app_id, api_key)
    if not ok:
        print("[!] Aborting — connection test failed.")
        return

    # Step 3: Run a sample auction search
    print("\n[*] Searching for 'estate' auctions (up to 5 results)...")
    auctions = search_auctions(session, app_id, api_key, query="estate", hits_per_page=5)

    if not auctions:
        print("[-] No auctions returned (MaxSold may have no live auctions right now).")
        return

    print(f"[+] Found {len(auctions)} auction(s):\n")
    for i, auction in enumerate(auctions, 1):
        title = auction.get("title") or auction.get("name") or "(no title)"
        auction_id = auction.get("objectID") or auction.get("id") or "?"
        city = auction.get("city") or ""
        province = auction.get("province") or auction.get("state") or ""
        end_date = auction.get("end_date") or auction.get("endDate") or "?"
        print(f"  {i}. [{auction_id}] {title}")
        if city or province:
            print(f"      Location : {city}, {province}".strip(", "))
        print(f"      Ends     : {end_date}")

    # Step 4: Fetch items from the first auction
    first_id = auctions[0].get("objectID") or auctions[0].get("id")
    if first_id:
        print(f"\n[*] Fetching items for auction ID {first_id}...")
        try:
            items_data = get_auction_items(session, first_id)
            items = items_data if isinstance(items_data, list) else items_data.get("items", [])
            print(f"[+] Got {len(items)} item(s) from auction {first_id}.")
            for item in items[:3]:
                item_id = item.get("id") or item.get("itemid") or "?"
                name = item.get("name") or item.get("title") or "(no name)"
                print(f"    - [{item_id}] {name}")
        except Exception as exc:
            print(f"[-] Could not fetch auction items: {exc}")


if __name__ == "__main__":
    main()
