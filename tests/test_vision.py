"""视觉解析模块测试"""
import pytest

from app.vision import _mock_parse, fuse_parsed_signals, PROMPT
from app.models import ParsedImageSignal


def _parsed(symbol: str, timeframe: str, close: float, confidence: float, **overrides) -> ParsedImageSignal:
    """构造测试用 ParsedImageSignal"""
    defaults = {
        "symbol": symbol,
        "timeframe": timeframe,
        "close": close,
        "ma5": close - 1,
        "ma10": close - 2,
        "ma20": close - 3,
        "ma40": close - 4,
        "ma60": close - 5,
        "macd_diff": -1.0,
        "macd_dea": -0.8,
        "macd_hist": -0.2,
        "volume": 1000,
        "open_interest": 800000,
        "support_levels": [close - 10],
        "resistance_levels": [close + 10],
        "confidence": confidence,
    }
    defaults.update(overrides)
    return ParsedImageSignal(**defaults)


def test_mock_parse_returns_valid_signal():
    """测试mock解析返回有效信号"""
    signal = _mock_parse("SA605", "5m")
    assert isinstance(signal, ParsedImageSignal)
    assert signal.symbol == "SA605"
    assert signal.timeframe == "5m"
    assert signal.close > 0
    assert 0 <= signal.confidence <= 1.0
    assert len(signal.support_levels) > 0
    assert len(signal.resistance_levels) > 0


def test_mock_parse_sa_symbol():
    """测试SA品种mock数据"""
    signal = _mock_parse("SA605", "15m")
    assert signal.close == 1180.0
    assert signal.symbol == "SA605"


def test_mock_parse_non_sa_symbol():
    """测试非SA品种mock数据"""
    signal = _mock_parse("FG605", "5m")
    assert signal.close == 1021.0
    assert signal.symbol == "FG605"


def test_mock_parse_has_all_fields():
    """测试mock解析返回所有必要字段"""
    signal = _mock_parse("SA605", "5m")
    assert signal.ma5 > 0
    assert signal.ma10 > 0
    assert signal.ma20 > 0
    assert signal.ma40 > 0
    assert signal.ma60 > 0
    assert signal.macd_diff != 0
    assert signal.volume > 0
    assert signal.open_interest > 0
    assert signal.swing_high is not None
    assert signal.swing_low is not None
    assert signal.raw_features.get("source") == "mock_vision"


def test_fuse_signals_averages_numeric_fields():
    """测试融合函数平均数值字段"""
    signals = [
        _parsed("SA605", "5m", 100, 0.6),
        _parsed("SA605", "15m", 200, 0.8),
    ]
    fused = fuse_parsed_signals(signals)
    # 权重: 5m=1.0, 15m=1.8, total=2.8
    # wavg close = (100*1.0 + 200*1.8) / 2.8 = (100 + 360) / 2.8 = 164.29
    expected_close = (100 * 1.0 + 200 * 1.8) / 2.8
    assert abs(fused.close - expected_close) < 0.01


def test_fuse_signals_dominant_timeframe():
    """测试主导时间框架选择"""
    signals = [
        _parsed("SA605", "5m", 100, 0.6),
        _parsed("SA605", "15m", 110, 0.7),
        _parsed("SA605", "30m", 120, 0.8),
    ]
    fused = fuse_parsed_signals(signals)
    # 30m has the highest weight (2.6)
    assert fused.timeframe == "30m"


def test_fuse_signals_60m_dominant():
    """测试60m时间框架为主导"""
    signals = [
        _parsed("SA605", "5m", 100, 0.6),
        _parsed("SA605", "60m", 120, 0.8),
    ]
    fused = fuse_parsed_signals(signals)
    assert fused.timeframe == "60m"


def test_fuse_signals_merges_support_resistance():
    """测试支撑阻力位合并"""
    signals = [
        _parsed("SA605", "5m", 100, 0.6, support_levels=[90, 95], resistance_levels=[110, 115]),
        _parsed("SA605", "15m", 100, 0.6, support_levels=[88, 95], resistance_levels=[112, 118]),
    ]
    fused = fuse_parsed_signals(signals)
    # 合并去重后排序
    assert 90 in fused.support_levels
    assert 95 in fused.support_levels
    assert 88 in fused.support_levels
    assert fused.support_levels == sorted(fused.support_levels)
    assert 110 in fused.resistance_levels
    assert 118 in fused.resistance_levels
    assert fused.resistance_levels == sorted(fused.resistance_levels)


def test_fuse_signals_single_input():
    """测试单时间框架输入"""
    signals = [
        _parsed("SA605", "5m", 100, 0.6),
    ]
    fused = fuse_parsed_signals(signals)
    assert fused.symbol == "SA605"
    assert fused.timeframe == "5m"
    assert fused.close == 100
    assert fused.confidence == 0.6


def test_fuse_signals_empty_input_raises():
    """测试空输入抛出异常"""
    with pytest.raises(ValueError, match="signals must not be empty"):
        fuse_parsed_signals([])


def test_fuse_signals_confidence_is_average():
    """测试融合后置信度为平均值"""
    signals = [
        _parsed("SA605", "5m", 100, 0.5),
        _parsed("SA605", "15m", 100, 0.7),
        _parsed("SA605", "30m", 100, 0.9),
    ]
    fused = fuse_parsed_signals(signals)
    # confidence = min(1.0, (0.5 + 0.7 + 0.9) / 3)
    expected = (0.5 + 0.7 + 0.9) / 3
    assert abs(fused.confidence - expected) < 0.01


def test_fuse_signals_swing_high_is_max():
    """测试融合后swing_high取最大值"""
    signals = [
        _parsed("SA605", "5m", 100, 0.6, swing_high=110),
        _parsed("SA605", "15m", 100, 0.6, swing_high=120),
    ]
    fused = fuse_parsed_signals(signals)
    assert fused.swing_high == 120


def test_fuse_signals_swing_low_is_min():
    """测试融合后swing_low取最小值"""
    signals = [
        _parsed("SA605", "5m", 100, 0.6, swing_low=90),
        _parsed("SA605", "15m", 100, 0.6, swing_low=85),
    ]
    fused = fuse_parsed_signals(signals)
    assert fused.swing_low == 85


def test_fuse_signals_chart_patterns_merged():
    """测试融合后图表形态合并去重"""
    signals = [
        _parsed("SA605", "5m", 100, 0.6, chart_patterns=["down_channel", "lower_highs"]),
        _parsed("SA605", "15m", 100, 0.6, chart_patterns=["down_channel", "double_top"]),
    ]
    fused = fuse_parsed_signals(signals)
    patterns = set(fused.chart_patterns)
    assert "down_channel" in patterns
    assert "lower_highs" in patterns
    assert "double_top" in patterns
    assert len(patterns) == 3


def test_fuse_signals_raw_features_metadata():
    """测试融合后raw_features包含元数据"""
    signals = [
        _parsed("SA605", "5m", 100, 0.6),
        _parsed("SA605", "15m", 100, 0.6),
    ]
    fused = fuse_parsed_signals(signals)
    assert fused.raw_features["source"] == "multi_image_fusion"
    assert "5m" in fused.raw_features["frames"]
    assert "15m" in fused.raw_features["frames"]
    assert fused.raw_features["count"] == "2"


def test_prompt_is_chinese():
    """测试视觉解析提示词包含中文"""
    assert "期货" in PROMPT
    assert "JSON" in PROMPT
