from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class Trend(str, Enum):
    bullish = "bullish"
    bearish = "bearish"
    neutral = "neutral"


class MarketRegime(str, Enum):
    bullish = "bullish"
    bearish = "bearish"
    neutral = "neutral"
    unknown = "unknown"


class SignalAction(str, Enum):
    wait = "wait"
    long = "long"
    short = "short"
    hold_long = "hold_long"
    hold_short = "hold_short"
    reduce_long = "reduce_long"
    reduce_short = "reduce_short"


class ParsedImageSignal(BaseModel):
    symbol: str
    timeframe: str
    close: float
    ma5: float
    ma10: float
    ma20: float
    ma40: float
    ma60: float
    macd_diff: float
    macd_dea: float
    macd_hist: float
    volume: float
    open_interest: float
    support_levels: List[float] = Field(default_factory=list)
    resistance_levels: List[float] = Field(default_factory=list)
    historical_support_levels: List[float] = Field(default_factory=list, description="Important historical supports")
    historical_resistance_levels: List[float] = Field(default_factory=list, description="Important historical resistances")
    swing_high: Optional[float] = Field(default=None, description="Recent swing high for Fibonacci")
    swing_low: Optional[float] = Field(default=None, description="Recent swing low for Fibonacci")
    leg_start_price: Optional[float] = Field(default=None, description="Current trend-leg start price")
    leg_elapsed_bars: Optional[int] = Field(default=None, description="Bars elapsed for current trend leg")
    avg_up_leg_bars: Optional[int] = Field(default=None, description="Historical average bullish leg duration in bars")
    avg_down_leg_bars: Optional[int] = Field(default=None, description="Historical average bearish leg duration in bars")
    avg_up_leg_move_pct: Optional[float] = Field(default=None, description="Historical average bullish leg move (ratio)")
    avg_down_leg_move_pct: Optional[float] = Field(default=None, description="Historical average bearish leg move (ratio)")
    chart_patterns: List[str] = Field(default_factory=list, description="Detected chart patterns, e.g. head_and_shoulders")
    confidence: float = Field(ge=0.0, le=1.0)
    raw_features: Dict[str, str] = Field(default_factory=dict)


class DecisionRequest(BaseModel):
    parsed: ParsedImageSignal
    position: str = Field(default="flat", pattern="^(flat|long|short)$")
    risk_per_trade: float = Field(default=0.01, ge=0.001, le=0.05)
    market_regime_30m: MarketRegime = MarketRegime.unknown
    market_regime_15m: MarketRegime = MarketRegime.unknown
    require_market_filter: bool = True


class DecisionResult(BaseModel):
    trend: Trend
    action: SignalAction
    reason: List[str]
    entry_zone: Optional[List[float]] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[List[float]] = None
    expected_remaining_bars: Optional[int] = None
    expected_total_move_pct: Optional[float] = None
    confidence: float


class SignalRecord(BaseModel):
    id: int
    created_at: datetime
    symbol: str
    timeframe: str
    position: str
    trend: Trend
    action: SignalAction
    confidence: float
    payload: Dict
    outcome_return: Optional[float] = None


class OutcomeUpdate(BaseModel):
    outcome_return: float = Field(description="Realized return ratio, e.g. 0.015 for +1.5%")


class DailyStats(BaseModel):
    date: str
    total_signals: int
    evaluated_signals: int
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    expectancy: float
    max_drawdown: float
    cumulative_return: float


class DailyReportResponse(BaseModel):
    stats: DailyStats
    chart_path: str
    html_path: str
