import streamlit as st
import pandas as pd
import random
import json
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

st.set_page_config(page_title="Malone Pairing App", page_icon="⛳", layout="wide")

st.markdown("""
<style>
  /* ── App header ── */
  .app-title {
    font-size:32px; font-weight:800; color:#006747; letter-spacing:-0.5px;
  }
  .app-sub {
    font-size:14px; color:#888; margin-top:-8px; margin-bottom:16px;
  }
  /* ── Step chips ── */
  .steps {
    display:flex; gap:8px; margin-bottom:20px; flex-wrap:wrap;
  }
  .step {
    background:#f0f0f0; border-radius:20px; padding:4px 14px;
    font-size:13px; color:#555;
  }
  .step-done { background:#d4edda; color:#155724; }
  .step-active { background:#006747; color:#fff; font-weight:600; }
  /* ── Group cards ── */
  .group-card {
    background:#fff; border:1px solid #ddd; border-radius:8px;
    padding:14px 16px; margin-bottom:12px;
  }
  .group-card-fixed {
    background:#fffbf0; border:1px solid #f0c040;
    border-left:4px solid #e6a817; border-radius:8px;
    padding:14px 16px; margin-bottom:12px;
  }
  .group-header { font-size:12px; font-weight:600; color:#666;
    margin-bottom:8px; letter-spacing:.5px; text-transform:uppercase;
  }
  .fixed-label {
    display:inline-block; background:#e6a817; color:#fff;
    border-radius:4px; font-size:10px; font-weight:700;
    padding:1px 6px; margin-left:6px; vertical-align:middle;
  }
  .team-row {
    display:flex; align-items:center; gap:8px; padding:5px 0; font-size:15px;
  }
  .badge {
    display:inline-block; border-radius:4px; padding:1px 7px;
    font-size:12px; font-weight:700; color:#fff;
  }
  .badge-a { background:#1a6fa8; }
  .badge-b { background:#c0392b; }
  .rank-chip {
    display:inline-block; background:#f0f0f0; border-radius:12px;
    padding:1px 8px; font-size:12px; color:#444; margin-left:4px;
  }
  .balance-ok  { color:#27ae60; font-weight:600; font-size:12px; }
  .balance-off { color:#e67e22; font-weight:600; font-size:12px; }
  /* ── Fixed-match cards in Fixed Matches tab ── */
  .fp-card {
    background:#fffbf0; border:1px solid #f0c040; border-radius:8px;
    padding:12px 16px; margin-bottom:8px;
    display:flex; justify-content:space-between; align-items:center;
  }
  .fp-text { font-size:14px; }
  .fp-round { font-size:12px; color:#888; }
</style>
""", unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────

ROUND_NAMES = {1: "Mon AM", 2: "Mon PM", 3: "Tue AM", 4: "Tue PM"}

SAMPLE_ROSTER = {
    "name_a": "Ultra Vagines",
    "name_b": "Gutter Sluts",
    "players": [
        {"name": "Dave Miller",  "team": "A", "rank": 1},
        {"name": "Sarah Chen",   "team": "A", "rank": 1},
        {"name": "Mike Torres",  "team": "A", "rank": 1},
        {"name": "Kate Walsh",   "team": "A", "rank": 2},
        {"name": "Tom Bradshaw", "team": "A", "rank": 2},
        {"name": "Lisa Park",    "team": "A", "rank": 2},
        {"name": "Jake Foster",  "team": "A", "rank": 3},
        {"name": "Emma Scott",   "team": "A", "rank": 3},
        {"name": "Ryan Hughes",  "team": "A", "rank": 3},
        {"name": "Nancy Kim",    "team": "A", "rank": 4},
        {"name": "Chris Bell",   "team": "A", "rank": 4},
        {"name": "Amy Grant",    "team": "A", "rank": 4},
        {"name": "Jack Davis",   "team": "B", "rank": 1},
        {"name": "Maria Lopez",  "team": "B", "rank": 1},
        {"name": "Pete Wilson",  "team": "B", "rank": 1},
        {"name": "Carol White",  "team": "B", "rank": 2},
        {"name": "Steve Nash",   "team": "B", "rank": 2},
        {"name": "Jen Adams",    "team": "B", "rank": 2},
        {"name": "Bob Johnson",  "team": "B", "rank": 3},
        {"name": "Sue Taylor",   "team": "B", "rank": 3},
        {"name": "Dan Brown",    "team": "B", "rank": 3},
        {"name": "Pat Green",    "team": "B", "rank": 4},
        {"name": "Liz Moore",    "team": "B", "rank": 4},
        {"name": "Sam Jackson",  "team": "B", "rank": 4},
    ],
}

# ── Session state ─────────────────────────────────────────────────────────────

def _init():
    defs = {
        "players": [],
        "pairings": {},          # {round_num: [[a1,a2,b1,b2], ...]}
        "fixed_pairings": [],    # [{"round":int,"a1":str,"a2":str,"b1":str,"b2":str}, ...]
        "name_a": "Team A",
        "name_b": "Team B",
        "tee_start": "08:00",
        "tee_interval": 12,
        "json_up_key": 0,        # incremented after each load to reset the file uploader
        "settings_key": 0,       # incremented after roster load to reset settings inputs
    }
    for k, v in defs.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()

# ── Helpers ───────────────────────────────────────────────────────────────────

def _rmap():
    return {p["name"]: p["rank"] for p in st.session_state.players}

def _team(tid):
    return [p for p in st.session_state.players if p["team"] == tid]

def _round_name(r):
    return ROUND_NAMES.get(r, f"Round {r}")

def _tee_times(n):
    try:
        base = datetime.strptime(st.session_state.tee_start, "%H:%M")
    except ValueError:
        base = datetime.strptime("08:00", "%H:%M")
    return [(base + timedelta(minutes=i * st.session_state.tee_interval)).strftime("%-I:%M %p")
            for i in range(n)]

def _pair_history(exclude_round=None):
    partner, opp = defaultdict(int), defaultdict(int)
    for r, groups in st.session_state.pairings.items():
        if r == exclude_round:
            continue
        for group in groups:
            a_pair, b_pair = group[:2], group[2:]
            partner[frozenset(a_pair)] += 1
            partner[frozenset(b_pair)] += 1
            for a in a_pair:
                for b in b_pair:
                    opp[frozenset({a, b})] += 1
    return partner, opp

def _all_pair_history(exclude_round=None):
    hist = defaultdict(int)
    for r, groups in st.session_state.pairings.items():
        if r == exclude_round:
            continue
        for group in groups:
            for p1, p2 in combinations(group, 2):
                hist[frozenset({p1, p2})] += 1
    return hist

def _score_groups(groups, hist):
    return sum(hist.get(frozenset({p1, p2}), 0)
               for g in groups for p1, p2 in combinations(g, 2))

def _is_fixed_group(group, round_num):
    """Return True if this group matches a fixed pairing for this round."""
    gset = frozenset(group)
    for fp in st.session_state.fixed_pairings:
        if fp["round"] == round_num:
            fpset = frozenset([fp["a1"], fp["a2"], fp["b1"], fp["b2"]])
            if fpset == gset:
                return True
    return False

def _fixed_conflicts():
    """Return list of conflict descriptions for fixed pairings."""
    issues = []
    all_player_names = {p["name"] for p in st.session_state.players}
    per_round = defaultdict(list)
    for fp in st.session_state.fixed_pairings:
        per_round[fp["round"]].append(fp)

    for r, fps in per_round.items():
        seen = []
        for fp in fps:
            players_in_fp = [fp["a1"], fp["a2"], fp["b1"], fp["b2"]]
            for name in players_in_fp:
                if name not in all_player_names:
                    issues.append(f"{_round_name(r)}: '{name}' is not in the roster.")
            for prev in seen:
                prev_players = [prev["a1"], prev["a2"], prev["b1"], prev["b2"]]
                overlap = set(players_in_fp) & set(prev_players)
                if overlap:
                    issues.append(
                        f"{_round_name(r)}: {', '.join(overlap)} appear in multiple fixed matches."
                    )
            seen.append(fp)
    return issues

# ── ILP + MC Algorithms ───────────────────────────────────────────────────────

def generate_round(round_num, time_limit=30):
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
    N = len(all_names)
    G = len(a_names) // 2

    name_idx = {n: i for i, n in enumerate(all_names)}
    a_set = set(range(len(a_names)))
    b_set = set(range(len(a_names), N))
    ranks = [rmap[n] for n in all_names]

    prob = pulp.LpProblem(f"Golf_R{round_num}", pulp.LpMinimize)

    x = [[pulp.LpVariable(f"x{p}g{g}", cat="Binary") for g in range(G)]
         for p in range(N)]

    hist_pairs = []
    for key, cnt in hist.items():
        ns = list(key)
        if len(ns) == 2 and ns[0] in name_idx and ns[1] in name_idx:
            i, j = name_idx[ns[0]], name_idx[ns[1]]
            if i > j:
                i, j = j, i
            hist_pairs.append((i, j, cnt))

    r_vars = {(i, j): pulp.LpVariable(f"r{i}_{j}", cat="Binary") for i, j, _ in hist_pairs}

    prob += pulp.lpSum(cnt * r_vars[(i, j)] for i, j, cnt in hist_pairs) if hist_pairs else 0

    for p in range(N):
        prob += pulp.lpSum(x[p][g] for g in range(G)) == 1
    for g in range(G):
        prob += pulp.lpSum(x[p][g] for p in a_set) == 2
        prob += pulp.lpSum(x[p][g] for p in b_set) == 2
        prob += (pulp.lpSum(ranks[p] * x[p][g] for p in a_set) ==
                 pulp.lpSum(ranks[p] * x[p][g] for p in b_set))
    for i, j, _ in hist_pairs:
        for g in range(G):
            prob += r_vars[(i, j)] >= x[i][g] + x[j][g] - 1

    # ── Fixed pairing constraints ─────────────────────────────────────────────
    for fp in st.session_state.fixed_pairings:
        if fp["round"] != round_num:
            continue
        fp_names = [fp["a1"], fp["a2"], fp["b1"], fp["b2"]]
        if not all(n in name_idx for n in fp_names):
            continue
        fp_idx = [name_idx[n] for n in fp_names]
        # All 4 must be in the same group: x[p0][g] == x[pi][g] for all g
        for g in range(G):
            for pi in fp_idx[1:]:
                prob += x[fp_idx[0]][g] == x[pi][g]

    prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=time_limit))

    if pulp.LpStatus[prob.status] not in ("Optimal", "Feasible"):
        return None, None

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
    """Monte Carlo fallback."""
    hist = _all_pair_history(exclude_round=round_num)
    rmap = _rmap()
    ta, tb = _team("A"), _team("B")
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
                ht = sum(hist.get(frozenset({p[0], p[1]}), 0) for p in pairs)
                if ht < best_h:
                    best_h, best = ht, pairs
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
            bb = random.sample(b_by_s[s], len(b_by_s[s]))
            for ap, bp in zip(a_by_s[s], bb):
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
    ta, tb = _team("A"), _team("B")
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
                issues.append(f"{name}: rank {r} has {by_rank[r]} players (expect 3).")
    return issues

