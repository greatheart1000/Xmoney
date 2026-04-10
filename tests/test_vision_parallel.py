from app.models import ParsedImageSignal
from app.vision import parse_image_with_parallel_vision_models


def _sig(confidence: float, close: float, ma20: float, macd_hist: float) -> ParsedImageSignal:
    return ParsedImageSignal(
        symbol="SA605",
        timeframe="15m",
        close=close,
        ma5=close + 1,
        ma10=close + 0.5,
        ma20=ma20,
        ma40=ma20 - 1,
        ma60=ma20 - 2,
        macd_diff=0.2,
        macd_dea=0.1,
        macd_hist=macd_hist,
        volume=1000,
        open_interest=10000,
        support_levels=[close - 5],
        resistance_levels=[close + 5],
        confidence=confidence,
        raw_features={},
    )


def test_parallel_vision_prefers_fusion_when_consistent(monkeypatch):
    monkeypatch.setattr("app.vision.parse_image_with_gemini", lambda **kwargs: _sig(0.7, 100, 99, 0.3))
    monkeypatch.setattr("app.vision.parse_image_with_deepseek_vl", lambda **kwargs: _sig(0.9, 101, 100, 0.2))

    out = parse_image_with_parallel_vision_models(b"x", "SA605", "15m")
    assert out.raw_features["selected_strategy"] == "fuse"
    assert "consistency_score" in out.raw_features


def test_parallel_vision_uses_high_confidence_when_conflict(monkeypatch):
    monkeypatch.setattr("app.vision.parse_image_with_gemini", lambda **kwargs: _sig(0.6, 100, 99, 0.3))
    monkeypatch.setattr(
        "app.vision.parse_image_with_deepseek_vl",
        lambda **kwargs: ParsedImageSignal(
            **{
                **_sig(0.9, 101, 103, -0.3).model_dump(),
                "support_levels": [80],
                "resistance_levels": [140],
            }
        ),
    )

    out = parse_image_with_parallel_vision_models(b"x", "SA605", "15m")
    assert out.raw_features["selected_strategy"] == "high_confidence"
    assert out.confidence == 0.9
