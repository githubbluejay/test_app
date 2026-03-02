"""
eBay Finding API — sold listing price lookup.

Uses the legacy Finding API `findCompletedItems` operation, which is the only
public eBay endpoint that returns actual *sold* prices without seller OAuth.

Getting a free App ID (Client ID):
  1. Sign up at https://developer.ebay.com
  2. Create an application → copy the "App ID (Client ID)"

Note: eBay is migrating away from the Finding API toward REST APIs, but as of
2025 it remains the sole public endpoint for sold-comp data.
"""

import statistics

import requests

FINDING_API_URL = "https://svcs.ebay.com/services/search/FindingService/v1"

_EMPTY = {
    "prices":   [],
    "median":   None,
    "low":      None,
    "high":     None,
    "count":    0,
    "currency": "USD",
}


def search_sold_prices(
    app_id: str,
    keywords: str,
    max_results: int = 20,
    global_id: str = "EBAY-US",
    timeout: int = 10,
) -> dict:
    """
    Query eBay for recently completed/sold listings matching *keywords*.

    Returns a dict:
        prices   – sorted list of individual sold prices (float)
        median   – median sold price
        low      – 25th-percentile price (conservative floor)
        high     – 75th-percentile price (optimistic ceiling)
        count    – number of sold listings found
        currency – ISO currency code of returned prices
    """
    params = {
        "OPERATION-NAME":                "findCompletedItems",
        "SERVICE-VERSION":               "1.0.0",
        "SECURITY-APPNAME":              app_id,
        "RESPONSE-DATA-FORMAT":          "JSON",
        "GLOBAL-ID":                     global_id,
        "keywords":                      keywords,
        "itemFilter(0).name":            "SoldItemsOnly",
        "itemFilter(0).value":           "true",
        "sortOrder":                     "EndTimeSoonest",
        "paginationInput.entriesPerPage": min(max_results, 100),
    }

    try:
        resp = requests.get(FINDING_API_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return dict(_EMPTY)

    wrapper = data.get("findCompletedItemsResponse", [{}])[0]
    if wrapper.get("ack", ["Failure"])[0] != "Success":
        return dict(_EMPTY)

    items = (
        wrapper
        .get("searchResult", [{}])[0]
        .get("item", [])
    )

    prices: list[float] = []
    currency = "USD"
    for item in items:
        try:
            state = item["sellingStatus"][0].get("sellingState", [""])[0]
            if "WithSales" not in state:
                continue
            price_node = item["sellingStatus"][0]["currentPrice"][0]
            currency   = price_node.get("@currencyId", "USD")
            prices.append(float(price_node["__value__"]))
        except (KeyError, IndexError, ValueError):
            continue

    if not prices:
        return dict(_EMPTY)

    prices.sort()
    n    = len(prices)
    low  = prices[max(0, int(n * 0.25))]
    high = prices[min(n - 1, int(n * 0.75))]

    return {
        "prices":   prices,
        "median":   round(statistics.median(prices), 2),
        "low":      round(low, 2),
        "high":     round(high, 2),
        "count":    n,
        "currency": currency,
    }


def liquidity_from_comps(comp_count: int) -> int:
    """
    Map number of recent eBay sold comps to a 1–10 liquidity score.

    More comps = more buyers in market = faster sale.
    """
    if comp_count == 0:   return 5   # unknown → neutral
    if comp_count <= 2:   return 3
    if comp_count <= 5:   return 5
    if comp_count <= 10:  return 7
    if comp_count <= 15:  return 8
    return 9
