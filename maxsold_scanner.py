"""
MaxSold Auction Opportunity Scanner — Streamlit App

Steps:
  1. Pull Auctions  — search MaxSold API, save to DB
  2. Pull Items     — fetch every item across saved auctions, save to DB
  3. Analyse        — Claude AI valuation + optional eBay comps, save to DB
  4. Results        — auto-loaded from DB, shown below the steps

Each step caches its output in maxsold.db (local only, not committed to git).
Click "Refresh" on any step to re-run it and clear all downstream data.

Run with:  streamlit run maxsold_scanner.py
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

import db
from ebay_api import liquidity_from_comps, search_sold_prices
from maxsold_api import get_auction_items, get_credentials, search_auctions

# ── Constants ─────────────────────────────────────────────────────────────────

EBAY_FEE_RATE  = 0.1325
CLAUDE_MODEL   = "claude-opus-4-6"
SOCIAL_MODEL   = "claude-haiku-4-5-20251001"
ITEMS_PER_BATCH = 15

CITY_COORDS: dict[str, str] = {
    # Canada
    "Toronto, ON":       "43.6532,-79.3832",
    "Ottawa, ON":        "45.4215,-75.6972",
    "Vancouver, BC":     "49.2827,-123.1207",
    "Calgary, AB":       "51.0447,-114.0719",
    "Montreal, QC":      "45.5017,-73.5673",
    # United States
    "New York, NY":      "40.7128,-74.0060",
    "Los Angeles, CA":   "34.0522,-118.2437",
    "Chicago, IL":       "41.8781,-87.6298",
    "Houston, TX":       "29.7604,-95.3698",
    "Phoenix, AZ":       "33.4484,-112.0740",
    "Philadelphia, PA":  "39.9526,-75.1652",
    "San Antonio, TX":   "29.4241,-98.4936",
    "San Diego, CA":     "32.7157,-117.1611",
    "Dallas, TX":        "32.7767,-96.7970",
    "San Francisco, CA": "37.7749,-122.4194",
    "Seattle, WA":       "47.6062,-122.3321",
    "Denver, CO":        "39.7392,-104.9903",
    "Boston, MA":        "42.3601,-71.0589",
    "Nashville, TN":     "36.1627,-86.7816",
    "Las Vegas, NV":     "36.1699,-115.1398",
    "Detroit, MI":       "42.3314,-83.0458",
    "Minneapolis, MN":   "44.9778,-93.2650",
    "Atlanta, GA":       "33.7490,-84.3880",
    "Miami, FL":         "25.7617,-80.1918",
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
- "condition": one of: Excellent, Good, Fair, Poor — inferred from the item \
description. Excellent=like new/complete; Good=normal used wear; \
Fair=visible wear or missing accessories; Poor=damaged/parts only
- "condition_notes": one short phrase explaining your condition assessment \
(e.g. "described as working, no accessories listed")
- "estimated_resale_low": conservative USD resale for this condition
- "estimated_resale_high": optimistic USD resale for this condition
- "estimated_shipping": typical USD shipping cost (0 for bulky furniture = \
local pickup)
- "liquidity_score": 1–10 (10=sells in 1-3 days, 7=1-2 weeks, 4=1 month, \
1=3+ months)
- "notes": one sentence on value/liquidity reasoning

Assumptions: seller pays eBay fees (~13.25%). Prices should already reflect \
the condition you assigned — do NOT double-penalise.
Be realistic/conservative — these are not collector-grade unless stated.

IMPORTANT: Return ONLY the JSON array. No markdown fences, no explanation.

Items:
"""

CONDITION_MULTIPLIERS = {
    "Excellent": 1.15,
    "Good":      1.00,
    "Fair":      0.65,
    "Poor":      0.30,
}

SOCIAL_PROMPT = """\
You write punchy social media deal alerts for estate sale flippers and bargain hunters.

For each item, write TWO posts:
1. "short" (≤ 240 chars including the link) — for Twitter/X or a quick Facebook share
2. "long" (3–5 sentences) — for Facebook groups, Reddit r/flipping, or deal communities.
   Append 3–5 relevant hashtags at the very end of the long post.

Rules:
- Tone: excited but honest. These are AI-estimated values, not guarantees.
- Mention the current bid and estimated resale range to show the opportunity.
- Include the exact link provided — do not modify it.
- Do NOT invent details not given.

Return a JSON array (same order as input), each element:
  {"index": <int>, "short": "<text>", "long": "<text>"}

IMPORTANT: Return ONLY the JSON array. No markdown fences, no explanation.

Items:
"""

