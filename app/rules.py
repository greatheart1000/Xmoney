"""规则引擎 - 纯规则驱动的交易信号生成。

v2.0 优化内容:
- 趋势强度分级（通过ADX+MA排列综合判断），影响信号置信度
- 震荡市检测（ADX < 20 + 布林带收窄 → 不开新仓）
- 改进多时间框架确认逻辑（趋势一致性评分）
"""
from __future__ import annotations

from typing import List, Tuple

from .models import DecisionRequest, DecisionResult, MarketRegime, SignalAction, Trend


# ==================== 趋势强度分级 ====================

def _trend_strength_grade(req: DecisionRequest) -> Tuple[str, float]:
    """趋势强度分级，影响信号置信度。

    综合ADX值和MA排列紧密程度，将趋势分为：
    - "strong": ADX > 30 且 MA完美排列 → 置信度+0.10
    - "moderate": ADX 25-30 或 MA大部分排列 → 置信度+0.05
    - "weak": ADX 20-25 且 MA部分排列 → 置信度不变
    - "ranging": ADX < 20 → 置信度-0.10

    返回 (强度标签, 置信度调整系数)。
    """
    p = req.parsed

    # 尝试获取ADX值
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
            return "strong", 0.10
        if adx_val > 25 and (has_ma_align or has_partial_align):
            return "moderate", 0.05
        if adx_val > 20:
            return "weak", 0.0
        return "ranging", -0.10

    # 无ADX数据时，根据MA排列判断
    if has_ma_align:
        return "moderate", 0.05
    if has_partial_align:
        return "weak", 0.0
    return "ranging", -0.10


# ==================== 震荡市检测 ====================

def _is_ranging_market(req: DecisionRequest) -> Tuple[bool, List[str]]:
    """震荡市检测。

    综合判断条件:
    1. ADX < 20（趋势强度不足）
    2. 布林带宽度收窄（波动率压缩）

    在震荡市中不建议开新仓，避免被假突破止损。

    返回 (是否为震荡市, 原因列表)。
    """
    p = req.parsed
    notes: List[str] = []

    # ADX检测
    adx_val = None
    if p.raw_features.get("adx_14"):
        try:
            adx_val = float(p.raw_features["adx_14"])
        except (ValueError, TypeError):
            pass

    if adx_val is None or adx_val >= 20:
        return False, notes

    # ADX < 20，检查布林带宽度
    boll_upper = p.raw_features.get("boll_upper")
    boll_lower = p.raw_features.get("boll_lower")

    boll_narrow = False
    if boll_upper and boll_lower:
        try:
            width_pct = (float(boll_upper) - float(boll_lower)) / p.close * 100
            if width_pct < 2.5:
                boll_narrow = True
                notes.append(f"布林带收窄（宽度{width_pct:.1f}%），波动率压缩")
        except (ValueError, TypeError):
            pass

    if adx_val < 20:
        notes.append(f"ADX={adx_val:.1f} < 20，趋势强度不足")
        if boll_narrow:
            notes.append("震荡市确认：ADX低迷 + 布林带收窄，不建议开新仓")
            return True, notes
        # ADX低但布林带未极端收窄，仅发出警告
        notes.append("趋势强度偏弱，谨慎操作")

    return False, notes


# ==================== 多时间框架确认 ====================

def _multi_timeframe_confirmation(req: DecisionRequest, trend: Trend) -> Tuple[float, List[str]]:
    """改进的多时间框架确认逻辑。

    通过多个维度的趋势一致性评分来增强信号可靠性：
    1. MA排列一致性（短期/中期/长期MA方向一致）
    2. MACD方向与趋势一致
    3. 价格位置与趋势一致（在关键均线上方/下方）
    4. 成交量确认（量价配合）

    每个维度通过得1分，满分4分。
    - 4分: 高度一致，置信度+0.10
    - 3分: 基本一致，置信度+0.05
    - 2分: 部分一致，置信度不变
    - 1分: 一致性差，置信度-0.05
    - 0分: 矛盾信号，置信度-0.15

    返回 (置信度调整, 原因列表)。
    """
    p = req.parsed
    notes: List[str] = []
    score = 0

    if trend == Trend.neutral:
        return 0.0, notes

    # 1. MA排列一致性
    if trend == Trend.bullish:
        if p.ma5 > p.ma10 > p.ma20:
            score += 1
            notes.append("短中期MA多头排列一致")
    else:
        if p.ma5 < p.ma10 < p.ma20:
            score += 1
            notes.append("短中期MA空头排列一致")

    # 2. MACD方向一致
    if trend == Trend.bullish and p.macd_hist > 0 and p.macd_diff > p.macd_dea:
        score += 1
        notes.append("MACD方向与多头趋势一致")
    elif trend == Trend.bearish and p.macd_hist < 0 and p.macd_diff < p.macd_dea:
        score += 1
        notes.append("MACD方向与空头趋势一致")

    # 3. 价格位置一致
    if trend == Trend.bullish and p.close > p.ma40 and p.close > p.ma60:
        score += 1
        notes.append("价格位于中长期均线上方，多头确认")
    elif trend == Trend.bearish and p.close < p.ma40 and p.close < p.ma60:
        score += 1
        notes.append("价格位于中长期均线下方，空头确认")

    # 4. 成交量确认
    vol_ratio = None
    if p.raw_features.get("volume_ratio"):
        try:
            vol_ratio = float(p.raw_features["volume_ratio"])
        except (ValueError, TypeError):
            pass

    if vol_ratio is not None:
        if trend == Trend.bullish and vol_ratio > 1.0:
            score += 1
            notes.append(f"放量配合多头（量比{vol_ratio:.1f}）")
        elif trend == Trend.bearish and vol_ratio > 1.0:
            score += 1
            notes.append(f"放量配合空头（量比{vol_ratio:.1f}）")

    # 评分转置信度调整
    adjustments = {4: 0.10, 3: 0.05, 2: 0.0, 1: -0.05, 0: -0.15}
    adj = adjustments.get(score, 0.0)

    notes.append(f"多时间框架确认评分: {score}/4（置信度调整{adj:+.2f}）")

    return adj, notes


