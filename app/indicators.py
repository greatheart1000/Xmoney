"""Technical indicators module - synthesized from 10 open-source quant projects.

Implements indicators commonly used across vnpy, backtrader, czsc, quant-trading,
ta, and other reference projects for CTA/futures trading.

Key sources:
- vnpy_ctastrategy: ArrayManager indicator calculation pattern (RSI, SMA, Keltner, ATR)
- backtrader: indicator composition pattern
- ta library: pandas-based batch calculation
- quant-trading: CTA signal confirmation indicators
"""
from __future__ import annotations

from typing import List, Tuple

import numpy as np


def sma(data: List[float] | np.ndarray, period: int) -> np.ndarray:
    """Simple moving average."""
    arr = np.array(data, dtype=float)
    if len(arr) < period:
        return np.full_like(arr, np.nan)
    cumsum = np.cumsum(arr)
    result = np.full_like(arr, np.nan)
    result[period - 1:] = (cumsum[period - 1:] - np.concatenate([[0], cumsum[:-period]])) / period
    return result


def ema(data: List[float] | np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average."""
    arr = np.array(data, dtype=float)
    result = np.full_like(arr, np.nan)
    if len(arr) < period:
        return result
    multiplier = 2.0 / (period + 1)
    # Initialize with SMA
    result[period - 1] = np.mean(arr[:period])
    for i in range(period, len(arr)):
        result[i] = (arr[i] - result[i - 1]) * multiplier + result[i - 1]
    return result


def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> np.ndarray:
    """Average True Range - key volatility measure from vnpy/backtrader.

    Used for:
    - ATR-based position sizing (vnpy CTA strategies)
    - Keltner Channel bands (vnpy KingKeltner)
    - Trailing stop-loss distance (turtle strategy)
    """
    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)
    c = np.array(closes, dtype=float)
    tr = np.full_like(h, np.nan)
    tr[0] = h[0] - l[0]
    for i in range(1, len(h)):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    return ema(tr, period)


def rsi(data: List[float] | np.ndarray, period: int = 14) -> np.ndarray:
    """Relative Strength Index - from vnpy ArrayManager / ta library.

    Used for overbought/oversold confirmation in multi-timeframe strategies.
    """
    arr = np.array(data, dtype=float)
    result = np.full_like(arr, np.nan)
    if len(arr) < period + 1:
        return result

    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period + 1, len(arr)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        if avg_loss == 0:
            result[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100.0 - (100.0 / (1.0 + rs))

    return result


def bollinger_bands(
    data: List[float] | np.ndarray, period: int = 20, num_std: float = 2.0
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bollinger Bands - from vnpy boll_channel_strategy / ta library.

    Returns (upper, middle, lower) bands.
    Used for mean-reversion entries and volatility breakout detection.
    """
    arr = np.array(data, dtype=float)
    middle = sma(arr, period)
    std_dev = np.full_like(arr, np.nan)
    for i in range(period - 1, len(arr)):
        std_dev[i] = np.std(arr[i - period + 1:i + 1])
    upper = middle + num_std * std_dev
    lower = middle - num_std * std_dev
    return upper, middle, lower


def keltner_channel(
    highs: List[float], lows: List[float], closes: List[float],
    period: int = 20, multiplier: float = 1.5
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Keltner Channel - from vnpy KingKeltnerStrategy.

    Uses EMA + ATR for adaptive bands. More responsive than Bollinger Bands
    for trend-following CTA strategies.
    Returns (upper, middle, lower).
    """
    c = np.array(closes, dtype=float)
    middle = ema(c, period)
    atr_vals = atr(highs, lows, closes, period)
    upper = middle + multiplier * atr_vals
    lower = middle - multiplier * atr_vals
    return upper, middle, lower


def macd(
    data: List[float] | np.ndarray,
    fast_period: int = 12, slow_period: int = 26, signal_period: int = 9
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MACD - standard implementation across all quant projects.

    Returns (macd_line, signal_line, histogram).
    """
    arr = np.array(data, dtype=float)
    fast_ema = ema(arr, fast_period)
    slow_ema = ema(arr, slow_period)
    macd_line = fast_ema - slow_ema
    # Signal line: EMA of MACD line (only valid portion)
    valid_macd = macd_line[~np.isnan(macd_line)]
    if len(valid_macd) < signal_period:
        signal_line = np.full_like(macd_line, np.nan)
    else:
        signal_line = ema(macd_line[~np.isnan(macd_line)], signal_period)
        # Pad signal_line to match macd_line length
        pad_len = len(macd_line) - len(signal_line)
        signal_line = np.concatenate([np.full(pad_len, np.nan), signal_line])
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def stochastic(
    highs: List[float], lows: List[float], closes: List[float],
    k_period: int = 9, d_period: int = 3
) -> Tuple[np.ndarray, np.ndarray]:
    """Stochastic Oscillator - from backtrader / quant-trading.

    Returns (%K, %D).
    Used for momentum confirmation and divergence detection.
    """
    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)
    c = np.array(closes, dtype=float)

    k_line = np.full_like(c, np.nan)
    for i in range(k_period - 1, len(c)):
        hh = np.max(h[i - k_period + 1:i + 1])
        ll = np.min(l[i - k_period + 1:i + 1])
        if hh == ll:
            k_line[i] = 50.0
        else:
            k_line[i] = (c[i] - ll) / (hh - ll) * 100.0

    d_line = sma(k_line[~np.isnan(k_line)], d_period)
    pad_len = len(k_line) - len(d_line)
    d_line = np.concatenate([np.full(pad_len, np.nan), d_line])
    return k_line, d_line


def adx(
    highs: List[float], lows: List[float], closes: List[float],
    period: int = 14
) -> np.ndarray:
    """Average Directional Index - from ta library / backtrader.

    Measures trend strength regardless of direction.
    ADX > 25 = strong trend, ADX < 20 = ranging market.
    """
    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)
    c = np.array(closes, dtype=float)

    # True Range
    tr = np.full_like(h, np.nan)
    tr[0] = h[0] - l[0]
    for i in range(1, len(h)):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))

    # Directional Movement
    plus_dm = np.zeros_like(h)
    minus_dm = np.zeros_like(h)
    for i in range(1, len(h)):
        up_move = h[i] - h[i - 1]
        down_move = l[i - 1] - l[i]
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move

    # Smooth
    atr_vals = ema(tr, period)
    plus_di = 100 * ema(plus_dm, period) / atr_vals
    minus_di = 100 * ema(minus_dm, period) / atr_vals

    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    adx_vals = ema(dx, period)
    return adx_vals


