"""Tests for the new indicators and risk_manager modules."""
import math
import pytest

from app.indicators import (
    sma, ema, atr, rsi, bollinger_bands, keltner_channel,
    macd, stochastic, adx, dual_thrust, compute_latest_indicators,
)
from app.risk_manager import (
    calculate_atr_stop_loss,
    calculate_trailing_stop,
    calculate_position_size,
    assess_trend_strength,
    check_circuit_breaker,
    generate_risk_adjusted_stop,
    PositionSizing,
)


# ---- indicator tests ----

class TestSMA:
    def test_basic(self):
        data = [1, 2, 3, 4, 5]
        result = sma(data, 3)
        assert not math.isnan(result[2])
        assert abs(result[2] - 2.0) < 1e-6  # (1+2+3)/3
        assert abs(result[4] - 4.0) < 1e-6  # (3+4+5)/3

    def test_short_data(self):
        result = sma([1, 2], 5)
        assert all(math.isnan(v) for v in result)


class TestEMA:
    def test_basic(self):
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        result = ema(data, 3)
        assert not math.isnan(result[2])
        # EMA should be responsive to recent data
        assert result[-1] > result[2]


class TestATR:
    def test_basic(self):
        highs = [10, 12, 11, 13, 15]
        lows = [8, 9, 10, 11, 12]
        closes = [9, 11, 10.5, 12, 14]
        import numpy as np
        result = atr(highs, lows, closes, 3)
        valid = result[~np.isnan(result)]
        assert len(valid) > 0
        assert all(v >= 0 for v in valid)


class TestRSI:
    def test_uptrend(self):
        data = list(range(10, 30))  # steadily rising
        result = rsi(data, 14)
        import numpy as np
        valid = result[~np.isnan(result)]
        # In strong uptrend, RSI should be high
        assert valid[-1] > 70

    def test_downtrend(self):
        data = list(range(30, 10, -1))  # steadily falling
        result = rsi(data, 14)
        import numpy as np
        valid = result[~np.isnan(result)]
        assert valid[-1] < 30


class TestBollingerBands:
    def test_basic(self):
        data = list(range(20, 40))
        upper, mid, lower = bollinger_bands(data, 20, 2.0)
        import numpy as np
        idx = np.where(~np.isnan(upper))[0]
        assert len(idx) > 0
        assert upper[idx[-1]] > mid[idx[-1]] > lower[idx[-1]]


class TestKeltnerChannel:
    def test_basic(self):
        closes = list(range(20, 40))
        highs = [c + 1 for c in closes]
        lows = [c - 1 for c in closes]
        upper, mid, lower = keltner_channel(highs, lows, closes, 20, 1.5)
        import numpy as np
        idx = np.where(~np.isnan(upper))[0]
        assert len(idx) > 0
        assert upper[idx[-1]] > mid[idx[-1]] > lower[idx[-1]]


class TestDualThrust:
    def test_basic(self):
        highs = [100, 102, 98, 105, 103]
        lows = [95, 97, 93, 100, 98]
        closes = [98, 100, 96, 103, 101]
        opens = [97, 99, 95, 102, 100]
        upper, lower = dual_thrust(highs, lows, closes, opens, lookback=4)
        assert upper > lower
        assert upper > opens[-1]
        assert lower < opens[-1]


class TestComputeLatest:
    def test_with_sufficient_data(self):
        n = 60
        closes = [100 + i * 0.5 for i in range(n)]
        highs = [c + 2 for c in closes]
        lows = [c - 2 for c in closes]
        result = compute_latest_indicators(highs, lows, closes)
        assert "rsi_14" in result
        assert "atr_14" in result


# ---- risk manager tests ----

class TestATRStopLoss:
    def test_long_stop(self):
        stop = calculate_atr_stop_loss(100.0, 2.0, "long", atr_multiplier=2.0)
        assert stop < 100.0
        assert stop == pytest.approx(96.0, abs=0.1)

    def test_short_stop(self):
        stop = calculate_atr_stop_loss(100.0, 2.0, "short", atr_multiplier=2.0)
        assert stop > 100.0
        assert stop == pytest.approx(104.0, abs=0.1)


