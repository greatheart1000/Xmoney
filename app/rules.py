from __future__ import annotations

from typing import List

from .models import DecisionRequest, DecisionResult, SignalAction, Trend


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


def make_decision(req: DecisionRequest) -> DecisionResult:
    p = req.parsed
    trend = _infer_trend(req)
    reason: List[str] = []

    macd_weak = p.macd_hist < 0 and p.macd_diff < p.macd_dea
    macd_strong = p.macd_hist > 0 and p.macd_diff > p.macd_dea

    support = sorted(p.support_levels)[:2]
    resistance = sorted(p.resistance_levels)[:2]

    if trend == Trend.bearish:
        reason.append("MA空头排列且价格位于中长期均线下方")
        if macd_weak:
            reason.append("MACD弱势，空头动能占优")
        if req.position == "long":
            return DecisionResult(
                trend=trend,
                action=SignalAction.reduce_long,
                reason=reason + ["持有多单与趋势冲突，优先减仓防守"],
                stop_loss=(support[0] * 0.997 if support else p.close * 0.995),
                confidence=min(0.9, p.confidence + 0.1),
            )
        if req.position == "short":
            return DecisionResult(
                trend=trend,
                action=SignalAction.hold_short,
                reason=reason + ["顺势空单可继续持有，采用跟踪止损"],
                stop_loss=(resistance[-1] * 1.003 if resistance else p.ma20 * 1.002),
                take_profit=support or [p.close * 0.99],
                confidence=min(0.92, p.confidence + 0.08),
            )
        return DecisionResult(
            trend=trend,
            action=SignalAction.short,
            reason=reason + ["空仓建议等待反弹至压力区后做空"],
            entry_zone=resistance or [p.ma10, p.ma20],
            stop_loss=(resistance[-1] * 1.004 if resistance else p.ma20 * 1.003),
            take_profit=support or [p.close * 0.99, p.close * 0.985],
            confidence=min(0.9, p.confidence + 0.05),
        )

    if trend == Trend.bullish:
        reason.append("MA多头排列且价格位于中长期均线上方")
        if macd_strong:
            reason.append("MACD强势，做多动能确认")
        if req.position == "short":
            return DecisionResult(
                trend=trend,
                action=SignalAction.reduce_short,
                reason=reason + ["持有空单与趋势冲突，优先减仓"],
                stop_loss=(resistance[-1] * 1.003 if resistance else p.close * 1.005),
                confidence=min(0.9, p.confidence + 0.1),
            )
        if req.position == "long":
            return DecisionResult(
                trend=trend,
                action=SignalAction.hold_long,
                reason=reason + ["顺势多单可持有"],
                stop_loss=(support[0] * 0.997 if support else p.ma20 * 0.998),
                take_profit=resistance or [p.close * 1.01],
                confidence=min(0.92, p.confidence + 0.08),
            )
        return DecisionResult(
            trend=trend,
            action=SignalAction.long,
            reason=reason + ["空仓建议回踩支撑不破后做多"],
            entry_zone=support or [p.ma10, p.ma20],
            stop_loss=(support[0] * 0.996 if support else p.ma20 * 0.997),
            take_profit=resistance or [p.close * 1.01, p.close * 1.015],
            confidence=min(0.9, p.confidence + 0.05),
        )

    reason.append("均线和MACD未形成一致性，等待更清晰信号")
    return DecisionResult(
        trend=trend,
        action=SignalAction.wait,
        reason=reason,
        confidence=max(0.3, p.confidence - 0.2),
    )