# ── Page config & CSS ─────────────────────────────────────────────────────────

st.set_page_config(
    page_title="MaxSold Opportunity Scanner",
    page_icon="🏷️",
    layout="wide",
)

st.markdown("""
<style>
    .scanner-title { font-size:2.3rem; font-weight:800; color:#1a1a2e; margin-bottom:2px; }
    .scanner-sub   { color:#666; font-size:0.98rem; margin-bottom:20px; }
    .step-box {
        background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px;
        padding:16px 20px; margin-bottom:12px;
    }
    .step-title { font-size:1rem; font-weight:700; color:#1a1a2e; margin-bottom:4px; }
    .opp-card {
        background:#fff; border:1px solid #e2e2e2; border-radius:12px;
        padding:18px 20px 14px; margin-bottom:14px; position:relative;
    }
    .rank-badge {
        display:inline-block; font-size:0.72rem; font-weight:700;
        border-radius:999px; padding:2px 10px; margin-bottom:8px;
        background:#1a1a2e; color:#fff;
    }
    .rank-1  { background:#d4a017 !important; }
    .rank-2  { background:#8a8a8a !important; }
    .rank-3  { background:#a0522d !important; }
    .item-name     { font-size:1.05rem; font-weight:700; color:#1a1a2e; margin-bottom:2px; }
    .item-category { font-size:0.74rem; color:#999; text-transform:uppercase;
                     letter-spacing:0.06em; margin-bottom:12px; }
    .metrics-row   { display:flex; gap:14px; flex-wrap:wrap; margin-bottom:10px; }
    .metric        { flex:1; min-width:80px; }
    .mlabel        { font-size:0.68rem; color:#aaa; text-transform:uppercase; letter-spacing:0.05em; }
    .mvalue        { font-size:1.05rem; font-weight:700; color:#1a1a2e; }
    .roi-pos  { color:#219653; }
    .roi-warn { color:#d97706; }
    .roi-neg  { color:#dc2626; }
    .liq-chip { display:inline-block; font-size:0.76rem; font-weight:600;
                border-radius:999px; padding:2px 10px; margin-right:6px; }
    .liq-high { background:#d1fae5; color:#065f46; }
    .liq-med  { background:#fef3c7; color:#92400e; }
    .liq-low  { background:#fee2e2; color:#991b1b; }
    .notes    { font-size:0.8rem; color:#777; font-style:italic; margin-top:6px; }
    .ainfo    { font-size:0.75rem; color:#bbb; margin-top:6px; }
    .ainfo a  { color:#2563eb; text-decoration:none; }
</style>
""", unsafe_allow_html=True)

# ── DB init & session restore ─────────────────────────────────────────────────

db.init_db()

if "run_id" not in st.session_state:
    latest = db.get_latest_run()
    st.session_state.run_id = latest["id"] if latest else None

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### Settings")

    anthropic_key = st.text_input(
        "Anthropic API Key",
        type="password",
        placeholder="sk-ant-...",
        help="Required for Step 3 (item valuation). console.anthropic.com",
    )

    ebay_app_id = st.text_input(
        "eBay App ID (optional)",
        placeholder="YourApp-XXXX-XXXX-...",
        help=(
            "If provided, replaces Claude's estimates with real eBay sold prices. "
            "Free: developer.ebay.com → My Account → Application Keysets → App ID."
        ),
    )

    ebay_site = st.radio(
        "eBay market",
        options=["Canada (CAD)", "US (USD)", "Both"],
        index=0,
        horizontal=True,
    )
    _EBAY_SITE_MAP = {
        "Canada (CAD)": ["EBAY-ENCA"],
        "US (USD)":     ["EBAY-US"],
        "Both":         ["EBAY-ENCA", "EBAY-US"],
    }
    ebay_global_ids = _EBAY_SITE_MAP[ebay_site]

    st.markdown("---")
    st.markdown("**Location** *(used in Step 1)*")
    loc_mode = st.radio("", ["Select city", "Custom coordinates"],
                        label_visibility="collapsed")
    if loc_mode == "Select city":
        city = st.selectbox("City", list(CITY_COORDS.keys()))
        location_str = CITY_COORDS[city]
    else:
        location_str = st.text_input("Lat, Lng", placeholder="43.6532,-79.3832")

    st.markdown("---")
    st.markdown("**Scan settings** *(used in Step 1)*")
    max_auctions = st.slider("Auctions to scan", 1, 10, 3)
    radius_km    = st.slider("Search radius (km)", 5, 500, 50)

    st.markdown("---")
    st.markdown("**Bid filter** *(applied in Step 3)*")
    min_bid = st.number_input("Min current bid ($)", min_value=0, value=0, step=5)
    max_bid = st.number_input("Max current bid ($)", min_value=1, value=500, step=25)

    st.markdown("---")
    st.markdown("**Display filters** *(applied to Results)*")
    min_roi = st.slider("Min ROI to display (%)", 0, 200, 20)
    categories_filter = st.multiselect(
        "Category filter (blank = all)",
        ["Electronics", "Furniture", "Jewelry", "Collectibles", "Clothing",
         "Tools", "Kitchen", "Art", "Books", "Sports", "Toys", "Other"],
    )

    st.markdown("---")
    referral_code = st.text_input(
        "MaxSold referral code",
        placeholder="your-referral-code",
        help="Appended as ?ref=CODE to every item link.",
    )

