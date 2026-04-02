from __future__ import annotations

from typing import List, Tuple

from .models import DecisionRequest, DecisionResult, MarketRegime, SignalAction, Trend


def _infer_trend(req: DecisionRequest) -> Trend:
    p = req.parsed
    ma_bear = p.ma5 < p.ma10 < p.ma20 < p.ma40 < p.ma60
    ma_bull = p.ma5 > p.ma10 > p.ma20 > p.ma40 > p.ma60
    price_below_mid = p.close < p.ma20 and p.close < p.ma40
    price_above_mid = p.close > p.ma20 and p.close > p.ma40

    if ma_bear and price_below_mid:
        return Trend.bearish
    if ma_bull and price_above_mid:
        return Trend.bullish
    return Trend.neutral


def _market_direction(req: DecisionRequest) -> MarketRegime:
    m30 = req.market_regime_30m
    m15 = req.market_regime_15m

    if m30 == MarketRegime.unknown and m15 == MarketRegime.unknown:
        return MarketRegime.unknown

    # 先看30m，再看15m确认（用户要求：先看文华指数大盘，再看单品种）
    if m30 == MarketRegime.bullish and m15 != MarketRegime.bearish:
        return MarketRegime.bullish
    if m30 == MarketRegime.bearish and m15 != MarketRegime.bullish:
        return MarketRegime.bearish
    return MarketRegime.neutral


def _resolve_swing_range(req: DecisionRequest) -> Tuple[float | None, float | None]:
    p = req.parsed
    swing_high = p.swing_high
    swing_low = p.swing_low

    if swing_high is None and (p.resistance_levels or p.historical_resistance_levels):
        swing_high = max((p.resistance_levels + p.historical_resistance_levels))
    if swing_low is None and (p.support_levels or p.historical_support_levels):
        swing_low = min((p.support_levels + p.historical_support_levels))

    if swing_high is None or swing_low is None:
        return None, None
    if swing_high <= swing_low:
        return None, None
    return swing_high, swing_low


def _fib_levels(req: DecisionRequest) -> List[float]:
    swing_high, swing_low = _resolve_swing_range(req)
    if swing_high is None or swing_low is None:
        return []

    span = swing_high - swing_low
    ratios = [0.236, 0.382, 0.5, 0.618, 0.786]
    return sorted([swing_low + span * r for r in ratios])


def _fib_time_and_move_projection(req: DecisionRequest, trend: Trend) -> Tuple[int | None, float | None, List[str]]:
    p = req.parsed
    notes: List[str] = []

    if trend == Trend.bearish:
        avg_bars = p.avg_down_leg_bars
        avg_move = p.avg_down_leg_move_pct
    elif trend == Trend.bullish:
        avg_bars = p.avg_up_leg_bars
        avg_move = p.avg_up_leg_move_pct
    else:
        return None, None, notes

    remaining: int | None = None
    if avg_bars and p.leg_elapsed_bars is not None and avg_bars > 0:
        # 斐波那契时间窗：0.618x, 1.0x, 1.618x 平均波段时长
        time_targets = [int(round(avg_bars * r)) for r in (0.618, 1.0, 1.618)]
        candidates = [t for t in time_targets if t >= p.leg_elapsed_bars]
        if candidates:
            remaining = max(0, min(candidates) - p.leg_elapsed_bars)
            notes.append("已应用斐波那契时间窗评估趋势剩余时长")

    expected_move: float | None = None
    if avg_move is not None and p.leg_start_price and p.leg_start_price > 0:
        # 给出本波段“历史平均总涨跌幅”参考
        expected_move = -abs(avg_move) if trend == Trend.bearish else abs(avg_move)
        notes.append("已结合历史平均波段涨跌幅评估空间")

    return remaining, expected_move, notes


def _merge_support_resistance(req: DecisionRequest, trend: Trend) -> Tuple[List[float], List[float], List[str]]:
    p = req.parsed
    close = p.close
    notes: List[str] = []

    support = sorted(set((p.support_levels + p.historical_support_levels)))[:5]
    resistance = sorted(set((p.resistance_levels + p.historical_resistance_levels)))[:5]
    if p.historical_support_levels or p.historical_resistance_levels:
        notes.append("已合并历史重要支撑位/压力位")

    fib = _fib_levels(req)
    if fib:
        fib_support = [x for x in fib if x <= close]
        fib_resistance = [x for x in fib if x >= close]
        support = sorted(set(support + fib_support))[:5]
        resistance = sorted(set(resistance + fib_resistance))[:5]
        notes.append("已合并斐波那契回调位作为支撑/压力参考")

    if not support and fib:
        support = [fib[0]]
    if not resistance and fib:
        resistance = [fib[-1]]

    # 趋势中优先使用更接近当前价的档位
    if trend == Trend.bearish and resistance:
        resistance = sorted(resistance, key=lambda x: abs(x - close))[:2]
    elif trend == Trend.bullish and support:
        support = sorted(support, key=lambda x: abs(x - close))[:2]

    return sorted(support), sorted(resistance), notes


