from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path("data/signals.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                position TEXT NOT NULL,
                asset_class TEXT NOT NULL DEFAULT 'cn_futures',
                exchange TEXT NOT NULL DEFAULT 'SIM',
                instrument_type TEXT NOT NULL DEFAULT 'futures',
                strategy_id TEXT NOT NULL DEFAULT 'hybrid_vision_v1',
                risk_verdict TEXT,
                trend TEXT NOT NULL,
                action TEXT NOT NULL,
                confidence REAL NOT NULL,
                payload TEXT NOT NULL,
                image_uri TEXT,
                outcome_return REAL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS risk_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER REFERENCES signals(id),
                policy_name TEXT NOT NULL,
                verdict TEXT NOT NULL,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER REFERENCES signals(id),
                entry_price REAL,
                exit_price REAL,
                entry_time TIMESTAMP,
                exit_time TIMESTAMP,
                side TEXT,
                qty REAL,
                pnl REAL,
                pnl_pct REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        columns = {row[1] for row in conn.execute("PRAGMA table_info(signals)").fetchall()}
        if "asset_class" not in columns:
            conn.execute("ALTER TABLE signals ADD COLUMN asset_class TEXT NOT NULL DEFAULT 'cn_futures'")
        if "exchange" not in columns:
            conn.execute("ALTER TABLE signals ADD COLUMN exchange TEXT NOT NULL DEFAULT 'SIM'")
        if "instrument_type" not in columns:
            conn.execute("ALTER TABLE signals ADD COLUMN instrument_type TEXT NOT NULL DEFAULT 'futures'")
        if "strategy_id" not in columns:
            conn.execute("ALTER TABLE signals ADD COLUMN strategy_id TEXT NOT NULL DEFAULT 'hybrid_vision_v1'")
        if "risk_verdict" not in columns:
            conn.execute("ALTER TABLE signals ADD COLUMN risk_verdict TEXT")
        if "image_uri" not in columns:
            conn.execute("ALTER TABLE signals ADD COLUMN image_uri TEXT")
        conn.commit()


def insert_signal(record: Dict[str, Any]) -> int:
    with _get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO signals (
                created_at, symbol, timeframe, position, asset_class, exchange, instrument_type,
                strategy_id, risk_verdict, trend, action, confidence, payload, image_uri, outcome_return
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["created_at"],
                record["symbol"],
                record["timeframe"],
                record["position"],
                record.get("asset_class", "cn_futures"),
                record.get("exchange", "SIM"),
                record.get("instrument_type", "futures"),
                record.get("strategy_id", "hybrid_vision_v1"),
                record.get("risk_verdict"),
                record["trend"],
                record["action"],
                record["confidence"],
                json.dumps(record["payload"], ensure_ascii=False),
                record.get("image_uri"),
                record.get("outcome_return"),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def update_outcome(signal_id: int, outcome_return: float) -> bool:
    with _get_conn() as conn:
        cur = conn.execute(
            "UPDATE signals SET outcome_return = ? WHERE id = ?",
            (outcome_return, signal_id),
        )
        conn.commit()
        return cur.rowcount > 0


def fetch_signals_by_date(date_str: str) -> List[Dict[str, Any]]:
    start = datetime.fromisoformat(f"{date_str}T00:00:00")
    end = datetime.fromisoformat(f"{date_str}T23:59:59")
    with _get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM signals
            WHERE created_at BETWEEN ? AND ?
            ORDER BY created_at ASC
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        result.append(d)
    return result


def fetch_signal(signal_id: int) -> Optional[Dict[str, Any]]:
    with _get_conn() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["payload"] = json.loads(d["payload"])
    return d


def fetch_signals_between(start_iso: str, end_iso: str) -> List[Dict[str, Any]]:
    with _get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM signals
            WHERE created_at BETWEEN ? AND ?
            ORDER BY created_at ASC
            """,
            (start_iso, end_iso),
        ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        result.append(d)
    return result


def insert_risk_log(signal_id: int, policy_name: str, verdict: str, reason: str = "") -> int:
    with _get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO risk_logs (signal_id, policy_name, verdict, reason)
            VALUES (?, ?, ?, ?)
            """,
            (signal_id, policy_name, verdict, reason),
        )
        conn.commit()
        return int(cur.lastrowid)


def fetch_risk_logs_by_date(date_str: str) -> List[Dict[str, Any]]:
    start = datetime.fromisoformat(f"{date_str}T00:00:00")
    end = datetime.fromisoformat(f"{date_str}T23:59:59")
    with _get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM risk_logs
            WHERE created_at BETWEEN ? AND ?
            ORDER BY created_at ASC
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    return [dict(row) for row in rows]


def insert_trade(signal_id: int, entry_price: float, side: str, qty: float) -> int:
    now = datetime.now().isoformat()
    with _get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO trades (signal_id, entry_price, entry_time, side, qty)
            VALUES (?, ?, ?, ?, ?)
            """,
            (signal_id, entry_price, now, side, qty),
        )
        conn.commit()
        return int(cur.lastrowid)


def update_trade_exit(trade_id: int, exit_price: float, exit_time: str, pnl: float, pnl_pct: float) -> bool:
    with _get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE trades
            SET exit_price = ?, exit_time = ?, pnl = ?, pnl_pct = ?
            WHERE id = ?
            """,
            (exit_price, exit_time, pnl, pnl_pct, trade_id),
        )
        conn.commit()
        return cur.rowcount > 0


def fetch_trades_by_date(date_str: str) -> List[Dict[str, Any]]:
    start = datetime.fromisoformat(f"{date_str}T00:00:00")
    end = datetime.fromisoformat(f"{date_str}T23:59:59")
    with _get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM trades
            WHERE entry_time BETWEEN ? AND ?
            ORDER BY entry_time ASC
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    return [dict(row) for row in rows]
