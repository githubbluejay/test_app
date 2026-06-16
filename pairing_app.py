import streamlit as st
import pandas as pd
import random
from itertools import combinations
from collections import defaultdict
try:
    import pulp
    _PULP_AVAILABLE = True
except ImportError:
    _PULP_AVAILABLE = False
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

# ── Core Pairing Algorithm (ILP via PuLP, MC fallback) ───────────────────────

def generate_round(round_num, time_limit=30):
    """
    Build 6 balanced groups of 4 (2 Team-A + 2 Team-B) per round.

    Uses Integer Linear Programming (PuLP/CBC) to find the provably optimal
    grouping that minimises repeat same-group appearances from earlier rounds,
    subject to:
      • Every player in exactly one group.
      • Exactly 2 Team-A and 2 Team-B players per group.
      • Team-A rank sum == Team-B rank sum within each group (skill balance).

    Falls back to Monte Carlo heuristic if PuLP is unavailable or the solver
    returns no feasible solution within time_limit seconds.
    """
    if _PULP_AVAILABLE:
        result = _generate_round_ilp(round_num, time_limit)
        if result[0] is not None:
            return result

    return _generate_round_mc(round_num)


def _generate_round_ilp(round_num, time_limit=30):
    hist = _all_pair_history(exclude_round=round_num)
    rmap = _rmap()

    ta = _team("A")
    tb = _team("B")
    if not ta or not tb:
        return None, None

    a_names = [p["name"] for p in ta]
    b_names = [p["name"] for p in tb]
    all_names = a_names + b_names
    N = len(all_names)          # 24
    G = len(a_names) // 2       # 6 groups

    name_idx = {n: i for i, n in enumerate(all_names)}
    a_set = set(range(len(a_names)))
    b_set = set(range(len(a_names), N))
    ranks = [rmap[n] for n in all_names]

    prob = pulp.LpProblem(f"Golf_R{round_num}", pulp.LpMinimize)

    # x[p][g] = 1 if player p is assigned to group g
    x = [[pulp.LpVariable(f"x{p}g{g}", cat="Binary") for g in range(G)]
         for p in range(N)]

    # Identify historical pairs (player-index pairs with repeat count)
    hist_pairs = []
    for key, cnt in hist.items():
        ns = list(key)
        if len(ns) == 2 and ns[0] in name_idx and ns[1] in name_idx:
            i, j = name_idx[ns[0]], name_idx[ns[1]]
            if i > j:
                i, j = j, i
            hist_pairs.append((i, j, cnt))

    # r[i,j] = 1 if players i and j share a group this round (only for historical pairs)
    r = {(i, j): pulp.LpVariable(f"r{i}_{j}", cat="Binary") for i, j, _ in hist_pairs}

    # Objective: minimise weighted repeat pairings
    prob += pulp.lpSum(cnt * r[(i, j)] for i, j, cnt in hist_pairs) if hist_pairs else 0

    # Each player in exactly one group
    for p in range(N):
        prob += pulp.lpSum(x[p][g] for g in range(G)) == 1

    # Each group: exactly 2 Team-A and 2 Team-B
    for g in range(G):
        prob += pulp.lpSum(x[p][g] for p in a_set) == 2
        prob += pulp.lpSum(x[p][g] for p in b_set) == 2

    # Skill balance: rank sum of A players == rank sum of B players per group
    for g in range(G):
        prob += (pulp.lpSum(ranks[p] * x[p][g] for p in a_set) ==
                 pulp.lpSum(ranks[p] * x[p][g] for p in b_set))

    # Link r[i,j] to group co-membership: r[i,j] >= x[i][g] + x[j][g] - 1
    for i, j, _ in hist_pairs:
        for g in range(G):
            prob += r[(i, j)] >= x[i][g] + x[j][g] - 1

    prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=time_limit))

    if pulp.LpStatus[prob.status] not in ("Optimal", "Feasible"):
        return None, None

    # Extract groups: A players first, then B players
    groups = defaultdict(lambda: ([], []))
    for p in range(N):
        name = all_names[p]
        for g in range(G):
            if (pulp.value(x[p][g]) or 0) > 0.5:
                if p in a_set:
                    groups[g][0].append(name)
                else:
                    groups[g][1].append(name)

    final_groups = [groups[g][0] + groups[g][1] for g in range(G)]
    score = int(round(pulp.value(prob.objective) or 0))
    return final_groups, score


def _generate_round_mc(round_num, n_outer=600):
    """Monte Carlo fallback — used when PuLP is unavailable."""
    hist = _all_pair_history(exclude_round=round_num)
    rmap = _rmap()

    ta = _team("A")
    tb = _team("B")
    if not ta or not tb:
        return None, None

    a_names = [p["name"] for p in ta]
    b_names = [p["name"] for p in tb]

    def build_b(target_sums, n_tries=40):
        target = sorted(target_sums)
        best, best_h = None, math.inf
        for _ in range(n_tries):
            rem = list(b_names)
            random.shuffle(rem)
            pairs, ok = [], True
            for t in target:
                cands = [(i, j) for i in range(len(rem))
                         for j in range(i + 1, len(rem))
                         if rmap[rem[i]] + rmap[rem[j]] == t]
                if not cands:
                    ok = False; break
                bc, bh = None, math.inf
                for i, j in cands:
                    h = hist.get(frozenset({rem[i], rem[j]}), 0)
                    if h < bh:
                        bh, bc = h, (i, j)
                pairs.append((rem[bc[0]], rem[bc[1]]))
                for idx in sorted(bc, reverse=True):
                    rem.pop(idx)
            if ok:
                h_total = sum(hist.get(frozenset({p[0], p[1]}), 0) for p in pairs)
                if h_total < best_h:
                    best_h, best = h_total, pairs
        return best

    best_groups, best_score = None, math.inf
    for _ in range(n_outer):
        a_perm = random.sample(a_names, len(a_names))
        a_pairs = [(a_perm[2*i], a_perm[2*i+1]) for i in range(len(a_perm)//2)]
        a_sums = [rmap[p[0]] + rmap[p[1]] for p in a_pairs]
        b_pairs = build_b(a_sums)
        if b_pairs is None:
            continue
        a_by_s, b_by_s = defaultdict(list), defaultdict(list)
        for ap in a_pairs:
            a_by_s[rmap[ap[0]] + rmap[ap[1]]].append(ap)
        for bp in b_pairs:
            b_by_s[rmap[bp[0]] + rmap[bp[1]]].append(bp)
        groups = []
        for s in sorted(a_by_s):
            b_bucket = random.sample(b_by_s[s], len(b_by_s[s]))
            for ap, bp in zip(a_by_s[s], b_bucket):
                groups.append(list(ap) + list(bp))
        score = _score_groups(groups, hist)
        if score < best_score:
            best_score, best_groups = score, groups
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