# ── Group card renderer ────────────────────────────────────────────────────────

def _render_group(group, gi, tee, rmap, name_a, name_b, fixed=False):
    a1, a2, b1, b2 = group
    a_sum = rmap.get(a1, 0) + rmap.get(a2, 0)
    b_sum = rmap.get(b1, 0) + rmap.get(b2, 0)
    bal_cls = "balance-ok" if a_sum == b_sum else "balance-off"
    bal_txt = "Balanced" if a_sum == b_sum else f"Off by {abs(a_sum-b_sum)}"
    card_cls = "group-card-fixed" if fixed else "group-card"
    fixed_badge = "<span class='fixed-label'>FIXED</span>" if fixed else ""

    def ph(name, badge_cls):
        r = rmap.get(name, "?")
        return (f"<span class='badge {badge_cls}'>&nbsp;</span>&nbsp;"
                f"<strong>{name}</strong><span class='rank-chip'>R{r}</span>")

    return f"""
    <div class="{card_cls}">
      <div class="group-header">Group {gi+1} &nbsp;·&nbsp; {tee}{fixed_badge}</div>
      <div class="team-row">
        <span style="width:70px;font-size:12px;font-weight:700;color:#1a6fa8;">{name_a}</span>
        {ph(a1,"badge-a")} &nbsp;&amp;&nbsp; {ph(a2,"badge-a")}
      </div>
      <div style="text-align:center;font-size:11px;color:#aaa;margin:2px 0;">vs</div>
      <div class="team-row">
        <span style="width:70px;font-size:12px;font-weight:700;color:#c0392b;">{name_b}</span>
        {ph(b1,"badge-b")} &nbsp;&amp;&nbsp; {ph(b2,"badge-b")}
      </div>
      <div style="margin-top:6px;font-size:12px;">
        Skill sums: <strong>{a_sum}</strong> vs <strong>{b_sum}</strong>
        &nbsp;—&nbsp; <span class="{bal_cls}">{bal_txt}</span>
      </div>
    </div>
    """

