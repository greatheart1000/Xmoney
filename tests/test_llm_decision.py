from app.llm_decision import hybrid_decision
from app.models import DecisionRequest, DecisionResult, MarketRegime, ParsedImageSignal


def _sample_parsed() -> ParsedImageSignal:
    return ParsedImageSignal(
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


def test_hybrid_falls_back_without_any_llm(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    result = hybrid_decision(
        DecisionRequest(
            parsed=_sample_parsed(),
            market_regime_30m=MarketRegime.bearish,
            market_regime_15m=MarketRegime.bearish,
        )
    )

    assert result.reason[0].startswith("LLM不可用")


def test_hybrid_uses_dual_model_consensus(monkeypatch):
    monkeypatch.setattr(
        "app.llm_decision._collect_model_decisions",
        lambda req: [
            (
                "gemini",
                DecisionResult(
                    trend="bearish",
                    action="short",
                    reason=["gemini short"],
                    entry_zone=[1188, 1190],
                    stop_loss=1192,
                    take_profit=[1177],
                    expected_remaining_bars=6,
                    expected_total_move_pct=-0.02,
                    confidence=0.8,
                ),
            ),
            (
                "deepseek",
                DecisionResult(
                    trend="bearish",
                    action="short",
                    reason=["deepseek short"],
                    entry_zone=[1187, 1189],
                    stop_loss=1191,
                    take_profit=[1176],
                    expected_remaining_bars=5,
                    expected_total_move_pct=-0.025,
                    confidence=0.9,
                ),
            ),
        ],
    )

    result = hybrid_decision(
        DecisionRequest(
            parsed=_sample_parsed(),
            market_regime_30m=MarketRegime.bearish,
            market_regime_15m=MarketRegime.bearish,
        )
    )

    assert result.action.value == "short"
    assert "双模型" in result.reason[0]
