import pytest
from fastapi.testclient import TestClient

from app.main import _validate_external_image_url, app
from app.models import DecisionResult


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


def test_validate_external_image_url_rejects_non_https(monkeypatch):
    monkeypatch.setattr("app.main._is_private_or_local_host", lambda host: False)
    with pytest.raises(Exception) as exc_info:
        _validate_external_image_url("http://example.com/chart.png")
    assert getattr(exc_info.value, "status_code", None) == 400


def test_validate_external_image_url_rejects_private_host(monkeypatch):
    monkeypatch.setattr("app.main._is_private_or_local_host", lambda host: True)
    with pytest.raises(Exception) as exc_info:
        _validate_external_image_url("https://example.com/chart.png")
    assert getattr(exc_info.value, "status_code", None) == 400


def test_validate_external_image_url_allows_public_https(monkeypatch):
    monkeypatch.setattr("app.main._is_private_or_local_host", lambda host: False)
    url = _validate_external_image_url("https://example.com/chart.png")
    assert url == "https://example.com/chart.png"
