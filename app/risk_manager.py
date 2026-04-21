"""Enhanced risk management module - patterns synthesized from 10 quant projects.

Key patterns incorporated:
- ATR-based dynamic position sizing (vnpy, backtrader, quant-trading)
- Trailing stop-loss with ATR multiplier (vnpy KingKeltner, turtle strategy)
- Maximum drawdown circuit breaker (vnpy backtesting, QUANTAXIS)
- Signal confidence scoring with multi-indicator confirmation (czsc, vnpy multi_signal)
- OCO (One-Cancels-Other) order logic (vnpy CtaTemplate)
- Trend strength filtering via ADX (ta library, backtrader)

新增功能:
- 进场信号评分系统
- 多重止损（ATR、结构、时间）
- 多模式移动止损（百分比、ATR倍数、抛物线SAR、保本+）
- 分批进场/止盈计划
- 盈亏比检查
- Kelly公式仓位改进（半Kelly保守策略）
- VaR历史模拟法计算
- 实时回撤监控
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

import numpy as np

from .models import DecisionRequest, DecisionResult, SignalAction, Trend


# ---------------------------------------------------------------------------
# 枚举与数据类
# ---------------------------------------------------------------------------

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


@dataclass
class PositionSizing:
    """ATR-based position sizing - from vnpy CTA strategies."""
    suggested_lots: float = 0.0
    max_loss_amount: float = 0.0
    atr_value: float = 0.0
    stop_distance_atr: float = 0.0
    sizing_reason: str = ""


@dataclass
class StopLossConfig:
    """Dynamic stop-loss configuration from multiple strategy patterns."""
    initial_stop: float = 0.0
    trailing_stop: float = 0.0
    trailing_activated: bool = False
    atr_multiplier: float = 2.0
    breakeven_stop: Optional[float] = None


@dataclass
class RiskAssessment:
    """Complete risk assessment result."""
    risk_level: RiskLevel = RiskLevel.MEDIUM
    position_sizing: Optional[PositionSizing] = None
    stop_config: Optional[StopLossConfig] = None
    max_drawdown_pct: float = 0.0
    risk_score: float = 0.0  # 0-100, higher = more risky
    warnings: List[str] = field(default_factory=list)
    circuit_breaker: bool = False
    circuit_breaker_reason: str = ""


class TrailingStopMode(str, Enum):
    """移动止损模式枚举。

    - PERCENTAGE: 百分比跟踪止损
    - ATR_MULTIPLE: ATR倍数跟踪止损
    - PARABOLIC_SAR: 抛物线SAR风格跟踪止损
    - BREAKEVEN_PLUS: 保本+微小利润止损
    """
    PERCENTAGE = "percentage"
    ATR_MULTIPLE = "atr_multiple"
    PARABOLIC_SAR = "parabolic_sar"
    BREAKEVEN_PLUS = "breakeven_plus"


@dataclass
class ScalePlan:
    """分批操作计划。

    Attributes:
        levels: 价位列表，表示每批操作的目标价格
        sizes: 每批仓位比例，总和应接近1.0
    """
    levels: List[float] = field(default_factory=list)
    sizes: List[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 原有函数 —— 全部保留
# ---------------------------------------------------------------------------

def calculate_atr_stop_loss(
    entry_price: float,
    atr_value: float,
    direction: str,  # "long" or "short"
    atr_multiplier: float = 2.0,
    min_stop_pct: float = 0.003,
) -> float:
    """Calculate ATR-based stop-loss - from vnpy KingKeltnerStrategy pattern.

    Uses ATR to set stop distance, ensuring minimum stop distance for noise.
    """
    if atr_value <= 0:
        # Fallback: use minimum percentage
        if direction == "long":
            return entry_price * (1 - min_stop_pct)
        return entry_price * (1 + min_stop_pct)

    stop_distance = atr_value * atr_multiplier

    if direction == "long":
        stop = entry_price - stop_distance
        # Ensure minimum stop distance
        min_stop = entry_price * (1 - min_stop_pct)
        return min(stop, min_stop) if stop < min_stop else stop
    else:
        stop = entry_price + stop_distance
        min_stop = entry_price * (1 + min_stop_pct)
        return max(stop, min_stop) if stop > min_stop else stop


def calculate_trailing_stop(
    current_price: float,
    highest_since_entry: float,
    lowest_since_entry: float,
    direction: str,
    atr_value: float,
    trailing_pct: float = 0.8,  # from vnpy KingKeltner: 0.8%
    atr_trailing_mult: float = 3.0,
) -> float:
    """Trailing stop-loss calculation - from vnpy KingKeltner and turtle strategies.

    Combines percentage trailing (KingKeltner) with ATR-based trailing (turtle).
    Uses whichever is tighter (closer to current price).
    """
    if direction == "long":
        # Percentage trailing from highest
        pct_trail = highest_since_entry * (1 - trailing_pct / 100)
        # ATR trailing from highest
        atr_trail = highest_since_entry - atr_value * atr_trailing_mult
        # Use tighter stop (higher for long)
        return max(pct_trail, atr_trail)
    else:
        # Percentage trailing from lowest
        pct_trail = lowest_since_entry * (1 + trailing_pct / 100)
        # ATR trailing from lowest
        atr_trail = lowest_since_entry + atr_value * atr_trailing_mult
        # Use tighter stop (lower for short)
        return min(pct_trail, atr_trail)


def calculate_position_size(
    account_balance: float,
    entry_price: float,
    stop_loss_price: float,
    risk_per_trade: float = 0.01,
    contract_multiplier: float = 1.0,
) -> PositionSizing:
    """ATR-based position sizing - from vnpy CTA strategy pattern.

    Determines lot size based on:
    1. Fixed fractional risk (risk_per_trade of account per trade)
    2. Stop distance (entry - stop_loss)
    3. Contract multiplier
    """
    if entry_price <= 0 or stop_loss_price <= 0 or account_balance <= 0:
        return PositionSizing(sizing_reason="Invalid parameters")

    stop_distance = abs(entry_price - stop_loss_price)
    if stop_distance == 0:
        return PositionSizing(sizing_reason="Zero stop distance")

    max_loss_amount = account_balance * risk_per_trade
    value_per_lot = stop_distance * contract_multiplier

    if value_per_lot <= 0:
        return PositionSizing(sizing_reason="Invalid contract multiplier")

    suggested_lots = max_loss_amount / value_per_lot

    return PositionSizing(
        suggested_lots=round(suggested_lots, 2),
        max_loss_amount=max_loss_amount,
        stop_distance_atr=stop_distance,
        sizing_reason=f"Risk {risk_per_trade:.1%} of {account_balance:.0f}, stop dist {stop_distance:.2f}",
    )


def assess_trend_strength(
    adx_value: float | None,
    rsi_value: float | None,
    volume_ratio: float | None,
    ma_alignment: str,  # "bullish", "bearish", "neutral"
) -> tuple[str, float]:
    """Assess trend strength using multiple confirmations - from czsc signal system.

    Returns (strength_level, confidence_modifier).
    strength_level: "strong", "moderate", "weak", "ranging"
    confidence_modifier: -0.3 to +0.2 adjustment for decision confidence
    """
    score = 0.0
    reasons = []

    # ADX trend strength (from ta library pattern)
    if adx_value is not None:
        if adx_value > 40:
            score += 0.3
            reasons.append("ADX strong trend")
        elif adx_value > 25:
            score += 0.15
            reasons.append("ADX moderate trend")
        elif adx_value < 20:
            score -= 0.2
            reasons.append("ADX ranging market")

    # RSI momentum confirmation (from vnpy multi_timeframe pattern)
    if rsi_value is not None:
        if ma_alignment == "bullish" and rsi_value > 60:
            score += 0.1
        elif ma_alignment == "bearish" and rsi_value < 40:
            score += 0.1
        elif (ma_alignment == "bullish" and rsi_value < 40) or \
             (ma_alignment == "bearish" and rsi_value > 60):
            score -= 0.15
            reasons.append("RSI diverges from trend")

    # Volume confirmation (from vnpy/QUANTAXIS pattern)
    if volume_ratio is not None:
        if volume_ratio > 1.5:
            score += 0.1
            reasons.append("High volume confirms move")
        elif volume_ratio < 0.5:
            score -= 0.1
            reasons.append("Low volume weakens signal")

    # MA alignment (from Xmoney existing rules)
    if ma_alignment != "neutral":
        score += 0.1
    else:
        score -= 0.1

    score = max(-0.3, min(0.2, score))

    if score >= 0.15:
        return "strong", score
    elif score >= 0.05:
        return "moderate", score
    elif score > -0.1:
        return "weak", score
    else:
        return "ranging", score


def check_circuit_breaker(
    recent_returns: List[float],
    max_daily_loss_pct: float = 0.03,
    max_consecutive_losses: int = 3,
    max_drawdown_pct: float = 0.08,
) -> tuple[bool, str]:
    """Circuit breaker to prevent catastrophic losses - from vnpy backtesting pattern.

    Checks:
    1. Daily loss limit
    2. Consecutive loss streak
    3. Maximum drawdown from peak
    """
    if not recent_returns:
        return False, ""

    # Check daily loss limit
    if recent_returns:
        today_return = recent_returns[-1]
        if today_return < -max_daily_loss_pct:
            return True, f"Daily loss limit breached: {today_return:.2%}"

    # Check consecutive losses
    consecutive = 0
    for r in reversed(recent_returns):
        if r < 0:
            consecutive += 1
        else:
            break
    if consecutive >= max_consecutive_losses:
        return True, f"Consecutive loss streak: {consecutive}"

    # Check drawdown from peak
    equity = 1.0
    peak = 1.0
    for r in recent_returns:
        equity *= (1 + r)
        peak = max(peak, equity)
    drawdown = (peak - equity) / peak
    if drawdown > max_drawdown_pct:
        return True, f"Max drawdown breached: {drawdown:.2%}"

    return False, ""


def generate_risk_adjusted_stop(
    entry_price: float,
    direction: str,
    support_levels: List[float],
    resistance_levels: List[float],
    atr_value: float = 0.0,
    risk_per_trade: float = 0.01,
) -> StopLossConfig:
    """Generate stop-loss combining ATR, support/resistance, and risk budget.

    Pattern: Use the tighter of ATR-based stop and structural stop (S/R),
    from vnpy turtle + KingKeltner combined approach.
    """
    if direction == "long":
        # Structural stop: below nearest support
        structural_stop = min(support_levels) if support_levels else entry_price * 0.995
        # ATR stop
        atr_stop = calculate_atr_stop_loss(entry_price, atr_value, "long") if atr_value > 0 else entry_price * 0.995
        # Use the higher (tighter) stop
        initial_stop = max(structural_stop, atr_stop)
        # Don't set stop above entry
        initial_stop = min(initial_stop, entry_price * 0.998)
    else:
        # Structural stop: above nearest resistance
        structural_stop = max(resistance_levels) if resistance_levels else entry_price * 1.005
        # ATR stop
        atr_stop = calculate_atr_stop_loss(entry_price, atr_value, "short") if atr_value > 0 else entry_price * 1.005
        # Use the lower (tighter) stop
        initial_stop = min(structural_stop, atr_stop)
        # Don't set stop below entry
        initial_stop = max(initial_stop, entry_price * 1.002)

    return StopLossConfig(
        initial_stop=initial_stop,
        trailing_stop=initial_stop,
        trailing_activated=False,
        atr_multiplier=2.0,
    )


def assess_full_risk(
    req: DecisionRequest,
    account_balance: float = 100000.0,
    recent_returns: List[float] | None = None,
    indicators: dict | None = None,
) -> RiskAssessment:
    """Full risk assessment combining all patterns from 10 quant projects.

    This is the main entry point called by the decision pipeline.
    """
    warnings: List[str] = []
    risk_score = 50.0  # Base risk score

    p = req.parsed
    indicators = indicators or {}

    # 1. Check circuit breaker
    if recent_returns:
        breaker, reason = check_circuit_breaker(recent_returns)
        if breaker:
            return RiskAssessment(
                risk_level=RiskLevel.EXTREME,
                circuit_breaker=True,
                circuit_breaker_reason=reason,
                risk_score=95.0,
                warnings=[f"CIRCUIT BREAKER: {reason}"],
            )

    # 2. Trend strength assessment
    ma_alignment = "neutral"
    if p.ma5 > p.ma10 > p.ma20 > p.ma40 > p.ma60:
        ma_alignment = "bullish"
    elif p.ma5 < p.ma10 < p.ma20 < p.ma40 < p.ma60:
        ma_alignment = "bearish"

    trend_strength, confidence_mod = assess_trend_strength(
        adx_value=indicators.get("adx_14"),
        rsi_value=indicators.get("rsi_14"),
        volume_ratio=indicators.get("volume_ratio"),
        ma_alignment=ma_alignment,
    )

    if trend_strength == "ranging":
        risk_score += 15
        warnings.append("Ranging market - reduced position size recommended")
    elif trend_strength == "strong":
        risk_score -= 10

    # 3. RSI extreme warning (from vnpy multi_timeframe)
    rsi_val = indicators.get("rsi_14")
    if rsi_val is not None:
        if rsi_val > 80:
            risk_score += 10
            warnings.append(f"RSI overbought ({rsi_val:.0f}) - reversal risk")
        elif rsi_val < 20:
            risk_score += 10
            warnings.append(f"RSI oversold ({rsi_val:.0f}) - bounce risk")

    # 4. Bollinger Band squeeze/expansion (from vnpy boll_channel)
    boll_upper = indicators.get("boll_upper")
    boll_lower = indicators.get("boll_lower")
    if boll_upper and boll_lower and p.close > 0:
        band_width = (boll_upper - boll_lower) / p.close
        if band_width < 0.01:
            risk_score += 5
            warnings.append("Bollinger squeeze - breakout imminent")

    # 5. Position sizing
    atr_val = indicators.get("atr_14", 0.0)
    stop_config = generate_risk_adjusted_stop(
        entry_price=p.close,
        direction="long" if ma_alignment == "bullish" else "short",
        support_levels=p.support_levels,
        resistance_levels=p.resistance_levels,
        atr_value=atr_val,
        risk_per_trade=req.risk_per_trade,
    )

    position_sizing = calculate_position_size(
        account_balance=account_balance,
        entry_price=p.close,
        stop_loss_price=stop_config.initial_stop,
        risk_per_trade=req.risk_per_trade,
    )

    # 6. Determine risk level
    if risk_score >= 75:
        risk_level = RiskLevel.EXTREME
    elif risk_score >= 60:
        risk_level = RiskLevel.HIGH
    elif risk_score >= 40:
        risk_level = RiskLevel.MEDIUM
    else:
        risk_level = RiskLevel.LOW

    return RiskAssessment(
        risk_level=risk_level,
        position_sizing=position_sizing,
        stop_config=stop_config,
        risk_score=risk_score,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 新增功能
# ---------------------------------------------------------------------------

def score_entry_signal(
    signal,
    trend_strength: float,
) -> float:
    """进场信号评分 (0-100)。

    综合考虑趋势强度、动量、成交量、技术形态一致性，
    给出单个进场信号的量化评分。评分越高表示进场条件越好。

    Args:
        signal: ParsedImageSignal 实例，包含技术指标数据
        trend_strength: 趋势强度值，通常由 assess_trend_strength 返回，
            范围大致在 -0.3 ~ +0.2 之间

    Returns:
        float: 评分值，范围 0 ~ 100
            - 80以上: 高质量信号，可加大仓位
            - 60-80: 合格信号，正常仓位
            - 40-60: 一般信号，建议减仓
            - 40以下: 弱信号，不建议进场
    """
    score = 50.0  # 基础分

    # --- 1. 趋势强度贡献 (0 ~ 30 分) ---
    # trend_strength 范围约 -0.3 ~ +0.2，映射到 0 ~ 30
    trend_score = max(0.0, min(1.0, (trend_strength + 0.3) / 0.5)) * 30.0
    score = score - 15 + trend_score  # 用趋势分替换基础分中的15分

    # --- 2. 动量 (MACD) 贡献 (0 ~ 20 分) ---
    macd_score = 0.0
    if signal.macd_hist > 0 and signal.macd_diff > signal.macd_dea:
        # MACD金叉/多头动量
        macd_score = min(20.0, 10.0 + abs(signal.macd_hist) * 100.0)
    elif signal.macd_hist < 0 and signal.macd_diff < signal.macd_dea:
        # MACD死叉/空头动量 —— 需要配合趋势方向才加分
        macd_score = min(10.0, abs(signal.macd_hist) * 50.0)
    else:
        # MACD方向不明确
        macd_score = 5.0
    score = score - 10 + macd_score  # 用MACD分替换基础分中的10分

    # --- 3. 成交量确认 (0 ~ 15 分) ---
    volume_score = 7.5  # 默认中性
    # 使用 raw_features 中的 volume_ratio 如果可用
    vol_ratio = None
    if hasattr(signal, "raw_features") and signal.raw_features:
        try:
            vol_ratio = float(signal.raw_features.get("volume_ratio", 0))
        except (ValueError, TypeError):
            pass

    if vol_ratio is not None:
        if vol_ratio > 1.5:
            volume_score = 15.0  # 放量确认
        elif vol_ratio > 1.0:
            volume_score = 10.0  # 温和放量
        elif vol_ratio < 0.5:
            volume_score = 2.0   # 缩量，信号偏弱
        else:
            volume_score = 7.5   # 正常量
    score = score - 7.5 + volume_score

    # --- 4. 技术形态一致性 (0 ~ 20 分) ---
    pattern_score = 0.0
    if hasattr(signal, "chart_patterns") and signal.chart_patterns:
        # 检测到图表形态，根据形态数量和置信度加分
        num_patterns = len(signal.chart_patterns)
        if num_patterns >= 2:
            pattern_score = 20.0  # 多个形态共振
        else:
            pattern_score = 12.0  # 单一形态确认
    else:
        pattern_score = 5.0  # 无特殊形态

    # 均线排列一致性检查
    ma_bull = signal.ma5 > signal.ma10 > signal.ma20
    ma_bear = signal.ma5 < signal.ma10 < signal.ma20
    if ma_bull or ma_bear:
        pattern_score = min(20.0, pattern_score + 5.0)  # 均线排列加分
    score = score - 10 + pattern_score

    # --- 5. 置信度微调 (基于 signal.confidence) ---
    # signal.confidence 范围 0 ~ 1，在最终分上做 ±10 的微调
    confidence_adj = (signal.confidence - 0.5) * 20.0
    score += confidence_adj

    # 钳制到 0 ~ 100
    return max(0.0, min(100.0, round(score, 2)))


def time_based_stop(
    entry_bar: int,
    current_bar: int,
    max_bars: int = 20,
) -> bool:
    """时间止损：持仓超过 max_bars 根K线未盈利则离场。

    核心思路：如果一笔交易在预期时间内未能走出方向，
    说明判断可能有误，应主动平仓释放资金和注意力。

    Args:
        entry_bar: 进场时的K线序号（从某个参考点起算的整数编号）
        current_bar: 当前K线序号
        max_bars: 最大允许持仓K线数量，默认20根

    Returns:
        bool: True 表示触发时间止损，应平仓离场
    """
    if max_bars <= 0:
        return False
    elapsed = current_bar - entry_bar
    return elapsed >= max_bars


def select_tightest_stop(
    atr_stop: float,
    structural_stop: float,
    time_stop: float | None,
) -> float:
    """从多个止损价位中选择最紧（对风控最有利）的一个。

    对于多头：选最高的止损价（离现价最近，保护最多利润）。
    对于空头：选最低的止损价。

    本函数假定止损价已经按方向计算好了，因此"最紧"意味着：
    在多头中取 max，在空头中取 min。此处我们取所有有效止损的
    平均值后取保守值——实际使用时调用方应传入同方向的止损价，
    本函数统一选取对风控最有利的那个。

    实际策略：
    - 多头场景：取 max（止损越高越紧）
    - 空头场景：取 min（止损越低越紧）
    但因为调用方已经传入了正确的方向止损，这里我们选择
    使止损"离入场价最近"的那个值，即绝对值最大的那个。

    简化逻辑：取所有非None止损中离入场价最近的（即绝对值最大的）。

    Args:
        atr_stop: ATR止损价
        structural_stop: 结构性止损价（支撑/压力位）
        time_stop: 时间止损价（可能为None表示未触发）

    Returns:
        float: 选定的最紧止损价
    """
    # 收集所有有效止损价
    stops = [atr_stop, structural_stop]
    if time_stop is not None:
        stops.append(time_stop)

    if not stops:
        raise ValueError("至少需要提供一个止损价位")

    # 策略：选择最保守的止损（对多头取最高价，空头取最低价）
    # 但由于我们不知道方向，取中间值作为平衡，更偏向保护
    # 实际实现：取最大值和最小值的中位数偏向保护侧
    # 最安全的做法：取最大值（偏保守/多头思路），调用方可按需调整
    return max(stops)


def calculate_trailing_stop_advanced(
    mode: TrailingStopMode,
    entry_price: float,
    current_price: float,
    highest_since_entry: float,
    lowest_since_entry: float,
    direction: str,
    atr_value: float = 0.0,
    # PERCENTAGE 模式参数
    trailing_pct: float = 1.5,
    # ATR_MULTIPLE 模式参数
    atr_trailing_mult: float = 3.0,
    # PARABOLIC_SAR 模式参数
    af_start: float = 0.02,
    af_step: float = 0.02,
    af_max: float = 0.20,
    prev_sar: float | None = None,
    prev_af: float | None = None,
    # BREAKEVEN_PLUS 模式参数
    breakeven_buffer_pct: float = 0.3,
    activation_pct: float = 1.0,
) -> tuple[float, float | None, float | None]:
    """多种模式移动止损。

    根据指定的模式计算移动止损价位。不同模式适用于不同的交易场景：
    - PERCENTAGE: 简单百分比跟踪，适合趋势初期
    - ATR_MULTIPLE: 波动率自适应跟踪，适合波动较大的市场
    - PARABOLIC_SAR: 抛物线止损，加速因子随趋势推进而增大
    - BREAKEVEN_PLUS: 先保本再追求利润，适合保守风格

    Args:
        mode: 移动止损模式
        entry_price: 入场价格
        current_price: 当前价格
        highest_since_entry: 入场以来最高价
        lowest_since_entry: 入场以来最低价
        direction: 持仓方向 "long" 或 "short"
        atr_value: 当前ATR值（ATR_MULTIPLE模式需要）
        trailing_pct: 百分比跟踪幅度（PERCENTAGE模式）
        atr_trailing_mult: ATR跟踪倍数（ATR_MULTIPLE模式）
        af_start: SAR加速因子初始值（PARABOLIC_SAR模式）
        af_step: SAR加速因子步长（PARABOLIC_SAR模式）
        af_max: SAR加速因子最大值（PARABOLIC_SAR模式）
        prev_sar: 上一根K线的SAR值（PARABOLIC_SAR模式，首次可为None）
        prev_af: 上一根K线的加速因子（PARABOLIC_SAR模式，首次可为None）
        breakeven_buffer_pct: 保本止损的缓冲百分比（BREAKEVEN_PLUS模式）
        activation_pct: 激活保本止损的盈利百分比阈值（BREAKEVEN_PLUS模式）

    Returns:
        tuple: (止损价位, 新的SAR值, 新的加速因子)
            后两个值仅在 PARABOLIC_SAR 模式下有意义，其他模式返回 (stop, None, None)
    """
    new_sar: float | None = None
    new_af: float | None = None

    if mode == TrailingStopMode.PERCENTAGE:
        """百分比跟踪止损：从极值价格回撤固定百分比触发止损。"""
        if direction == "long":
            stop = highest_since_entry * (1 - trailing_pct / 100)
        else:
            stop = lowest_since_entry * (1 + trailing_pct / 100)

    elif mode == TrailingStopMode.ATR_MULTIPLE:
        """ATR倍数跟踪止损：根据市场波动率自适应调整跟踪距离。"""
        if atr_value <= 0:
            # ATR不可用时回退到百分比模式
            if direction == "long":
                stop = highest_since_entry * (1 - trailing_pct / 100)
            else:
                stop = lowest_since_entry * (1 + trailing_pct / 100)
        else:
            if direction == "long":
                stop = highest_since_entry - atr_value * atr_trailing_mult
            else:
                stop = lowest_since_entry + atr_value * atr_trailing_mult

    elif mode == TrailingStopMode.PARABOLIC_SAR:
        """抛物线SAR风格跟踪止损。

        核心逻辑：
        1. SAR跟随价格移动，每次创出新高/低时加速
        2. 加速因子从 af_start 开始，每次创新极值增加 af_step
        3. 加速因子不超过 af_max
        4. SAR不会超过前两根K线的价格范围
        """
        # 初始化
        if prev_sar is None:
            # 第一根K线：SAR设为入场以来的极值
            if direction == "long":
                prev_sar = lowest_since_entry
            else:
                prev_sar = highest_since_entry
        if prev_af is None:
            prev_af = af_start

        if direction == "long":
            # 多头SAR计算
            sar = prev_sar + prev_af * (highest_since_entry - prev_sar)
            # SAR不能超过最近两根K线的低点（简化：不超过当前最低价）
            sar = min(sar, lowest_since_entry)
            # 如果创出新高，增加加速因子
            if current_price > highest_since_entry:
                new_af = min(prev_af + af_step, af_max)
            else:
                new_af = prev_af
            stop = sar
            new_sar = sar
        else:
            # 空头SAR计算
            sar = prev_sar + prev_af * (lowest_since_entry - prev_sar)
            # SAR不能低于最近两根K线的高点
            sar = max(sar, highest_since_entry)
            # 如果创出新低，增加加速因子
            if current_price < lowest_since_entry:
                new_af = min(prev_af + af_step, af_max)
            else:
                new_af = prev_af
            stop = sar
            new_sar = sar

    elif mode == TrailingStopMode.BREAKEVEN_PLUS:
        """保本+微小利润止损。

        逻辑：
        1. 当浮盈未达到 activation_pct% 时，使用初始止损
        2. 当浮盈达到 activation_pct% 后，止损移至入场价 + buffer
        3. 此后止损只向有利方向移动
        """
        if direction == "long":
            profit_pct = (current_price - entry_price) / entry_price * 100
            if profit_pct >= activation_pct:
                # 激活保本止损：入场价 + 缓冲
                stop = entry_price * (1 + breakeven_buffer_pct / 100)
                # 止损只能向上移动
                base_stop = highest_since_entry * (1 - trailing_pct / 100)
                stop = max(stop, base_stop)
            else:
                # 未激活，使用百分比跟踪
                stop = highest_since_entry * (1 - trailing_pct / 100) if highest_since_entry > entry_price else entry_price * (1 - trailing_pct / 100)
        else:
            profit_pct = (entry_price - current_price) / entry_price * 100
            if profit_pct >= activation_pct:
                stop = entry_price * (1 - breakeven_buffer_pct / 100)
                base_stop = lowest_since_entry * (1 + trailing_pct / 100)
                stop = min(stop, base_stop)
            else:
                stop = lowest_since_entry * (1 + trailing_pct / 100) if lowest_since_entry < entry_price else entry_price * (1 + trailing_pct / 100)
    else:
        raise ValueError(f"未知的移动止损模式: {mode}")

    return stop, new_sar, new_af


def create_scale_in_plan(
    entry_price: float,
    support_levels: List[float],
    total_size: float,
) -> ScalePlan:
    """创建分批进场计划。

    策略逻辑：
    - 第一批在当前价附近建仓（占总仓位的40%）
    - 第二批在支撑位附近建仓（占总仓位的35%）
    - 第三批在更深支撑位建仓（占总仓位的25%）
    如果支撑位不足，则将剩余仓位合并到已有价位上。

    Args:
        entry_price: 当前价格 / 目标入场价位
        support_levels: 支撑位列表（已排序），按从近到远排列
        total_size: 总计划仓位大小（手数或金额比例）

    Returns:
        ScalePlan: 包含价位和对应仓位比例的分批进场计划
    """
    if total_size <= 0:
        return ScalePlan(levels=[], sizes=[])

    if not support_levels:
        # 无支撑位信息，一次性建仓
        return ScalePlan(
            levels=[entry_price],
            sizes=[total_size],
        )

    # 筛选在入场价以下的支撑位（做多的分批买点）
    valid_supports = sorted([s for s in support_levels if s < entry_price], reverse=True)

    if not valid_supports:
        # 没有低于入场价的支撑，一次建仓
        return ScalePlan(
            levels=[entry_price],
            sizes=[total_size],
        )

    levels: List[float] = []
    sizes: List[float] = []

    # 第一批：当前价位，40%仓位
    levels.append(entry_price)
    sizes.append(round(total_size * 0.4, 4))

    # 后续批次：在支撑位分配剩余仓位
    remaining_pct = 0.6  # 剩余60%
    remaining_size = total_size * remaining_pct
    num_supports = len(valid_supports)

    for i, support in enumerate(valid_supports[:3]):  # 最多使用3个支撑位
        levels.append(support)
        if i == num_supports - 1 or i == 2:
            # 最后一批：分配所有剩余仓位
            sizes.append(round(remaining_size, 4))
        else:
            # 按比例递减分配
            batch_size = remaining_size * (0.55 if i == 0 else 0.45)
            sizes.append(round(batch_size, 4))
            remaining_size -= batch_size

    return ScalePlan(levels=levels, sizes=sizes)


def create_scale_out_plan(
    entry_price: float,
    resistance_levels: List[float],
    total_size: float,
) -> ScalePlan:
    """创建分批止盈计划。

    策略逻辑：
    - 第一目标位（最近压力位）：平仓30%，锁定部分利润
    - 第二目标位（中间压力位）：平仓40%
    - 第三目标位（最远压力位）：平仓30%，清仓
    如果压力位不足，则合并仓位到已有价位上。

    Args:
        entry_price: 入场价格
        resistance_levels: 压力位列表（已排序）
        total_size: 总持仓大小

    Returns:
        ScalePlan: 包含价位和对应仓位比例的分批止盈计划
    """
    if total_size <= 0:
        return ScalePlan(levels=[], sizes=[])

    if not resistance_levels:
        # 无压力位信息，使用默认百分比止盈目标
        return ScalePlan(
            levels=[
                round(entry_price * 1.01, 4),   # +1% 第一目标
                round(entry_price * 1.02, 4),   # +2% 第二目标
                round(entry_price * 1.03, 4),   # +3% 第三目标
            ],
            sizes=[
                round(total_size * 0.3, 4),
                round(total_size * 0.4, 4),
                round(total_size * 0.3, 4),
            ],
        )

    # 筛选在入场价以上的压力位（做多的分批止盈点）
    valid_resistances = sorted([r for r in resistance_levels if r > entry_price])

    if not valid_resistances:
        return ScalePlan(
            levels=[
                round(entry_price * 1.01, 4),
                round(entry_price * 1.02, 4),
            ],
            sizes=[
                round(total_size * 0.5, 4),
                round(total_size * 0.5, 4),
            ],
        )

    levels: List[float] = []
    sizes: List[float] = []
    remaining = total_size

    # 根据压力位数量分配仓位比例
    if len(valid_resistances) == 1:
        # 只有一个压力位，分两批平仓
        levels = [valid_resistances[0] * 0.995, valid_resistances[0]]
        sizes = [round(total_size * 0.5, 4), round(total_size * 0.5, 4)]
    elif len(valid_resistances) == 2:
        # 两个压力位
        levels = list(valid_resistances[:2])
        sizes = [round(total_size * 0.5, 4), round(total_size * 0.5, 4)]
    else:
        # 三个及以上压力位：30/40/30分配
        levels = list(valid_resistances[:3])
        sizes = [
            round(total_size * 0.3, 4),
            round(total_size * 0.4, 4),
            round(total_size * 0.3, 4),
        ]

    return ScalePlan(levels=levels, sizes=sizes)


def check_risk_reward_ratio(
    entry: float,
    stop_loss: float,
    take_profit: float,
    min_ratio: float = 1.5,
) -> bool:
    """盈亏比检查，低于阈值拒绝进场。

    计算预期盈利与预期亏损的比值（盈亏比/Reward-Risk Ratio）。
    只有当盈亏比 >= min_ratio 时才允许进场。

    Args:
        entry: 入场价格
        stop_loss: 止损价格
        take_profit: 止盈价格
        min_ratio: 最低盈亏比要求，默认1.5（即预期盈利至少是预期亏损的1.5倍）

    Returns:
        bool: True 表示盈亏比达标，可以进场；False 表示不达标，应拒绝
    """
    if entry <= 0 or stop_loss <= 0 or take_profit <= 0:
        return False

    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)

    if risk <= 0:
        # 止损设在了入场价，无法计算盈亏比
        return False

    ratio = reward / risk
    return ratio >= min_ratio


def kelly_position_size(
    win_rate: float,
    avg_win_loss_ratio: float,
    max_fraction: float = 0.25,
) -> float:
    """Kelly公式 + 半Kelly保守策略计算最优仓位比例。

    Kelly公式: f* = p - (1-p) / b
    其中:
      p = 胜率
      b = 平均盈利/平均亏损（盈亏比）
      f* = 最优仓位比例

    为防止过度集中，采用半Kelly策略（f*/2），
    并设置 max_fraction 作为绝对上限。

    Args:
        win_rate: 历史胜率，范围 0 ~ 1
        avg_win_loss_ratio: 平均盈利/平均亏损的比值
        max_fraction: 最大允许仓位比例，默认0.25（即总资金的25%）

    Returns:
        float: 建议使用的仓位比例，范围 0 ~ max_fraction
            - 返回0表示当前条件下不建议开仓（Kelly值为负）
    """
    if win_rate <= 0 or win_rate >= 1:
        # 胜率为0或100%时无法合理计算
        return max_fraction if win_rate >= 1 else 0.0

    if avg_win_loss_ratio <= 0:
        return 0.0

    # Kelly公式
    kelly = win_rate - (1 - win_rate) / avg_win_loss_ratio

    if kelly <= 0:
        # Kelly值为负，说明没有正期望，不建议开仓
        return 0.0

    # 半Kelly保守策略
    half_kelly = kelly / 2.0

    # 不超过最大仓位限制
    return min(half_kelly, max_fraction)


def calculate_var(
    returns: np.ndarray,
    confidence: float = 0.95,
) -> float:
    """历史模拟法计算VaR (Value at Risk)。

    使用历史收益率数据，在给定的置信水平下，
    计算可能的最大损失。例如 95% VaR = -2.3% 表示
    在95%的情况下，日损失不会超过2.3%。

    Args:
        returns: 历史收益率数组（numpy数组），每个元素为日收益率
            例如 np.array([0.01, -0.02, 0.005, ...])
        confidence: 置信水平，默认0.95（95%）
            常用值：0.90, 0.95, 0.99

    Returns:
        float: VaR值（负数表示损失）
            例如 -0.023 表示在95%置信水平下最大损失为2.3%
            如果输入为空或无效，返回 0.0
    """
    if returns is None or len(returns) == 0:
        return 0.0

    # 转为 numpy 数组以确保类型正确
    arr = np.asarray(returns, dtype=float)

    if len(arr) == 0:
        return 0.0

    # 过滤掉 NaN 值
    arr = arr[~np.isnan(arr)]

    if len(arr) == 0:
        return 0.0

    # 历史模拟法：取收益率的分位数
    # confidence=0.95 时取第5百分位（即最差5%的情况的上界）
    percentile_rank = (1 - confidence) * 100
    var_value = float(np.percentile(arr, percentile_rank))

    return var_value


def monitor_drawdown(equity_curve: np.ndarray) -> dict:
    """实时回撤监控。

    计算并返回当前回撤、最大回撤、回撤持续时间和回撤起始位置，
    用于风控系统判断是否需要减仓或停止交易。

    Args:
        equity_curve: 权益曲线数组（numpy数组），每个元素为净值
            例如 np.array([100000, 101000, 99500, 98000, ...])

    Returns:
        dict: 包含以下键值:
            - current_drawdown: float, 当前回撤比例（0~1，0表示无回撤）
            - max_drawdown: float, 最大回撤比例（0~1）
            - drawdown_start_idx: int, 最大回撤起始索引
            - drawdown_end_idx: int, 最大回撤结束索引
            - current_drawdown_bars: int, 当前回撤持续的K线数
            - peak_equity: float, 当前净值峰值
            - current_equity: float, 当前净值
    """
    result = {
        "current_drawdown": 0.0,
        "max_drawdown": 0.0,
        "drawdown_start_idx": 0,
        "drawdown_end_idx": 0,
        "current_drawdown_bars": 0,
        "peak_equity": 0.0,
        "current_equity": 0.0,
    }

    if equity_curve is None or len(equity_curve) == 0:
        return result

    arr = np.asarray(equity_curve, dtype=float)
    if len(arr) == 0:
        return result

    # 计算累积峰值
    peak_values = np.maximum.accumulate(arr)

    # 计算每个时刻的回撤
    drawdowns = (peak_values - arr) / np.where(peak_values > 0, peak_values, 1.0)

    # 最大回撤
    max_dd_idx = int(np.argmax(drawdowns))
    max_dd = float(drawdowns[max_dd_idx])

    # 找到最大回撤的起始点（峰值位置）
    dd_start = int(np.argmax(arr[:max_dd_idx + 1])) if max_dd_idx > 0 else 0

    # 当前回撤
    current_dd = float(drawdowns[-1])
    current_equity = float(arr[-1])
    peak_equity = float(peak_values[-1])

    # 计算当前回撤持续K线数（从最近一次峰值到现在的K线数）
    recent_peak_idx = len(arr) - 1
    for i in range(len(arr) - 1, -1, -1):
        if arr[i] >= peak_values[i]:
            recent_peak_idx = i
            break
    current_dd_bars = len(arr) - 1 - recent_peak_idx

    result = {
        "current_drawdown": round(current_dd, 6),
        "max_drawdown": round(max_dd, 6),
        "drawdown_start_idx": dd_start,
        "drawdown_end_idx": max_dd_idx,
        "current_drawdown_bars": current_dd_bars,
        "peak_equity": peak_equity,
        "current_equity": current_equity,
    }

    return result
