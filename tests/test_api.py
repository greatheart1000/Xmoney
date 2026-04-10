from fastapi.testclient import TestClient

from app.main import app
from app.models import DecisionResult, ParsedImageSignal


client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_decision_multi_endpoint(monkeypatch):
    monkeypatch.setattr(
        "app.main.hybrid_decision_multi",
        lambda req: {
            "short_term": DecisionResult(
                trend="bullish",
                action="long",
                reason=["short term"],
                ai_decision_report="【AI 交易助手决策报告】\n当前状态：符合进场做多条件。",
                entry_zone=[100, 101],
                stop_loss=99,
                take_profit=[103],
                expected_remaining_bars=5,
                expected_total_move_pct=0.02,
                confidence=0.8,
            ),
            "swing": DecisionResult(
                trend="neutral",
                action="wait",
                reason=["swing"],
                confidence=0.7,
            ),
            "long_term": DecisionResult(
                trend="bearish",
                action="short",
                reason=["long term"],
                entry_zone=[100, 99],
                stop_loss=101,
                take_profit=[97],
                expected_remaining_bars=20,
                expected_total_move_pct=-0.05,
                confidence=0.75,
            ),
        },
    )

    payload = {
        "parsed": {
            "symbol": "SA605",
            "timeframe": "15m",
            "close": 1180,
            "ma5": 1181,
            "ma10": 1182,
            "ma20": 1184,
            "ma40": 1188,
            "ma60": 1192,
            "macd_diff": -2.2,
            "macd_dea": -2.0,
            "macd_hist": -0.2,
            "volume": 1000,
            "open_interest": 800000,
            "support_levels": [1177],
            "resistance_levels": [1188, 1198],
            "confidence": 0.7,
        },
        "position": "flat",
    }
    resp = client.post("/api/v1/decision/multi", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["strategies"].keys()) == {"short_term", "swing", "long_term"}
    assert "AI 交易助手决策报告" in body["strategies"]["short_term"]["ai_decision_report"]


def test_backtest_summary_endpoint(monkeypatch):
    monkeypatch.setattr(
        "app.main.fetch_signals_between",
        lambda start, end: [
            {
                "action": "long",
                "outcome_return": 0.01,
                "payload": {"decision": {"is_high_quality_setup": True}},
            },
            {
                "action": "short",
                "outcome_return": -0.02,
                "payload": {"decision": {"is_high_quality_setup": False}},
            },
            {
                "action": "wait",
                "outcome_return": 0.0005,
                "payload": {"decision": {"is_high_quality_setup": False}},
            },
        ],
    )
    resp = client.get("/api/v1/backtest/summary?period=7d")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_signals"] == 3
    assert body["evaluated_signals"] == 3
    assert body["correct_signals"] == 3


def test_signal_from_oss_image_endpoint(monkeypatch):
    monkeypatch.setattr("app.main._download_image_from_url", lambda url: b"fake-image")
    monkeypatch.setattr(
        "app.main.parse_image_with_parallel_vision_models",
        lambda data, symbol, timeframe: ParsedImageSignal(
            symbol=symbol,
            timeframe=timeframe,
            close=100,
            ma5=101,
            ma10=100.5,
            ma20=100,
            ma40=99,
            ma60=98,
            macd_diff=0.5,
            macd_dea=0.3,
            macd_hist=0.2,
            volume=1000,
            open_interest=10000,
            confidence=0.8,
        ),
    )
    monkeypatch.setattr(
        "app.main.hybrid_decision_from_images",
        lambda req, image_payloads: DecisionResult(
            trend="bullish",
            action="long",
            reason=["oss test"],
            entry_zone=[100, 101],
            stop_loss=99,
            take_profit=[104],
            confidence=0.8,
            ai_decision_report="【AI 交易助手决策报告】",
        ),
    )
    monkeypatch.setattr("app.main.insert_signal", lambda record: 123)

    resp = client.post(
        "/api/v1/signal-from-oss-image",
        json={
            "symbol": "SA605",
            "timeframe": "15m",
            "image_url": "https://oss.example.com/a.png",
            "position": "flat",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["signal_id"] == 123
    assert body["image_url"] == "https://oss.example.com/a.png"


def test_signal_flexible_with_image_url(monkeypatch):
    monkeypatch.setattr("app.main._download_image_from_url", lambda url: b"fake-image")
    monkeypatch.setattr(
        "app.main.parse_image_with_parallel_vision_models",
        lambda data, symbol, timeframe: ParsedImageSignal(
            symbol=symbol,
            timeframe=timeframe,
            close=100,
            ma5=101,
            ma10=100.5,
            ma20=100,
            ma40=99,
            ma60=98,
            macd_diff=0.5,
            macd_dea=0.3,
            macd_hist=0.2,
            volume=1000,
            open_interest=10000,
            confidence=0.8,
        ),
    )
    monkeypatch.setattr(
        "app.main.hybrid_decision_from_images",
        lambda req, image_payloads: DecisionResult(
            trend="bullish",
            action="long",
            reason=["flex oss test"],
            entry_zone=[100, 101],
            stop_loss=99,
            take_profit=[104],
            confidence=0.8,
            ai_decision_report="【AI 交易助手决策报告】",
        ),
    )
    monkeypatch.setattr("app.main.insert_signal", lambda record: 456)
    resp = client.post(
        "/api/v1/signal?symbol=SA605&timeframe=15m&position=flat&image_url=https://oss.example.com/flex.png"
    )
    assert resp.status_code == 200
    assert resp.json()["signal_id"] == 456


def test_signal_flexible_with_uploaded_file(monkeypatch):
    monkeypatch.setattr(
        "app.main.parse_image_with_parallel_vision_models",
        lambda data, symbol, timeframe: ParsedImageSignal(
            symbol=symbol,
            timeframe=timeframe,
            close=100,
            ma5=101,
            ma10=100.5,
            ma20=100,
            ma40=99,
            ma60=98,
            macd_diff=0.5,
            macd_dea=0.3,
            macd_hist=0.2,
            volume=1000,
            open_interest=10000,
            confidence=0.8,
        ),
    )
    monkeypatch.setattr(
        "app.main.hybrid_decision_from_images",
        lambda req, image_payloads: DecisionResult(
            trend="bullish",
            action="long",
            reason=["flex upload test"],
            entry_zone=[100, 101],
            stop_loss=99,
            take_profit=[104],
            confidence=0.8,
            ai_decision_report="【AI 交易助手决策报告】",
        ),
    )
    monkeypatch.setattr("app.main.insert_signal", lambda record: 789)
    resp = client.post(
        "/api/v1/signal?symbol=SA605&timeframe=15m&position=flat",
        files={"image": ("chart.png", b"fake-image-bytes", "image/png")},
    )
    assert resp.status_code == 200
    assert resp.json()["signal_id"] == 789
