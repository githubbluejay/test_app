"""
MaxSold API Connection Script

MaxSold does not have an official public API. This script connects to
MaxSold's backend via the same REST endpoints used by their web app.

As of 2025 MaxSold migrated from Algolia to their own search API.
Credentials are read from /__ENV.js (a Next.js public env-var file).

Key endpoints:
  /__ENV.js                               — public env vars (includes x-api-key)
  https://maxsold.maxsold.com/api/auctions — auction search
  https://maxsold.maxsold.com/api/getitems — items in an auction
  https://maxsold.maxsold.com/api/itemdata — single item detail
"""

import re
import json
import requests

MAXSOLD_HOME    = "https://www.maxsold.com"
MAXSOLD_API_BASE = "https://maxsold.maxsold.com/api"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
}


def get_credentials(session: requests.Session) -> dict:
    """
    Read the public API key from MaxSold's /__ENV.js file.

    Returns:
        {"x_api_key": "<32-char hex key>"}
    """
    resp = session.get(MAXSOLD_HOME + "/__ENV.js", headers=HEADERS, timeout=15)
    resp.raise_for_status()

    match = re.search(r'window\.__ENV\s*=\s*(\{[^;]+\})', resp.text)
    if not match:
        raise RuntimeError("Could not parse window.__ENV from /__ENV.js")

    env = json.loads(match.group(1))
    x_api_key = env.get("NEXT_PUBLIC_X_API_KEY")
    if not x_api_key:
        raise RuntimeError("NEXT_PUBLIC_X_API_KEY not found in /__ENV.js")

    return {"x_api_key": x_api_key}


def build_api_headers(x_api_key: str) -> dict:
    return {
        **HEADERS,
        "x-api-key": x_api_key,
    }


def test_connection(session: requests.Session, x_api_key: str) -> bool:
    """Send a minimal query to verify credentials work."""
    url = f"{MAXSOLD_API_BASE}/auctions"
    headers = build_api_headers(x_api_key)

    print(f"[*] Testing connection to: {url}")
    resp = session.get(url, headers=headers, params={"saleState": "open", "limit": 1}, timeout=15)

    if resp.status_code == 200:
        data = resp.json()
        count = len(data) if isinstance(data, list) else len(data.get("auctions", data.get("data", [])))
        print(f"[+] Connection successful! Got {count} result(s) in test query.")
        return True
    else:
        print(f"[-] Connection failed: HTTP {resp.status_code} — {resp.text[:200]}")
        return False


def search_auctions(
    session: requests.Session,
    x_api_key: str,
    query: str = "",
    location: str = "",
    radius_km: int = 160,
    page: int = 1,
    hits_per_page: int = 5,
) -> list:
    """
    Search for live MaxSold auctions via their REST API.

    Args:
        x_api_key:     API key from /__ENV.js (NEXT_PUBLIC_X_API_KEY).
        query:         Free-text search term (e.g. 'furniture', 'estate').
        location:      Lat/lng string, e.g. '43.6532,-79.3832' (Toronto).
        radius_km:     Search radius in kilometres (default 160 km).
        page:          Page number (1-indexed).
        hits_per_page: Results per page.

    Returns:
        List of auction dicts.
    """
    params = {
        "saleState":  "open",
        "searchType": "live",
        "pageNumber": page,
        "limit":      hits_per_page,
    }
    if location:
        lat, lng = location.split(",", 1)
        params["lat"] = lat.strip()
        params["lng"] = lng.strip()
        params["radiusMetres"] = radius_km * 1000
    if query:
        params["query"] = query

    url = f"{MAXSOLD_API_BASE}/auctions"
    headers = build_api_headers(x_api_key)

    resp = session.get(url, headers=headers, params=params, timeout=15)
    resp.raise_for_status()

    data = resp.json()
    # Handle both list response and wrapped {auctions: [...]} / {data: [...]}
    if isinstance(data, list):
        return data
    return data.get("auctions", data.get("data", data.get("hits", [])))


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

    # Step 1: Read credentials from /__ENV.js
    try:
        creds = get_credentials(session)
    except Exception as exc:
        print(f"[!] Failed to read credentials: {exc}")
        return

    x_api_key = creds["x_api_key"]
    print(f"[+] x_api_key={x_api_key[:6]}...{x_api_key[-4:]!r}")

    # Step 2: Verify the connection
    ok = test_connection(session, x_api_key)
    if not ok:
        print("[!] Aborting — connection test failed.")
        return

    # Step 3: Run a sample auction search
    print("\n[*] Searching for live auctions (up to 5 results)...")
    auctions = search_auctions(session, x_api_key, hits_per_page=5)

    if not auctions:
        print("[-] No auctions returned.")
        print("    Raw response from /api/auctions (no params):")
        r = session.get(f"{MAXSOLD_API_BASE}/auctions", headers=build_api_headers(x_api_key), timeout=15)
        print(f"    HTTP {r.status_code}: {r.text[:500]}")
        return

    print(f"[+] Found {len(auctions)} auction(s):\n")
    for i, auction in enumerate(auctions, 1):
        # Try both old Algolia field names and new REST API field names
        title      = auction.get("title") or auction.get("name") or "(no title)"
        auction_id = (auction.get("amAuctionId") or auction.get("objectID")
                      or auction.get("id") or "?")
        city       = auction.get("city") or ""
        province   = auction.get("province") or auction.get("state") or ""
        end_date   = auction.get("endDate") or auction.get("end_date") or auction.get("end") or "?"
        print(f"  {i}. [{auction_id}] {title}")
        if city or province:
            print(f"      Location : {city}, {province}".strip(", "))
        print(f"      Ends     : {end_date}")

    # Step 4: Fetch items from the first auction
    first_id = (auctions[0].get("amAuctionId") or auctions[0].get("objectID")
                or auctions[0].get("id"))
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
