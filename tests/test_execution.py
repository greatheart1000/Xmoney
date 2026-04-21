"""执行模块测试"""
from app.execution.paper import PaperExecutionGateway, PaperExecutionResult
from app.models import DecisionRequest, DecisionResult, ParsedImageSignal, SignalAction, MarketRegime


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
        "risk_per_trade": 0.01,
    }
    defaults.update(overrides)
    return DecisionRequest(**defaults)


def _sample_decision(**overrides) -> DecisionResult:
    defaults = {
        "trend": "bearish",
        "action": "short",
        "reason": ["test"],
        "confidence": 0.7,
    }
    defaults.update(overrides)
    return DecisionResult(**defaults)


def test_paper_execution_long():
    """测试做多模拟执行"""
    gateway = PaperExecutionGateway()
    req = _sample_request()
    decision = _sample_decision(action=SignalAction.long, trend="bullish")
    result = gateway.execute(req, decision)

    assert result.status == "filled"
    assert result.side == "buy"
    assert result.qty > 0
    assert "paper execution" in result.note


def test_paper_execution_short():
    """测试做空模拟执行"""
    gateway = PaperExecutionGateway()
    req = _sample_request()
    decision = _sample_decision(action=SignalAction.short)
    result = gateway.execute(req, decision)

    assert result.status == "filled"
    assert result.side == "sell"
    assert result.qty > 0


def test_paper_execution_wait():
    """测试等待信号"""
    gateway = PaperExecutionGateway()
    req = _sample_request()
    decision = _sample_decision(action=SignalAction.wait)
    result = gateway.execute(req, decision)

    assert result.status == "noop"
    assert result.side == "none"
    assert result.qty == 0.0
    assert "no execution required" in result.note


def test_paper_execution_hold_long():
    """测试持有多单信号"""
    gateway = PaperExecutionGateway()
    req = _sample_request()
    decision = _sample_decision(action=SignalAction.hold_long, trend="bullish")
    result = gateway.execute(req, decision)

    assert result.status == "noop"
    assert result.side == "none"
    assert result.qty == 0.0


def test_paper_execution_hold_short():
    """测试持有空单信号"""
    gateway = PaperExecutionGateway()
    req = _sample_request()
    decision = _sample_decision(action=SignalAction.hold_short)
    result = gateway.execute(req, decision)

    assert result.status == "noop"
    assert result.side == "none"
    assert result.qty == 0.0


def test_paper_execution_reduce_short():
    """测试减空仓信号"""
    gateway = PaperExecutionGateway()
    req = _sample_request()
    decision = _sample_decision(action=SignalAction.reduce_short)
    result = gateway.execute(req, decision)

    assert result.status == "filled"
    assert result.side == "buy"
    assert result.qty > 0


def test_paper_execution_reduce_long():
    """测试减多仓信号"""
    gateway = PaperExecutionGateway()
    req = _sample_request()
    decision = _sample_decision(action=SignalAction.reduce_long)
    result = gateway.execute(req, decision)

    assert result.status == "filled"
    assert result.side == "sell"
    assert result.qty > 0


def test_paper_execution_qty_scales_with_risk():
    """测试下单数量随风险比例缩放"""
    gateway = PaperExecutionGateway()

    req_low_risk = _sample_request(risk_per_trade=0.005)
    decision = _sample_decision(action=SignalAction.long)
    result_low = gateway.execute(req_low_risk, decision)

    req_high_risk = _sample_request(risk_per_trade=0.03)
    result_high = gateway.execute(req_high_risk, decision)

    assert result_high.qty >= result_low.qty


def test_paper_execution_result_type():
    """测试执行结果的数据类型"""
    gateway = PaperExecutionGateway()
    req = _sample_request()
    decision = _sample_decision(action=SignalAction.short)
    result = gateway.execute(req, decision)

    assert isinstance(result, PaperExecutionResult)
    assert isinstance(result.status, str)
    assert isinstance(result.side, str)
    assert isinstance(result.qty, float)
    assert isinstance(result.note, str)
