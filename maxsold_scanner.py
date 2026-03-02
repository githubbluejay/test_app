"""
MaxSold Auction Opportunity Scanner — Streamlit App

Scans live MaxSold auctions, uses Claude AI to estimate resale value for each
item, then surfaces the top 10 bidding opportunities ranked by ROI × liquidity.

Run with:  streamlit run maxsold_scanner.py
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

from ebay_api import liquidity_from_comps, search_sold_prices
from maxsold_api import (
    extract_algolia_credentials,
    get_auction_items,
    search_auctions,
)

# ── Constants ─────────────────────────────────────────────────────────────────

EBAY_FEE_RATE = 0.1325   # 13.25% eBay final value fee
CLAUDE_MODEL = "claude-opus-4-6"
ITEMS_PER_BATCH = 15     # items sent per Claude API call

CITY_COORDS: dict[str, str] = {
    # Canada
    "Toronto, ON":      "43.6532,-79.3832",
    "Ottawa, ON":       "45.4215,-75.6972",
    "Vancouver, BC":    "49.2827,-123.1207",
    "Calgary, AB":      "51.0447,-114.0719",
    "Montreal, QC":     "45.5017,-73.5673",
    # United States
    "New York, NY":     "40.7128,-74.0060",
    "Los Angeles, CA":  "34.0522,-118.2437",
    "Chicago, IL":      "41.8781,-87.6298",
    "Houston, TX":      "29.7604,-95.3698",
    "Phoenix, AZ":      "33.4484,-112.0740",
    "Philadelphia, PA": "39.9526,-75.1652",
    "San Antonio, TX":  "29.4241,-98.4936",
    "San Diego, CA":    "32.7157,-117.1611",
    "Dallas, TX":       "32.7767,-96.7970",
    "San Francisco, CA":"37.7749,-122.4194",
    "Seattle, WA":      "47.6062,-122.3321",
    "Denver, CO":       "39.7392,-104.9903",
    "Boston, MA":       "42.3601,-71.0589",
    "Nashville, TN":    "36.1627,-86.7816",
    "Las Vegas, NV":    "36.1699,-115.1398",
    "Detroit, MI":      "42.3314,-83.0458",
    "Minneapolis, MN":  "44.9778,-93.2650",
    "Atlanta, GA":      "33.7490,-84.3880",
    "Miami, FL":        "25.7617,-80.1918",
}

VALUATION_PROMPT = """\
You are an expert in secondhand/resale markets (eBay, Facebook Marketplace, \
Craigslist). You analyze estate sale items and estimate their resale value.

For each item below, return a JSON array (same order, zero-indexed) where each \
element contains:
- "index": same integer index I gave you
- "normalized_name": specific clear name (e.g. "KitchenAid 5-Qt Stand Mixer", \
not just "mixer")
- "category": one of: Electronics, Furniture, Jewelry, Collectibles, Clothing, \
Tools, Kitchen, Art, Books, Sports, Toys, Other
- "estimated_resale_low": conservative USD resale (used/estate condition, as-is)
- "estimated_resale_high": optimistic USD resale
- "estimated_shipping": typical USD shipping cost (0 for bulky furniture = \
local pickup)
- "liquidity_score": 1–10 (10=sells in 1-3 days, 7=1-2 weeks, 4=1 month, \
1=3+ months)
- "notes": one sentence on value/liquidity reasoning

Assumptions: estate/used condition, seller pays eBay fees (~13.25%).
Be realistic/conservative — these are not collector-grade unless stated.

IMPORTANT: Return ONLY the JSON array. No markdown fences, no explanation.