# ==================== 原有辅助函数 ====================

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
        # 给出本波段"历史平均总涨跌幅"参考
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


# ==================== 主决策函数 ====================

def make_decision(req: DecisionRequest) -> DecisionResult:
    """规则引擎主决策函数（v2.0）。

    优化内容:
    1. 趋势强度分级影响信号置信度
    2. 震荡市检测（不开新仓）
    3. 改进多时间框架确认逻辑
    """
    p = req.parsed
    trend = _infer_trend(req)
    reason: List[str] = []
    if p.chart_patterns:
        reason.append(f"识别到形态: {', '.join(p.chart_patterns[:3])}")

    # === 新增：趋势强度分级 ===
    strength, strength_adj = _trend_strength_grade(req)
    reason.append(f"趋势强度: {strength}")

    # === 新增：震荡市检测 ===
    is_ranging, ranging_notes = _is_ranging_market(req)
    reason.extend(ranging_notes)

    market_dir = _market_direction(req)
    if req.require_market_filter:
        if market_dir == MarketRegime.unknown:
            return DecisionResult(
                trend=trend,
                action=SignalAction.wait,
                reason=["文华指数过滤未提供，按市场优先原则先观望"],
                confidence=max(0.2, p.confidence - 0.25),
                trend_strength=strength,
            )
        if market_dir == MarketRegime.neutral:
            return DecisionResult(
                trend=trend,
                action=SignalAction.wait,
                reason=["文华指数30m与15m未同向，按市场优先原则先观望"],
                confidence=max(0.25, p.confidence - 0.2),
                trend_strength=strength,
            )
        reason.append(f"文华指数方向确认: {market_dir.value}")

    macd_weak = p.macd_hist < 0 and p.macd_diff < p.macd_dea
    macd_strong = p.macd_hist > 0 and p.macd_diff > p.macd_dea

    support, resistance, fib_notes = _merge_support_resistance(req, trend)
    remaining_bars, expected_move_pct, projection_notes = _fib_time_and_move_projection(req, trend)
    reason.extend(fib_notes)
    reason.extend(projection_notes)

    # === 新增：多时间框架确认评分 ===
    mtf_adj, mtf_notes = _multi_timeframe_confirmation(req, trend)
    reason.extend(mtf_notes)

    # 综合置信度调整
    total_adj = strength_adj + mtf_adj

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
                trend_strength=strength,
            )

        # === 新增：震荡市不开新仓 ===
        if is_ranging and req.position == "flat":
            return DecisionResult(
                trend=trend,
                action=SignalAction.wait,
                reason=reason + ["震荡市检测触发，不开新空仓"],
                expected_remaining_bars=remaining_bars,
                expected_total_move_pct=expected_move_pct,
                confidence=max(0.3, p.confidence + total_adj - 0.1),
                trend_strength=strength,
            )

        if req.position == "long":
            return DecisionResult(
                trend=trend,
                action=SignalAction.reduce_long,
                reason=reason + ["持有多单与趋势冲突，优先减仓防守"],
                stop_loss=(support[0] * 0.997 if support else p.close * 0.995),
                expected_remaining_bars=remaining_bars,
                expected_total_move_pct=expected_move_pct,
                confidence=min(0.9, p.confidence + 0.1 + total_adj),
                trend_strength=strength,
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
                confidence=min(0.92, p.confidence + 0.08 + total_adj),
                trend_strength=strength,
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
            confidence=min(0.9, p.confidence + 0.05 + total_adj),
            trend_strength=strength,
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
                trend_strength=strength,
            )

        # === 新增：震荡市不开新仓 ===
        if is_ranging and req.position == "flat":
            return DecisionResult(
                trend=trend,
                action=SignalAction.wait,
                reason=reason + ["震荡市检测触发，不开新多仓"],
                expected_remaining_bars=remaining_bars,
                expected_total_move_pct=expected_move_pct,
                confidence=max(0.3, p.confidence + total_adj - 0.1),
                trend_strength=strength,
            )

        if req.position == "short":
            return DecisionResult(
                trend=trend,
                action=SignalAction.reduce_short,
                reason=reason + ["持有空单与趋势冲突，优先减仓"],
                stop_loss=(resistance[-1] * 1.003 if resistance else p.close * 1.005),
                expected_remaining_bars=remaining_bars,
                expected_total_move_pct=expected_move_pct,
                confidence=min(0.9, p.confidence + 0.1 + total_adj),
                trend_strength=strength,
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
                confidence=min(0.92, p.confidence + 0.08 + total_adj),
                trend_strength=strength,
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
            confidence=min(0.9, p.confidence + 0.05 + total_adj),
            trend_strength=strength,
        )

    reason.append("单品种均线和MACD未形成一致性，等待更清晰信号")
    return DecisionResult(
        trend=trend,
        action=SignalAction.wait,
        reason=reason,
        expected_remaining_bars=remaining_bars,
        expected_total_move_pct=expected_move_pct,
        confidence=max(0.3, p.confidence - 0.2 + total_adj),
        trend_strength=strength,
    )
