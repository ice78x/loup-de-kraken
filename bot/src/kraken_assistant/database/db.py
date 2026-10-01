"""Stockage SQLite : journal des signaux, positions (paper + Kraken), exécutions, scans, état."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    scan_id INTEGER,
    instrument_key TEXT NOT NULL,
    display TEXT,
    asset_class TEXT,
    direction TEXT NOT NULL,
    status TEXT NOT NULL,             -- TRADE | WATCH
    strategy TEXT,
    score REAL,
    entry_low REAL, entry_high REAL, entry REAL,
    sl REAL, tp1 REAL, tp2 REAL, tp3 REAL,
    leverage INTEGER,
    risk_percent REAL, risk_amount REAL, position_size REAL, notional_eur REAL,
    catalyst TEXT, technical_reason TEXT, source TEXT, invalidation TEXT,
    result TEXT,                      -- WIN | LOSS | BE | EXPIRED | NOT_TAKEN
    r_achieved REAL,
    outcome_status TEXT DEFAULT 'open',
    payload TEXT
);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,             -- paper | kraken_margin | kraken_futures | kraken_spot
    external_id TEXT,
    signal_id INTEGER,
    instrument_key TEXT NOT NULL,
    display TEXT, base TEXT, venue TEXT, asset_class TEXT,
    direction TEXT NOT NULL,
    entry REAL, entry_low REAL, entry_high REAL,
    qty_initial REAL, qty_remaining REAL,
    sl REAL, sl_initial REAL, tp1 REAL, tp2 REAL, tp3 REAL,
    tp1_hit INTEGER DEFAULT 0, tp2_hit INTEGER DEFAULT 0, tp3_hit INTEGER DEFAULT 0,
    invalidation REAL,
    status TEXT NOT NULL,             -- pending | open | closed | cancelled
    opened_at TEXT, closed_at TEXT, created_at TEXT,
    realized_pnl_eur REAL DEFAULT 0, fees_eur REAL DEFAULT 0,
    strategy TEXT, catalyst TEXT, leverage INTEGER, risk_eur_initial REAL,
    eur_per_quote REAL, fee_rate_pct REAL, maker_fee_pct REAL, last_checked TEXT, notes TEXT,
    UNIQUE(source, external_id)
);
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,               -- entry | tp1 | tp2 | tp3 | sl | manual | expire
    price REAL, qty REAL, pnl_eur REAL, fee_eur REAL, note TEXT
);
CREATE TABLE IF NOT EXISTS cash_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, amount_eur REAL NOT NULL, note TEXT
);
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, mode TEXT, instruments INTEGER, candidates INTEGER, analyzed INTEGER,
    valid INTEGER, watch INTEGER, duration_s REAL, verdict TEXT, report TEXT
);
CREATE TABLE IF NOT EXISTS news (
    id TEXT PRIMARY KEY, title TEXT, url TEXT, source TEXT, tier INTEGER, published_at TEXT,
    fetched_at TEXT, payload TEXT
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(ts);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL") if self.path != ":memory:" else None
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(positions)").fetchall()}
        if "maker_fee_pct" not in cols:
            self.conn.execute("ALTER TABLE positions ADD COLUMN maker_fee_pct REAL")

    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        with self._lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur.lastrowid or 0

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple | dict = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def insert(self, table: str, data: dict) -> int:
        cols = ", ".join(data)
        ph = ", ".join(f":{k}" for k in data)
        return self.execute(f"INSERT INTO {table} ({cols}) VALUES ({ph})", data)

    def update(self, table: str, row_id: int, data: dict) -> None:
        sets = ", ".join(f"{k}=:{k}" for k in data)
        self.execute(f"UPDATE {table} SET {sets} WHERE id=:_id", {**data, "_id": row_id})

    # --- kv ---
    def kv_get(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def kv_set(self, key: str, value: Any) -> None:
        self.execute("INSERT INTO kv(key, value, updated_at) VALUES(?,?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                     (key, json.dumps(value, default=str), utcnow()))
