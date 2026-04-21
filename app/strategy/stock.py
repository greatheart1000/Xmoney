"""股票专用策略模块 - 针对A股市场特点优化。

核心特征:
- 量价关系分析（放量突破、缩量回调、量价背离）
- 涨跌停板处理（接近涨停/跌停时调整信号）
- 行业动量信号（板块轮动参考）
- T+1交易限制考虑
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from app.models import (
    DecisionRequest,
    DecisionResult,
    SignalAction,
    Trend,
)


# 涨跌停阈值（A股主板为10%，创业板/科创板为20%）
_LIMIT_UP_PCT = 0.10
_LIMIT_DOWN_PCT = -0.10
# 接近涨跌停的距离阈值（距离涨停2%以内视为"接近"）
_NEAR_LIMIT_PCT = 0.02


def _infer_trend(req: DecisionRequest) -> Trend:
    """趋势推断 - 股票版本。

    与基础版一致，但增加量价确认条件。
    """
    p = req.parsed
    ma_bull = p.ma5 > p.ma10 > p.ma20 > p.ma40 > p.ma60
    ma_bear = p.ma5 < p.ma10 < p.ma20 < p.ma40 < p.ma60
    price_above_mid = p.close > p.ma20 and p.close > p.ma40
    price_below_mid = p.close < p.ma20 and p.close < p.ma40

    if ma_bull and price_above_mid:
        return Trend.bullish
    if ma_bear and price_below_mid:
        return Trend.bearish
    return Trend.neutral


def _volume_price_analysis(req: DecisionRequest) -> Tuple[str, List[str]]:
    """量价关系分析。

    分析量价配合关系，判断当前量价状态：
    - "volume_breakout": 放量突破（量比>1.5 + 价格突破关键位）→ 强做多信号
    - "volume_shrink_pullback": 缩量回调（量比<0.7 + 价格回调至支撑位）→ 做多机会
    - "volume_divergence": 量价背离（价格上涨但量能萎缩）→ 警惕反转
    - "volume_climax": 放量滞涨（量比>2.0 但价格涨幅有限）→ 可能见顶
    - "normal": 正常量价关系

    返回 (量价状态, 原因列表)。
    """
    p = req.parsed
    notes: List[str] = []

    volume_ratio = None
    if p.raw_features.get("volume_ratio"):
        try:
            volume_ratio = float(p.raw_features["volume_ratio"])
        except (ValueError, TypeError):
            pass

    if volume_ratio is None:
        return "normal", notes

    # 价格相对MA20的位置百分比
    price_vs_ma20 = (p.close - p.ma20) / p.ma20 * 100 if p.ma20 > 0 else 0

    # 放量突破：量比>1.5 且 价格在MA20上方
    if volume_ratio > 1.5 and price_vs_ma20 > 1.0:
        notes.append(f"放量突破（量比{volume_ratio:.1f}，价格高于MA20 {price_vs_ma20:.1f}%），强势做多信号")
        return "volume_breakout", notes

    # 缩量回调：量比<0.7 且 价格在MA20附近或下方
    if volume_ratio < 0.7 and abs(price_vs_ma20) < 3.0:
        notes.append(f"缩量回调（量比{volume_ratio:.1f}），回调幅度有限，可能是买入机会")
        return "volume_shrink_pullback", notes

    # 量价背离：价格在均线上方但量能萎缩
    if volume_ratio < 0.6 and price_vs_ma20 > 2.0:
        notes.append(f"量价背离（价格高于MA20 {price_vs_ma20:.1f}%但量比仅{volume_ratio:.1f}），警惕反转")
        return "volume_divergence", notes

    # 放量滞涨：量比>2.0 但价格涨幅有限
    if volume_ratio > 2.0 and abs(price_vs_ma20) < 1.0:
        notes.append(f"放量滞涨（量比{volume_ratio:.1f}但价格未有效突破），可能见顶")
        return "volume_climax", notes

    return "normal", notes


def _limit_price_check(req: DecisionRequest) -> Tuple[Optional[str], List[str]]:
    """涨跌停板处理。

    检测价格是否接近涨跌停板，并据此调整交易策略：
    - 接近涨停：不建议追高买入（可能次日回落），可持有
    - 接近跌停：不建议恐慌卖出（可能超跌反弹），但空单可继续持有
    - 涨停封板：不建议开多（难买入），观望
    - 跌停封板：不建议开空（难卖出），观望

    返回 (涨跌停状态: "near_limit_up"/"near_limit_down"/"limit_up"/"limit_down"/None, 原因列表)。
    """
    p = req.parsed
    notes: List[str] = []

    # 计算日涨跌幅（使用open作为参考价，若没有则使用MA5）
    if p.raw_features.get("open"):
        try:
            open_price = float(p.raw_features["open"])
        except (ValueError, TypeError):
            open_price = p.ma5
    else:
        open_price = p.ma5

    if open_price <= 0:
        return None, notes

    daily_change_pct = (p.close - open_price) / open_price

    # 跌停封板（日跌幅接近-10%）
    if daily_change_pct <= _LIMIT_DOWN_PCT:
        notes.append(f"跌停封板（日跌幅{daily_change_pct:.1%}），观望为主")
        return "limit_down", notes

    # 涨停封板
    if daily_change_pct >= _LIMIT_UP_PCT:
        notes.append(f"涨停封板（日涨幅{daily_change_pct:.1%}），封板不追高")
        return "limit_up", notes

    # 接近涨停
    if daily_change_pct >= _LIMIT_UP_PCT - _NEAR_LIMIT_PCT:
        notes.append(f"接近涨停（日涨幅{daily_change_pct:.1%}），谨慎追高")
        return "near_limit_up", notes

    # 接近跌停
    if daily_change_pct <= _LIMIT_DOWN_PCT + _NEAR_LIMIT_PCT:
        notes.append(f"接近跌停（日跌幅{daily_change_pct:.1%}），注意风险")
        return "near_limit_down", notes

    return None, notes


def _sector_momentum_signal(req: DecisionRequest) -> Tuple[str, List[str]]:
    """行业动量信号。

    通过分析品种的相对强弱（相对于MA的偏离度）判断行业/板块动量：
    - 多个品种同步走强 → 板块动量向上
    - 多个品种同步走弱 → 板块动量向下

    简化实现：基于当前品种的MA排列强度推断。
    返回 (动量方向: "bullish"/"bearish"/"neutral", 原因列表)。
    """
    p = req.parsed
    notes: List[str] = []

    # 使用MA发散度作为动量代理指标
    if p.ma20 == 0:
        return "neutral", notes

    # 短期动量：MA5相对MA20的偏离
    short_momentum = (p.ma5 - p.ma20) / p.ma20 * 100
    # 中期动量：MA20相对MA60的偏离
    mid_momentum = (p.ma20 - p.ma60) / p.ma60 * 100 if p.ma60 != 0 else 0

    if short_momentum > 1.5 and mid_momentum > 2.0:
        notes.append(f"行业动量偏多（短期动量{short_momentum:.1f}%，中期动量{mid_momentum:.1f}%）")
        return "bullish", notes

    if short_momentum < -1.5 and mid_momentum < -2.0:
        notes.append(f"行业动量偏空（短期动量{short_momentum:.1f}%，中期动量{mid_momentum:.1f}%）")
        return "bearish", notes

    return "neutral", notes


class StockStrategy:
    """股票专用策略。

    结合量价关系分析、涨跌停板处理和行业动量信号，
    生成适合A股市场的交易信号。
    注意A股T+1限制：当日买入不能当日卖出。
    """

    def decide(self, req: DecisionRequest) -> DecisionResult:
        p = req.parsed
        reason: List[str] = []
        reason.append("[股票专用策略]")

        # 1. 趋势判断
        trend = _infer_trend(req)

        # 2. 量价关系分析
        vp_state, vp_notes = _volume_price_analysis(req)
        reason.extend(vp_notes)

        # 3. 涨跌停检测
        limit_state, limit_notes = _limit_price_check(req)
        reason.extend(limit_notes)

        # 4. 行业动量
        sector_mom, sector_notes = _sector_momentum_signal(req)
        reason.extend(sector_notes)

        # 5. MACD状态
        macd_strong = p.macd_hist > 0 and p.macd_diff > p.macd_dea
        macd_weak = p.macd_hist < 0 and p.macd_diff < p.macd_dea

        # ========== 涨跌停特殊处理 ==========
        if limit_state == "limit_up":
            # 涨停封板：持有多单不动，不开新仓（买不进去）
            if req.position == "long":
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.hold_long,
                    reason=reason + ["涨停封板，多单继续持有"],
                    confidence=min(0.9, p.confidence + 0.1),
                    trend_strength="bullish",
                )
            return DecisionResult(
                trend=trend,
                action=SignalAction.wait,
                reason=reason + ["涨停封板，不追高买入"],
                confidence=max(0.3, p.confidence - 0.1),
                trend_strength="bullish",
            )

        if limit_state == "limit_down":
            # 跌停封板：持有空单不动，不开新仓
            if req.position == "short":
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.hold_short,
                    reason=reason + ["跌停封板，空单继续持有"],
                    confidence=min(0.9, p.confidence + 0.1),
                    trend_strength="bearish",
                )
            if req.position == "long":
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.reduce_long,
                    reason=reason + ["跌停封板，持有多单风险极大，优先减仓"],
                    confidence=0.9,
                    trend_strength="bearish",
                )
            return DecisionResult(
                trend=trend,
                action=SignalAction.wait,
                reason=reason + ["跌停封板，观望为主"],
                confidence=max(0.3, p.confidence - 0.1),
                trend_strength="bearish",
            )

        # ========== 量价背离保护 ==========
        if vp_state == "volume_divergence":
            if trend == Trend.bullish and req.position == "long":
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.reduce_long,
                    reason=reason + ["量价背离警告，多单建议减仓"],
                    stop_loss=p.close * 0.97,
                    confidence=max(0.4, p.confidence - 0.1),
                    trend_strength="warning",
                )
            if trend == Trend.bearish:
                reason.append("空头趋势中量价背离，可能预示空头动能衰竭")

        # ========== 放量滞涨保护 ==========
        if vp_state == "volume_climax":
            return DecisionResult(
                trend=trend,
                action=SignalAction.wait,
                reason=reason + ["放量滞涨，可能见顶信号，观望"],
                confidence=max(0.3, p.confidence - 0.15),
                trend_strength="warning",
            )

        # ========== 多头趋势决策 ==========
        if trend == Trend.bullish:
            reason.append("MA多头排列，多头趋势确认")
            if macd_strong:
                reason.append("MACD强势确认")

            if req.position == "short":
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.reduce_short,
                    reason=reason + ["持有空单与趋势冲突，优先减仓"],
                    stop_loss=p.close * 1.02,
                    confidence=min(0.9, p.confidence + 0.1),
                    trend_strength="bullish",
                )

            if req.position == "long":
                # 接近涨停时继续持有
                if limit_state == "near_limit_up":
                    return DecisionResult(
                        trend=trend,
                        action=SignalAction.hold_long,
                        reason=reason + ["接近涨停，多单继续持有"],
                        confidence=min(0.9, p.confidence + 0.05),
                        trend_strength="bullish",
                    )
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.hold_long,
                    reason=reason + ["顺势多单可持有"],
                    stop_loss=p.ma20 * 0.995 if p.ma20 > 0 else p.close * 0.97,
                    take_profit=[p.close * 1.05, p.close * 1.10],
                    confidence=min(0.92, p.confidence + 0.08),
                    trend_strength="bullish",
                )

            # 空仓做多
            if limit_state == "near_limit_up":
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.wait,
                    reason=reason + ["接近涨停不追高"],
                    confidence=max(0.3, p.confidence - 0.1),
                    trend_strength="bullish",
                )

            # 放量突破信号增强
            if vp_state == "volume_breakout":
                reason.append("放量突破确认做多信号强度")
                confidence_adj = 0.08
            elif vp_state == "volume_shrink_pullback":
                reason.append("缩量回调至支撑位，良好买入时机")
                confidence_adj = 0.05
            else:
                confidence_adj = 0.03

            # 行业动量确认
            if sector_mom == "bullish":
                reason.append("行业动量偏多，增强做多信心")
                confidence_adj += 0.03
            elif sector_mom == "bearish":
                reason.append("行业动量偏空，降低做多信心")
                confidence_adj -= 0.05

            return DecisionResult(
                trend=trend,
                action=SignalAction.long,
                reason=reason + ["建议做多入场"],
                entry_zone=[p.ma10, p.ma20],
                stop_loss=p.ma20 * 0.995 if p.ma20 > 0 else p.close * 0.97,
                take_profit=[p.close * 1.05, p.close * 1.10],
                confidence=min(0.9, p.confidence + confidence_adj),
                trend_strength="bullish",
            )

        # ========== 空头趋势决策 ==========
        if trend == Trend.bearish:
            reason.append("MA空头排列，空头趋势确认")
            if macd_weak:
                reason.append("MACD弱势确认")

            if req.position == "long":
                # 接近跌停时紧急减仓
                if limit_state == "near_limit_down":
                    return DecisionResult(
                        trend=trend,
                        action=SignalAction.reduce_long,
                        reason=reason + ["接近跌停，多单紧急减仓"],
                        confidence=0.9,
                        trend_strength="bearish",
                    )
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.reduce_long,
                    reason=reason + ["持有多单与趋势冲突，优先减仓"],
                    stop_loss=p.close * 1.02,
                    confidence=min(0.9, p.confidence + 0.1),
                    trend_strength="bearish",
                )

            if req.position == "short":
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.hold_short,
                    reason=reason + ["顺势空单可持有"],
                    stop_loss=p.ma20 * 1.005 if p.ma20 > 0 else p.close * 1.03,
                    take_profit=[p.close * 0.95, p.close * 0.90],
                    confidence=min(0.92, p.confidence + 0.08),
                    trend_strength="bearish",
                )

            # 空仓做空
            if limit_state == "near_limit_down":
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.wait,
                    reason=reason + ["接近跌停不宜追空"],
                    confidence=max(0.3, p.confidence - 0.1),
                    trend_strength="bearish",
                )

            # 量价确认
            if vp_state == "volume_breakout":
                # 注意：空头趋势中的放量可能是杀跌
                reason.append("空头放量杀跌，做空信号增强")
                confidence_adj = 0.08
            else:
                confidence_adj = 0.03

            if sector_mom == "bearish":
                reason.append("行业动量偏空，增强做空信心")
                confidence_adj += 0.03
            elif sector_mom == "bullish":
                reason.append("行业动量偏多，降低做空信心")
                confidence_adj -= 0.05

            # 股票做空需要谨慎（A股融券限制较多）
            return DecisionResult(
                trend=trend,
                action=SignalAction.short,
                reason=reason + ["建议做空（注意A股融券限制）"],
                entry_zone=[p.ma10, p.ma20],
                stop_loss=p.ma20 * 1.005 if p.ma20 > 0 else p.close * 1.03,
                take_profit=[p.close * 0.95, p.close * 0.90],
                confidence=min(0.85, p.confidence + confidence_adj),
                trend_strength="bearish",
            )

        # ========== 中性趋势 ==========
        reason.append("趋势不明确，等待信号确认")

        # 中性市场中，缩量回调可能是机会
        if vp_state == "volume_shrink_pullback" and sector_mom == "bullish":
            return DecisionResult(
                trend=trend,
                action=SignalAction.long,
                reason=reason + ["中性市场缩量回调+行业动量偏多，轻仓试多"],
                stop_loss=p.close * 0.97,
                confidence=max(0.4, p.confidence - 0.1),
                trend_strength="neutral",
            )

        return DecisionResult(
            trend=trend,
            action=SignalAction.wait,
            reason=reason,
            confidence=max(0.3, p.confidence - 0.2),
            trend_strength="neutral",
        )
