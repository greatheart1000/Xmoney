"""存储层测试"""
import os
import sqlite3
import pytest
from datetime import date, datetime
from pathlib import Path

from app.storage import init_db, insert_signal, update_outcome, fetch_signals_by_date, fetch_signal


# 每个测试使用独立的临时数据库
@pytest.fixture
def db(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.storage.DB_PATH", db_path)
    init_db()
    yield str(db_path)


def _sample_record(**overrides):
    """构造测试用信号记录"""
    record = {
        "created_at": datetime(2026, 4, 18, 10, 30, 0).isoformat(),
        "symbol": "SA605",
        "timeframe": "5m",
        "position": "flat",
        "trend": "bearish",
        "action": "short",
        "confidence": 0.7,
        "payload": {"reason": "test signal", "entry_zone": [1188, 1190]},
    }
    record.update(overrides)
    return record


def test_init_db_creates_tables(db):
    """测试数据库初始化创建所有表"""
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()
    assert "signals" in tables


def test_init_db_creates_all_columns(db):
    """测试数据库初始化创建所有必要列"""
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(signals)")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()
    expected_columns = {
        "id", "created_at", "symbol", "timeframe", "position",
        "asset_class", "exchange", "instrument_type", "strategy_id",
        "risk_verdict", "trend", "action", "confidence", "payload",
        "outcome_return",
    }
    assert expected_columns.issubset(columns)


def test_insert_and_fetch_signal(db):
    """测试信号插入和查询"""
    record = _sample_record()
    signal_id = insert_signal(record)
    assert signal_id > 0

    fetched = fetch_signal(signal_id)
    assert fetched is not None
    assert fetched["symbol"] == "SA605"
    assert fetched["timeframe"] == "5m"
    assert fetched["trend"] == "bearish"
    assert fetched["action"] == "short"
    assert fetched["confidence"] == 0.7
    assert fetched["payload"]["reason"] == "test signal"


def test_insert_signal_with_optional_fields(db):
    """测试包含可选字段的信号插入"""
    record = _sample_record(
        asset_class="cn_futures",
        exchange="SIM",
        instrument_type="futures",
        strategy_id="hybrid_vision_v1",
        risk_verdict="risk_policy:ok",
    )
    signal_id = insert_signal(record)
    fetched = fetch_signal(signal_id)
    assert fetched["asset_class"] == "cn_futures"
    assert fetched["risk_verdict"] == "risk_policy:ok"


def test_update_outcome(db):
    """测试交易结果更新"""
    record = _sample_record()
    signal_id = insert_signal(record)

    # 更新交易结果
    result = update_outcome(signal_id, 0.015)
    assert result is True

    # 验证更新后的值
    fetched = fetch_signal(signal_id)
    assert fetched["outcome_return"] == 0.015


def test_update_outcome_nonexistent_signal(db):
    """测试更新不存在的信号返回False"""
    result = update_outcome(99999, 0.01)
    assert result is False


def test_fetch_signals_by_date(db):
    """测试按日期查询信号"""
    # 插入同一天的多条信号
    insert_signal(_sample_record(
        created_at=datetime(2026, 4, 18, 9, 0, 0).isoformat(),
        symbol="SA605",
    ))
    insert_signal(_sample_record(
        created_at=datetime(2026, 4, 18, 14, 0, 0).isoformat(),
        symbol="FG605",
    ))
    # 插入不同日期的信号
    insert_signal(_sample_record(
        created_at=datetime(2026, 4, 19, 10, 0, 0).isoformat(),
        symbol="SA605",
    ))

    signals = fetch_signals_by_date("2026-04-18")
    assert len(signals) == 2
    symbols = {s["symbol"] for s in signals}
    assert symbols == {"SA605", "FG605"}


def test_fetch_signals_by_date_empty(db):
    """测试查询没有信号的日期返回空列表"""
    signals = fetch_signals_by_date("2026-01-01")
    assert signals == []


def test_fetch_signal_nonexistent(db):
    """测试查询不存在的信号返回None"""
    result = fetch_signal(99999)
    assert result is None


def test_insert_signal_default_values(db):
    """测试插入信号时使用默认值"""
    record = _sample_record()  # 不传可选字段
    signal_id = insert_signal(record)
    fetched = fetch_signal(signal_id)
    assert fetched["asset_class"] == "cn_futures"
    assert fetched["exchange"] == "SIM"
    assert fetched["instrument_type"] == "futures"
    assert fetched["strategy_id"] == "hybrid_vision_v1"
    assert fetched["outcome_return"] is None


def test_migration_adds_columns(db):
    """测试数据库迁移添加新列"""
    # 手动删除列来模拟旧表（通过重建表结构）
    conn = sqlite3.connect(db)
    conn.execute("DROP TABLE signals")
    conn.execute(
        """
        CREATE TABLE signals (
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
    conn.close()

    # 重新运行 init_db 触发迁移
    init_db()

    # 验证迁移后的表包含所有列
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(signals)")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()
    assert "asset_class" in columns
    assert "exchange" in columns
    assert "instrument_type" in columns
    assert "strategy_id" in columns
    assert "risk_verdict" in columns

    # 迁移后应能正常插入数据
    record = _sample_record()
    signal_id = insert_signal(record)
    assert signal_id > 0


def test_payload_stored_as_json(db):
    """测试payload字段以JSON格式存储和解析"""
    payload = {
        "reason": "测试中文",
        "entry_zone": [1180.5, 1190.3],
        "nested": {"key": "value"},
    }
    record = _sample_record(payload=payload)
    signal_id = insert_signal(record)
    fetched = fetch_signal(signal_id)
    assert fetched["payload"]["reason"] == "测试中文"
    assert fetched["payload"]["entry_zone"] == [1180.5, 1190.3]
    assert fetched["payload"]["nested"]["key"] == "value"
