from app.models import DecisionRequest, ParsedImageSignal
from app.rules import make_decision


def test_bearish_short_signal():
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
    result = make_decision(DecisionRequest(parsed=parsed, position="flat"))
    assert result.action.value == "short"


def test_bullish_hold_long():
    parsed = ParsedImageSignal(
        symbol="XX",
        timeframe="15m",
        close=100,
        ma5=101,
        ma10=100.5,
        ma20=100,
        ma40=99,
        ma60=98,
        macd_diff=0.5,
        macd_dea=0.2,
        macd_hist=0.3,
        volume=1000,
        open_interest=10000,
        support_levels=[99],
        resistance_levels=[103],
        confidence=0.8,
    )
    result = make_decision(DecisionRequest(parsed=parsed, position="long"))
    assert result.action.value == "hold_long"
