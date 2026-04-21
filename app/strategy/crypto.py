"""数字货币专用策略模块 - 针对加密货币市场特点优化。

核心特征:
- 7x24小时市场适配（无需交易时间过滤）
- 高波动率自适应仓位（ATR占比动态调整）
- 布林带回归策略（价格触及布林带边界时的均值回归）
- Keltner通道突破（趋势确认与入场信号）
- 波动率自适应止损（基于ATR的动态止损距离）
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from app.models import (
    DecisionRequest,
    DecisionResult,
    SignalAction,
    Trend,
)


def _infer_trend(req: DecisionRequest) -> Trend:
    """趋势推断 - 加密货币版本。

    加密货币市场波动大，使用更宽松的MA排列判断。
    """
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


def _volatility_regime(req: DecisionRequest) -> Tuple[str, float]:
    """波动率状态判断。

    根据ATR占价格的百分比将波动率分为：
    - "extreme"（极端）: ATR/价格 > 5% → 极高波动，保守操作
    - "high"（高）: ATR/价格 3%-5% → 高波动，减仓
    - "normal"（正常）: ATR/价格 1%-3% → 正常波动
    - "low"（低）: ATR/价格 < 1% → 低波动，可适当加仓

    返回 (波动率状态, 仓位调整系数)。
    """
    p = req.parsed
    atr_val = None

    # 从raw_features中获取ATR值
    if p.raw_features.get("atr_14"):
        try:
            atr_val = float(p.raw_features["atr_14"])
        except (ValueError, TypeError):
            pass

    if atr_val is None or p.close <= 0:
        return "normal", 1.0

    atr_pct = atr_val / p.close * 100

    if atr_pct > 5.0:
        return "extreme", 0.3  # 极端波动，仓位缩减至30%
    if atr_pct > 3.0:
        return "high", 0.6  # 高波动，仓位缩减至60%
    if atr_pct > 1.0:
        return "normal", 1.0  # 正常波动，标准仓位
    return "low", 1.3  # 低波动，可适当放大仓位


def _bollinger_band_signal(req: DecisionRequest) -> Tuple[str, List[str]]:
    """布林带回归策略。

    在震荡市中：
    - 价格触及上轨 → 做空信号（均值回归）
    - 价格触及下轨 → 做多信号（均值回归）

    在趋势市中：
    - 价格沿上轨运行 → 强多头
    - 价格沿下轨运行 → 强空头

    返回 (信号方向: "long"/"short"/"neutral", 原因列表)。
    """
    p = req.parsed
    notes: List[str] = []

    boll_upper = p.raw_features.get("boll_upper")
    boll_lower = p.raw_features.get("boll_lower")
    boll_mid = p.raw_features.get("boll_mid")

    if not all([boll_upper, boll_lower, boll_mid]):
        return "neutral", notes

    try:
        upper = float(boll_upper)
        lower = float(boll_lower)
        mid = float(boll_mid)
    except (ValueError, TypeError):
        return "neutral", notes

    band_width = upper - lower
    if band_width <= 0:
        return "neutral", notes

    # 价格在布林带中的位置（0=下轨，1=上轨）
    position = (p.close - lower) / band_width

    if position > 0.95:
        notes.append(f"价格触及布林带上轨（位置{position:.1%}），均值回归做空信号")
        return "short", notes
    if position < 0.05:
        notes.append(f"价格触及布林带下轨（位置{position:.1%}），均值回归做多信号")
        return "long", notes

    # 沿轨道运行的判断
    if position > 0.8:
        notes.append(f"价格沿布林带上轨运行（位置{position:.1%}），强多头")
        return "long", notes
    if position < 0.2:
        notes.append(f"价格沿布林带下轨运行（位置{position:.1%}），强空头")
        return "short", notes

    return "neutral", notes


def _keltner_breakout_signal(req: DecisionRequest) -> Tuple[str, List[str]]:
    """Keltner通道突破策略。

    价格突破Keltner上轨 → 做多（趋势突破确认）
    价格跌破Keltner下轨 → 做空（趋势突破确认）

    结合Squeeze（挤压）判断：
    当布林带在Keltner通道内部时为Squeeze状态，突破后通常伴随大行情。

    返回 (信号方向, 原因列表)。
    """
    p = req.parsed
    notes: List[str] = []

    kc_upper = p.raw_features.get("keltner_upper")
    kc_lower = p.raw_features.get("keltner_lower")
    boll_upper = p.raw_features.get("boll_upper")
    boll_lower = p.raw_features.get("boll_lower")

    if not kc_upper or not kc_lower:
        return "neutral", notes

    try:
        upper = float(kc_upper)
        lower = float(kc_lower)
    except (ValueError, TypeError):
        return "neutral", notes

    # Squeeze检测：布林带宽度 < Keltner通道宽度
    squeeze = False
    if boll_upper and boll_lower:
        try:
            bb_width = float(boll_upper) - float(boll_lower)
            kc_width = upper - lower
            if bb_width < kc_width:
                squeeze = True
                notes.append("Keltner Squeeze状态（布林带收缩在Keltner通道内），突破后可能产生大行情")
        except (ValueError, TypeError):
            pass

    if p.close > upper:
        strength_note = "Squeeze突破" if squeeze else "通道突破"
        notes.append(f"价格突破Keltner上轨（{upper:.2f}），{strength_note}做多信号")
        return "long", notes

    if p.close < lower:
        strength_note = "Squeeze突破" if squeeze else "通道跌破"
        notes.append(f"价格跌破Keltner下轨（{lower:.2f}），{strength_note}做空信号")
        return "short", notes

    return "neutral", notes


def _adaptive_stop_loss(req: DecisionRequest, trend: Trend, vol_state: str) -> float:
    """波动率自适应止损。

    根据波动率状态调整止损距离：
    - 极端波动: 3x ATR
    - 高波动: 2.5x ATR
    - 正常波动: 2x ATR
    - 低波动: 1.5x ATR
    """
    p = req.parsed
    atr_val = None

    if p.raw_features.get("atr_14"):
        try:
            atr_val = float(p.raw_features["atr_14"])
        except (ValueError, TypeError):
            pass

    if atr_val is None:
        # 无ATR数据时使用固定百分比
        return p.close * (0.97 if trend == Trend.bullish else 1.03)

    # 波动率倍数
    multipliers = {"extreme": 3.0, "high": 2.5, "normal": 2.0, "low": 1.5}
    mult = multipliers.get(vol_state, 2.0)

    if trend == Trend.bullish:
        return p.close - atr_val * mult
    return p.close + atr_val * mult


class CryptoStrategy:
    """数字货币专用策略。

    适配7x24小时市场，高波动率环境下自适应调整仓位和止损。
    结合布林带回归与Keltner通道突破生成交易信号。
    """

    def decide(self, req: DecisionRequest) -> DecisionResult:
        p = req.parsed
        reason: List[str] = []
        reason.append("[数字货币专用策略]")

        # 加密货币市场无交易时间限制，无需时间过滤
        reason.append("7x24小时市场，无交易时间过滤")

        # 1. 波动率状态判断
        vol_state, pos_adj = _volatility_regime(req)
        reason.append(f"波动率状态: {vol_state}，仓位调整系数: {pos_adj:.1f}")

        # 2. 趋势判断
        trend = _infer_trend(req)

        # 3. 布林带信号
        bb_signal, bb_notes = _bollinger_band_signal(req)
        reason.extend(bb_notes)

        # 4. Keltner通道突破信号
        kc_signal, kc_notes = _keltner_breakout_signal(req)
        reason.extend(kc_notes)

        # 5. 极端波动保护
        if vol_state == "extreme":
            reason.append("极端波动警告：建议保守操作，降低仓位至30%以下")
            if req.position == "flat":
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.wait,
                    reason=reason + ["极端波动环境，不建议新开仓"],
                    confidence=max(0.2, p.confidence - 0.2),
                    risk_level="extreme",
                    position_sizing=pos_adj,
                    trend_strength="extreme_volatility",
                )

        # 6. 止损计算
        stop = _adaptive_stop_loss(req, trend, vol_state)

        # ========== 多头趋势决策 ==========
        if trend == Trend.bullish:
            reason.append("MA多头排列，多头趋势确认")

            if req.position == "short":
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.reduce_short,
                    reason=reason + ["持有空单与趋势冲突，优先减仓"],
                    stop_loss=p.close * 1.01,
                    confidence=min(0.9, p.confidence + 0.1),
                    position_sizing=pos_adj,
                    trend_strength="bullish",
                )

            if req.position == "long":
                # 持有多单：检查是否需要止盈
                if bb_signal == "short":
                    return DecisionResult(
                        trend=trend,
                        action=SignalAction.reduce_long,
                        reason=reason + ["多头趋势但触及布林带上轨，建议部分止盈"],
                        stop_loss=stop,
                        take_profit=[p.close * 1.02],
                        confidence=min(0.85, p.confidence),
                        position_sizing=pos_adj,
                        trend_strength="bullish",
                    )
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.hold_long,
                    reason=reason + ["顺势多单可持有"],
                    stop_loss=stop,
                    take_profit=[p.close * 1.03, p.close * 1.05],
                    confidence=min(0.92, p.confidence + 0.08),
                    position_sizing=pos_adj,
                    trend_strength="bullish",
                )

            # 空仓：寻找入场机会
            if kc_signal == "long":
                reason.append("Keltner通道突破确认做多入场")
            elif bb_signal == "long":
                reason.append("布林带下轨反弹，均值回归做多")

            if kc_signal == "long" or bb_signal == "long" or trend == Trend.bullish:
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.long,
                    reason=reason + ["建议做多入场"],
                    entry_zone=[p.ma10, p.ma20],
                    stop_loss=stop,
                    take_profit=[p.close * 1.02, p.close * 1.05],
                    confidence=min(0.9, p.confidence + 0.05),
                    position_sizing=pos_adj,
                    trend_strength="bullish",
                )

        # ========== 空头趋势决策 ==========
        if trend == Trend.bearish:
            reason.append("MA空头排列，空头趋势确认")

            if req.position == "long":
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.reduce_long,
                    reason=reason + ["持有多单与趋势冲突，优先减仓"],
                    stop_loss=p.close * 0.99,
                    confidence=min(0.9, p.confidence + 0.1),
                    position_sizing=pos_adj,
                    trend_strength="bearish",
                )

            if req.position == "short":
                # 持有空单：检查是否需要止盈
                if bb_signal == "long":
                    return DecisionResult(
                        trend=trend,
                        action=SignalAction.reduce_short,
                        reason=reason + ["空头趋势但触及布林带下轨，建议部分止盈"],
                        stop_loss=stop,
                        take_profit=[p.close * 0.98],
                        confidence=min(0.85, p.confidence),
                        position_sizing=pos_adj,
                        trend_strength="bearish",
                    )
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.hold_short,
                    reason=reason + ["顺势空单可持有"],
                    stop_loss=stop,
                    take_profit=[p.close * 0.97, p.close * 0.95],
                    confidence=min(0.92, p.confidence + 0.08),
                    position_sizing=pos_adj,
                    trend_strength="bearish",
                )

            # 空仓：寻找做空机会
            if kc_signal == "short":
                reason.append("Keltner通道跌破确认做空入场")
            elif bb_signal == "short":
                reason.append("布林带上轨回落，均值回归做空")

            if kc_signal == "short" or bb_signal == "short" or trend == Trend.bearish:
                return DecisionResult(
                    trend=trend,
                    action=SignalAction.short,
                    reason=reason + ["建议做空入场"],
                    entry_zone=[p.ma10, p.ma20],
                    stop_loss=stop,
                    take_profit=[p.close * 0.98, p.close * 0.95],
                    confidence=min(0.9, p.confidence + 0.05),
                    position_sizing=pos_adj,
                    trend_strength="bearish",
                )

        # ========== 中性趋势 ==========
        reason.append("趋势不明确，等待信号确认")

        # 中性市场中，布林带回归策略可作为辅助
        if bb_signal != "neutral":
            action = SignalAction.long if bb_signal == "long" else SignalAction.short
            return DecisionResult(
                trend=trend,
                action=action,
                reason=reason + [f"中性市场中布林带回归信号: {bb_signal}"],
                stop_loss=stop,
                confidence=max(0.4, p.confidence - 0.1),
                position_sizing=min(pos_adj, 0.5),  # 中性市场减仓
                trend_strength="neutral",
            )

        return DecisionResult(
            trend=trend,
            action=SignalAction.wait,
            reason=reason,
            confidence=max(0.3, p.confidence - 0.2),
            position_sizing=pos_adj,
            trend_strength="neutral",
        )
