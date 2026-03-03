"""
SQLite persistence layer for MaxSold Opportunity Scanner.

Tables:
    scan_runs   – one row per scan session (location, radius, timestamps per step)
    auctions    – auctions fetched in Step 1
    items       – items fetched in Step 2
    valuations  – Claude + eBay analysis results from Step 3

The DB file (maxsold.db) lives locally and is NOT committed to git.
"""

import sqlite3
from contextlib import contextmanager

DB_PATH = "maxsold.db"


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Create all tables if they don't exist."""
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS scan_runs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                location     TEXT    NOT NULL,
                radius_km    INTEGER,
                max_auctions INTEGER,
                started_at   TEXT    DEFAULT (datetime('now')),
                auctions_at  TEXT,
                items_at     TEXT,
                analysed_at  TEXT
            );

            CREATE TABLE IF NOT EXISTS auctions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      INTEGER NOT NULL REFERENCES scan_runs(id),
                auction_id  TEXT    NOT NULL,
                title       TEXT,
                city        TEXT,
                province    TEXT,
                ends        TEXT,
                fetched_at  TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS items (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id            INTEGER NOT NULL REFERENCES scan_runs(id),
                auction_id        TEXT    NOT NULL,
                item_id           TEXT    NOT NULL,
                raw_name          TEXT,
                description       TEXT,
                current_bid       REAL,
                auction_title     TEXT,
                auction_city      TEXT,
                auction_province  TEXT,
                auction_end       TEXT,
                auction_url       TEXT,
                item_url          TEXT,
                fetched_at        TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS valuations (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id           INTEGER NOT NULL REFERENCES scan_runs(id),
                item_id          TEXT    NOT NULL,
                normalized_name  TEXT,
                category         TEXT,
                condition        TEXT,
                condition_notes  TEXT,
                resale_low       REAL,
                resale_high      REAL,
                shipping         REAL,
                liquidity_score  INTEGER,
                notes            TEXT,
                price_source     TEXT,
                ebay_count       INTEGER,
                resale_mid       REAL,
                net_proceeds     REAL,
                roi              REAL,
                opp_score        REAL,
                analysed_at      TEXT    DEFAULT (datetime('now'))
            );
        """)


# ── scan_runs ─────────────────────────────────────────────────────────────────

def create_run(location: str, radius_km: int, max_auctions: int) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO scan_runs (location, radius_km, max_auctions) VALUES (?,?,?)",
            (location, radius_km, max_auctions),
        )
        return cur.lastrowid


def get_run(run_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM scan_runs WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None


def get_latest_run() -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM scan_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def mark_step_done(run_id: int, step: int):
    """Record the completion timestamp for steps 1 (auctions), 2 (items), 3 (analyse)."""
    col = {1: "auctions_at", 2: "items_at", 3: "analysed_at"}.get(step)
    if col:
        with _conn() as conn:
            conn.execute(
                f"UPDATE scan_runs SET {col}=datetime('now') WHERE id=?", (run_id,)
            )


def clear_from_step(run_id: int, step: int):
    """Delete all data for run_id at and downstream of the given step."""
    with _conn() as conn:
        if step <= 1:
            conn.execute("DELETE FROM auctions WHERE run_id=?", (run_id,))
            conn.execute(
                "UPDATE scan_runs SET auctions_at=NULL, items_at=NULL, analysed_at=NULL WHERE id=?",
                (run_id,),
            )
        if step <= 2:
            conn.execute("DELETE FROM items WHERE run_id=?", (run_id,))
            conn.execute(
                "UPDATE scan_runs SET items_at=NULL, analysed_at=NULL WHERE id=?",
                (run_id,),
            )
        if step <= 3:
            conn.execute("DELETE FROM valuations WHERE run_id=?", (run_id,))
            conn.execute(
                "UPDATE scan_runs SET analysed_at=NULL WHERE id=?", (run_id,)
            )


# ── auctions ──────────────────────────────────────────────────────────────────

def save_auctions(run_id: int, auctions: list[dict]):
    rows = [
        {
            "run_id":     run_id,
            "auction_id": str(a.get("id") or a.get("amAuctionId") or ""),
            "title":      a.get("title") or a.get("name") or "",
            "city":       a.get("city") or "",
            "province":   a.get("province") or a.get("state") or "",
            "ends":       a.get("ends") or a.get("endDate") or "",
        }
        for a in auctions
    ]
    with _conn() as conn:
        conn.executemany(
            """INSERT INTO auctions (run_id, auction_id, title, city, province, ends)
               VALUES (:run_id, :auction_id, :title, :city, :province, :ends)""",
            rows,
        )


def load_auctions(run_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM auctions WHERE run_id=?", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def count_auctions(run_id: int | None) -> int:
    if run_id is None:
        return 0
    with _conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM auctions WHERE run_id=?", (run_id,)
        ).fetchone()[0]


# ── items ─────────────────────────────────────────────────────────────────────

def save_items(run_id: int, items: list[dict]):
    rows = [{**i, "run_id": run_id} for i in items]
    with _conn() as conn:
        conn.executemany(
            """INSERT INTO items
               (run_id, auction_id, item_id, raw_name, description, current_bid,
                auction_title, auction_city, auction_province, auction_end,
                auction_url, item_url)
               VALUES
               (:run_id, :auction_id, :item_id, :raw_name, :description, :current_bid,
                :auction_title, :auction_city, :auction_province, :auction_end,
                :auction_url, :item_url)""",
            rows,
        )


def load_items(run_id: int) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM items WHERE run_id=?", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def count_items(run_id: int | None) -> int:
    if run_id is None:
        return 0
    with _conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM items WHERE run_id=?", (run_id,)
        ).fetchone()[0]


# ── valuations ────────────────────────────────────────────────────────────────

def save_valuations(run_id: int, results: list[dict]):
    rows = [{**r, "run_id": run_id} for r in results]
    with _conn() as conn:
        conn.executemany(
            """INSERT INTO valuations
               (run_id, item_id, normalized_name, category, condition, condition_notes,
                resale_low, resale_high, shipping, liquidity_score, notes,
                price_source, ebay_count, resale_mid, net_proceeds, roi, opp_score)
               VALUES
               (:run_id, :item_id, :normalized_name, :category, :condition, :condition_notes,
                :resale_low, :resale_high, :shipping, :liquidity_score, :notes,
                :price_source, :ebay_count, :resale_mid, :net_proceeds, :roi, :opp_score)""",
            rows,
        )


def load_valuations(run_id: int) -> list[dict]:
    """Load valuations joined with item fields needed for display, sorted best first."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT v.*,
                      i.raw_name, i.auction_title, i.auction_city,
                      i.auction_province, i.auction_end, i.item_url
               FROM valuations v
               JOIN items i ON i.item_id = v.item_id AND i.run_id = v.run_id
               WHERE v.run_id=?
               ORDER BY v.opp_score DESC""",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def count_valuations(run_id: int | None) -> int:
    if run_id is None:
        return 0
    with _conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM valuations WHERE run_id=?", (run_id,)
        ).fetchone()[0]
