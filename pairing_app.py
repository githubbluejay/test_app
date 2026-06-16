import streamlit as st
import pandas as pd
import random
from itertools import combinations
from collections import defaultdict
import math
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta

st.set_page_config(page_title="Golf Tournament Pairings", page_icon="⛳", layout="wide")

st.markdown("""
<style>
  .group-card {
    background:#fff;
    border:1px solid #ddd;
    border-radius:8px;
    padding:14px 16px;
    margin-bottom:12px;
  }
  .group-header {
    font-size:13px;
    font-weight:600;
    color:#555;
    margin-bottom:8px;
    letter-spacing:.5px;
    text-transform:uppercase;
  }
  .team-row {
    display:flex;
    align-items:center;
    gap:8px;
    padding:5px 0;
    font-size:15px;
  }
  .badge {
    display:inline-block;
    border-radius:4px;
    padding:1px 7px;
    font-size:12px;
    font-weight:700;
    color:#fff;
  }
  .badge-a { background:#1a6fa8; }
  .badge-b { background:#c0392b; }
  .rank-chip {
    display:inline-block;
    background:#f0f0f0;
    border-radius:12px;
    padding:1px 8px;
    font-size:12px;
    color:#444;
    margin-left:4px;
  }
  .balance-ok  { color:#27ae60; font-weight:600; font-size:12px; }
  .balance-off { color:#e67e22; font-weight:600; font-size:12px; }
  .score-good  { color:#27ae60; }
  .score-bad   { color:#e74c3c; }
</style>
""", unsafe_allow_html=True)

# ── State ─────────────────────────────────────────────────────────────────────

SAMPLE_ROSTER = {
    "name_a": "Ultra Vagines",
    "name_b": "Gutter Sluts",
    "players": [
        # Ultra Vagines – rank 1 (scratch / elite)
        {"name": "Dave Miller",    "team": "A", "rank": 1},
        {"name": "Sarah Chen",     "team": "A", "rank": 1},
        {"name": "Mike Torres",    "team": "A", "rank": 1},
        # Ultra Vagines – rank 2
        {"name": "Kate Walsh",     "team": "A", "rank": 2},
        {"name": "Tom Bradshaw",   "team": "A", "rank": 2},
        {"name": "Lisa Park",      "team": "A", "rank": 2},
        # Ultra Vagines – rank 3
        {"name": "Jake Foster",    "team": "A", "rank": 3},
        {"name": "Emma Scott",     "team": "A", "rank": 3},
        {"name": "Ryan Hughes",    "team": "A", "rank": 3},
        # Ultra Vagines – rank 4 (high handicap)
        {"name": "Nancy Kim",      "team": "A", "rank": 4},
        {"name": "Chris Bell",     "team": "A", "rank": 4},
        {"name": "Amy Grant",      "team": "A", "rank": 4},
        # Gutter Sluts – rank 1
        {"name": "Jack Davis",     "team": "B", "rank": 1},
        {"name": "Maria Lopez",    "team": "B", "rank": 1},
        {"name": "Pete Wilson",    "team": "B", "rank": 1},
        # Gutter Sluts – rank 2
        {"name": "Carol White",    "team": "B", "rank": 2},
        {"name": "Steve Nash",     "team": "B", "rank": 2},
        {"name": "Jen Adams",      "team": "B", "rank": 2},
        # Gutter Sluts – rank 3
        {"name": "Bob Johnson",    "team": "B", "rank": 3},
        {"name": "Sue Taylor",     "team": "B", "rank": 3},
        {"name": "Dan Brown",      "team": "B", "rank": 3},
        # Gutter Sluts – rank 4
        {"name": "Pat Green",      "team": "B", "rank": 4},
        {"name": "Liz Moore",      "team": "B", "rank": 4},
        {"name": "Sam Jackson",    "team": "B", "rank": 4},
    ],
}

def _init():
    defs = {
        "players": [],          # [{"name","team","rank"}]
        "pairings": {},         # {round_num: [[n1,n2,n3,n4], ...]}
        "name_a": "Team A",
        "name_b": "Team B",
        "tee_start": "08:00",
        "tee_interval": 12,
    }
    for k, v in defs.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()

# ── Helpers ────────────────────────────────────────────────────────────────────

def _rmap():
    return {p["name"]: p["rank"] for p in st.session_state.players}

def _team(tid):
    return [p for p in st.session_state.players if p["team"] == tid]