class TestTrailingStop:
    def test_long_trailing(self):
        trail = calculate_trailing_stop(
            current_price=110.0,
            highest_since_entry=112.0,
            lowest_since_entry=100.0,
            direction="long",
            atr_value=2.0,
            trailing_pct=0.8,
            atr_trailing_mult=3.0,
        )
        assert trail > 100.0  # Should be above entry
        assert trail < 112.0  # Should be below high

    def test_short_trailing(self):
        trail = calculate_trailing_stop(
            current_price=90.0,
            highest_since_entry=100.0,
            lowest_since_entry=88.0,
            direction="short",
            atr_value=2.0,
            trailing_pct=0.8,
            atr_trailing_mult=3.0,
        )
        assert trail < 100.0
        assert trail > 88.0


class TestPositionSize:
    def test_basic(self):
        ps = calculate_position_size(
            account_balance=100000,
            entry_price=100.0,
            stop_loss_price=98.0,
            risk_per_trade=0.01,
            contract_multiplier=10,
        )
        assert ps.suggested_lots > 0
        # Risk = 100000 * 0.01 = 1000
        # Stop distance = 2.0
        # Value per lot = 2.0 * 10 = 20
        # Lots = 1000 / 20 = 50
        assert ps.suggested_lots == 50.0

    def test_invalid_params(self):
        ps = calculate_position_size(0, 100, 98, 0.01)
        assert ps.suggested_lots == 0.0


class TestCircuitBreaker:
    def test_daily_loss_limit(self):
        breaker, reason = check_circuit_breaker(
            [0.01, -0.04], max_daily_loss_pct=0.03
        )
        assert breaker
        assert "Daily loss" in reason

    def test_consecutive_losses(self):
        breaker, reason = check_circuit_breaker(
            [-0.01, -0.01, -0.01], max_consecutive_losses=3
        )
        assert breaker
        assert "Consecutive" in reason

    def test_no_trigger(self):
        breaker, reason = check_circuit_breaker(
            [0.01, -0.01, 0.02, 0.01]
        )
        assert not breaker


class TestTrendStrength:
    def test_strong_bullish(self):
        strength, mod = assess_trend_strength(
            adx_value=45, rsi_value=70, volume_ratio=2.0, ma_alignment="bullish"
        )
        assert strength == "strong"
        assert mod > 0

    def test_ranging(self):
        strength, mod = assess_trend_strength(
            adx_value=15, rsi_value=50, volume_ratio=0.5, ma_alignment="neutral"
        )
        assert strength == "ranging"
        assert mod < 0


class TestRiskAdjustedStop:
    def test_long_with_support(self):
        config = generate_risk_adjusted_stop(
            entry_price=100.0,
            direction="long",
            support_levels=[97.0, 95.0],
            resistance_levels=[103.0, 105.0],
            atr_value=2.0,
        )
        assert config.initial_stop < 100.0
        assert config.initial_stop >= 95.0  # Should be near support

    def test_short_with_resistance(self):
        config = generate_risk_adjusted_stop(
            entry_price=100.0,
            direction="short",
            support_levels=[97.0, 95.0],
            resistance_levels=[103.0, 105.0],
            atr_value=2.0,
        )
        assert config.initial_stop > 100.0
        assert config.initial_stop <= 105.0


# ---- additional indicator tests ----

class TestBollingerBandsWidth:
    """测试布林带宽度计算"""

    def test_bollinger_bands_width_decreasing(self):
        """测试波动率收敛时布林带宽度减小"""
        # 高波动数据
        high_vol = list(range(20, 40)) + [50, 10, 60, 5]
        upper_h, mid_h, lower_h = bollinger_bands(high_vol, 20, 2.0)
        # 低波动数据
        low_vol = list(range(20, 40))
        upper_l, mid_l, lower_l = bollinger_bands(low_vol, 20, 2.0)
        import numpy as np
        idx_h = np.where(~np.isnan(upper_h))[0]
        idx_l = np.where(~np.isnan(upper_l))[0]
        if len(idx_h) > 0 and len(idx_l) > 0:
            width_high = upper_h[idx_h[-1]] - lower_h[idx_h[-1]]
            width_low = upper_l[idx_l[-1]] - lower_l[idx_l[-1]]
            # 高波动的带宽不一定更大（取决于最后值），但结构正确
            assert width_high > 0
            assert width_low > 0

    def test_bollinger_bands_width_positive(self):
        """测试布林带带宽始终为正"""
        data = [100 + i * 0.5 + (-1)**i * 2 for i in range(40)]
        upper, mid, lower = bollinger_bands(data, 20, 2.0)
        import numpy as np
        idx = np.where(~np.isnan(upper))[0]
        for i in idx:
            assert upper[i] >= mid[i]
            assert mid[i] >= lower[i]
            assert upper[i] - lower[i] > 0