# ── Step indicator ────────────────────────────────────────────────────────────

def _step_html(active_tab):
    steps = [
        ("1 · Players",       bool(st.session_state.players)),
        ("2 · Fixed Matches", True),
        ("3 · Pairings",      bool(st.session_state.pairings)),
        ("4 · Stats & Export",bool(st.session_state.pairings)),
    ]
    tabs = ["Players", "Fixed Matches", "Pairings", "Stats & Export"]
    chips = []
    for (label, done), tab in zip(steps, tabs):
        if tab == active_tab:
            cls = "step step-active"
        elif done:
            cls = "step step-done"
        else:
            cls = "step"
        chips.append(f"<span class='{cls}'>{label}</span>")
    return "<div class='steps'>" + "".join(chips) + "</div>"

# ══════════════════════════════════════════════════════════════════════════════
# APP HEADER
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("<div class='app-title'>⛳ Malone Pairing App</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='app-sub'>Mon AM &nbsp;·&nbsp; Mon PM &nbsp;·&nbsp; Tue AM &nbsp;·&nbsp; Tue PM</div>",
    unsafe_allow_html=True,
)

ta_count = len(_team("A"))
tb_count = len(_team("B"))
fp_count = len(st.session_state.fixed_pairings)
r_count  = len(st.session_state.pairings)
st.caption(
    f"{st.session_state.name_a}: {ta_count}/12 players  ·  "
    f"{st.session_state.name_b}: {tb_count}/12 players  ·  "
    f"{fp_count} fixed match{'es' if fp_count!=1 else ''}  ·  "
    f"{r_count}/4 rounds generated"
)
st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════