def _tee_times(n):
    try:
        base = datetime.strptime(st.session_state.tee_start, "%H:%M")
    except ValueError:
        base = datetime.strptime("08:00", "%H:%M")
    return [(base + timedelta(minutes=i * st.session_state.tee_interval)).strftime("%-I:%M %p")
            for i in range(n)]

def _pair_history(exclude_round=None):
    """
    Returns two dicts: partner_hist (same team, same group) and opp_hist (diff team, same group).
    Both keyed by frozenset of two names.
    """
    partner = defaultdict(int)
    opp = defaultdict(int)
    for r, groups in st.session_state.pairings.items():
        if r == exclude_round:
            continue
        for group in groups:
            # group = [a1, a2, b1, b2]  (first 2 = team A, last 2 = team B)
            a_pair = group[:2]
            b_pair = group[2:]
            partner[frozenset(a_pair)] += 1
            partner[frozenset(b_pair)] += 1
            for a in a_pair:
                for b in b_pair:
                    opp[frozenset({a, b})] += 1
    return partner, opp

def _all_pair_history(exclude_round=None):
    """Unified history: penalise any two players in same group regardless of role."""
    hist = defaultdict(int)
    for r, groups in st.session_state.pairings.items():
        if r == exclude_round:
            continue
        for group in groups:
            for p1, p2 in combinations(group, 2):
                hist[frozenset({p1, p2})] += 1
    return hist

def _score_groups(groups, hist):
    s = 0
    for g in groups:
        for p1, p2 in combinations(g, 2):
            s += hist.get(frozenset({p1, p2}), 0)
    return s

def _rank_sum_pair(pair, rmap):
    return rmap[pair[0]] + rmap[pair[1]]

# ── Core Pairing Algorithm ────────────────────────────────────────────────────

def _build_b_pairs_for_sums(b_names, target_sums, rmap, hist, n_tries=40):
    """
    Build pairs from b_names whose rank sums exactly match target_sums.
    Tries n_tries random orderings and returns the pairing with lowest
    history penalty, or None if no valid pairing is found.
    """
    target = sorted(target_sums)
    best_pairs = None
    best_h = math.inf

    for _ in range(n_tries):
        remaining = list(b_names)
        random.shuffle(remaining)
        pairs = []
        success = True

        for t in target:
            # Find all pairs in remaining that hit this rank sum
            candidates = [
                (i, j)
                for i in range(len(remaining))
                for j in range(i + 1, len(remaining))
                if rmap[remaining[i]] + rmap[remaining[j]] == t
            ]
            if not candidates:
                success = False
                break

            # Pick candidate with lowest history count
            best_c, best_ch = None, math.inf
            for i, j in candidates:
                h = hist.get(frozenset({remaining[i], remaining[j]}), 0)
                if h < best_ch:
                    best_ch = h
                    best_c = (i, j)

            pairs.append((remaining[best_c[0]], remaining[best_c[1]]))
            for idx in sorted(best_c, reverse=True):
                remaining.pop(idx)

        if success:
            h_total = sum(hist.get(frozenset({p[0], p[1]}), 0) for p in pairs)
            if h_total < best_h:
                best_h = h_total
                best_pairs = pairs

    return best_pairs


