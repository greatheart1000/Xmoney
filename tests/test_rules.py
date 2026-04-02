from app.models import DecisionRequest, MarketRegime, ParsedImageSignal
from app.rules import make_decision


def test_bearish_short_signal_with_market_confirmed():
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
        swing_high=1198,
        swing_low=1177,
        confidence=0.7,
    )
    result = make_decision(
        DecisionRequest(
            parsed=parsed,
            position="flat",
            market_regime_30m=MarketRegime.bearish,
            market_regime_15m=MarketRegime.bearish,
            require_market_filter=True,
        )
    )
    assert result.action.value == "short"


def test_wait_when_market_unknown_and_filter_required():
    parsed = ParsedImageSignal(
        symbol="FG605",
        timeframe="5m",
        close=1020,
        ma5=1021,
        ma10=1022,
        ma20=1023,
        ma40=1026,
        ma60=1029,
        macd_diff=-1.1,
        macd_dea=-1.0,
        macd_hist=-0.1,
        volume=1000,
        open_interest=10000,
        support_levels=[1017],
        resistance_levels=[1024],
        confidence=0.8,
    )
    result = make_decision(DecisionRequest(parsed=parsed, position="flat"))
    assert result.action.value == "wait"


def test_bullish_hold_long_with_market_confirmed():
    parsed = ParsedImageSignal(
        symbol="XX",
        timeframe="15m",
        close=100.2,
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
    result = make_decision(
        DecisionRequest(
            parsed=parsed,
            position="long",
            market_regime_30m=MarketRegime.bullish,
            market_regime_15m=MarketRegime.bullish,
        )
    )
    assert result.action.value == "hold_long"


def test_fib_levels_used_when_sr_missing():
    parsed = ParsedImageSignal(
        symbol="FG605",
        timeframe="5m",
        close=1020,
        ma5=1019,
        ma10=1020,
        ma20=1022,
        ma40=1025,
        ma60=1028,
        macd_diff=-1.2,
        macd_dea=-1.1,
        macd_hist=-0.2,
        volume=900,
        open_interest=90000,
        support_levels=[],
        resistance_levels=[],
        swing_high=1048,
        swing_low=1017,
        confidence=0.78,
    )
    result = make_decision(
        DecisionRequest(
            parsed=parsed,
            position="flat",
            market_regime_30m=MarketRegime.bearish,
            market_regime_15m=MarketRegime.bearish,
        )
    )
    assert result.action.value == "short"
    assert result.entry_zone is not None and len(result.entry_zone) > 0
    assert any("斐波那契" in r for r in result.reason)


def test_fib_time_and_historical_sr_projection():
    parsed = ParsedImageSignal(
        symbol="SA605",
        timeframe="15m",
        close=1180,
        ma5=1181,
        ma10=1182,
        ma20=1184,
        ma40=1189,
        ma60=1193,
        macd_diff=-2.1,
        macd_dea=-2.0,
        macd_hist=-0.1,
        volume=1200,
        open_interest=810000,
        support_levels=[1177],
        resistance_levels=[1189],
        historical_support_levels=[1172, 1168],
        historical_resistance_levels=[1204],
        swing_high=1204,
        swing_low=1177,
        leg_start_price=1204,
        leg_elapsed_bars=18,
        avg_down_leg_bars=28,
        avg_down_leg_move_pct=0.026,
        confidence=0.8,
    )
    result = make_decision(
        DecisionRequest(
            parsed=parsed,
            position="short",
            market_regime_30m=MarketRegime.bearish,
            market_regime_15m=MarketRegime.bearish,
        )
    )
    assert result.action.value == "hold_short"
    assert result.expected_remaining_bars is not None
    assert result.expected_total_move_pct is not None
    assert any("历史重要支撑位/压力位" in r for r in result.reason)
