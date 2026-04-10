from fastapi.testclient import TestClient

from app.main import app
from app.models import DecisionResult, ParsedImageSignal
from app.vision import fuse_parsed_signals


client = TestClient(app)


def _parsed(symbol: str, timeframe: str, close: float, confidence: float) -> ParsedImageSignal:
    return ParsedImageSignal(
        symbol=symbol,
        timeframe=timeframe,
        close=close,
        ma5=close - 1,
        ma10=close - 2,
        ma20=close - 3,
        ma40=close - 4,
        ma60=close - 5,
        macd_diff=-1.0,
        macd_dea=-0.8,
        macd_hist=-0.2,
        volume=1000,
        open_interest=800000,
        support_levels=[close - 10],
        resistance_levels=[close + 10],
        historical_support_levels=[close - 20],
        historical_resistance_levels=[close + 20],
        swing_high=close + 12,
        swing_low=close - 12,
        chart_patterns=["down_channel"],
        confidence=confidence,
        raw_features={"source": "test"},
    )


def test_fuse_parsed_signals_prefers_higher_timeframe_weight():
    fused = fuse_parsed_signals(
        [
            _parsed("SA605", "5m", 100, 0.6),
            _parsed("SA605", "15m", 110, 0.7),
            _parsed("SA605", "30m", 120, 0.8),
        ]
    )
    assert fused.timeframe == "30m"
    assert 110 < fused.close < 120


def test_signal_from_images_returns_single_decision(monkeypatch):
    monkeypatch.setattr(
        "app.main.parse_images_with_parallel_vision_models",
        lambda payloads, symbol: [
            _parsed(symbol, "5m", 100, 0.6),
            _parsed(symbol, "15m", 110, 0.7),
        ],
    )
    monkeypatch.setattr(
        "app.main.hybrid_decision_from_images",
        lambda req, image_payloads: DecisionResult(
            trend="bearish",
            action="wait",
            reason=["ok"],
            confidence=0.66,
        ),
    )
    monkeypatch.setattr("app.main.insert_signal", lambda record: 1)

    files = [
        ("images", ("a.png", b"x", "image/png")),
        ("images", ("b.png", b"y", "image/png")),
    ]
    resp = client.post(
        "/api/v1/signal-from-images",
        params={"symbol": "SA605", "timeframes": "5m,15m", "position": "flat"},
        files=files,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"]["action"] == "wait"
    assert len(body["parsed_list"]) == 2