def make_decision(req: DecisionRequest) -> DecisionResult:
    p = req.parsed
    trend = _infer_trend(req)
    reason: List[str] = []
    if p.chart_patterns:
        reason.append(f"识别到形态: {', '.join(p.chart_patterns[:3])}")

    market_dir = _market_direction(req)
    if req.require_market_filter:
        if market_dir == MarketRegime.unknown:
            return DecisionResult(
                trend=trend,
                action=SignalAction.wait,
                reason=["文华指数过滤未提供，按市场优先原则先观望"],
                confidence=max(0.2, p.confidence - 0.25),
            )
        if market_dir == MarketRegime.neutral:
            return DecisionResult(
                trend=trend,
                action=SignalAction.wait,
                reason=["文华指数30m与15m未同向，按市场优先原则先观望"],
                confidence=max(0.25, p.confidence - 0.2),
            )
        reason.append(f"文华指数方向确认: {market_dir.value}")

    macd_weak = p.macd_hist < 0 and p.macd_diff < p.macd_dea
    macd_strong = p.macd_hist > 0 and p.macd_diff > p.macd_dea

    support, resistance, fib_notes = _merge_support_resistance(req, trend)
    remaining_bars, expected_move_pct, projection_notes = _fib_time_and_move_projection(req, trend)
    reason.extend(fib_notes)
    reason.extend(projection_notes)

    if trend == Trend.bearish:
        reason.append("单品种MA空头排列且价格位于中长期均线下方")
        if macd_weak:
            reason.append("MACD弱势，空头动能占优")

        if req.require_market_filter and market_dir == MarketRegime.bullish:
            return DecisionResult(
                trend=trend,
                action=SignalAction.wait,
                reason=reason + ["文华指数偏多，不逆大盘开空"],
                expected_remaining_bars=remaining_bars,
                expected_total_move_pct=expected_move_pct,
                confidence=max(0.3, p.confidence - 0.15),
            )

        if req.position == "long":
            return DecisionResult(
                trend=trend,
                action=SignalAction.reduce_long,
                reason=reason + ["持有多单与趋势冲突，优先减仓防守"],
                stop_loss=(support[0] * 0.997 if support else p.close * 0.995),
                expected_remaining_bars=remaining_bars,
                expected_total_move_pct=expected_move_pct,
                confidence=min(0.9, p.confidence + 0.1),
            )
        if req.position == "short":
            return DecisionResult(
                trend=trend,
                action=SignalAction.hold_short,
                reason=reason + ["顺势空单可继续持有，采用跟踪止损"],
                stop_loss=(resistance[-1] * 1.003 if resistance else p.ma20 * 1.002),
                take_profit=support or [p.close * 0.99],
                expected_remaining_bars=remaining_bars,
                expected_total_move_pct=expected_move_pct,
                confidence=min(0.92, p.confidence + 0.08),
            )
        return DecisionResult(
            trend=trend,
            action=SignalAction.short,
            reason=reason + ["空仓建议等待反弹至压力区后做空"],
            entry_zone=resistance or [p.ma10, p.ma20],
            stop_loss=(resistance[-1] * 1.004 if resistance else p.ma20 * 1.003),
            take_profit=support or [p.close * 0.99, p.close * 0.985],
            expected_remaining_bars=remaining_bars,
            expected_total_move_pct=expected_move_pct,
            confidence=min(0.9, p.confidence + 0.05),
        )

    if trend == Trend.bullish:
        reason.append("单品种MA多头排列且价格位于中长期均线上方")
        if macd_strong:
            reason.append("MACD强势，做多动能确认")

        if req.require_market_filter and market_dir == MarketRegime.bearish:
            return DecisionResult(
                trend=trend,
                action=SignalAction.wait,
                reason=reason + ["文华指数偏空，不逆大盘开多"],
                expected_remaining_bars=remaining_bars,
                expected_total_move_pct=expected_move_pct,
                confidence=max(0.3, p.confidence - 0.15),
            )

        if req.position == "short":
            return DecisionResult(
                trend=trend,
                action=SignalAction.reduce_short,
                reason=reason + ["持有空单与趋势冲突，优先减仓"],
                stop_loss=(resistance[-1] * 1.003 if resistance else p.close * 1.005),
                expected_remaining_bars=remaining_bars,
                expected_total_move_pct=expected_move_pct,
                confidence=min(0.9, p.confidence + 0.1),
            )
        if req.position == "long":
            return DecisionResult(
                trend=trend,
                action=SignalAction.hold_long,
                reason=reason + ["顺势多单可持有"],
                stop_loss=(support[0] * 0.997 if support else p.ma20 * 0.998),
                take_profit=resistance or [p.close * 1.01],
                expected_remaining_bars=remaining_bars,
                expected_total_move_pct=expected_move_pct,
                confidence=min(0.92, p.confidence + 0.08),
            )
        return DecisionResult(
            trend=trend,
            action=SignalAction.long,
            reason=reason + ["空仓建议回踩支撑不破后做多"],
            entry_zone=support or [p.ma10, p.ma20],
            stop_loss=(support[0] * 0.996 if support else p.ma20 * 0.997),
            take_profit=resistance or [p.close * 1.01, p.close * 1.015],
            expected_remaining_bars=remaining_bars,
            expected_total_move_pct=expected_move_pct,
            confidence=min(0.9, p.confidence + 0.05),
        )

    reason.append("单品种均线和MACD未形成一致性，等待更清晰信号")
    return DecisionResult(
        trend=trend,
        action=SignalAction.wait,
        reason=reason,
        expected_remaining_bars=remaining_bars,
        expected_total_move_pct=expected_move_pct,
        confidence=max(0.3, p.confidence - 0.2),
    )