def dual_thrust(
    highs: List[float], lows: List[float], closes: List[float],
    opens: List[float], lookback: int = 4, k_up: float = 0.5, k_down: float = 0.5
) -> Tuple[float, float]:
    """Dual Thrust range breakout - from vnpy dual_thrust_strategy.

    A classic CTA range breakout system. Calculates upper/lower breakout levels
    based on the N-day range with separate up/down coefficients.
    Returns (upper_bound, lower_bound).
    """
    h = np.array(highs[-lookback:], dtype=float)
    l = np.array(lows[-lookback:], dtype=float)
    c = np.array(closes[-lookback:], dtype=float)
    o = np.array(opens[-1:], dtype=float)

    hh = np.max(h)
    hc = np.max(c)
    lc = np.min(c)
    ll = np.min(l)

    range_val = max(hh - lc, hc - ll)
    upper = o[0] + k_up * range_val
    lower = o[0] - k_down * range_val
    return upper, lower


def williams_r(
    highs: List[float], lows: List[float], closes: List[float],
    period: int = 14
) -> np.ndarray:
    """Williams %R - momentum indicator from ta library.

    Range: -100 (oversold) to 0 (overbought).
    """
    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)
    c = np.array(closes, dtype=float)

    result = np.full_like(c, np.nan)
    for i in range(period - 1, len(c)):
        hh = np.max(h[i - period + 1:i + 1])
        ll = np.min(l[i - period + 1:i + 1])
        if hh == ll:
            result[i] = -50.0
        else:
            result[i] = (hh - c[i]) / (hh - ll) * -100.0
    return result


# ==================== 新增指标实现 ====================


