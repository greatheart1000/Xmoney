"""风控策略链测试"""
from app.risk.policies import (
    NoOpenAgainstUnknownMarketPolicy,
    MaxConfidenceFloorPolicy,
    RiskPolicyChain,
    RiskVerdict,
)
from app.models import DecisionRequest, DecisionResult, MarketRegime, ParsedImageSignal, SignalAction


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


def _sample_request(**overrides) -> DecisionRequest:
    defaults = {
        "parsed": _sample_parsed(),
        "position": "flat",
        "market_regime_30m": MarketRegime.unknown,
        "market_regime_15m": MarketRegime.unknown,
        "require_market_filter": True,
    }
    defaults.update(overrides)
    return DecisionRequest(**defaults)


def _sample_decision(**overrides) -> DecisionResult:
    defaults = {
        "trend": "bearish",
        "action": SignalAction.short,
        "reason": ["test short"],
        "confidence": 0.7,
    }
    defaults.update(overrides)
    return DecisionResult(**defaults)


def test_unknown_market_blocks_new_position():
    """测试未知市场状态阻止开仓"""
    policy = NoOpenAgainstUnknownMarketPolicy()
    req = _sample_request(
        market_regime_30m=MarketRegime.unknown,
        require_market_filter=True,
    )
    decision = _sample_decision(action=SignalAction.short)
    verdict = policy.evaluate(req, decision)

    assert verdict.allow is False
    assert "block_open_when_market_unknown" in verdict.reason


def test_known_market_allows_position():
    """测试已知市场状态允许开仓"""
    policy = NoOpenAgainstUnknownMarketPolicy()
    req = _sample_request(
        market_regime_30m=MarketRegime.bearish,
        require_market_filter=True,
    )
    decision = _sample_decision(action=SignalAction.short)
    verdict = policy.evaluate(req, decision)

    assert verdict.allow is True
    assert verdict.reason == "risk_policy:ok"


def test_unknown_market_allows_hold():
    """测试未知市场状态允许持有操作"""
    policy = NoOpenAgainstUnknownMarketPolicy()
    req = _sample_request(
        market_regime_30m=MarketRegime.unknown,
        require_market_filter=True,
    )
    # hold_short 不是开仓操作
    decision = _sample_decision(action=SignalAction.hold_short)
    verdict = policy.evaluate(req, decision)

    assert verdict.allow is True


def test_unknown_market_allows_wait():
    """测试未知市场状态允许等待"""
    policy = NoOpenAgainstUnknownMarketPolicy()
    req = _sample_request(
        market_regime_30m=MarketRegime.unknown,
        require_market_filter=True,
    )
    decision = _sample_decision(action=SignalAction.wait)
    verdict = policy.evaluate(req, decision)

    assert verdict.allow is True


def test_no_filter_unknown_market_allows_position():
    """测试不要求市场过滤时，未知状态允许开仓"""
    policy = NoOpenAgainstUnknownMarketPolicy()
    req = _sample_request(
        market_regime_30m=MarketRegime.unknown,
        require_market_filter=False,
    )
    decision = _sample_decision(action=SignalAction.short)
    verdict = policy.evaluate(req, decision)

    assert verdict.allow is True


def test_low_confidence_blocked():
    """测试低置信度被阻止"""
    policy = MaxConfidenceFloorPolicy(min_confidence=0.35)
    req = _sample_request()
    decision = _sample_decision(action=SignalAction.short, confidence=0.2)
    verdict = policy.evaluate(req, decision)

    assert verdict.allow is False
    assert "block_open_low_confidence" in verdict.reason


def test_high_confidence_allowed():
    """测试高置信度允许通过"""
    policy = MaxConfidenceFloorPolicy(min_confidence=0.35)
    req = _sample_request()
    decision = _sample_decision(action=SignalAction.short, confidence=0.7)
    verdict = policy.evaluate(req, decision)

    assert verdict.allow is True