# ── Header ────────────────────────────────────────────────────────────────────

st.markdown("<div class='scanner-title'>MaxSold Opportunity Scanner</div>",
            unsafe_allow_html=True)
st.markdown(
    "<div class='scanner-sub'>AI-powered resale opportunity finder — "
    "pull auctions → fetch items → analyse with Claude</div>",
    unsafe_allow_html=True,
)

# ── Helper functions ──────────────────────────────────────────────────────────

def _field(d: dict, *keys, default=None):
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def _ref_suffix(code: str) -> str:
    return f"?ref={code}" if code else ""


def analyze_batch(client: anthropic.Anthropic, batch: list[dict]) -> list[dict]:
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
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
    return json.loads(raw)


def score_item(current_bid, resale_low, resale_high, shipping, liquidity) -> dict:
    resale_mid   = (resale_low + resale_high) / 2
    net_proceeds = resale_mid * (1 - EBAY_FEE_RATE) - shipping
    roi          = ((net_proceeds - current_bid) / current_bid * 100
                    if current_bid > 0 else 0.0)
    opp_score    = roi * (0.6 + 0.4 * liquidity / 10)
    return {
        "resale_mid":   round(resale_mid, 2),
        "net_proceeds": round(net_proceeds, 2),
        "roi":          round(roi, 1),
        "opp_score":    round(opp_score, 1),
    }


def enrich_with_ebay(results: list[dict], ebay_app_id: str,
                     global_ids: list[str] | None = None) -> list[dict]:
    if global_ids is None:
        global_ids = ["EBAY-ENCA"]

    def _fetch(idx, item):
        candidates = [
            search_sold_prices(ebay_app_id, item["normalized_name"], global_id=gid)
            for gid in global_ids
        ]
        return idx, max(candidates, key=lambda r: r["count"])

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_fetch, i, r): i for i, r in enumerate(results)}
        for future in as_completed(futures):
            idx, ebay = future.result()
            item = results[idx]
            item["ebay_count"] = ebay["count"]
            if ebay["count"] >= 2:
                mult = CONDITION_MULTIPLIERS.get(item.get("condition", "Good"), 1.0)
                item["resale_low"]      = round(ebay["low"]  * mult, 2)
                item["resale_high"]     = round(ebay["high"] * mult, 2)
                item["liquidity_score"] = liquidity_from_comps(ebay["count"])
                item["price_source"]    = f"eBay · {ebay['count']} comps"
                item.update(score_item(
                    item["current_bid"], item["resale_low"], item["resale_high"],
                    item["shipping"], item["liquidity_score"],
                ))
            else:
                item["price_source"] = "AI estimate"
    return results


