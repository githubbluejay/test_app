import streamlit as st
import pandas as pd
import random
import math
from datetime import datetime, timedelta
from io import StringIO

st.set_page_config(
    page_title="Golf Tournament Pairing Planner",
    page_icon="⛳",
    layout="wide",
)

st.markdown("""
<style>
    .group-card {
        background: #f8f9fa;
        border: 1px solid #dee2e6;
        border-left: 4px solid #006747;
        border-radius: 6px;
        padding: 12px 16px;
        margin-bottom: 10px;
    }
    .group-title {
        font-weight: bold;
        color: #006747;
        font-size: 15px;
        margin-bottom: 4px;
    }
    .player-row {
        font-size: 14px;
        color: #333;
        padding: 2px 0;
    }
    .section-header {
        color: #006747;
        border-bottom: 2px solid #006747;
        padding-bottom: 6px;
        margin-bottom: 16px;
    }
</style>
""", unsafe_allow_html=True)

# ── Session state defaults ───────────────────────────────────────────────────

def _init_state():
    defaults = {
        "players": [],          # list of {"name": str, "handicap": int}
        "pairings": {},         # {round_num: [[player_name, ...], ...]}
        "num_rounds": 1,
        "group_size": 4,
        "tee_time_start": "08:00",
        "tee_time_interval": 10,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()

# ── Helpers ──────────────────────────────────────────────────────────────────

def _player_names():
    return [p["name"] for p in st.session_state.players]

def _handicap_map():
    return {p["name"]: p["handicap"] for p in st.session_state.players}

def _generate_pairings(names, group_size, strategy):
    pool = names[:]
    if strategy == "Random":
        random.shuffle(pool)
    elif strategy == "By Handicap (low → high)":
        hmap = _handicap_map()
        pool.sort(key=lambda n: hmap.get(n, 0))
    elif strategy == "By Handicap (balanced)":
        hmap = _handicap_map()
        pool.sort(key=lambda n: hmap.get(n, 0))
        # snake-draft into groups so each group has spread of handicaps
        n_groups = math.ceil(len(pool) / group_size)
        groups = [[] for _ in range(n_groups)]
        for i, player in enumerate(pool):
            idx = i % n_groups if (i // n_groups) % 2 == 0 else n_groups - 1 - (i % n_groups)
            groups[idx].append(player)
        return [g for g in groups if g]

    groups = []
    for i in range(0, len(pool), group_size):
        groups.append(pool[i:i + group_size])
    return groups

def _tee_times(n_groups, start_str, interval_min):
    try:
        base = datetime.strptime(start_str, "%H:%M")
    except ValueError:
        base = datetime.strptime("08:00", "%H:%M")
    return [(base + timedelta(minutes=i * interval_min)).strftime("%I:%M %p") for i in range(n_groups)]

def _pairings_to_df(round_num):
    groups = st.session_state.pairings.get(round_num, [])
    times = _tee_times(len(groups), st.session_state.tee_time_start, st.session_state.tee_time_interval)
    hmap = _handicap_map()
    rows = []
    for gi, group in enumerate(groups):
        tee = times[gi] if gi < len(times) else ""
        for player in group:
            rows.append({
                "Round": round_num,
                "Group": gi + 1,
                "Tee Time": tee,
                "Player": player,
                "Handicap": hmap.get(player, ""),
            })
    return pd.DataFrame(rows)

# ── Sidebar ──────────────────────────────────────────────────────────────────

st.sidebar.title("⛳ Tournament Settings")
st.session_state.num_rounds = st.sidebar.number_input("Number of Rounds", 1, 8, st.session_state.num_rounds)
st.session_state.group_size = st.sidebar.selectbox(
    "Default Group Size", [2, 3, 4], index=[2, 3, 4].index(st.session_state.group_size)
)
st.session_state.tee_time_start = st.sidebar.text_input("First Tee Time (HH:MM)", st.session_state.tee_time_start)
st.session_state.tee_time_interval = st.sidebar.number_input("Minutes Between Groups", 5, 30, st.session_state.tee_time_interval)

# ── Main tabs ────────────────────────────────────────────────────────────────

tab_players, tab_pairings, tab_export = st.tabs(["Players", "Pairings", "Export"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 – Players
# ══════════════════════════════════════════════════════════════════════════════

with tab_players:
    st.markdown("<h2 class='section-header'>Player Roster</h2>", unsafe_allow_html=True)

    col_add, col_import = st.columns([1, 1])

    with col_add:
        st.subheader("Add Player")
        with st.form("add_player_form", clear_on_submit=True):
            new_name = st.text_input("Name")
            new_hcp = st.number_input("Handicap", min_value=-10, max_value=54, value=18)
            if st.form_submit_button("Add Player"):
                if new_name.strip():
                    if new_name.strip() in _player_names():
                        st.warning(f"'{new_name.strip()}' is already in the roster.")
                    else:
                        st.session_state.players.append({"name": new_name.strip(), "handicap": new_hcp})
                        st.success(f"Added {new_name.strip()}")
                        st.rerun()
                else:
                    st.error("Name cannot be empty.")

    with col_import:
        st.subheader("Import from CSV")
        st.caption("CSV must have columns: `name`, `handicap`")
        uploaded = st.file_uploader("Upload CSV", type="csv", key="player_csv")
        if uploaded:
            try:
                df_import = pd.read_csv(uploaded)
                df_import.columns = df_import.columns.str.lower().str.strip()
                if "name" not in df_import.columns:
                    st.error("CSV missing 'name' column.")
                else:
                    added = 0
                    for _, row in df_import.iterrows():
                        name = str(row["name"]).strip()
                        hcp = int(row.get("handicap", 18)) if "handicap" in df_import.columns else 18
                        if name and name not in _player_names():
                            st.session_state.players.append({"name": name, "handicap": hcp})
                            added += 1
                    st.success(f"Imported {added} player(s).")
                    st.rerun()
            except Exception as e:
                st.error(f"Import failed: {e}")

    st.divider()

    if st.session_state.players:
        st.subheader(f"Roster ({len(st.session_state.players)} players)")

        df_players = pd.DataFrame(st.session_state.players)
        edited = st.data_editor(
            df_players,
            column_config={
                "name": st.column_config.TextColumn("Name"),
                "handicap": st.column_config.NumberColumn("Handicap", min_value=-10, max_value=54),
            },
            use_container_width=True,
            num_rows="dynamic",
            key="player_editor",
        )

        col_save, col_clear = st.columns([1, 5])
        with col_save:
            if st.button("Save Edits"):
                edited = edited.dropna(subset=["name"])
                edited["name"] = edited["name"].astype(str).str.strip()
                edited = edited[edited["name"] != ""]
                st.session_state.players = edited.to_dict("records")
                st.success("Roster saved.")
                st.rerun()
        with col_clear:
            if st.button("Clear All Players", type="secondary"):
                st.session_state.players = []
                st.session_state.pairings = {}
                st.rerun()
    else:
        st.info("No players yet. Add some above or import a CSV.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 – Pairings
# ══════════════════════════════════════════════════════════════════════════════

with tab_pairings:
    st.markdown("<h2 class='section-header'>Pairings</h2>", unsafe_allow_html=True)

    if not st.session_state.players:
        st.info("Add players on the Players tab first.")
    else:
        round_tabs = st.tabs([f"Round {r}" for r in range(1, st.session_state.num_rounds + 1)])

        for r_idx, r_tab in enumerate(round_tabs):
            round_num = r_idx + 1
            with r_tab:
                col_gen, col_opts = st.columns([2, 2])

                with col_opts:
                    strategy = st.selectbox(
                        "Pairing Strategy",
                        ["Random", "By Handicap (low → high)", "By Handicap (balanced)"],
                        key=f"strategy_{round_num}",
                    )
                    group_size_r = st.selectbox(
                        "Group Size",
                        [2, 3, 4],
                        index=[2, 3, 4].index(st.session_state.group_size),
                        key=f"gsize_{round_num}",
                    )

                with col_gen:
                    if st.button(f"Generate Pairings – Round {round_num}", key=f"gen_{round_num}", type="primary"):
                        groups = _generate_pairings(_player_names(), group_size_r, strategy)
                        st.session_state.pairings[round_num] = groups
                        st.rerun()

                    if round_num in st.session_state.pairings and round_num > 1:
                        st.caption("Tip: use 'By Handicap (balanced)' across rounds for variety.")

                if round_num in st.session_state.pairings:
                    groups = st.session_state.pairings[round_num]
                    times = _tee_times(len(groups), st.session_state.tee_time_start, st.session_state.tee_time_interval)
                    hmap = _handicap_map()

                    st.divider()
                    st.markdown(f"**{len(groups)} groups · {len(_player_names())} players**")

                    # Display groups in a 3-column grid
                    cols = st.columns(3)
                    for gi, group in enumerate(groups):
                        tee = times[gi] if gi < len(times) else ""
                        player_lines = "".join(
                            "<div class='player-row'>• {} <span style='color:#888;font-size:12px;'>(HCP {})</span></div>".format(
                                p, hmap.get(p, "?")
                            )
                            for p in group
                        )
                        with cols[gi % 3]:
                            st.markdown(f"""
                            <div class="group-card">
                                <div class="group-title">Group {gi + 1} &nbsp;·&nbsp; {tee}</div>
                                {player_lines}
                            </div>
                            """, unsafe_allow_html=True)

                    # Manual editing section
                    with st.expander("Edit Pairings Manually"):
                        flat = [p for g in groups for p in g]
                        st.caption("Reassign players to groups by editing the table below, then click Save.")

                        edit_rows = []
                        for gi, group in enumerate(groups):
                            for p in group:
                                edit_rows.append({"Group": gi + 1, "Player": p})
                        df_edit = pd.DataFrame(edit_rows)

                        all_names = _player_names()
                        edited_pairings = st.data_editor(
                            df_edit,
                            column_config={
                                "Group": st.column_config.NumberColumn("Group", min_value=1),
                                "Player": st.column_config.SelectboxColumn("Player", options=all_names),
                            },
                            use_container_width=True,
                            key=f"edit_pairings_{round_num}",
                        )

                        if st.button("Save Manual Edits", key=f"save_manual_{round_num}"):
                            new_groups = {}
                            for _, row in edited_pairings.iterrows():
                                g = int(row["Group"])
                                new_groups.setdefault(g, []).append(row["Player"])
                            st.session_state.pairings[round_num] = [
                                new_groups[k] for k in sorted(new_groups)
                            ]
                            st.success("Pairings updated.")
                            st.rerun()

                else:
                    st.info("Click 'Generate Pairings' to create groups for this round.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 – Export
# ══════════════════════════════════════════════════════════════════════════════

with tab_export:
    st.markdown("<h2 class='section-header'>Export</h2>", unsafe_allow_html=True)

    if not st.session_state.pairings:
        st.info("Generate pairings first before exporting.")
    else:
        rounds_with_pairings = sorted(st.session_state.pairings.keys())

        export_rounds = st.multiselect(
            "Rounds to export",
            options=rounds_with_pairings,
            default=rounds_with_pairings,
            format_func=lambda r: f"Round {r}",
        )

        if export_rounds:
            all_dfs = [_pairings_to_df(r) for r in export_rounds]
            df_export = pd.concat(all_dfs, ignore_index=True)

            st.dataframe(df_export, use_container_width=True)

            csv_bytes = df_export.to_csv(index=False).encode()
            st.download_button(
                "Download CSV",
                data=csv_bytes,
                file_name="tournament_pairings.csv",
                mime="text/csv",
            )

            st.divider()
            st.subheader("Print-Friendly View")
            for r in export_rounds:
                st.markdown(f"### Round {r}")
                groups = st.session_state.pairings[r]
                times = _tee_times(len(groups), st.session_state.tee_time_start, st.session_state.tee_time_interval)
                hmap = _handicap_map()
                for gi, group in enumerate(groups):
                    tee = times[gi] if gi < len(times) else ""
                    players_str = " · ".join(
                        f"{p} ({hmap.get(p, '?')})" for p in group
                    )
                    st.markdown(f"**Group {gi + 1}** &nbsp; `{tee}` &nbsp;—&nbsp; {players_str}")
                st.markdown("")