def ichimoku_cloud(
    highs: List[float], lows: List[float], closes: List[float],
    tenkan_period: int = 9, kijun_period: int = 26,
    senkou_b_period: int = 52, displacement: int = 26
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Ichimoku Cloud（一目均衡表）- 经典趋势跟踪系统。

    组成部分:
    - tenkan_sen（转换线）: (9日最高 + 9日最低) / 2，短期动能
    - kijun_sen（基准线）: (26日最高 + 26日最低) / 2，中期趋势
    - senkou_span_a（先行带A）: (转换线 + 基准线) / 2，前移26日
    - senkou_span_b（先行带B）: (52日最高 + 52日最低) / 2，前移26日
    - chikou_span（迟行线）: 收盘价后移26日

    返回 (tenkan, kijun, span_a, span_b, chikou) 五个等长数组。
    """
    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)
    c = np.array(closes, dtype=float)
    n = len(c)

    # 辅助函数: 计算 (period内最高+最低)/2
    def _midpoint(data_h: np.ndarray, data_l: np.ndarray, period: int) -> np.ndarray:
        result = np.full_like(data_h, np.nan)
        for i in range(period - 1, len(data_h)):
            hh = np.max(data_h[i - period + 1:i + 1])
            ll = np.min(data_l[i - period + 1:i + 1])
            result[i] = (hh + ll) / 2.0
        return result

    tenkan = _midpoint(h, l, tenkan_period)    # 转换线
    kijun = _midpoint(h, l, kijun_period)       # 基准线

    # 先行带A = (转换线 + 基准线) / 2，前移displacement期
    span_a = np.full_like(c, np.nan)
    span_b = np.full_like(c, np.nan)
    for i in range(max(tenkan_period, kijun_period) - 1, n):
        # 注意：这里不真正前移，只标记计算位置
        # 实际使用时 span_a[i] 对应未来 displacement 期的位置
        t_val = tenkan[i] if not np.isnan(tenkan[i]) else np.nan
        k_val = kijun[i] if not np.isnan(kijun[i]) else np.nan
        if not np.isnan(t_val) and not np.isnan(k_val):
            span_a[i] = (t_val + k_val) / 2.0

    # 先行带B = (52日最高+最低)/2
    senkou_b_mid = _midpoint(h, l, senkou_b_period)
    for i in range(senkou_b_period - 1, n):
        if not np.isnan(senkou_b_mid[i]):
            span_b[i] = senkou_b_mid[i]

    # 迟行线 = 收盘价前移displacement期（简化：在当前位置放入过去displacement期的收盘价）
    chikou = np.full_like(c, np.nan)
    for i in range(displacement, n):
        chikou[i - displacement] = c[i]

    return tenkan, kijun, span_a, span_b, chikou


def volume_weighted_average_price(
    highs: List[float], lows: List[float], closes: List[float],
    volumes: List[float]
) -> np.ndarray:
    """VWAP（成交量加权平均价）- 机构常用基准价格。

    计算累计(典型价格 x 成交量) / 累计成交量。
    典型价格 = (最高 + 最低 + 收盘) / 3。
    价格在VWAP之上为多头区域，之下为空头区域。
    """
    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)
    c = np.array(closes, dtype=float)
    v = np.array(volumes, dtype=float)

    # 典型价格
    typical = (h + l + c) / 3.0
    cumulative_tp_vol = np.cumsum(typical * v)
    cumulative_vol = np.cumsum(v)

    # 避免除以零
    result = np.where(cumulative_vol > 0, cumulative_tp_vol / cumulative_vol, np.nan)
    return result


def on_balance_volume(
    closes: List[float], volumes: List[float]
) -> np.ndarray:
    """OBV（能量潮指标）- 量价关系分析。

    价格上涨时累加成交量，下跌时累减成交量。
    OBV上升+价格上升 = 多头确认；OBV背离价格 = 趋势可能反转。
    """
    c = np.array(closes, dtype=float)
    v = np.array(volumes, dtype=float)
    n = len(c)

    result = np.full(n, np.nan)
    if n < 2:
        return result

    result[0] = v[0]
    for i in range(1, n):
        if c[i] > c[i - 1]:
            result[i] = result[i - 1] + v[i]
        elif c[i] < c[i - 1]:
            result[i] = result[i - 1] - v[i]
        else:
            result[i] = result[i - 1]

    return result


def parabolic_sar(
    highs: List[float], lows: List[float],
    af_start: float = 0.02, af_max: float = 0.20, af_step: float = 0.02
) -> np.ndarray:
    """Parabolic SAR（抛物线止损反转指标）- 趋势跟踪止损系统。

    核心参数:
    - af_start: 初始加速因子
    - af_max: 最大加速因子
    - af_step: 加速因子递增步长

    SAR在价格之下为多头信号（持仓做多），SAR在价格之上为空头信号（持仓做空）。
    """
    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)
    n = len(h)

    if n < 2:
        return np.full(n, np.nan)

    sar = np.full(n, np.nan)

    # 初始化：假设前几根K线为上涨趋势
    is_long = True
    af = af_start
    ep = h[0]  # 极值点（上涨时为最高价，下跌时为最低价）
    sar[0] = l[0]  # 初始SAR

    for i in range(1, n):
        # 计算当前SAR
        sar[i] = sar[i - 1] + af * (ep - sar[i - 1])

        if is_long:
            # 多头状态：SAR不应高于前两根K线的最低价
            if i >= 2:
                sar[i] = min(sar[i], l[i - 1], l[i - 2])
            else:
                sar[i] = min(sar[i], l[i - 1])

            # 反转判断：最低价跌破SAR
            if l[i] < sar[i]:
                is_long = False
                sar[i] = ep  # 切换到前极值点
                ep = l[i]
                af = af_start
            else:
                # 更新极值和加速因子
                if h[i] > ep:
                    ep = h[i]
                    af = min(af + af_step, af_max)
        else:
            # 空头状态：SAR不应低于前两根K线的最高价
            if i >= 2:
                sar[i] = max(sar[i], h[i - 1], h[i - 2])
            else:
                sar[i] = max(sar[i], h[i - 1])

            # 反转判断：最高价突破SAR
            if h[i] > sar[i]:
                is_long = True
                sar[i] = ep  # 切换到前极值点
                ep = h[i]
                af = af_start
            else:
                # 更新极值和加速因子
                if l[i] < ep:
                    ep = l[i]
                    af = min(af + af_step, af_max)

    return sar


def donchian_channel(
    highs: List[float], lows: List[float], period: int = 20
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Donchian Channel（唐奇安通道）- 海龟交易法核心指标。

    计算过去period根K线的最高价和最低价形成的通道。
    - 上轨 = period内最高价
    - 下轨 = period内最低价
    - 中轨 = (上轨 + 下轨) / 2

    突破上轨做多，突破下轨做空。
    返回 (upper, middle, lower)。
    """
    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)
    n = len(h)

    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    middle = np.full(n, np.nan)

    for i in range(period - 1, n):
        upper[i] = np.max(h[i - period + 1:i + 1])
        lower[i] = np.min(l[i - period + 1:i + 1])
        middle[i] = (upper[i] + lower[i]) / 2.0

    return upper, middle, lower