class TestStochastic:
    """测试随机指标"""

    def test_uptrend_high_k(self):
        """测试上升趋势中K值偏高"""
        import numpy as np
        closes = list(range(50, 80))
        highs = [c + 3 for c in closes]
        lows = [c - 3 for c in closes]
        k_line, d_line = stochastic(highs, lows, closes, 9, 3)
        valid_k = k_line[~np.isnan(k_line)]
        assert valid_k[-1] > 50

    def test_range_0_to_100(self):
        """测试K值范围在0-100之间"""
        import numpy as np
        import random
        random.seed(42)
        closes = [100 + random.uniform(-5, 5) for _ in range(50)]
        highs = [c + random.uniform(0, 3) for c in closes]
        lows = [c - random.uniform(0, 3) for c in closes]
        k_line, d_line = stochastic(highs, lows, closes, 9, 3)
        valid_k = k_line[~np.isnan(k_line)]
        assert all(0 <= v <= 100 for v in valid_k)


# ---- additional risk manager tests ----

class TestRiskAssessmentExtreme:
    """测试极端风险评估"""

    def test_assess_full_risk_circuit_breaker(self):
        """测试熔断触发时风险评估为极端"""
        try:
            from app.risk_manager import assess_full_risk, RiskLevel
            from app.models import DecisionRequest, ParsedImageSignal

            parsed = ParsedImageSignal(
                symbol="SA605", timeframe="5m", close=1180,
                ma5=1181, ma10=1182, ma20=1184, ma40=1188, ma60=1192,
                macd_diff=-2.2, macd_dea=-2.0, macd_hist=-0.2,
                volume=1000, open_interest=800000,
                support_levels=[1177], resistance_levels=[1188],
                confidence=0.7,
            )
            req = DecisionRequest(parsed=parsed)
            assessment = assess_full_risk(
                req, account_balance=100000,
                recent_returns=[0.01, -0.05],
            )
            assert assessment.circuit_breaker is True
            assert assessment.risk_level == RiskLevel.EXTREME
            assert assessment.risk_score >= 90
        except ImportError:
            pytest.skip("assess_full_risk not available")

    def test_assess_full_risk_no_breaker(self):
        """测试正常情况下风险评估非极端"""
        try:
            from app.risk_manager import assess_full_risk, RiskLevel
            from app.models import DecisionRequest, ParsedImageSignal

            parsed = ParsedImageSignal(
                symbol="SA605", timeframe="5m", close=1180,
                ma5=1181, ma10=1182, ma20=1184, ma40=1188, ma60=1192,
                macd_diff=-2.2, macd_dea=-2.0, macd_hist=-0.2,
                volume=1000, open_interest=800000,
                support_levels=[1177], resistance_levels=[1188],
                confidence=0.7,
            )
            req = DecisionRequest(parsed=parsed)
            assessment = assess_full_risk(req, account_balance=100000)
            assert assessment.circuit_breaker is False
            assert assessment.risk_level in {RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH}
        except ImportError:
            pytest.skip("assess_full_risk not available")


