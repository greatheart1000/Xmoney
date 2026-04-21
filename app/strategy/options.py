"""期权专用策略模块 - 针对期权交易特点优化。

核心特征:
- 波动率状态判断（IV percentile / 历史波动率对比）
- Covered Call / Protective Put 信号生成
- 价差策略信号（牛市价差、熊市价差、跨式/宽跨式）
- Greeks感知的信号调整
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from app.models import (
    DecisionRequest,
    DecisionResult,
    SignalAction,
    Trend,
)


def _infer_underlying_trend(req: DecisionRequest) -> Trend:
    """标的资产趋势推断。"""
    p = req.parsed
    ma_bull = p.ma5 > p.ma10 > p.ma20 > p.ma40
    ma_bear = p.ma5 < p.ma10 < p.ma20 < p.ma40
    price_above_mid = p.close > p.ma20 and p.close > p.ma40
    price_below_mid = p.close < p.ma20 and p.close < p.ma40

    if ma_bull and price_above_mid:
        return Trend.bullish
    if ma_bear and price_below_mid:
        return Trend.bearish
    return Trend.neutral


def _iv_percentile_estimate(req: DecisionRequest) -> Tuple[str, float, List[str]]:
    """隐含波动率百分位估算。

    通过ATR与历史波动率的关系估算当前波动率水平：
    - 使用ATR/价格比率作为波动率代理
    - 结合布林带宽度判断当前波动率相对水平

    返回 (波动率状态, 估算百分位0-1, 原因列表)。
    状态:
    - "high_iv": 高波动率（百分位>70%）→ 适合卖出期权/价差策略
    - "normal_iv": 正常波动率（百分位30%-70%）
    - "low_iv": 低波动率（百分位<30%）→ 适合买入期权
    """
    p = req.parsed
    notes: List[str] = []

    # 使用ATR作为波动率代理
    atr_val = None
    if p.raw_features.get("atr_14"):
        try:
            atr_val = float(p.raw_features["atr_14"])
        except (ValueError, TypeError):
            pass

    # 使用布林带宽度作为波动率代理
    boll_width_pct = None
    if p.raw_features.get("boll_upper") and p.raw_features.get("boll_lower"):
        try:
            boll_width = float(p.raw_features["boll_upper"]) - float(p.raw_features["boll_lower"])
            if p.close > 0:
                boll_width_pct = boll_width / p.close * 100
        except (ValueError, TypeError):
            pass

    # 综合评估波动率水平
    atr_pct = atr_val / p.close * 100 if atr_val and p.close > 0 else None

    # 波动率百分位估算（简化模型）
    iv_percentile = 0.5  # 默认中性

    if atr_pct is not None:
        # ATR占比 > 3% 通常为高波动率
        if atr_pct > 4.0:
            iv_percentile = 0.85
        elif atr_pct > 3.0:
            iv_percentile = 0.70
        elif atr_pct > 2.0:
            iv_percentile = 0.50
        elif atr_pct > 1.0:
            iv_percentile = 0.30
        else:
            iv_percentile = 0.15

    if boll_width_pct is not None:
        # 布林带宽度 > 6% 通常为高波动率
        if boll_width_pct > 8.0:
            iv_percentile = max(iv_percentile, 0.85)
        elif boll_width_pct > 6.0:
            iv_percentile = max(iv_percentile, 0.70)
        elif boll_width_pct < 3.0:
            iv_percentile = min(iv_percentile, 0.25)

    # 确定波动率状态
    if iv_percentile > 0.70:
        state = "high_iv"
        notes.append(f"高波动率环境（估算IV百分位{iv_percentile:.0%}），适合卖出期权策略")
    elif iv_percentile < 0.30:
        state = "low_iv"
        notes.append(f"低波动率环境（估算IV百分位{iv_percentile:.0%}），适合买入期权策略")
    else:
        state = "normal_iv"
        notes.append(f"正常波动率环境（估算IV百分位{iv_percentile:.0%}）")

    return state, iv_percentile, notes


def _covered_call_signal(
    req: DecisionRequest, trend: Trend, iv_state: str
) -> Tuple[bool, List[str]]:
    """Covered Call（备兑看涨）信号。

    适用条件:
    - 持有标的资产多头
    - 中性或温和看多
    - 高波动率（收取更多权利金）

    返回 (是否触发, 原因列表)。
    """
    notes: List[str] = []
    triggered = False

    if req.position != "long":
        return False, notes

    if trend in (Trend.neutral, Trend.bullish) and iv_state == "high_iv":
        triggered = True
        notes.append("持有标的多头 + 温和看多 + 高波动率 → 建议卖出虚值看涨期权（Covered Call）收取权利金")

    return triggered, notes


def _protective_put_signal(
    req: DecisionRequest, trend: Trend, iv_state: str
) -> Tuple[bool, List[str]]:
    """Protective Put（保护性看跌）信号。

    适用条件:
    - 持有标的资产多头
    - 看空或不确定
    - 低波动率（权利金便宜）

    返回 (是否触发, 原因列表)。
    """
    notes: List[str] = []
    triggered = False

    if req.position != "long":
        return False, notes

    if trend in (Trend.bearish, Trend.neutral) and iv_state == "low_iv":
        triggered = True
        notes.append("持有标的多头 + 看空或不确定 + 低波动率 → 建议买入看跌期权（Protective Put）做保险")

    return triggered, notes


def _spread_strategy_signal(
    req: DecisionRequest, trend: Trend, iv_state: str
) -> Tuple[str, List[str]]:
    """价差策略信号。

    根据趋势方向和波动率状态推荐价差策略：
    - 牛市看涨价差（Bull Call Spread）: 温和看多 + 高波动率
    - 熊市看跌价差（Bear Put Spread）: 温和看空 + 高波动率
    - 跨式做多（Long Straddle）: 低波动率 + 预期大波动
    - 铁鹰式（Iron Condor）: 震荡市 + 高波动率

    返回 (策略名称, 原因列表)。
    """
    notes: List[str] = []

    if trend == Trend.bullish and iv_state == "high_iv":
        notes.append("温和看多 + 高波动率 → 建议牛市看涨价差（Bull Call Spread），降低权利金成本")
        return "bull_call_spread", notes

    if trend == Trend.bearish and iv_state == "high_iv":
        notes.append("温和看空 + 高波动率 → 建议熊市看跌价差（Bear Put Spread），降低权利金成本")
        return "bear_put_spread", notes

    if trend == Trend.neutral and iv_state == "high_iv":
        notes.append("震荡市 + 高波动率 → 建议铁鹰式（Iron Condor），收取时间价值")
        return "iron_condor", notes

    if trend == Trend.neutral and iv_state == "low_iv":
        notes.append("震荡市 + 低波动率 → 建议跨式做多（Long Straddle），押注波动率回升")
        return "long_straddle", notes

    if trend == Trend.bullish and iv_state == "low_iv":
        notes.append("看多 + 低波动率 → 建议直接买入看涨期权（Long Call），权利金便宜")
        return "long_call", notes

    if trend == Trend.bearish and iv_state == "low_iv":
        notes.append("看空 + 低波动率 → 建议直接买入看跌期权（Long Put），权利金便宜")
        return "long_put", notes

    return "none", notes


class OptionsStrategy:
    """期权专用策略。

    根据标的资产趋势方向和隐含波动率水平，
    推荐适合的期权策略组合。
    """

    def decide(self, req: DecisionRequest) -> DecisionResult:
        p = req.parsed
        reason: List[str] = []
        reason.append("[期权专用策略]")

        # 1. 标的趋势判断
        trend = _infer_underlying_trend(req)
        reason.append(f"标的趋势: {trend.value}")

        # 2. 波动率状态
        iv_state, iv_pct, iv_notes = _iv_percentile_estimate(req)
        reason.extend(iv_notes)

        # 3. MACD状态
        macd_strong = p.macd_hist > 0 and p.macd_diff > p.macd_dea
        macd_weak = p.macd_hist < 0 and p.macd_diff < p.macd_dea

        # 4. Covered Call信号
        cc_triggered, cc_notes = _covered_call_signal(req, trend, iv_state)
        reason.extend(cc_notes)

        # 5. Protective Put信号
        pp_triggered, pp_notes = _protective_put_signal(req, trend, iv_state)
        reason.extend(pp_notes)

        # 6. 价差策略信号
        spread_name, spread_notes = _spread_strategy_signal(req, trend, iv_state)
        reason.extend(spread_notes)

        # ========== Covered Call 触发 ==========
        if cc_triggered:
            return DecisionResult(
                trend=trend,
                action=SignalAction.hold_long,
                reason=reason + ["执行Covered Call策略：持有标的 + 卖出虚值看涨期权"],
                stop_loss=p.close * 0.95,
                confidence=min(0.85, p.confidence + 0.05),
                risk_level="low",
                trend_strength=trend.value,
                indicators_used=["covered_call", iv_state],
            )

        # ========== Protective Put 触发 ==========
        if pp_triggered:
            return DecisionResult(
                trend=trend,
                action=SignalAction.hold_long,
                reason=reason + ["执行Protective Put策略：持有标的 + 买入看跌期权做保险"],
                stop_loss=p.close * 0.95,
                confidence=min(0.8, p.confidence),
                risk_level="low",
                trend_strength=trend.value,
                indicators_used=["protective_put", iv_state],
            )

        # ========== 基于趋势和波动率的决策 ==========
        if trend == Trend.bullish:
            reason.append("标的多头趋势")
            if macd_strong:
                reason.append("MACD动能确认")

            if req.position == "short":
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.reduce_short,
                    reason=reason + ["标的看多，空单减仓"],
                    confidence=min(0.85, p.confidence + 0.1),
                    trend_strength="bullish",
                    indicators_used=[spread_name, iv_state],
                )

            if req.position == "long":
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.hold_long,
                    reason=reason + ["持有多头，可考虑" + spread_name if spread_name != "none" else "持有多头"],
                    stop_loss=p.close * 0.95,
                    confidence=min(0.9, p.confidence + 0.08),
                    trend_strength="bullish",
                    indicators_used=[spread_name, iv_state],
                )

            # 空仓做多
            return DecisionResult(
                trend=trend,
                action=SignalAction.long,
                reason=reason + [f"建议{spread_name}策略做多"],
                entry_zone=[p.ma10, p.ma20],
                stop_loss=p.close * 0.95,
                take_profit=[p.close * 1.05, p.close * 1.10],
                confidence=min(0.85, p.confidence + 0.05),
                trend_strength="bullish",
                indicators_used=[spread_name, iv_state],
            )

        if trend == Trend.bearish:
            reason.append("标的空头趋势")
            if macd_weak:
                reason.append("MACD空头动能确认")

            if req.position == "long":
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.reduce_long,
                    reason=reason + ["标的看空，多单减仓" + ("，建议买入Protective Put" if iv_state == "low_iv" else "")],
                    stop_loss=p.close * 1.05,
                    confidence=min(0.85, p.confidence + 0.1),
                    trend_strength="bearish",
                    indicators_used=[spread_name, iv_state],
                )

            if req.position == "short":
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.hold_short,
                    reason=reason + ["持有空头"],
                    stop_loss=p.close * 1.05,
                    confidence=min(0.9, p.confidence + 0.08),
                    trend_strength="bearish",
                    indicators_used=[spread_name, iv_state],
                )

            # 空仓做空
            return DecisionResult(
                trend=trend,
                action=SignalAction.short,
                reason=reason + [f"建议{spread_name}策略做空"],
                entry_zone=[p.ma10, p.ma20],
                stop_loss=p.close * 1.05,
                take_profit=[p.close * 0.95, p.close * 0.90],
                confidence=min(0.85, p.confidence + 0.05),
                trend_strength="bearish",
                indicators_used=[spread_name, iv_state],
            )

        # ========== 中性趋势 ==========
        reason.append("标的趋势不明确")

        if spread_name != "none":
            return DecisionResult(
                trend=trend,
                action=SignalAction.wait,
                reason=reason + [f"建议{spread_name}策略（波动率交易）"],
                confidence=max(0.4, p.confidence - 0.1),
                risk_level="medium",
                trend_strength="neutral",
                indicators_used=[spread_name, iv_state],
            )

        return DecisionResult(
            trend=trend,
            action=SignalAction.wait,
            reason=reason + ["等待趋势明确或波动率极端"],
            confidence=max(0.3, p.confidence - 0.2),
            trend_strength="neutral",
            indicators_used=[iv_state],
        )