def generate_round(round_num, n_outer=600):
    """
    Build 6 groups of 4 (2 Team-A + 2 Team-B) per round.

    Flexible strategy — any rank combination is allowed as long as the
    Team-A pair's rank sum equals the Team-B pair's rank sum within each group:
      e.g.  (R1+R1) vs (R1+R1),  (R2+R2) vs (R2+R2),  (R1+R4) vs (R2+R3), etc.

    Algorithm:
    1. Randomly pair Team-A players (any order — no complementary constraint).
    2. Record the resulting rank-sum multiset.
    3. Build a Team-B pairing that matches those rank sums exactly.
    4. Within each rank-sum bucket, randomly assign A-pairs to B-pairs.
    5. Score by cumulative same-group repeats from earlier rounds; keep best.
    """
    hist = _all_pair_history(exclude_round=round_num)
    rmap = _rmap()

    ta = _team("A")
    tb = _team("B")
    if not ta or not tb:
        return None, None

    a_names = [p["name"] for p in ta]
    b_names = [p["name"] for p in tb]

    best_groups = None
    best_score = math.inf

    for _ in range(n_outer):
        # Random A pairing — any rank combination allowed
        a_perm = random.sample(a_names, len(a_names))
        a_pairs = [(a_perm[2 * i], a_perm[2 * i + 1]) for i in range(len(a_perm) // 2)]

        # Rank sums for each A pair
        a_sums = [rmap[p[0]] + rmap[p[1]] for p in a_pairs]

        # Build B pairs with the same rank-sum multiset
        b_pairs = _build_b_pairs_for_sums(b_names, a_sums, rmap, hist)
        if b_pairs is None:
            continue

        # Group pairs by rank sum, then randomly assign A↔B within each bucket
        a_by_sum = defaultdict(list)
        b_by_sum = defaultdict(list)
        for ap in a_pairs:
            a_by_sum[rmap[ap[0]] + rmap[ap[1]]].append(ap)
        for bp in b_pairs:
            b_by_sum[rmap[bp[0]] + rmap[bp[1]]].append(bp)

        groups = []
        for s in sorted(a_by_sum):
            b_bucket = random.sample(b_by_sum[s], len(b_by_sum[s]))
            for ap, bp in zip(a_by_sum[s], b_bucket):
                groups.append(list(ap) + list(bp))

        score = _score_groups(groups, hist)
        if score < best_score:
            best_score = score
            best_groups = groups

        if best_score == 0:
            break

    return best_groups, best_score

# ── Validation ────────────────────────────────────────────────────────────────

def _validate():
    players = st.session_state.players
    ta = _team("A")
    tb = _team("B")
    issues = []
    if len(ta) != 12:
        issues.append(f"{st.session_state.name_a} has {len(ta)} players (need 12).")
    if len(tb) != 12:
        issues.append(f"{st.session_state.name_b} has {len(tb)} players (need 12).")
    for team, name in [("A", st.session_state.name_a), ("B", st.session_state.name_b)]:
        by_rank = defaultdict(int)
        for p in players:
            if p["team"] == team:
                by_rank[p["rank"]] += 1
        for r in [1, 2, 3, 4]:
            if by_rank[r] != 3:
                issues.append(f"{name}: rank {r} has {by_rank[r]} players (expect 3 for perfect balance).")
    return issues

# ── Group rendering helper ────────────────────────────────────────────────────

def _render_group(group, gi, tee, rmap, name_a, name_b):
    a1, a2, b1, b2 = group
    a_sum = rmap.get(a1, 0) + rmap.get(a2, 0)
    b_sum = rmap.get(b1, 0) + rmap.get(b2, 0)
    bal_cls = "balance-ok" if a_sum == b_sum else "balance-off"
    bal_txt = "Balanced" if a_sum == b_sum else f"Off by {abs(a_sum - b_sum)}"

    def player_html(name, badge_cls):
        r = rmap.get(name, "?")
        return (f"<span class='badge {badge_cls}'>&nbsp;</span>&nbsp;"
                f"<strong>{name}</strong><span class='rank-chip'>R{r}</span>")

    html = f"""
    <div class="group-card">
      <div class="group-header">Group {gi + 1} &nbsp;·&nbsp; {tee}</div>
      <div class="team-row">
        <span style="width:70px;font-size:12px;font-weight:700;color:#1a6fa8;">{name_a}</span>
        {player_html(a1, "badge-a")} &nbsp;&amp;&nbsp; {player_html(a2, "badge-a")}
      </div>
      <div style="text-align:center;font-size:11px;color:#aaa;margin:2px 0;">vs</div>
      <div class="team-row">
        <span style="width:70px;font-size:12px;font-weight:700;color:#c0392b;">{name_b}</span>
        {player_html(b1, "badge-b")} &nbsp;&amp;&nbsp; {player_html(b2, "badge-b")}
      </div>
      <div style="margin-top:6px;font-size:12px;">
        Skill sums: <strong>{a_sum}</strong> vs <strong>{b_sum}</strong>
        &nbsp;—&nbsp; <span class="{bal_cls}">{bal_txt}</span>
      </div>
    </div>
    """
    return html

# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════

tab_players, tab_pairings, tab_stats, tab_export = st.tabs(
    ["Players", "Pairings", "Variety Stats", "Export"]
)

# ── Tab 1: Players ────────────────────────────────────────────────────────────

with tab_players:
    st.markdown("### Team Setup")
    c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
    with c1:
        st.session_state.name_a = st.text_input("Team A Name", st.session_state.name_a)
    with c2:
        st.session_state.name_b = st.text_input("Team B Name", st.session_state.name_b)
    with c3:
        st.session_state.tee_start = st.text_input("First Tee (HH:MM)", st.session_state.tee_start)
    with c4:
        st.session_state.tee_interval = st.number_input("Mins Between Groups", 5, 30,
                                                          st.session_state.tee_interval)

    if st.button("Load Sample Roster (Ultra Vagines vs Gutter Sluts)", width="stretch"):
        st.session_state.players = [dict(p) for p in SAMPLE_ROSTER["players"]]
        st.session_state.name_a = SAMPLE_ROSTER["name_a"]
        st.session_state.name_b = SAMPLE_ROSTER["name_b"]
        st.session_state.pairings = {}
        st.rerun()

    st.divider()

    col_form, col_import = st.columns([1, 1])

    with col_form:
        st.markdown("#### Add Player")
        with st.form("add_player", clear_on_submit=True):
            name = st.text_input("Name")
            team = st.radio("Team", ["A", "B"],
                            format_func=lambda x: st.session_state.name_a if x == "A" else st.session_state.name_b,
                            horizontal=True)
            rank = st.select_slider("Skill Rank", [1, 2, 3, 4],
                                    help="1 = strongest · 4 = weakest")
            if st.form_submit_button("Add"):
                name = name.strip()
                existing = [p["name"] for p in st.session_state.players]
                if not name:
                    st.error("Name required.")
                elif name in existing:
                    st.warning(f"'{name}' already exists.")
                else:
                    st.session_state.players.append({"name": name, "team": team, "rank": rank})
                    st.rerun()

    with col_import:
        st.markdown("#### Import CSV")
        st.caption("Columns: `name`, `team` (A or B), `rank` (1–4)")
        f = st.file_uploader("Upload", type="csv", key="csv_up")
        if f:
            try:
                df = pd.read_csv(f)
                df.columns = df.columns.str.lower().str.strip()
                added = 0
                existing = {p["name"] for p in st.session_state.players}
                for _, row in df.iterrows():
                    n = str(row.get("name", "")).strip()
                    t = str(row.get("team", "A")).strip().upper()
                    r = int(row.get("rank", 2))
                    if n and n not in existing and t in ("A", "B") and 1 <= r <= 4:
                        st.session_state.players.append({"name": n, "team": t, "rank": r})
                        existing.add(n)
                        added += 1
                st.success(f"Imported {added} players.")
                st.rerun()
            except Exception as e:
                st.error(f"Import error: {e}")

    st.divider()

    # Validation
    issues = _validate()
    if not issues:
        st.success("Roster valid — 12 per team, 3 per rank. Ready to generate pairings.")
    else:
        for issue in issues:
            st.warning(issue)

    # Roster table split by team
    players = st.session_state.players
    if players:
        ca, cb = st.columns(2)
        for col, tid, tname in [(ca, "A", st.session_state.name_a),
                                 (cb, "B", st.session_state.name_b)]:
            with col:
                team_ps = [p for p in players if p["team"] == tid]
                st.markdown(f"**{tname}** ({len(team_ps)} players)")
                if team_ps:
                    df_t = pd.DataFrame(team_ps)[["name", "rank"]].rename(
                        columns={"name": "Name", "rank": "Rank"}
                    ).sort_values("Rank")
                    edited = st.data_editor(
                        df_t,
                        column_config={
                            "Name": st.column_config.TextColumn("Name"),
                            "Rank": st.column_config.SelectboxColumn("Rank", options=[1, 2, 3, 4]),
                        },
                        width="stretch",
                        num_rows="dynamic",
                        key=f"edit_{tid}",
                    )
                    if st.button(f"Save {tname} edits", key=f"save_{tid}"):
                        other = [p for p in st.session_state.players if p["team"] != tid]
                        updated = [{"name": str(r["Name"]).strip(), "team": tid, "rank": int(r["Rank"])}
                                   for _, r in edited.iterrows() if str(r["Name"]).strip()]
                        st.session_state.players = other + updated
                        st.session_state.pairings = {}
                        st.rerun()

        if st.button("Clear All Players", type="secondary"):
            st.session_state.players = []
            st.session_state.pairings = {}
            st.rerun()
    else:
        st.info("Add players above or import a CSV.")

# ── Tab 2: Pairings ───────────────────────────────────────────────────────────

with tab_pairings:
    issues = _validate()
    if issues:
        st.warning("Fix roster issues on the Players tab before generating pairings.")
        for i in issues:
            st.caption(f"• {i}")
    else:
        rmap = _rmap()
        name_a = st.session_state.name_a
        name_b = st.session_state.name_b

        c_gen, c_clr = st.columns([3, 1])
        with c_gen:
            if st.button("Generate All 4 Rounds", type="primary", width="stretch"):
                with st.spinner("Optimising pairings…"):
                    st.session_state.pairings = {}
                    for r in range(1, 5):
                        groups, _ = generate_round(r)
                        if groups:
                            st.session_state.pairings[r] = groups
                st.rerun()
        with c_clr:
            if st.button("Clear Pairings", width="stretch"):
                st.session_state.pairings = {}
                st.rerun()

        if not st.session_state.pairings:
            st.info("Click 'Generate All 4 Rounds' to create the schedule.")
        else:
            r_tabs = st.tabs([f"Round {r}" for r in range(1, 5)])
            for r_idx, r_tab in enumerate(r_tabs):
                round_num = r_idx + 1
                with r_tab:
                    # Per-round regenerate
                    if st.button(f"Re-generate Round {round_num}", key=f"regen_{round_num}"):
                        with st.spinner("Re-optimising…"):
                            groups, _ = generate_round(round_num)
                            if groups:
                                st.session_state.pairings[round_num] = groups
                        st.rerun()

                    groups = st.session_state.pairings.get(round_num, [])
                    times = _tee_times(len(groups))

                    # Summary line
                    total_repeats = _score_groups(groups, _all_pair_history(exclude_round=round_num))
                    st.caption(
                        f"6 groups · repeat-pairing penalty vs earlier rounds: "
                        f"{'✅ 0 (perfect)' if total_repeats == 0 else f'⚠️ {total_repeats}'}"
                    )

                    cols = st.columns(3)
                    for gi, group in enumerate(groups):
                        with cols[gi % 3]:
                            html = _render_group(group, gi, times[gi], rmap, name_a, name_b)
                            st.markdown(html, unsafe_allow_html=True)

# ── Tab 3: Variety Stats ──────────────────────────────────────────────────────

with tab_stats:
    if not st.session_state.pairings:
        st.info("Generate pairings first.")
    else:
        all_names = sorted(p["name"] for p in st.session_state.players)
        n = len(all_names)
        idx = {name: i for i, name in enumerate(all_names)}

        partner_hist, opp_hist = _pair_history()

        # Build matrices
        partner_mat = np.zeros((n, n), dtype=int)
        opp_mat = np.zeros((n, n), dtype=int)
        same_group_mat = np.zeros((n, n), dtype=int)

        for key, cnt in partner_hist.items():
            p1, p2 = tuple(key)
            if p1 in idx and p2 in idx:
                partner_mat[idx[p1]][idx[p2]] = cnt
                partner_mat[idx[p2]][idx[p1]] = cnt

        for key, cnt in opp_hist.items():
            p1, p2 = tuple(key)
            if p1 in idx and p2 in idx:
                opp_mat[idx[p1]][idx[p2]] = cnt
                opp_mat[idx[p2]][idx[p1]] = cnt

        same_group_mat = partner_mat + opp_mat  # proxy (not exact but good enough for display)

        rounds_played = len(st.session_state.pairings)

        st.markdown(f"### Pairing variety after {rounds_played} round(s)")

        # Per-player summary
        player_stats = []
        rmap = _rmap()
        for p in st.session_state.players:
            name = p["name"]
            if name not in idx:
                continue
            i = idx[name]
            # Unique partners (same team, same group)
            same_team = [q["name"] for q in st.session_state.players
                         if q["team"] == p["team"] and q["name"] != name]
            unique_partners = sum(1 for q in same_team if partner_mat[i][idx[q]] > 0)

            # Unique opponents
            opp_team = [q["name"] for q in st.session_state.players if q["team"] != p["team"]]
            unique_opps = sum(1 for q in opp_team if opp_mat[i][idx[q]] > 0)

            player_stats.append({
                "Player": name,
                "Team": st.session_state.name_a if p["team"] == "A" else st.session_state.name_b,
                "Rank": rmap[name],
                f"Unique Partners (of {len(same_team)})": unique_partners,
                f"Unique Opponents (of {len(opp_team)})": unique_opps,
            })

        df_stats = pd.DataFrame(player_stats).sort_values(["Team", "Rank"])
        st.dataframe(df_stats, width="stretch", hide_index=True)

        st.divider()

        # Heatmap
        view = st.radio("Heatmap view", ["Same Group", "Partners (same team)", "Opponents"],
                        horizontal=True)
        mat = {"Same Group": same_group_mat,
               "Partners (same team)": partner_mat,
               "Opponents": opp_mat}[view]

        # Color by team for axis labels
        team_map = {p["name"]: p["team"] for p in st.session_state.players}
        label_colors = ["#1a6fa8" if team_map.get(n) == "A" else "#c0392b" for n in all_names]
        short_names = [n.split()[0] if " " in n else n for n in all_names]

        fig = go.Figure(go.Heatmap(
            z=mat,
            x=short_names,
            y=short_names,
            colorscale=[[0, "#f7f7f7"], [0.5, "#f4a261"], [1, "#e63946"]],
            zmin=0,
            zmax=max(rounds_played, 1),
            text=mat,
            texttemplate="%{text}",
            showscale=True,
            hoverongaps=False,
        ))
        fig.update_layout(
            height=600,
            margin=dict(l=10, r=10, t=30, b=10),
            xaxis=dict(tickfont=dict(size=10)),
            yaxis=dict(tickfont=dict(size=10), autorange="reversed"),
        )
        st.plotly_chart(fig, width="stretch")
        st.caption("0 = never paired · darker = more repeats. "
                   "Blue names = " + st.session_state.name_a +
                   " · Red names = " + st.session_state.name_b)

# ── Tab 4: Export ─────────────────────────────────────────────────────────────

with tab_export:
    if not st.session_state.pairings:
        st.info("Generate pairings first.")
    else:
        rmap = _rmap()
        rows = []
        for r in range(1, 5):
            groups = st.session_state.pairings.get(r, [])
            times = _tee_times(len(groups))
            for gi, group in enumerate(groups):
                a1, a2, b1, b2 = group
                a_sum = rmap.get(a1, 0) + rmap.get(a2, 0)
                b_sum = rmap.get(b1, 0) + rmap.get(b2, 0)
                rows.append({
                    "Round": r,
                    "Group": gi + 1,
                    "Tee Time": times[gi] if gi < len(times) else "",
                    f"{st.session_state.name_a} Player 1": a1,
                    f"{st.session_state.name_a} R1": rmap.get(a1, ""),
                    f"{st.session_state.name_a} Player 2": a2,
                    f"{st.session_state.name_a} R2": rmap.get(a2, ""),
                    f"{st.session_state.name_b} Player 1": b1,
                    f"{st.session_state.name_b} R1": rmap.get(b1, ""),
                    f"{st.session_state.name_b} Player 2": b2,
                    f"{st.session_state.name_b} R2": rmap.get(b2, ""),
                    "Skill Sums": f"{a_sum} vs {b_sum}",
                    "Balanced": "Yes" if a_sum == b_sum else "No",
                })

        df_export = pd.DataFrame(rows)
        st.dataframe(df_export, width="stretch")

        st.download_button(
            "Download CSV",
            data=df_export.to_csv(index=False).encode(),
            file_name="tournament_pairings.csv",
            mime="text/csv",
        )

        st.divider()
        st.subheader("Quick-Print Schedule")
        name_a = st.session_state.name_a
        name_b = st.session_state.name_b
        for r in range(1, 5):
            groups = st.session_state.pairings.get(r, [])
            times = _tee_times(len(groups))
            st.markdown(f"#### Round {r}")
            for gi, group in enumerate(groups):
                a1, a2, b1, b2 = group
                a_sum = rmap.get(a1, 0) + rmap.get(a2, 0)
                b_sum = rmap.get(b1, 0) + rmap.get(b2, 0)
                tee = times[gi] if gi < len(times) else ""
                st.markdown(
                    f"**G{gi+1}** `{tee}` — "
                    f"{name_a}: **{a1}** (R{rmap.get(a1,'?')}) & **{a2}** (R{rmap.get(a2,'?')}) "
                    f"*(sum {a_sum})* &nbsp; vs &nbsp; "
                    f"{name_b}: **{b1}** (R{rmap.get(b1,'?')}) & **{b2}** (R{rmap.get(b2,'?')}) "
                    f"*(sum {b_sum})*"
                )
            st.markdown("")
