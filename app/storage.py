from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path("data/signals.db")


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                position TEXT NOT NULL,
                trend TEXT NOT NULL,
                action TEXT NOT NULL,
                confidence REAL NOT NULL,
                payload TEXT NOT NULL,
                outcome_return REAL
            )
            """
        )
        conn.commit()


def insert_signal(record: Dict[str, Any]) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            INSERT INTO signals (
                created_at, symbol, timeframe, position, trend, action,
                confidence, payload, outcome_return
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["created_at"],
                record["symbol"],
                record["timeframe"],
                record["position"],
                record["trend"],
                record["action"],
                record["confidence"],
                json.dumps(record["payload"], ensure_ascii=False),
                record.get("outcome_return"),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def update_outcome(signal_id: int, outcome_return: float) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "UPDATE signals SET outcome_return = ? WHERE id = ?", (outcome_return, signal_id)
        )
        conn.commit()
        return cur.rowcount > 0


def fetch_signals_by_date(date_str: str) -> List[Dict[str, Any]]:
    start = datetime.fromisoformat(f"{date_str}T00:00:00")
    end = datetime.fromisoformat(f"{date_str}T23:59:59")
    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["payload"] = json.loads(d["payload"])
    return d
