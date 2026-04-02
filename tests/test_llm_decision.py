from app.llm_decision import hybrid_decision
from app.models import DecisionRequest, MarketRegime, ParsedImageSignal


def test_hybrid_falls_back_without_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    parsed = ParsedImageSignal(
        symbol="SA605",
        timeframe="5m",
        close=1180,
        ma5=1181,
        ma10=1182,
        ma20=1184,
        ma40=1188,
        ma60=1192,
        macd_diff=-2.2,
        macd_dea=-2.0,
        macd_hist=-0.2,
        volume=1000,
        open_interest=800000,
        support_levels=[1177],
        resistance_levels=[1188, 1198],
        confidence=0.7,
    )

    result = hybrid_decision(
        DecisionRequest(
            parsed=parsed,
            market_regime_30m=MarketRegime.bearish,
            market_regime_15m=MarketRegime.bearish,
        )
    )

    assert result.action.value in {"short", "hold_short", "reduce_long", "wait"}
    assert result.reason[0].startswith("LLM不可用")