def compute_latest_indicators(
    highs: List[float], lows: List[float], closes: List[float],
    opens: List[float] | None = None,
    volumes: List[float] | None = None,
) -> dict:
    """Compute all indicators for the latest bar - returns a dict of current values.

    This is the main entry point called by the rules engine to enrich
    ParsedImageSignal with additional computed indicators.
    """
    result: dict = {}

    if len(closes) < 2:
        return result

    # RSI
    rsi_vals = rsi(closes, 14)
    latest_rsi = rsi_vals[~np.isnan(rsi_vals)]
    if len(latest_rsi) > 0:
        result["rsi_14"] = float(latest_rsi[-1])

    # ATR
    atr_vals = atr(highs, lows, closes, 14)
    latest_atr = atr_vals[~np.isnan(atr_vals)]
    if len(latest_atr) > 0:
        result["atr_14"] = float(latest_atr[-1])

    # Bollinger Bands
    bb_upper, bb_mid, bb_lower = bollinger_bands(closes, 20, 2.0)
    latest_bb = bb_upper[~np.isnan(bb_upper)]
    if len(latest_bb) > 0:
        idx = np.where(~np.isnan(bb_upper))[0][-1]
        result["boll_upper"] = float(bb_upper[idx])
        result["boll_mid"] = float(bb_mid[idx])
        result["boll_lower"] = float(bb_lower[idx])

    # Keltner Channel
    kc_upper, kc_mid, kc_lower = keltner_channel(highs, lows, closes, 20, 1.5)
    latest_kc = kc_upper[~np.isnan(kc_upper)]
    if len(latest_kc) > 0:
        idx = np.where(~np.isnan(kc_upper))[0][-1]
        result["keltner_upper"] = float(kc_upper[idx])
        result["keltner_mid"] = float(kc_mid[idx])
        result["keltner_lower"] = float(kc_lower[idx])

    # ADX (trend strength)
    adx_vals = adx(highs, lows, closes, 14)
    latest_adx = adx_vals[~np.isnan(adx_vals)]
    if len(latest_adx) > 0:
        result["adx_14"] = float(latest_adx[-1])

    # Stochastic
    k_vals, d_vals = stochastic(highs, lows, closes, 9, 3)
    latest_k = k_vals[~np.isnan(k_vals)]
    if len(latest_k) > 0:
        idx = np.where(~np.isnan(k_vals))[0][-1]
        result["stoch_k"] = float(k_vals[idx])
        if not np.isnan(d_vals[idx]):
            result["stoch_d"] = float(d_vals[idx])

    # Dual Thrust (needs opens)
    if opens and len(opens) >= 5 and len(highs) >= 5:
        upper, lower = dual_thrust(highs, lows, closes, opens, lookback=4, k_up=0.5, k_down=0.5)
        result["dual_thrust_upper"] = float(upper)
        result["dual_thrust_lower"] = float(lower)

    # Williams %R
    wr_vals = williams_r(highs, lows, closes, 14)
    latest_wr = wr_vals[~np.isnan(wr_vals)]
    if len(latest_wr) > 0:
        result["williams_r"] = float(latest_wr[-1])

    # Volume-weighted analysis
    if volumes and len(volumes) > 20:
        vol_arr = np.array(volumes, dtype=float)
        vol_ma20 = np.mean(vol_arr[-20:])
        result["volume_ratio"] = float(vol_arr[-1] / vol_ma20) if vol_ma20 > 0 else 1.0

    # ==================== 新增指标 ====================

    # Ichimoku Cloud（一目均衡表）
    if len(highs) >= 52 and len(lows) >= 52 and len(closes) >= 52:
        tenkan, kijun, span_a, span_b, chikou = ichimoku_cloud(highs, lows, closes)
        idx_ic = np.where(~np.isnan(tenkan))[0]
        if len(idx_ic) > 0:
            i = idx_ic[-1]
            result["ichimoku_tenkan"] = float(tenkan[i])
            result["ichimoku_kijun"] = float(kijun[i]) if not np.isnan(kijun[i]) else None
            result["ichimoku_span_a"] = float(span_a[i]) if not np.isnan(span_a[i]) else None
            result["ichimoku_span_b"] = float(span_b[i]) if not np.isnan(span_b[i]) else None
            result["ichimoku_chikou"] = float(chikou[i]) if not np.isnan(chikou[i]) else None
            # 云带颜色判断：span_a > span_b 为多头云，反之为空头云
            if result["ichimoku_span_a"] is not None and result["ichimoku_span_b"] is not None:
                result["ichimoku_cloud_bullish"] = result["ichimoku_span_a"] > result["ichimoku_span_b"]

    # VWAP（成交量加权平均价）
    if volumes and len(volumes) >= 2 and len(closes) >= 2:
        vwap_vals = volume_weighted_average_price(highs, lows, closes, volumes)
        latest_vwap = vwap_vals[~np.isnan(vwap_vals)]
        if len(latest_vwap) > 0:
            result["vwap"] = float(latest_vwap[-1])

    # OBV（能量潮指标）
    if volumes and len(volumes) >= 2:
        obv_vals = on_balance_volume(closes, volumes)
        latest_obv = obv_vals[~np.isnan(obv_vals)]
        if len(latest_obv) > 0:
            result["obv"] = float(latest_obv[-1])

    # Parabolic SAR（抛物线止损反转指标）
    if len(highs) >= 5 and len(lows) >= 5:
        sar_vals = parabolic_sar(highs, lows)
        latest_sar = sar_vals[~np.isnan(sar_vals)]
        if len(latest_sar) > 0:
            result["parabolic_sar"] = float(latest_sar[-1])

    # Donchian Channel（唐奇安通道）
    if len(highs) >= 20 and len(lows) >= 20:
        dc_upper, dc_mid, dc_lower = donchian_channel(highs, lows, period=20)
        latest_dc = dc_upper[~np.isnan(dc_upper)]
        if len(latest_dc) > 0:
            idx_dc = np.where(~np.isnan(dc_upper))[0][-1]
            result["donchian_upper"] = float(dc_upper[idx_dc])
            result["donchian_mid"] = float(dc_mid[idx_dc])
            result["donchian_lower"] = float(dc_lower[idx_dc])

    return result