Items:
"""

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="MaxSold Opportunity Scanner",
    page_icon="🏷️",
    layout="wide",
)

st.markdown("""
<style>
    .scanner-title {
        font-size: 2.3rem; font-weight: 800; color: #1a1a2e; margin-bottom: 2px;
    }
    .scanner-sub {
        color: #666; font-size: 0.98rem; margin-bottom: 20px;
    }
    .opp-card {
        background: #fff; border: 1px solid #e2e2e2; border-radius: 12px;
        padding: 18px 20px 14px; margin-bottom: 14px; position: relative;
    }
    .rank-badge {
        display: inline-block; font-size: 0.72rem; font-weight: 700;
        border-radius: 999px; padding: 2px 10px; margin-bottom: 8px;
        background: #1a1a2e; color: #fff;
    }
    .rank-1  { background: #d4a017 !important; }
    .rank-2  { background: #8a8a8a !important; }
    .rank-3  { background: #a0522d !important; }
    .item-name     { font-size: 1.05rem; font-weight: 700; color: #1a1a2e; margin-bottom: 2px; }
    .item-category { font-size: 0.74rem; color: #999; text-transform: uppercase;
                     letter-spacing: 0.06em; margin-bottom: 12px; }
    .metrics-row   { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 10px; }
    .metric        { flex: 1; min-width: 80px; }
    .mlabel        { font-size: 0.68rem; color: #aaa; text-transform: uppercase;
                     letter-spacing: 0.05em; }
    .mvalue        { font-size: 1.05rem; font-weight: 700; color: #1a1a2e; }
    .roi-pos  { color: #219653; }
    .roi-warn { color: #d97706; }
    .roi-neg  { color: #dc2626; }
    .liq-chip {
        display: inline-block; font-size: 0.76rem; font-weight: 600;
        border-radius: 999px; padding: 2px 10px; margin-right: 6px;
    }
    .liq-high { background: #d1fae5; color: #065f46; }
    .liq-med  { background: #fef3c7; color: #92400e; }
    .liq-low  { background: #fee2e2; color: #991b1b; }
    .notes    { font-size: 0.8rem; color: #777; font-style: italic; margin-top: 6px; }
    .ainfo    { font-size: 0.75rem; color: #bbb; margin-top: 6px; }
    .ainfo a  { color: #2563eb; text-decoration: none; }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### Settings")

    anthropic_key = st.text_input(
        "Anthropic API Key",
        type="password",
        placeholder="sk-ant-...",
        help="Required for item identification and fallback pricing. console.anthropic.com",
    )

    ebay_app_id = st.text_input(
        "eBay App ID (optional)",
        placeholder="YourApp-XXXX-XXXX-...",
        help=(
            "If provided, replaces Claude's estimates with real eBay sold prices. "
            "Free: developer.ebay.com → My Account → Application Keysets → App ID (Client ID)"
        ),
    )

    ebay_site = st.radio(
        "eBay market",
        options=["Canada (CAD)", "US (USD)", "Both"],
        index=0,
        help="Canada is most relevant for MaxSold buyers. 'Both' searches each and takes the higher comp count.",
        horizontal=True,
    )
    _EBAY_SITE_MAP = {"Canada (CAD)": ["EBAY-ENCA"], "US (USD)": ["EBAY-US"], "Both": ["EBAY-ENCA", "EBAY-US"]}
    ebay_global_ids = _EBAY_SITE_MAP[ebay_site]

    st.markdown("---")
    st.markdown("**Location**")
    loc_mode = st.radio("", ["Select city", "Custom coordinates"],
                        label_visibility="collapsed")
    if loc_mode == "Select city":
        city = st.selectbox("City", list(CITY_COORDS.keys()))
        location_str = CITY_COORDS[city]
    else:
        location_str = st.text_input("Lat, Lng", placeholder="43.6532,-79.3832")

    st.markdown("---")
    st.markdown("**Scan settings**")
    max_auctions = st.slider("Auctions to scan", 1, 10, 3)
    radius_km = st.slider(
        "Search radius (km)", 5, 500, 50,
        help="How far from the selected city to look for auctions. 15 = within 15 km.",
    )

    min_bid = st.number_input("Min current bid ($)", min_value=0, value=0, step=5)
    max_bid = st.number_input("Max current bid ($)", min_value=1, value=500, step=25)

    min_roi = st.slider(
        "Min ROI to display (%)", 0, 200, 20,
        help="Hides items below this ROI threshold.",
    )

    st.markdown("---")
    st.markdown("**Category filter** (blank = all)")
    categories_filter = st.multiselect(
        "",
        ["Electronics", "Furniture", "Jewelry", "Collectibles", "Clothing",
         "Tools", "Kitchen", "Art", "Books", "Sports", "Toys", "Other"],
        label_visibility="collapsed",
    )

# ── Header ────────────────────────────────────────────────────────────────────

st.markdown("<div class='scanner-title'>MaxSold Opportunity Scanner</div>",
            unsafe_allow_html=True)
st.markdown(
    "<div class='scanner-sub'>AI-powered resale opportunity finder for "
    "MaxSold estate auctions — powered by Claude</div>",
    unsafe_allow_html=True,
)

# ── Helper functions ──────────────────────────────────────────────────────────

def _field(d: dict, *keys, default=None):
    """Return the first non-None value found among multiple field name variants."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def fetch_items_from_auctions(
    session: requests.Session,
    app_id: str,
    api_key: str,
    n_auctions: int,
    location: str,
    radius_km: int = 50,
) -> list[dict]:
    """Fetch all items across the nearest n_auctions within radius_km of location."""
    auctions = search_auctions(
        session, app_id, api_key,
        location=location,
        radius_km=radius_km,
        hits_per_page=n_auctions,
    )

    all_items: list[dict] = []
    for auction in auctions:
        auction_id    = _field(auction, "objectID", "id")
        auction_title = _field(auction, "title", "name", default="Unknown Auction")
        auction_city  = _field(auction, "city", default="")
        auction_prov  = _field(auction, "province", "state", default="")
        auction_end   = _field(auction, "end_date", "endDate", "end", default="")
        auction_url   = f"https://www.maxsold.com/auctions/{auction_id}"

        try:
            raw = get_auction_items(session, auction_id)
            items = raw if isinstance(raw, list) else raw.get("items", raw.get("data", []))
        except Exception:
            continue

        for item in items:
            current_bid = float(
                _field(item, "current_bid", "currentBid", "bid",
                       "winning_bid", "price", default=0) or 0
            )
            item_id = _field(item, "id", "itemid", "item_id", default="")
            all_items.append({
                "item_id":          item_id,
                "raw_name":         _field(item, "name", "title", default="Unknown item"),
                "description":      _field(item, "description", "details", default=""),
                "current_bid":      current_bid,
                "auction_id":       auction_id,
                "auction_title":    auction_title,
                "auction_city":     auction_city,
                "auction_province": auction_prov,
                "auction_end":      auction_end,
                "auction_url":      auction_url,
                "item_url":         f"{auction_url}/items/{item_id}",
            })

    return all_items


def analyze_batch(client: anthropic.Anthropic, batch: list[dict]) -> list[dict]:
    """Send a batch of items to Claude and return valuation dicts."""
    items_text = "\n".join(
        f"{i}. [{item['raw_name']}]"
        + (f" — {item['description'][:140]}" if item.get("description") else "")
        for i, item in enumerate(batch)
    )
    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": VALUATION_PROMPT + items_text}],
    )
    raw = msg.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def score_item(
    current_bid: float,
    resale_low: float,
    resale_high: float,
    shipping: float,
    liquidity: int,
) -> dict:
    """Compute net proceeds, ROI, and opportunity score."""
    resale_mid   = (resale_low + resale_high) / 2
    net_proceeds = resale_mid * (1 - EBAY_FEE_RATE) - shipping
    roi          = ((net_proceeds - current_bid) / current_bid * 100
                    if current_bid > 0 else 0.0)
    # Opportunity score: ROI boosted by liquidity (up to +40% weight)
    opp_score = roi * (0.6 + 0.4 * liquidity / 10)
    return {
        "resale_mid":    round(resale_mid, 2),
        "net_proceeds":  round(net_proceeds, 2),
        "roi":           round(roi, 1),
        "opp_score":     round(opp_score, 1),
    }


def enrich_with_ebay(
    results: list[dict],
    ebay_app_id: str,
    global_ids: list[str] | None = None,
) -> list[dict]:
    """
    Fetch eBay sold comps for every result in parallel and update pricing in-place.

    Items with ≥ 2 comps get their resale_low/high and liquidity_score replaced
    with real market data. Items with 0–1 comps keep Claude's estimates.
    When multiple global_ids are provided (e.g. EBAY-ENCA + EBAY-US), results
    from the site with the highest comp count win.
    """
    if global_ids is None:
        global_ids = ["EBAY-ENCA"]

    def _fetch(idx: int, item: dict) -> tuple[int, dict]:
        candidates = [
            search_sold_prices(ebay_app_id, item["normalized_name"], global_id=gid)
            for gid in global_ids
        ]
        # prefer whichever site returned more comps
        best = max(candidates, key=lambda r: r["count"])
        return idx, best

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_fetch, i, r): i for i, r in enumerate(results)}
        for future in as_completed(futures):
            idx, ebay = future.result()
            item = results[idx]
            item["ebay_count"] = ebay["count"]

            if ebay["count"] >= 2:
                item["resale_low"]      = ebay["low"]
                item["resale_high"]     = ebay["high"]
                item["liquidity_score"] = liquidity_from_comps(ebay["count"])
                item["price_source"]    = f"eBay · {ebay['count']} comps"
                # Recalculate all downstream scores with real prices
                updated = score_item(
                    item["current_bid"],
                    item["resale_low"],
                    item["resale_high"],
                    item["shipping"],
                    item["liquidity_score"],
                )
                item.update(updated)
            else:
                item["price_source"] = "AI estimate"

    return results


def _liq_label(score: int) -> str:
    if score >= 7: return "High"
    if score >= 4: return "Medium"
    return "Low"


def _roi_cls(roi: float) -> str:
    if roi >= 50: return "roi-pos"
    if roi >= 10: return "roi-warn"
    return "roi-neg"


def render_card(rank: int, item: dict) -> None:
    rank_cls  = f"rank-{rank}" if rank <= 3 else "rank-badge"
    liq_label = _liq_label(item["liquidity_score"])
    liq_cls   = {"High": "liq-high", "Medium": "liq-med", "Low": "liq-low"}[liq_label]
    roi_cls   = _roi_cls(item["roi"])
    liq_bar   = "█" * item["liquidity_score"] + "░" * (10 - item["liquidity_score"])
    location  = ", ".join(filter(None, [item.get("auction_city", ""),
                                        item.get("auction_province", "")]))

    # Price source badge
    source = item.get("price_source", "AI estimate")
    if source.startswith("eBay"):
        src_badge = (f'<span style="font-size:0.7rem;background:#dcfce7;color:#166534;'
                     f'border-radius:4px;padding:1px 7px;margin-left:6px;">📊 {source}</span>')
    else:
        src_badge = (f'<span style="font-size:0.7rem;background:#f1f5f9;color:#64748b;'
                     f'border-radius:4px;padding:1px 7px;margin-left:6px;">🤖 {source}</span>')

    st.markdown(f"""
    <div class="opp-card">
      <div class="rank-badge {rank_cls}">#{rank}</div>
      <div class="item-name">{item['normalized_name']}{src_badge}</div>
      <div class="item-category">{item['category']}</div>
      <div class="metrics-row">
        <div class="metric">
          <div class="mlabel">Current Bid</div>
          <div class="mvalue">${item['current_bid']:.0f}</div>
        </div>
        <div class="metric">
          <div class="mlabel">Est. Resale</div>
          <div class="mvalue">${item['resale_low']:.0f}–${item['resale_high']:.0f}</div>
        </div>
        <div class="metric">
          <div class="mlabel">Net Proceeds</div>
          <div class="mvalue">${item['net_proceeds']:.0f}</div>
        </div>
        <div class="metric">
          <div class="mlabel">ROI</div>
          <div class="mvalue {roi_cls}">{item['roi']:+.0f}%</div>
        </div>
        <div class="metric">
          <div class="mlabel">Opp. Score</div>
          <div class="mvalue">{item['opp_score']:.0f}</div>
        </div>
      </div>
      <span class="liq-chip {liq_cls}">{liq_label} Liquidity</span>
      <span style="font-size:0.78rem;color:#ccc;font-family:monospace;">{liq_bar}</span>
      <div class="notes">"{item['notes']}"</div>
      <div class="ainfo">
        📍 {location or 'Unknown'} &nbsp;|&nbsp;
        ⏰ Ends: {item['auction_end'] or '?'} &nbsp;|&nbsp;
        <a href="{item['item_url']}" target="_blank">View on MaxSold ↗</a>
      </div>
    </div>
    """, unsafe_allow_html=True)


# ── Scan button & main logic ──────────────────────────────────────────────────

scan_clicked = st.button("Scan Auctions", type="primary")

if scan_clicked:
    errors: list[str] = []
    if not anthropic_key:
        errors.append("Enter your Anthropic API key in the sidebar.")
    if not location_str:
        errors.append("Select or enter a location.")
    if errors:
        for e in errors:
            st.error(e)
        st.stop()

    progress = st.progress(0, text="Connecting to MaxSold...")
    status   = st.empty()

    try:
        # 1. Extract Algolia credentials from MaxSold's JS bundle
        session = requests.Session()
        creds   = extract_algolia_credentials(session)
        progress.progress(10, text="Connected. Fetching auctions...")

        # 2. Fetch items across nearby auctions
        status.info(f"Scanning {max_auctions} auction(s) within {radius_km} km of {location_str}...")
        all_items = fetch_items_from_auctions(
            session, creds["app_id"], creds["api_key"],
            max_auctions, location_str, radius_km,
        )

        if not all_items:
            progress.empty(); status.empty()
            st.warning("No items found. Try a different city or increase the search radius.")
            st.stop()

        # 3. Apply bid-range filter
        in_range = [i for i in all_items if min_bid <= i["current_bid"] <= max_bid]
        progress.progress(25, text=f"Found {len(in_range)} items in bid range — analysing...")
        status.info(f"Found {len(in_range)} items in ${min_bid}–${max_bid} range. "
                    f"Sending to Claude AI for valuation...")

        if not in_range:
            progress.empty(); status.empty()
            st.warning("No items matched your bid range. Try widening min/max bid.")
            st.stop()

        # 4. Batch analyse with Claude
        client  = anthropic.Anthropic(api_key=anthropic_key)
        batches = [in_range[i:i + ITEMS_PER_BATCH]
                   for i in range(0, len(in_range), ITEMS_PER_BATCH)]
        results: list[dict] = []

        for b_idx, batch in enumerate(batches):
            pct = 25 + int(55 * b_idx / len(batches))
            progress.progress(pct, text=f"Analysing batch {b_idx+1}/{len(batches)}...")

            try:
                valuations = analyze_batch(client, batch)
            except Exception as exc:
                st.warning(f"Batch {b_idx+1} failed ({exc}). Skipping.")
                continue

            for val in valuations:
                idx = val.get("index", 0)
                if idx >= len(batch):
                    continue
                item   = batch[idx].copy()
                scores = score_item(
                    item["current_bid"],
                    val.get("estimated_resale_low", 0),
                    val.get("estimated_resale_high", 0),
                    val.get("estimated_shipping", 15.0),
                    val.get("liquidity_score", 5),
                )
                results.append({
                    **item,
                    "normalized_name": val.get("normalized_name", item["raw_name"]),
                    "category":        val.get("category", "Other"),
                    "resale_low":      val.get("estimated_resale_low", 0),
                    "resale_high":     val.get("estimated_resale_high", 0),
                    "shipping":        val.get("estimated_shipping", 15.0),
                    "liquidity_score": val.get("liquidity_score", 5),
                    "notes":           val.get("notes", ""),
                    "price_source":    "AI estimate",
                    "ebay_count":      0,
                    **scores,
                })

        # ── Optional eBay enrichment ─────────────────────────────────────────
        if ebay_app_id and results:
            progress.progress(72, text=f"Fetching eBay sold comps for {len(results)} items (parallel)...")
            status.info("Looking up real eBay sold prices — this runs in parallel and takes ~15 s...")
            results = enrich_with_ebay(results, ebay_app_id, global_ids=ebay_global_ids)
            ebay_hits = sum(1 for r in results if r["price_source"] != "AI estimate")
            status.info(f"eBay data found for {ebay_hits}/{len(results)} items.")

        progress.progress(85, text="Ranking opportunities...")

        # 5. Apply ROI floor and category filter; sort by opportunity score
        if categories_filter:
            results = [r for r in results if r["category"] in categories_filter]
        results = [r for r in results if r["roi"] >= min_roi]
        results.sort(key=lambda x: x["opp_score"], reverse=True)

        progress.progress(100, text="Done!")
        time.sleep(0.4)
        progress.empty(); status.empty()

        st.session_state["results"]       = results
        st.session_state["top10"]         = results[:10]
        st.session_state["total_scanned"] = len(all_items)
        st.session_state["in_range"]      = len(in_range)

    except Exception as exc:
        progress.empty(); status.empty()
        st.error(f"Scan failed: {exc}")

# ── Results ───────────────────────────────────────────────────────────────────

if st.session_state.get("top10") is not None:
    top10   = st.session_state["top10"]
    results = st.session_state["results"]

    if not top10:
        st.info("No items met the ROI and filter criteria. "
                "Try lowering the minimum ROI or widening the bid range.")
    else:
        total_scanned = st.session_state.get("total_scanned", 0)
        in_range      = st.session_state.get("in_range", len(results))

        st.markdown(
            f"Scanned **{total_scanned}** items across **{max_auctions}** auction(s) · "
            f"**{in_range}** matched bid range · "
            f"**{len(results)}** passed ROI filter · "
            f"showing top **{len(top10)}**"
        )

        # Summary metrics
        avg_roi  = sum(r["roi"] for r in top10) / len(top10)
        best_roi = max(r["roi"] for r in top10)
        avg_liq  = sum(r["liquidity_score"] for r in top10) / len(top10)
        best_net = max(r["net_proceeds"] for r in top10)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Top Opportunities", len(top10))
        c2.metric("Avg ROI (top 10)", f"{avg_roi:.0f}%")
        c3.metric("Best ROI", f"{best_roi:.0f}%")
        c4.metric("Best Net Proceeds", f"${best_net:.0f}")

        st.markdown("---")
        st.markdown("### Top 10 Bidding Opportunities")

        left, right = st.columns(2)
        for i, item in enumerate(top10):
            with (left if i % 2 == 0 else right):
                render_card(i + 1, item)

        st.markdown("---")

        # ── Charts ────────────────────────────────────────────────────────────

        chart_df = pd.DataFrame([
            {
                "Item":        r["normalized_name"][:38],
                "ROI (%)":     r["roi"],
                "Category":    r["category"],
                "Opp. Score":  r["opp_score"],
            }
            for r in top10
        ])

        col_a, col_b = st.columns(2)

        with col_a:
            fig_bar = px.bar(
                chart_df,
                x="ROI (%)", y="Item",
                color="Category",
                orientation="h",
                title="ROI by Item",
                color_discrete_sequence=px.colors.qualitative.Set2,
                height=380,
            )
            fig_bar.update_layout(
                yaxis={"autorange": "reversed"},
                plot_bgcolor="white",
                margin=dict(l=10, r=10, t=40, b=10),
                showlegend=False,
            )
            st.plotly_chart(fig_bar, use_container_width=True)

        with col_b:
            scatter_df = pd.DataFrame([
                {
                    "Item":            r["normalized_name"][:32],
                    "ROI (%)":         r["roi"],
                    "Liquidity Score": r["liquidity_score"],
                    "Current Bid ($)": r["current_bid"],
                    "Category":        r["category"],
                    "Opp. Score":      r["opp_score"],
                }
                for r in top10
            ])
            fig_scatter = px.scatter(
                scatter_df,
                x="Liquidity Score", y="ROI (%)",
                size="Opp. Score",
                color="Category",
                hover_name="Item",
                hover_data=["Current Bid ($)", "Opp. Score"],
                title="Liquidity vs. ROI  (bubble = Opp. Score)",
                color_discrete_sequence=px.colors.qualitative.Set2,
                height=380,
            )
            fig_scatter.update_layout(
                plot_bgcolor="white",
                margin=dict(l=10, r=10, t=40, b=10),
            )
            st.plotly_chart(fig_scatter, use_container_width=True)

        # ── Full table ────────────────────────────────────────────────────────

        st.markdown("---")
        st.markdown("### All Results")

        table_df = pd.DataFrame([
            {
                "Item":           r["normalized_name"],
                "Category":       r["category"],
                "Bid ($)":        r["current_bid"],
                "Resale Low ($)": r["resale_low"],
                "Resale High ($)":r["resale_high"],
                "Net ($)":        r["net_proceeds"],
                "ROI (%)":        r["roi"],
                "Liquidity":      r["liquidity_score"],
                "Opp. Score":     r["opp_score"],
                "Auction":        r["auction_title"],
                "Ends":           r["auction_end"],
                "Link":           r["item_url"],
            }
            for r in results
        ]).sort_values("Opp. Score", ascending=False)

        st.dataframe(
            table_df,
            column_config={
                "Link":      st.column_config.LinkColumn("Link"),
                "ROI (%)":   st.column_config.NumberColumn(format="%.1f%%"),
                "Opp. Score":st.column_config.NumberColumn(format="%.1f"),
            },
            use_container_width=True,
            hide_index=True,
        )

        st.download_button(
            "Download CSV",
            data=table_df.to_csv(index=False),
            file_name="maxsold_opportunities.csv",
            mime="text/csv",
        )

else:
    # Welcome / explainer shown before first scan
    st.info("Configure settings in the sidebar, then click **Scan Auctions**.")
    st.markdown("""
**How it works**

1. Fetches live auctions near your chosen city from MaxSold
2. Retrieves all items with their current bids
3. Uses Claude AI to identify/normalize each item name and estimate resale value
4. *(If eBay App ID provided)* Fetches real sold comps from eBay in parallel — replaces AI estimates where ≥ 2 comps exist
5. Calculates ROI after eBay fees (13.25%) and estimated shipping
6. Ranks items by an **Opportunity Score** = ROI × liquidity weight

**Scoring**

| Metric | Formula |
|---|---|
| Net Proceeds | Est. Resale × (1 − 13.25%) − Shipping |
| ROI | (Net Proceeds − Current Bid) / Current Bid × 100% |
| Opportunity Score | ROI × (0.6 + 0.4 × Liquidity/10) |

A high ROI on a fast-moving item (liquidity 8–10) scores much better than the
same ROI on a slow seller — because capital stuck in unsold inventory has its
own cost.

**Tips**
- Start with 3–5 auctions and a $0–$200 bid range to keep Claude API costs low
- Set **Min ROI ≥ 50%** to focus only on strong flips
- Use the **Category filter** to target your resale expertise
""")

# ── Footer ────────────────────────────────────────────────────────────────────

st.markdown("---")
st.markdown(
    "<div style='font-size:0.73rem;color:#bbb;text-align:center;'>"
    "MaxSold Opportunity Scanner &nbsp;·&nbsp; "
    "Uses MaxSold's Algolia search APIs (unofficial) &nbsp;·&nbsp; "
    "AI valuation via Claude &nbsp;·&nbsp; "
    "Not affiliated with MaxSold or Anthropic &nbsp;·&nbsp; "
    "Always verify items before bidding"
    "</div>",
    unsafe_allow_html=True,
)