def generate_social_posts(client: anthropic.Anthropic, items: list[dict],
                           referral_code: str = "") -> list[dict]:
    lines = []
    for i, item in enumerate(items):
        location = ", ".join(filter(None, [item.get("auction_city", ""),
                                           item.get("auction_province", "")]))
        lines.append(
            f"{i}. {item['normalized_name']} | "
            f"Bid: ${item['current_bid']:.0f} | "
            f"Est. resale: ${item['resale_low']:.0f}–${item['resale_high']:.0f} | "
            f"ROI: {item['roi']:+.0f}% | "
            f"Ends: {item.get('auction_end', '?')} | "
            f"Location: {location or 'Unknown'} | "
            f"Link: {item['item_url']}"
        )
    msg = client.messages.create(
        model=SOCIAL_MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": SOCIAL_PROMPT + "\n".join(lines)}],
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
    return json.loads(raw)


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

    source = item.get("price_source", "AI estimate")
    if source.startswith("eBay"):
        src_badge = (f'<span style="font-size:0.7rem;background:#dcfce7;color:#166534;'
                     f'border-radius:4px;padding:1px 7px;margin-left:6px;">📊 {source}</span>')
    else:
        src_badge = (f'<span style="font-size:0.7rem;background:#f1f5f9;color:#64748b;'
                     f'border-radius:4px;padding:1px 7px;margin-left:6px;">🤖 {source}</span>')

    condition = item.get("condition", "Good")
    cond_colors = {
        "Excellent": ("#dcfce7", "#166534"),
        "Good":      ("#dbeafe", "#1e40af"),
        "Fair":      ("#fef9c3", "#854d0e"),
        "Poor":      ("#fee2e2", "#991b1b"),
    }
    cond_bg, cond_fg = cond_colors.get(condition, ("#f1f5f9", "#475569"))
    cond_notes = item.get("condition_notes", "")
    cond_title = f' title="{cond_notes}"' if cond_notes else ""
    cond_badge = (f'<span style="font-size:0.7rem;background:{cond_bg};color:{cond_fg};'
                  f'border-radius:4px;padding:1px 7px;margin-left:4px;cursor:default;"'
                  f'{cond_title}>{condition}</span>')

    st.markdown(f"""
    <div class="opp-card">
      <div class="rank-badge {rank_cls}">#{rank}</div>
      <div class="item-name">{item['normalized_name']}{src_badge}{cond_badge}</div>
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


# ── Step rendering helpers ────────────────────────────────────────────────────

def _step_header(number: int, title: str):
    st.markdown(
        f"<div class='step-title'>Step {number} &nbsp;·&nbsp; {title}</div>",
        unsafe_allow_html=True,
    )


def _fmt_ts(ts: str | None) -> str:
    """Strip the seconds from an SQLite datetime string for cleaner display."""
    if not ts:
        return ""
    return ts[:16]  # "YYYY-MM-DD HH:MM"


# ── Steps ─────────────────────────────────────────────────────────────────────

run_id = st.session_state.run_id
run    = db.get_run(run_id) if run_id else None
n_auctions = db.count_auctions(run_id)
n_items    = db.count_items(run_id)
n_vals     = db.count_valuations(run_id)

# ── Step 1 · Pull Auctions ────────────────────────────────────────────────────

with st.container():
    st.markdown("<div class='step-box'>", unsafe_allow_html=True)
    _step_header(1, "Pull Auctions")

    if n_auctions:
        st.success(
            f"✓ {n_auctions} auctions cached · {run['location']} · "
            f"{run['radius_km']} km radius · fetched {_fmt_ts(run['auctions_at'])}"
        )
        col_btn, _ = st.columns([1, 5])
        step1_clicked = col_btn.button("Refresh Auctions", key="s1")
    else:
        st.info("No data yet — configure location in the sidebar then pull auctions.")
        step1_clicked = st.button("Pull Auctions", key="s1", type="primary")

    st.markdown("</div>", unsafe_allow_html=True)

if step1_clicked:
    if not location_str:
        st.error("Select a location in the sidebar first.")
    else:
        with st.spinner("Connecting to MaxSold and fetching auctions..."):
            try:
                session = requests.Session()
                creds   = get_credentials(session)
                auctions = search_auctions(
                    session, creds["x_api_key"],
                    location=location_str,
                    radius_km=radius_km,
                    hits_per_page=max_auctions,
                )
                new_run_id = db.create_run(location_str, radius_km, max_auctions)
                db.save_auctions(new_run_id, auctions)
                db.mark_step_done(new_run_id, 1)
                st.session_state.run_id = new_run_id
                st.rerun()
            except Exception as exc:
                st.error(f"Step 1 failed: {exc}")

# ── Step 2 · Pull Items ───────────────────────────────────────────────────────

st.markdown("---")
with st.container():
    st.markdown("<div class='step-box'>", unsafe_allow_html=True)
    _step_header(2, "Pull Items")

    if n_items:
        st.success(
            f"✓ {n_items} items cached across {n_auctions} auction(s) · "
            f"fetched {_fmt_ts(run['items_at'])}"
        )
        col_btn, _ = st.columns([1, 5])
        step2_clicked = col_btn.button("Refresh Items", key="s2")
    elif n_auctions:
        st.info(f"{n_auctions} auction(s) ready — click to fetch all items.")
        step2_clicked = st.button("Pull Items", key="s2", type="primary")
    else:
        st.warning("Complete Step 1 first.")
        step2_clicked = False

    st.markdown("</div>", unsafe_allow_html=True)

if step2_clicked:
    db.clear_from_step(run_id, 2)
    db_auctions = db.load_auctions(run_id)
    ref = _ref_suffix(referral_code)

    progress = st.progress(0, text="Fetching items...")
    all_items: list[dict] = []
    errors: list[str] = []

    try:
        session = requests.Session()
        get_credentials(session)   # establishes session cookies / headers

        for i, auction in enumerate(db_auctions):
            auction_id  = auction["auction_id"]
            auction_url = f"https://www.maxsold.com/auctions/{auction_id}"
            pct = int(100 * i / len(db_auctions))
            progress.progress(pct, text=f"Fetching auction {i+1}/{len(db_auctions)}: {auction['title'][:50]}")

            try:
                raw   = get_auction_items(session, auction_id)
                items = raw if isinstance(raw, list) else raw.get("items", raw.get("data", []))
            except Exception as exc:
                errors.append(f"Auction {auction_id}: {exc}")
                continue

            for item in items:
                current_bid = float(
                    _field(item, "current_bid", "currentBid", "bid",
                           "winning_bid", "price", default=0) or 0
                )
                item_id = str(_field(item, "id", "itemid", "item_id", default=""))
                all_items.append({
                    "item_id":          item_id,
                    "auction_id":       auction_id,
                    "raw_name":         _field(item, "name", "title", default="Unknown item"),
                    "description":      _field(item, "description", "details", default=""),
                    "current_bid":      current_bid,
                    "auction_title":    auction["title"],
                    "auction_city":     auction["city"],
                    "auction_province": auction["province"],
                    "auction_end":      auction["ends"],
                    "auction_url":      auction_url,
                    "item_url":         f"{auction_url}/items/{item_id}{ref}",
                })

        progress.progress(100, text=f"Saving {len(all_items)} items...")
        db.save_items(run_id, all_items)
        db.mark_step_done(run_id, 2)
        progress.empty()

        if errors:
            st.warning(f"Completed with {len(errors)} error(s): " + "; ".join(errors[:3]))
        st.rerun()

    except Exception as exc:
        progress.empty()
        st.error(f"Step 2 failed: {exc}")

# ── Step 3 · Analyse ──────────────────────────────────────────────────────────

st.markdown("---")
with st.container():
    st.markdown("<div class='step-box'>", unsafe_allow_html=True)
    _step_header(3, "Analyse with Claude")

    if n_vals:
        st.success(
            f"✓ {n_vals} items analysed · "
            f"bid filter ${min_bid}–${max_bid} applied at last run · "
            f"analysed {_fmt_ts(run['analysed_at'])}"
        )
        col_btn, _ = st.columns([1, 5])
        step3_clicked = col_btn.button("Re-analyse", key="s3")
    elif n_items:
        st.info(f"{n_items} items ready — click to analyse with Claude AI.")
        step3_clicked = st.button("Analyse Items", key="s3", type="primary")
    else:
        st.warning("Complete Step 2 first.")
        step3_clicked = False

    st.markdown("</div>", unsafe_allow_html=True)

if step3_clicked:
    if not anthropic_key:
        st.error("Enter your Anthropic API key in the sidebar.")
    else:
        db.clear_from_step(run_id, 3)
        items = db.load_items(run_id)
        in_range = [i for i in items if min_bid <= i["current_bid"] <= max_bid]

        if not in_range:
            st.warning(f"No items in the ${min_bid}–${max_bid} bid range. "
                       "Try widening the range in the sidebar.")
        else:
            progress = st.progress(0, text="Starting analysis...")
            status   = st.empty()

            try:
                client  = anthropic.Anthropic(api_key=anthropic_key)
                batches = [in_range[i:i + ITEMS_PER_BATCH]
                           for i in range(0, len(in_range), ITEMS_PER_BATCH)]
                results: list[dict] = []

                for b_idx, batch in enumerate(batches):
                    pct = int(60 * b_idx / len(batches))
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
                            "condition":       val.get("condition", "Good"),
                            "condition_notes": val.get("condition_notes", ""),
                            "resale_low":      val.get("estimated_resale_low", 0),
                            "resale_high":     val.get("estimated_resale_high", 0),
                            "shipping":        val.get("estimated_shipping", 15.0),
                            "liquidity_score": val.get("liquidity_score", 5),
                            "notes":           val.get("notes", ""),
                            "price_source":    "AI estimate",
                            "ebay_count":      0,
                            **scores,
                        })

                if ebay_app_id and results:
                    progress.progress(65, text=f"Fetching eBay comps for {len(results)} items...")
                    status.info("Looking up real eBay sold prices — runs in parallel, ~15 s...")
                    results = enrich_with_ebay(results, ebay_app_id, global_ids=ebay_global_ids)
                    ebay_hits = sum(1 for r in results if r["price_source"] != "AI estimate")
                    status.info(f"eBay data found for {ebay_hits}/{len(results)} items.")

                progress.progress(90, text="Saving to database...")
                db.save_valuations(run_id, results)
                db.mark_step_done(run_id, 3)

                progress.progress(100, text="Done!")
                time.sleep(0.3)
                progress.empty()
                status.empty()
                st.rerun()

            except Exception as exc:
                progress.empty()
                status.empty()
                st.error(f"Step 3 failed: {exc}")

# ── Results ───────────────────────────────────────────────────────────────────

if n_vals:
    st.markdown("---")
    all_results = db.load_valuations(run_id)

    # Apply display filters (these don't require re-running — just filter on the fly)
    filtered = all_results
    if categories_filter:
        filtered = [r for r in filtered if r["category"] in categories_filter]
    filtered = [r for r in filtered if r["roi"] >= min_roi]
    top10 = filtered[:10]

    if not top10:
        st.info("No items matched the current ROI/category filters. "
                "Try lowering Min ROI or clearing the category filter.")
    else:
        st.markdown(
            f"Scanned **{n_items}** items across **{n_auctions}** auction(s) · "
            f"**{n_vals}** analysed · "
            f"**{len(filtered)}** passed filters · "
            f"showing top **{len(top10)}**"
        )

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

        # Charts
        chart_df = pd.DataFrame([
            {"Item": r["normalized_name"][:38], "ROI (%)": r["roi"],
             "Category": r["category"], "Opp. Score": r["opp_score"]}
            for r in top10
        ])

        col_a, col_b = st.columns(2)

        with col_a:
            fig_bar = px.bar(
                chart_df, x="ROI (%)", y="Item", color="Category",
                orientation="h", title="ROI by Item",
                color_discrete_sequence=px.colors.qualitative.Set2, height=380,
            )
            fig_bar.update_layout(
                yaxis={"autorange": "reversed"}, plot_bgcolor="white",
                margin=dict(l=10, r=10, t=40, b=10), showlegend=False,
            )
            st.plotly_chart(fig_bar, use_container_width=True)

        with col_b:
            scatter_df = pd.DataFrame([
                {"Item": r["normalized_name"][:32], "ROI (%)": r["roi"],
                 "Liquidity Score": r["liquidity_score"],
                 "Current Bid ($)": r["current_bid"],
                 "Category": r["category"], "Opp. Score": r["opp_score"]}
                for r in top10
            ])
            fig_scatter = px.scatter(
                scatter_df, x="Liquidity Score", y="ROI (%)",
                size="Opp. Score", color="Category",
                hover_name="Item", hover_data=["Current Bid ($)", "Opp. Score"],
                title="Liquidity vs. ROI  (bubble = Opp. Score)",
                color_discrete_sequence=px.colors.qualitative.Set2, height=380,
            )
            fig_scatter.update_layout(
                plot_bgcolor="white", margin=dict(l=10, r=10, t=40, b=10),
            )
            st.plotly_chart(fig_scatter, use_container_width=True)

        # Full table
        st.markdown("---")
        st.markdown("### All Results")

        table_df = pd.DataFrame([
            {
                "Item":            r["normalized_name"],
                "Category":        r["category"],
                "Bid ($)":         r["current_bid"],
                "Resale Low ($)":  r["resale_low"],
                "Resale High ($)": r["resale_high"],
                "Net ($)":         r["net_proceeds"],
                "ROI (%)":         r["roi"],
                "Liquidity":       r["liquidity_score"],
                "Opp. Score":      r["opp_score"],
                "Auction":         r["auction_title"],
                "Ends":            r["auction_end"],
                "Link":            r["item_url"],
            }
            for r in filtered
        ]).sort_values("Opp. Score", ascending=False)

        st.dataframe(
            table_df,
            column_config={
                "Link":       st.column_config.LinkColumn("Link"),
                "ROI (%)":    st.column_config.NumberColumn(format="%.1f%%"),
                "Opp. Score": st.column_config.NumberColumn(format="%.1f"),
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

        # Social media posts
        st.markdown("---")
        st.markdown("### Generate Deal Alert Posts")
        st.caption(
            "Uses Claude to write ready-to-copy social media posts for your top finds. "
            + ("Links will include your referral code." if referral_code
               else "Add your referral code in the sidebar to embed it in every link.")
        )

        n_posts   = st.slider("Items to generate posts for", 1, min(5, len(top10)), 3)
        gen_posts = st.button("Generate Posts", key="gen_posts")

        if gen_posts:
            if not anthropic_key:
                st.error("Anthropic API key required.")
            else:
                with st.spinner("Writing posts with Claude..."):
                    try:
                        client_haiku = anthropic.Anthropic(api_key=anthropic_key)
                        posts = generate_social_posts(
                            client_haiku, top10[:n_posts], referral_code
                        )
                        st.session_state["social_posts"] = posts
                    except Exception as exc:
                        st.error(f"Post generation failed: {exc}")

        if st.session_state.get("social_posts"):
            posts = st.session_state["social_posts"]
            for post in posts:
                idx       = post.get("index", 0)
                item_name = top10[idx]["normalized_name"] if idx < len(top10) else f"Item {idx+1}"
                with st.expander(f"#{idx+1} · {item_name}", expanded=True):
                    col_s, col_l = st.columns(2)
                    with col_s:
                        st.markdown("**Twitter / X**")
                        st.text_area("", value=post.get("short", ""), height=120,
                                     key=f"short_{idx}")
                        st.caption(f"{len(post.get('short', ''))}/240 chars")
                    with col_l:
                        st.markdown("**Facebook / Reddit / Community**")
                        st.text_area("", value=post.get("long", ""), height=160,
                                     key=f"long_{idx}")

else:
    # Welcome shown before any analysis exists
    if not run_id:
        st.info("Configure settings in the sidebar, then work through Steps 1 → 2 → 3 above.")
        st.markdown("""
**How it works**

| Step | What it does | Cached? |
|---|---|---|
| 1 · Pull Auctions | Searches MaxSold for live auctions near your city | Yes — reuse or Refresh |
| 2 · Pull Items | Fetches every lot across those auctions | Yes — reuse or Refresh |
| 3 · Analyse | Claude AI estimates resale value; eBay comps (optional) | Yes — reuse or Re-analyse |
| Results | Loads from DB, applies ROI/category filters | Auto-loads |

**Scoring**

| Metric | Formula |
|---|---|
| Net Proceeds | Est. Resale × (1 − 13.25%) − Shipping |
| ROI | (Net Proceeds − Current Bid) / Current Bid × 100% |
| Opportunity Score | ROI × (0.6 + 0.4 × Liquidity/10) |

**Tips**
- Steps 1–3 cache results locally in `maxsold.db` — no need to re-run unless you want fresh data
- Change the bid range or ROI filter in the sidebar to instantly re-filter without re-running Step 3
- eBay App ID is optional but greatly improves pricing accuracy
""")

# ── Footer ────────────────────────────────────────────────────────────────────

st.markdown("---")
st.markdown(
    "<div style='font-size:0.73rem;color:#bbb;text-align:center;'>"
    "MaxSold Opportunity Scanner &nbsp;·&nbsp; "
    "Uses MaxSold's REST API (unofficial) &nbsp;·&nbsp; "
    "AI valuation via Claude &nbsp;·&nbsp; "
    "Not affiliated with MaxSold or Anthropic &nbsp;·&nbsp; "
    "Always verify items before bidding"
    "</div>",
    unsafe_allow_html=True,
)