tab_players, tab_fixed, tab_pairings, tab_stats = st.tabs(
    ["Players", "Fixed Matches", "Pairings", "Stats & Export"]
)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 · PLAYERS
# ══════════════════════════════════════════════════════════════════════════════

with tab_players:
    st.markdown(_step_html("Players"), unsafe_allow_html=True)

    # Team / tee settings
    c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
    sk = st.session_state.settings_key
    with c1:
        st.session_state.name_a = st.text_input(
            "Team A name", st.session_state.name_a, key=f"name_a_{sk}")
    with c2:
        st.session_state.name_b = st.text_input(
            "Team B name", st.session_state.name_b, key=f"name_b_{sk}")
    with c3:
        st.session_state.tee_start = st.text_input(
            "First tee (HH:MM)", st.session_state.tee_start, key=f"tee_start_{sk}")
    with c4:
        st.session_state.tee_interval = st.number_input(
            "Mins between groups", 5, 30, st.session_state.tee_interval, key=f"tee_interval_{sk}")

    if st.button("Load sample roster  (Ultra Vagines vs Gutter Sluts)", width="stretch"):
        st.session_state.players        = [dict(p) for p in SAMPLE_ROSTER["players"]]
        st.session_state.name_a         = SAMPLE_ROSTER["name_a"]
        st.session_state.name_b         = SAMPLE_ROSTER["name_b"]
        st.session_state.pairings       = {}
        st.session_state.fixed_pairings = []
        st.session_state.settings_key  += 1
        st.rerun()

    st.divider()

    # ── Save / Load roster ────────────────────────────────────────────────────
    st.markdown("#### Save / Load roster")
    st.caption("Download your roster (including fixed matches) as a JSON file to reload it after a reboot.")
    col_dl, col_ul = st.columns(2)
    with col_dl:
        if st.session_state.players:
            roster_json = json.dumps({
                "name_a": st.session_state.name_a,
                "name_b": st.session_state.name_b,
                "players": st.session_state.players,
                "fixed_pairings": st.session_state.fixed_pairings,
            }, indent=2).encode()
            st.download_button(
                "⬇  Save roster as JSON",
                data=roster_json,
                file_name="malone_roster.json",
                mime="application/json",
            )
        else:
            st.caption("No roster to save yet.")
    with col_ul:
        roster_file = st.file_uploader(
            "⬆  Load roster from JSON", type="json",
            key=f"json_up_{st.session_state.json_up_key}",
        )
        if roster_file:
            try:
                loaded = json.loads(roster_file.read())
                st.session_state.name_a         = loaded.get("name_a", st.session_state.name_a)
                st.session_state.name_b         = loaded.get("name_b", st.session_state.name_b)
                st.session_state.players        = loaded.get("players", [])
                st.session_state.fixed_pairings = loaded.get("fixed_pairings", [])
                st.session_state.pairings       = {}
                st.session_state.json_up_key   += 1  # new key → uploader resets on next rerun
                st.session_state.settings_key  += 1  # new key → text inputs reset with new defaults
                st.rerun()
            except Exception as e:
                st.error(f"Could not load roster: {e}")

    st.divider()

    col_form, col_import = st.columns(2)

    with col_form:
        st.markdown("#### Add player")
        with st.form("add_player", clear_on_submit=True):
            pname = st.text_input("Name")
            pteam = st.radio(
                "Team", ["A", "B"],
                format_func=lambda x: st.session_state.name_a if x == "A" else st.session_state.name_b,
                horizontal=True,
            )
            prank = st.select_slider(
                "Skill rank", [1, 2, 3, 4],
                help="1 = strongest  ·  4 = weakest"
            )
            if st.form_submit_button("Add player"):
                pname = pname.strip()
                existing = [p["name"] for p in st.session_state.players]
                if not pname:
                    st.error("Name required.")
                elif pname in existing:
                    st.warning(f"'{pname}' already in roster.")
                else:
                    st.session_state.players.append({"name": pname, "team": pteam, "rank": prank})
                    st.rerun()

    with col_import:
        st.markdown("#### Import CSV")
        st.caption("Required columns: `name`, `team` (A or B), `rank` (1–4)")
        uploaded = st.file_uploader("Upload CSV", type="csv", key="csv_up")
        if uploaded:
            try:
                df_in = pd.read_csv(uploaded)
                df_in.columns = df_in.columns.str.lower().str.strip()
                added, existing = 0, {p["name"] for p in st.session_state.players}
                for _, row in df_in.iterrows():
                    n = str(row.get("name", "")).strip()
                    t = str(row.get("team", "A")).strip().upper()
                    r = int(row.get("rank", 2))
                    if n and n not in existing and t in ("A", "B") and 1 <= r <= 4:
                        st.session_state.players.append({"name": n, "team": t, "rank": r})
                        existing.add(n)
                        added += 1
                st.success(f"Imported {added} player(s).")
                st.rerun()
            except Exception as e:
                st.error(f"Import failed: {e}")

    st.divider()

    # Validation banner
    issues = _validate()
    if not issues:
        st.success("Roster ready — 12 per team, 3 per rank. Head to Pairings to generate the schedule.")
    else:
        for issue in issues:
            st.warning(issue)

    # Roster tables
    players = st.session_state.players
    if players:
        ca, cb = st.columns(2)
        for col, tid, tname, color in [
            (ca, "A", st.session_state.name_a, "#1a6fa8"),
            (cb, "B", st.session_state.name_b, "#c0392b"),
        ]:
            with col:
                team_ps = [p for p in players if p["team"] == tid]
                st.markdown(
                    f"<span style='color:{color};font-weight:700;font-size:15px;'>"
                    f"{tname}</span> &nbsp;<span style='color:#888;font-size:13px;'>"
                    f"({len(team_ps)} players)</span>",
                    unsafe_allow_html=True,
                )
                if team_ps:
                    rank_counts = defaultdict(int)
                    for p in team_ps:
                        rank_counts[p["rank"]] += 1
                    st.caption("  ".join(f"R{r}: {rank_counts[r]}" for r in [1,2,3,4]))

                    df_t = (
                        pd.DataFrame(team_ps)[["name", "rank"]]
                        .rename(columns={"name": "Name", "rank": "Rank"})
                        .sort_values("Rank")
                    )
                    edited = st.data_editor(
                        df_t,
                        column_config={
                            "Name": st.column_config.TextColumn("Name"),
                            "Rank": st.column_config.SelectboxColumn("Rank", options=[1,2,3,4]),
                        },
                        width="stretch",
                        num_rows="dynamic",
                        key=f"edit_{tid}",
                    )
                    if st.button(f"Save {tname} edits", key=f"save_{tid}"):
                        other = [p for p in st.session_state.players if p["team"] != tid]
                        updated = [
                            {"name": str(row["Name"]).strip(), "team": tid, "rank": int(row["Rank"])}
                            for _, row in edited.iterrows()
                            if str(row["Name"]).strip()
                        ]
                        st.session_state.players  = other + updated
                        st.session_state.pairings = {}
                        st.rerun()

        if st.button("Clear all players", type="secondary"):
            st.session_state.players        = []
            st.session_state.pairings       = {}
            st.session_state.fixed_pairings = []
            st.rerun()
    else:
        st.info("Add players above or import a CSV to get started.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 · FIXED MATCHES
# ══════════════════════════════════════════════════════════════════════════════

with tab_fixed:
    st.markdown(_step_html("Fixed Matches"), unsafe_allow_html=True)
    st.markdown(
        "Specify match-ups that **must** happen in a particular session. "
        "The optimizer will lock these in and arrange the remaining groups around them."
    )

    a_names_all = [p["name"] for p in _team("A")]
    b_names_all = [p["name"] for p in _team("B")]

    if not a_names_all or not b_names_all:
        st.info("Add players on the Players tab first.")
    else:
        with st.form("add_fixed", clear_on_submit=True):
            st.markdown("#### Add a fixed match")
            fc1, fc2 = st.columns(2)
            with fc1:
                fp_round = st.selectbox(
                    "Session",
                    options=[1, 2, 3, 4],
                    format_func=_round_name,
                )
                fp_a1 = st.selectbox(f"{st.session_state.name_a} – Player 1", a_names_all, key="fa1")
                fp_b1 = st.selectbox(f"{st.session_state.name_b} – Player 1", b_names_all, key="fb1")
            with fc2:
                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                fp_a2 = st.selectbox(f"{st.session_state.name_a} – Player 2",
                                     [n for n in a_names_all if n != fp_a1], key="fa2")
                fp_b2 = st.selectbox(f"{st.session_state.name_b} – Player 2",
                                     [n for n in b_names_all if n != fp_b1], key="fb2")

            if st.form_submit_button("Add fixed match"):
                new_fp = {"round": fp_round, "a1": fp_a1, "a2": fp_a2, "b1": fp_b1, "b2": fp_b2}
                # Prevent duplicate
                existing_sets = [
                    frozenset([f["a1"], f["a2"], f["b1"], f["b2"]])
                    for f in st.session_state.fixed_pairings
                    if f["round"] == fp_round
                ]
                new_set = frozenset([fp_a1, fp_a2, fp_b1, fp_b2])
                if new_set in existing_sets:
                    st.warning("This match-up already exists for that session.")
                else:
                    st.session_state.fixed_pairings.append(new_fp)
                    st.session_state.pairings = {}  # invalidate generated pairings
                    st.rerun()

        # Show conflicts
        conflicts = _fixed_conflicts()
        for c in conflicts:
            st.error(c)

        st.divider()

        if not st.session_state.fixed_pairings:
            st.info("No fixed matches yet. All groups will be determined by the optimizer.")
        else:
            st.markdown(f"**{len(st.session_state.fixed_pairings)} fixed match(es)**")
            rmap = _rmap()
            for i, fp in enumerate(st.session_state.fixed_pairings):
                a_sum = rmap.get(fp["a1"], 0) + rmap.get(fp["a2"], 0)
                b_sum = rmap.get(fp["b1"], 0) + rmap.get(fp["b2"], 0)
                bal = "Balanced" if a_sum == b_sum else f"Unbalanced ({a_sum} vs {b_sum})"
                bal_color = "#27ae60" if a_sum == b_sum else "#e67e22"
                col_info, col_del = st.columns([5, 1])
                with col_info:
                    st.markdown(
                        f"**{_round_name(fp['round'])}** &nbsp;·&nbsp; "
                        f"<span style='color:#1a6fa8;'>{fp['a1']} (R{rmap.get(fp['a1'],'?')}) "
                        f"& {fp['a2']} (R{rmap.get(fp['a2'],'?')})</span>"
                        f" &nbsp;vs&nbsp; "
                        f"<span style='color:#c0392b;'>{fp['b1']} (R{rmap.get(fp['b1'],'?')}) "
                        f"& {fp['b2']} (R{rmap.get(fp['b2'],'?')})</span>"
                        f" &nbsp;<span style='color:{bal_color};font-size:12px;'>({bal})</span>",
                        unsafe_allow_html=True,
                    )
                with col_del:
                    if st.button("Remove", key=f"del_fp_{i}"):
                        st.session_state.fixed_pairings.pop(i)
                        st.session_state.pairings = {}
                        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 · PAIRINGS
# ══════════════════════════════════════════════════════════════════════════════

with tab_pairings:
    st.markdown(_step_html("Pairings"), unsafe_allow_html=True)

    issues = _validate()
    if issues:
        st.warning("Fix roster issues on the Players tab first.")
        for i in issues:
            st.caption(f"• {i}")
    else:
        conflicts = _fixed_conflicts()
        if conflicts:
            for c in conflicts:
                st.error(f"Fixed match conflict: {c}")
        else:
            rmap     = _rmap()
            name_a   = st.session_state.name_a
            name_b   = st.session_state.name_b
            fp_count = len(st.session_state.fixed_pairings)

            c_gen, c_clr = st.columns([3, 1])
            with c_gen:
                gen_label = (
                    f"Generate all 4 sessions"
                    + (f"  ({fp_count} fixed match{'es' if fp_count!=1 else ''} locked in)" if fp_count else "")
                )
                if st.button(gen_label, type="primary", width="stretch"):
                    progress = st.progress(0.0, text="Starting…")
                    st.session_state.pairings = {}
                    for i, r in enumerate([1, 2, 3, 4]):
                        progress.progress(i / 4, text=f"Solving {_round_name(r)}…")
                        groups, _ = generate_round(r)
                        if groups:
                            st.session_state.pairings[r] = groups
                    progress.progress(1.0, text="Done!")
                    st.rerun()
            with c_clr:
                if st.button("Clear", width="stretch"):
                    st.session_state.pairings = {}
                    st.rerun()

            if not st.session_state.pairings:
                st.info("Click the button above to generate the full schedule.")
            else:
                round_tab_labels = [
                    f"{'✅ ' if r in st.session_state.pairings else ''}{_round_name(r)}"
                    for r in range(1, 5)
                ]
                r_tabs = st.tabs(round_tab_labels)

                for r_idx, r_tab in enumerate(r_tabs):
                    round_num = r_idx + 1
                    with r_tab:
                        col_regen, col_info = st.columns([2, 3])
                        with col_regen:
                            if st.button(f"Re-generate {_round_name(round_num)}",
                                         key=f"regen_{round_num}"):
                                with st.spinner(f"Solving {_round_name(round_num)}…"):
                                    groups, _ = generate_round(round_num)
                                    if groups:
                                        st.session_state.pairings[round_num] = groups
                                st.rerun()

                        groups = st.session_state.pairings.get(round_num, [])
                        if not groups:
                            st.info("Not generated yet.")
                            continue

                        times = _tee_times(len(groups))
                        repeats = _score_groups(groups, _all_pair_history(exclude_round=round_num))
                        fp_in_round = sum(1 for fp in st.session_state.fixed_pairings
                                          if fp["round"] == round_num)
                        with col_info:
                            parts = [f"6 groups"]
                            if fp_in_round:
                                parts.append(f"{fp_in_round} fixed")
                            parts.append(
                                "no repeats from earlier sessions" if repeats == 0
                                else f"⚠️ {repeats} repeat pairing(s)"
                            )
                            st.caption("  ·  ".join(parts))

                        cols = st.columns(3)
                        for gi, group in enumerate(groups):
                            with cols[gi % 3]:
                                fixed = _is_fixed_group(group, round_num)
                                html = _render_group(group, gi, times[gi],
                                                     rmap, name_a, name_b, fixed=fixed)
                                st.markdown(html, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 · STATS & EXPORT
# ══════════════════════════════════════════════════════════════════════════════

with tab_stats:
    st.markdown(_step_html("Stats & Export"), unsafe_allow_html=True)

    if not st.session_state.pairings:
        st.info("Generate pairings first.")
    else:
        # ── Variety stats ─────────────────────────────────────────────────────
        st.markdown("### Variety stats")
        all_names = sorted(p["name"] for p in st.session_state.players)
        n = len(all_names)
        idx = {name: i for i, name in enumerate(all_names)}
        partner_hist, opp_hist = _pair_history()

        partner_mat = np.zeros((n, n), dtype=int)
        opp_mat     = np.zeros((n, n), dtype=int)
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
        same_mat = partner_mat + opp_mat

        rmap = _rmap()
        rounds_done = len(st.session_state.pairings)
        player_stats = []
        for p in st.session_state.players:
            name = p["name"]
            if name not in idx:
                continue
            i = idx[name]
            same_team = [q["name"] for q in st.session_state.players
                         if q["team"] == p["team"] and q["name"] != name]
            opp_team  = [q["name"] for q in st.session_state.players if q["team"] != p["team"]]
            player_stats.append({
                "Player": name,
                "Team": st.session_state.name_a if p["team"] == "A" else st.session_state.name_b,
                "Rank": rmap[name],
                "Unique partners": sum(1 for q in same_team if partner_mat[i][idx[q]] > 0),
                "Possible partners": len(same_team),
                "Unique opponents": sum(1 for q in opp_team if opp_mat[i][idx[q]] > 0),
                "Possible opponents": len(opp_team),
            })

        df_stats = pd.DataFrame(player_stats).sort_values(["Team", "Rank"])
        st.dataframe(df_stats, width="stretch", hide_index=True)

        st.divider()
        st.markdown("### Pairing heatmap")
        view = st.radio(
            "Show",
            ["Same group", "Partners (same team)", "Opponents"],
            horizontal=True,
        )
        mat = {"Same group": same_mat,
               "Partners (same team)": partner_mat,
               "Opponents": opp_mat}[view]

        team_map   = {p["name"]: p["team"] for p in st.session_state.players}
        short_names = [n.split()[0] for n in all_names]
        fig = go.Figure(go.Heatmap(
            z=mat, x=short_names, y=short_names,
            colorscale=[[0,"#f7f7f7"],[0.5,"#f4a261"],[1,"#e63946"]],
            zmin=0, zmax=max(rounds_done, 1),
            text=mat, texttemplate="%{text}",
            showscale=True, hoverongaps=False,
        ))
        fig.update_layout(
            height=580, margin=dict(l=10, r=10, t=20, b=10),
            xaxis=dict(tickfont=dict(size=10)),
            yaxis=dict(tickfont=dict(size=10), autorange="reversed"),
        )
        st.plotly_chart(fig, width="stretch")
        st.caption(
            "0 = never in same group · darker = more times together  ·  "
            f"Blue = {st.session_state.name_a}  ·  Red = {st.session_state.name_b}"
        )

        # ── Export ────────────────────────────────────────────────────────────
        st.divider()
        st.markdown("### Export")
        rows = []
        for r in range(1, 5):
            groups = st.session_state.pairings.get(r, [])
            times  = _tee_times(len(groups))
            for gi, group in enumerate(groups):
                a1, a2, b1, b2 = group
                a_sum = rmap.get(a1, 0) + rmap.get(a2, 0)
                b_sum = rmap.get(b1, 0) + rmap.get(b2, 0)
                rows.append({
                    "Session":    _round_name(r),
                    "Group":      gi + 1,
                    "Tee Time":   times[gi] if gi < len(times) else "",
                    "Fixed":      "Yes" if _is_fixed_group(group, r) else "",
                    f"{st.session_state.name_a} P1": a1,
                    "R1":         rmap.get(a1, ""),
                    f"{st.session_state.name_a} P2": a2,
                    "R2":         rmap.get(a2, ""),
                    f"{st.session_state.name_b} P1": b1,
                    "R3":         rmap.get(b1, ""),
                    f"{st.session_state.name_b} P2": b2,
                    "R4":         rmap.get(b2, ""),
                    "Skill sums": f"{a_sum} vs {b_sum}",
                    "Balanced":   "Yes" if a_sum == b_sum else "No",
                })

        df_export = pd.DataFrame(rows)
        st.dataframe(df_export, width="stretch")
        st.download_button(
            "Download CSV",
            data=df_export.to_csv(index=False).encode(),
            file_name="malone_pairings.csv",
            mime="text/csv",
        )

        st.divider()
        st.markdown("### Quick-print schedule")
        for r in range(1, 5):
            if r not in st.session_state.pairings:
                continue
            groups = st.session_state.pairings[r]
            times  = _tee_times(len(groups))
            st.markdown(f"#### {_round_name(r)}")
            for gi, group in enumerate(groups):
                a1, a2, b1, b2 = group
                a_sum = rmap.get(a1, 0) + rmap.get(a2, 0)
                b_sum = rmap.get(b1, 0) + rmap.get(b2, 0)
                tee   = times[gi] if gi < len(times) else ""
                fixed_tag = " 🔒" if _is_fixed_group(group, r) else ""
                st.markdown(
                    f"**G{gi+1}**{fixed_tag} `{tee}` — "
                    f"{st.session_state.name_a}: **{a1}** (R{rmap.get(a1,'?')}) & "
                    f"**{a2}** (R{rmap.get(a2,'?')}) *(sum {a_sum})* &nbsp;vs&nbsp; "
                    f"{st.session_state.name_b}: **{b1}** (R{rmap.get(b1,'?')}) & "
                    f"**{b2}** (R{rmap.get(b2,'?')}) *(sum {b_sum})*"
                )
            st.markdown("")
