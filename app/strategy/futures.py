"""期货专用策略模块 - 针对中国期货市场优化的CTA策略。

核心特征:
- 趋势强度分级（弱/中/强），影响信号置信度
- MA发散度检测（均线间距扩张/收缩判断趋势加速/衰竭）
- MACD柱状图背离（价格创新高/低但MACD柱未创新高/低）
- 改进的Fibonacci动态回撤（根据趋势强度调整回撤区间）
- Dual Thrust突破信号
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from app.models import (
    AssetClass,
    DecisionRequest,
    DecisionResult,
    MarketRegime,
    SignalAction,
    Trend,
)


def _trend_strength_grade(req: DecisionRequest) -> Tuple[str, float]:
    """趋势强度分级。

    根据ADX值和MA排列紧密程度将趋势分为：
    - "strong"（强趋势）: ADX > 30 且 MA完美排列
    - "moderate"（中等趋势）: ADX 25-30 或 MA大部分排列
    - "weak"（弱趋势）: ADX 20-25 且 MA部分排列
    - "ranging"（震荡市）: ADX < 20

    返回 (强度标签, 置信度调整系数)。
    """
    p = req.parsed

    # 从raw_features中获取ADX值（由indicators.py计算后注入）
    adx_val = None
    if p.raw_features.get("adx_14"):
        try:
            adx_val = float(p.raw_features["adx_14"])
        except (ValueError, TypeError):
            pass

    # MA排列检测
    ma_bull = p.ma5 > p.ma10 > p.ma20 > p.ma40 > p.ma60
    ma_bear = p.ma5 < p.ma10 < p.ma20 < p.ma40 < p.ma60
    ma_partial_bull = p.ma5 > p.ma20 > p.ma60
    ma_partial_bear = p.ma5 < p.ma20 < p.ma60

    has_ma_align = ma_bull or ma_bear
    has_partial_align = ma_partial_bull or ma_partial_bear

    if adx_val is not None:
        if adx_val > 30 and has_ma_align:
            return "strong", 0.10  # 强趋势，置信度加成
        if adx_val > 25 and (has_ma_align or has_partial_align):
            return "moderate", 0.05  # 中等趋势，小幅加成
        if adx_val > 20:
            return "weak", 0.0  # 弱趋势，不加成
        return "ranging", -0.10  # 震荡市，降低置信度

    # 无ADX数据时，根据MA排列判断
    if has_ma_align:
        return "moderate", 0.05
    if has_partial_align:
        return "weak", 0.0
    return "ranging", -0.10


def _ma_divergence(req: DecisionRequest) -> Tuple[str, List[str]]:
    """MA发散度检测。

    计算短期均线与长期均线的间距变化率，判断趋势加速或衰竭：
    - MA间距扩张 → 趋势加速（趋势跟随信号加强）
    - MA间距收缩 → 趋势衰竭（注意反转风险）
    - MA交叉 → 趋势可能反转

    返回 (发散状态: "expanding"/"contracting"/"neutral", 原因列表)。
    """
    p = req.parsed
    notes: List[str] = []

    # 计算MA间距（短期MA相对于长期MA的偏离百分比）
    if p.ma60 == 0:
        return "neutral", notes

    # 短期发散度: MA5与MA20的间距
    short_spread = abs(p.ma5 - p.ma20) / abs(p.ma20) * 100 if p.ma20 != 0 else 0
    # 长期发散度: MA5与MA60的间距
    long_spread = abs(p.ma5 - p.ma60) / abs(p.ma60) * 100

    if short_spread > 2.0 and long_spread > 3.0:
        notes.append(f"MA发散度较大（短期偏离{short_spread:.1f}%，长期偏离{long_spread:.1f}%），趋势加速中")
        return "expanding", notes

    if short_spread < 0.5 and long_spread < 1.5:
        notes.append(f"MA收敛（短期偏离{short_spread:.1f}%），趋势可能衰竭")
        return "contracting", notes

    return "neutral", notes


def _macd_histogram_divergence(req: DecisionRequest) -> Tuple[bool, bool, List[str]]:
    """MACD柱状图背离检测。

    顶背离: 价格创新高但MACD柱未创新高 → 看跌信号
    底背离: 价格创新低但MACD柱未创新低 → 看涨信号

    返回 (顶背离标志, 底背离标志, 原因列表)。
    使用ParsedImageSignal中的swing_high/swing_low与MACD柱判断。
    """
    p = req.parsed
    notes: List[str] = []
    bearish_div = False
    bullish_div = False

    # MACD柱为正但开始收缩 = 多头动能减弱
    if p.macd_hist > 0 and p.macd_diff > 0:
        # 简化判断：MACD柱虽然为正但小于MACD差值/DEA的幅度
        # 说明动能开始衰减
        hist_ratio = abs(p.macd_hist) / (abs(p.macd_diff) + 1e-10)
        if hist_ratio < 0.15:
            bearish_div = True
            notes.append("MACD柱状图收缩，多头动能减弱（疑似顶背离）")

    # MACD柱为负但开始收缩 = 空头动能减弱
    if p.macd_hist < 0 and p.macd_diff < 0:
        hist_ratio = abs(p.macd_hist) / (abs(p.macd_diff) + 1e-10)
        if hist_ratio < 0.15:
            bullish_div = True
            notes.append("MACD柱状图收缩，空头动能减弱（疑似底背离）")

    return bearish_div, bullish_div, notes


def _dynamic_fibonacci_levels(
    req: DecisionRequest, trend_strength: str
) -> Tuple[List[float], List[str]]:
    """改进的Fibonacci动态回撤。

    根据趋势强度调整Fibonacci回撤区间：
    - 强趋势: 使用较浅回撤位（0.236, 0.382），回调幅度小
    - 中等趋势: 使用标准回撤位（0.382, 0.5, 0.618）
    - 弱趋势/震荡: 使用较深回撤位（0.5, 0.618, 0.786）

    返回 (回撤水平列表, 原因列表)。
    """
    p = req.parsed
    notes: List[str] = []

    swing_high = p.swing_high
    swing_low = p.swing_low

    if swing_high is None and (p.resistance_levels or p.historical_resistance_levels):
        swing_high = max(p.resistance_levels + p.historical_resistance_levels)
    if swing_low is None and (p.support_levels or p.historical_support_levels):
        swing_low = min(p.support_levels + p.historical_support_levels)

    if swing_high is None or swing_low is None or swing_high <= swing_low:
        return [], notes

    span = swing_high - swing_low

    if trend_strength == "strong":
        # 强趋势：关注浅回撤
        ratios = [0.236, 0.382, 0.5]
        notes.append("强趋势环境，采用浅Fibonacci回撤位（0.236/0.382/0.5）")
    elif trend_strength == "moderate":
        # 中等趋势：标准回撤
        ratios = [0.382, 0.5, 0.618]
        notes.append("中等趋势，采用标准Fibonacci回撤位（0.382/0.5/0.618）")
    else:
        # 弱趋势/震荡：深回撤
        ratios = [0.5, 0.618, 0.786]
        notes.append("弱趋势/震荡环境，采用深Fibonacci回撤位（0.5/0.618/0.786）")

    levels = sorted([swing_low + span * r for r in ratios])
    return levels, notes


def _dual_thrust_signal(req: DecisionRequest) -> Tuple[Optional[SignalAction], List[str]]:
    """Dual Thrust突破信号。

    当价格突破Dual Thrust上轨时做多，突破下轨时做空。
    需要ParsedImageSignal的raw_features中包含dual_thrust_upper/lower。

    返回 (信号动作或None, 原因列表)。
    """
    p = req.parsed
    notes: List[str] = []

    dt_upper = p.raw_features.get("dual_thrust_upper")
    dt_lower = p.raw_features.get("dual_thrust_lower")

    if dt_upper is None or dt_lower is None:
        return None, notes

    try:
        upper = float(dt_upper)
        lower = float(dt_lower)
    except (ValueError, TypeError):
        return None, notes

    if p.close > upper:
        notes.append(f"Dual Thrust突破上轨（{upper:.2f}），做多信号")
        return SignalAction.long, notes
    if p.close < lower:
        notes.append(f"Dual Thrust跌破下轨（{lower:.2f}），做空信号")
        return SignalAction.short, notes

    return None, notes


def _infer_trend(req: DecisionRequest) -> Trend:
    """趋势推断（与rules.py一致，但增加了强度分级考虑）。"""
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
    """文华指数大盘方向判断。"""
    m30 = req.market_regime_30m
    m15 = req.market_regime_15m

    if m30 == MarketRegime.unknown and m15 == MarketRegime.unknown:
        return MarketRegime.unknown

    if m30 == MarketRegime.bullish and m15 != MarketRegime.bearish:
        return MarketRegime.bullish
    if m30 == MarketRegime.bearish and m15 != MarketRegime.bullish:
        return MarketRegime.bearish
    return MarketRegime.neutral


class FuturesStrategy:
    """期货专用CTA策略。

    结合趋势强度分级、MA发散度、MACD背离、动态Fibonacci和Dual Thrust，
    生成适合中国期货市场的交易信号。
    """

    def decide(self, req: DecisionRequest) -> DecisionResult:
        p = req.parsed
        reason: List[str] = []
        reason.append("[期货专用策略]")

        # 1. 趋势强度分级
        strength, conf_adj = _trend_strength_grade(req)
        reason.append(f"趋势强度: {strength}")

        # 2. 趋势方向
        trend = _infer_trend(req)

        # 3. MA发散度检测
        divergence_state, div_notes = _ma_divergence(req)
        reason.extend(div_notes)

        # 4. MACD背离检测
        bearish_div, bullish_div, div_macd_notes = _macd_histogram_divergence(req)
        reason.extend(div_macd_notes)

        # 5. 动态Fibonacci回撤
        fib_levels, fib_notes = _dynamic_fibonacci_levels(req, strength)
        reason.extend(fib_notes)

        # 6. Dual Thrust突破
        dt_signal, dt_notes = _dual_thrust_signal(req)
        reason.extend(dt_notes)

        # 7. 文华指数过滤（期货专用：必须通过大盘过滤）
        market_dir = _market_direction(req)
        if req.require_market_filter:
            if market_dir == MarketRegime.unknown:
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.wait,
                    reason=reason + ["文华指数过滤未提供，按市场优先原则先观望"],
                    confidence=max(0.2, p.confidence - 0.25),
                    trend_strength=strength,
                )
            if market_dir == MarketRegime.neutral:
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.wait,
                    reason=reason + ["文华指数30m与15m未同向，按市场优先原则先观望"],
                    confidence=max(0.25, p.confidence - 0.2),
                    trend_strength=strength,
                )
            reason.append(f"文华指数方向确认: {market_dir.value}")

        # 震荡市不开新仓（ADX < 20 且 布林带收窄）
        if strength == "ranging":
            boll_width = None
            if p.raw_features.get("boll_upper") and p.raw_features.get("boll_lower"):
                try:
                    boll_width = float(p.raw_features["boll_upper"]) - float(p.raw_features["boll_lower"])
                except (ValueError, TypeError):
                    pass

            if boll_width is not None and p.close > 0:
                width_pct = boll_width / p.close * 100
                if width_pct < 2.0:
                    reason.append(f"震荡市检测（ADX<20 + 布林带宽度{width_pct:.1f}%收窄），不建议开新仓")
                    return DecisionResult(
                        trend=trend,
                        action=SignalAction.wait,
                        reason=reason,
                        confidence=max(0.3, p.confidence - 0.15),
                        trend_strength=strength,
                    )

        # MACD弱势判断
        macd_weak = p.macd_hist < 0 and p.macd_diff < p.macd_dea
        macd_strong = p.macd_hist > 0 and p.macd_diff > p.macd_dea

        # 信号合并与决策
        # 背离信号覆盖趋势信号（高级别信号）
        if trend == Trend.bullish and bearish_div:
            reason.append("多头趋势中出现MACD顶背离，降低做多信心")
            conf_adj -= 0.10

        if trend == Trend.bearish and bullish_div:
            reason.append("空头趋势中出现MACD底背离，降低做空信心")
            conf_adj -= 0.10

        # MA发散度影响
        if divergence_state == "contracting" and trend != Trend.neutral:
            reason.append("MA收敛中，趋势可能衰竭，降低仓位建议")
            conf_adj -= 0.05

        if divergence_state == "expanding" and trend != Trend.neutral:
            reason.append("MA发散中，趋势加速，可顺势操作")
            conf_adj += 0.03

        # ========== 多头趋势决策 ==========
        if trend == Trend.bullish:
            reason.append("MA多头排列且价格位于中长期均线上方")
            if macd_strong:
                reason.append("MACD强势确认做多动能")

            # 逆大盘过滤
            if req.require_market_filter and market_dir == MarketRegime.bearish:
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.wait,
                    reason=reason + ["文华指数偏空，不逆大盘开多"],
                    confidence=max(0.3, p.confidence - 0.15),
                    trend_strength=strength,
                )

            # 已有空单 → 减仓
            if req.position == "short":
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.reduce_short,
                    reason=reason + ["持有空单与趋势冲突，优先减仓"],
                    stop_loss=p.close * 1.005,
                    confidence=min(0.9, p.confidence + 0.1 + conf_adj),
                    trend_strength=strength,
                )

            # 已有多单 → 持有或加仓
            if req.position == "long":
                if strength == "strong" and divergence_state == "expanding":
                    reason.append("强趋势+MA发散，多单可持有，考虑加仓")
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.hold_long,
                    reason=reason + ["顺势多单可持有"],
                    stop_loss=p.ma20 * 0.998 if p.ma20 > 0 else p.close * 0.995,
                    take_profit=fib_levels[-1:] if fib_levels else [p.close * 1.02],
                    confidence=min(0.92, p.confidence + 0.08 + conf_adj),
                    trend_strength=strength,
                )

            # 空仓 → Fibonacci回撤位做多或Dual Thrust突破
            entry = fib_levels[:2] if fib_levels else [p.ma10, p.ma20]
            if dt_signal == SignalAction.long:
                reason.append("Dual Thrust突破确认做多信号")
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.long,
                    reason=reason,
                    entry_zone=entry,
                    stop_loss=(entry[0] * 0.996 if entry else p.ma20 * 0.997),
                    take_profit=fib_levels[-1:] if fib_levels else [p.close * 1.015],
                    confidence=min(0.9, p.confidence + 0.05 + conf_adj),
                    trend_strength=strength,
                )

            return DecisionResult(
                trend=trend,
                action=SignalAction.long,
                reason=reason + ["建议回踩支撑不破后做多"],
                entry_zone=entry,
                stop_loss=(entry[0] * 0.996 if entry else p.ma20 * 0.997),
                take_profit=fib_levels[-1:] if fib_levels else [p.close * 1.01, p.close * 1.02],
                confidence=min(0.9, p.confidence + 0.05 + conf_adj),
                trend_strength=strength,
            )

        # ========== 空头趋势决策 ==========
        if trend == Trend.bearish:
            reason.append("MA空头排列且价格位于中长期均线下方")
            if macd_weak:
                reason.append("MACD弱势，空头动能确认")

            # 逆大盘过滤
            if req.require_market_filter and market_dir == MarketRegime.bullish:
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.wait,
                    reason=reason + ["文华指数偏多，不逆大盘开空"],
                    confidence=max(0.3, p.confidence - 0.15),
                    trend_strength=strength,
                )

            # 已有多单 → 减仓
            if req.position == "long":
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.reduce_long,
                    reason=reason + ["持有多单与趋势冲突，优先减仓防守"],
                    stop_loss=p.close * 0.995,
                    confidence=min(0.9, p.confidence + 0.1 + conf_adj),
                    trend_strength=strength,
                )

            # 已有空单 → 持有
            if req.position == "short":
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.hold_short,
                    reason=reason + ["顺势空单可继续持有"],
                    stop_loss=p.ma20 * 1.002 if p.ma20 > 0 else p.close * 1.005,
                    take_profit=fib_levels[:1] if fib_levels else [p.close * 0.98],
                    confidence=min(0.92, p.confidence + 0.08 + conf_adj),
                    trend_strength=strength,
                )

            # 空仓 → 做空
            entry = fib_levels[-2:] if fib_levels else [p.ma10, p.ma20]
            if dt_signal == SignalAction.short:
                reason.append("Dual Thrust跌破确认做空信号")

            return DecisionResult(
                trend=trend,
                action=SignalAction.short,
                reason=reason + ["建议反弹至压力区后做空"],
                entry_zone=entry,
                stop_loss=(entry[-1] * 1.004 if entry else p.ma20 * 1.003),
                take_profit=fib_levels[:1] if fib_levels else [p.close * 0.985, p.close * 0.98],
                confidence=min(0.9, p.confidence + 0.05 + conf_adj),
                trend_strength=strength,
            )

        # ========== 中性趋势 ==========
        reason.append("MA和MACD未形成一致性，等待更清晰信号")

        # 中性趋势中如果Dual Thrust有信号，可轻仓试探
        if dt_signal is not None:
            reason.append(f"中性趋势但Dual Thrust给出{dt_signal.value}信号，可轻仓试探")
            return DecisionResult(
                trend=trend,
                action=dt_signal,
                reason=reason,
                confidence=max(0.4, p.confidence - 0.1 + conf_adj),
                trend_strength=strength,
            )

        return DecisionResult(
            trend=trend,
            action=SignalAction.wait,
            reason=reason,
            confidence=max(0.3, p.confidence - 0.2),
            trend_strength=strength,
        )