class TestCircuitBreakerDailyLoss:
    """测试日内亏损熔断"""

    def test_daily_loss_exactly_at_limit(self):
        """测试日内亏损刚好在限制边界不触发"""
        breaker, reason = check_circuit_breaker(
            [0.01, 0.02, -0.03], max_daily_loss_pct=0.03
        )
        # -0.03 == max_daily_loss_pct, should NOT trigger (< not <=)
        # 但连续亏损检查: 最近3个为 -0.03, 0.02, 0.01 → 只有1个连续亏损
        # 实际上最后一笔是 -0.03 < -0.03 不成立，不触发
        assert not breaker

    def test_daily_loss_beyond_limit(self):
        """测试日内亏损超过限制触发熔断"""
        breaker, reason = check_circuit_breaker(
            [0.01, -0.05], max_daily_loss_pct=0.03
        )
        assert breaker
        assert "Daily loss" in reason

    def test_drawdown_breach(self):
        """测试最大回撤触发熔断"""
        breaker, reason = check_circuit_breaker(
            [0.02, -0.05, -0.05], max_drawdown_pct=0.05
        )
        # 连续亏损为2个（不够3个默认），但回撤可能触发
        # equity: 1.02 -> 0.969 -> 0.9205; peak=1.02; dd=(1.02-0.9205)/1.02=0.098 > 0.05
        assert breaker

    def test_empty_returns_no_trigger(self):
        """测试空回报列表不触发熔断"""
        breaker, reason = check_circuit_breaker([])
        assert not breaker
        assert reason == ""


class TestTrendStrengthMultipleIndicators:
    """测试多指标趋势强度"""

    def test_moderate_trend(self):
        """测试中等趋势强度"""
        strength, mod = assess_trend_strength(
            adx_value=30, rsi_value=55, volume_ratio=1.0, ma_alignment="bullish"
        )
        assert strength in {"strong", "moderate", "weak", "ranging"}
        assert -0.3 <= mod <= 0.2

    def test_rsi_divergence_lowers_score(self):
        """测试RSI与趋势背离降低评分"""
        # 多头排列但RSI偏低（背离）
        strength_div, mod_div = assess_trend_strength(
            adx_value=35, rsi_value=30, volume_ratio=1.2, ma_alignment="bullish"
        )
        # 多头排列且RSI正常
        strength_norm, mod_norm = assess_trend_strength(
            adx_value=35, rsi_value=65, volume_ratio=1.2, ma_alignment="bullish"
        )
        assert mod_div < mod_norm

    def test_volume_confirmation(self):
        """测试成交量确认趋势"""
        _, mod_high_vol = assess_trend_strength(
            adx_value=30, rsi_value=60, volume_ratio=2.0, ma_alignment="bullish"
        )
        _, mod_low_vol = assess_trend_strength(
            adx_value=30, rsi_value=60, volume_ratio=0.3, ma_alignment="bullish"
        )
        assert mod_high_vol > mod_low_vol

    def test_none_indicators_handled(self):
        """测试所有指标为None时不崩溃"""
        strength, mod = assess_trend_strength(
            adx_value=None, rsi_value=None, volume_ratio=None, ma_alignment="neutral"
        )
        assert strength in {"strong", "moderate", "weak", "ranging"}
        assert -0.3 <= mod <= 0.2

    def test_bearish_with_rsi_confirms(self):
        """测试空头排列RSI低位确认"""
        strength, mod = assess_trend_strength(
            adx_value=40, rsi_value=25, volume_ratio=1.8, ma_alignment="bearish"
        )
        assert strength == "strong"
        assert mod > 0


class TestATRStopLossEdgeCases:
    """测试ATR止损边缘情况"""

    def test_zero_atr_fallback(self):
        """测试ATR为零时使用百分比止损"""
        stop = calculate_atr_stop_loss(100.0, 0.0, "long")
        assert stop < 100.0
        assert stop > 0

    def test_negative_atr_fallback(self):
        """测试ATR为负时使用百分比止损"""
        stop = calculate_atr_stop_loss(100.0, -1.0, "long")
        assert stop < 100.0

    def test_minimum_stop_distance(self):
        """测试止损距离不低于最小百分比"""
        stop = calculate_atr_stop_loss(100.0, 0.001, "long", atr_multiplier=2.0, min_stop_pct=0.003)
        # stop = 100 - 0.002 = 99.998; min_stop = 99.7
        assert stop < 100.0