def test_confidence_floor_allows_hold():
    """测试置信度底线策略允许持有操作"""
    policy = MaxConfidenceFloorPolicy(min_confidence=0.35)
    req = _sample_request()
    # 即使低置信度，hold_long 不应被阻止
    decision = _sample_decision(action=SignalAction.hold_long, confidence=0.2)
    verdict = policy.evaluate(req, decision)

    assert verdict.allow is True


def test_confidence_floor_at_boundary():
    """测试置信度在临界值时允许通过"""
    policy = MaxConfidenceFloorPolicy(min_confidence=0.35)
    req = _sample_request()
    decision = _sample_decision(action=SignalAction.short, confidence=0.35)
    verdict = policy.evaluate(req, decision)

    assert verdict.allow is True


def test_confidence_floor_just_below_boundary():
    """测试置信度略低于临界值时被阻止"""
    policy = MaxConfidenceFloorPolicy(min_confidence=0.35)
    req = _sample_request()
    decision = _sample_decision(action=SignalAction.short, confidence=0.34)
    verdict = policy.evaluate(req, decision)

    assert verdict.allow is False


def test_policy_chain_first_rejection_wins():
    """测试策略链首个拒绝生效"""
    # 创建一个总是拒绝的策略
    class AlwaysBlockPolicy:
        def evaluate(self, req, decision):
            return RiskVerdict(False, "risk_policy:always_block")

    # AlwaysBlockPolicy 在前面，应该先被触发
    chain = RiskPolicyChain(policies=[
        AlwaysBlockPolicy(),
        MaxConfidenceFloorPolicy(min_confidence=0.35),
    ])

    req = _sample_request(
        market_regime_30m=MarketRegime.bearish,
    )
    decision = _sample_decision(action=SignalAction.short, confidence=0.7)
    result = chain.apply(req, decision)

    assert result.action == SignalAction.wait
    assert result.risk_verdict == "risk_policy:always_block"


def test_policy_chain_all_pass():
    """测试所有策略通过"""
    chain = RiskPolicyChain(policies=[
        NoOpenAgainstUnknownMarketPolicy(),
        MaxConfidenceFloorPolicy(min_confidence=0.35),
    ])

    req = _sample_request(
        market_regime_30m=MarketRegime.bearish,
        require_market_filter=True,
    )
    decision = _sample_decision(action=SignalAction.short, confidence=0.7)
    result = chain.apply(req, decision)

    assert result.action == SignalAction.short
    assert result.risk_verdict == "risk_policy:ok"


def test_policy_chain_second_policy_blocks():
    """测试策略链第二个策略阻止"""
    chain = RiskPolicyChain(policies=[
        NoOpenAgainstUnknownMarketPolicy(),
        MaxConfidenceFloorPolicy(min_confidence=0.35),
    ])

    req = _sample_request(
        market_regime_30m=MarketRegime.bearish,
        require_market_filter=True,
    )
    # 市场已知通过第一个策略，但置信度低被第二个策略阻止
    decision = _sample_decision(action=SignalAction.short, confidence=0.2)
    result = chain.apply(req, decision)

    assert result.action == SignalAction.wait
    assert "block_open_low_confidence" in result.risk_verdict


def test_policy_chain_blocked_clears_order_fields():
    """测试策略链拦截时清空委托字段"""
    chain = RiskPolicyChain(policies=[
        MaxConfidenceFloorPolicy(min_confidence=0.35),
    ])

    req = _sample_request()
    decision = _sample_decision(
        action=SignalAction.long,
        confidence=0.2,
        entry_zone=[100, 105],
        stop_loss=99,
        take_profit=[110],
    )
    result = chain.apply(req, decision)

    assert result.action == SignalAction.wait
    assert result.entry_zone is None
    assert result.stop_loss is None
    assert result.take_profit is None


def test_policy_chain_blocked_adds_reason():
    """测试策略链拦截时添加拦截原因"""
    chain = RiskPolicyChain(policies=[
        MaxConfidenceFloorPolicy(min_confidence=0.35),
    ])

    req = _sample_request()
    decision = _sample_decision(action=SignalAction.short, confidence=0.2)
    result = chain.apply(req, decision)

    assert any("风控策略拦截" in r for r in result.reason)
