from app.models import AssetClass, DecisionRequest, DecisionResult, MarketRegime, ParsedImageSignal
from app.runtime.engine import run_decision_pipeline


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


def test_runtime_pipeline_sets_risk_verdict(monkeypatch):
    monkeypatch.setattr(
        "app.strategy.default.hybrid_decision",
        lambda req: DecisionResult(
            trend="bearish",
            action="short",
            reason=["ok"],
            confidence=0.6,
        ),
    )

    req = DecisionRequest(
        parsed=_sample_parsed(),
        asset_class=AssetClass.crypto,
        market_regime_30m=MarketRegime.bearish,
        market_regime_15m=MarketRegime.bearish,
    )

    decision, runtime_meta = run_decision_pipeline(req)
    assert decision.risk_verdict is not None
    assert runtime_meta["execution"]["status"] in {"noop", "filled"}


def test_runtime_pipeline_blocks_unknown_market_for_open(monkeypatch):
    """测试市场方向未知时，风控策略链阻止开仓。"""
    # 使用 multi 资产类别走 HybridVisionStrategy 路径，便于 monkeypatch
    monkeypatch.setattr(
        "app.strategy.default.hybrid_decision",
        lambda req: DecisionResult(
            trend="bearish",
            action="short",
            reason=["open"],
            confidence=0.8,
        ),
    )

    req = DecisionRequest(
        parsed=_sample_parsed(),
        asset_class=AssetClass.multi,
        market_regime_30m=MarketRegime.unknown,
        market_regime_15m=MarketRegime.unknown,
        require_market_filter=True,
    )

    decision, runtime_meta = run_decision_pipeline(req)
    assert decision.action.value == "wait"
    assert runtime_meta["risk_verdict"] == "risk_policy:block_open_when_market_unknown"
