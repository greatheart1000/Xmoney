from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from .models import ParsedImageSignal


PROMPT = """
你是期货技术图像解析器。请基于图像识别输出JSON，字段必须完整：
{
  "symbol": "",
  "timeframe": "5m|15m|30m|60m",
  "close": 0,
  "ma5": 0,
  "ma10": 0,
  "ma20": 0,
  "ma40": 0,
  "ma60": 0,
  "macd_diff": 0,
  "macd_dea": 0,
  "macd_hist": 0,
  "volume": 0,
  "open_interest": 0,
  "support_levels": [0,0],
  "resistance_levels": [0,0],
  "swing_high": 0,
  "swing_low": 0,
  "historical_support_levels": [0,0],
  "historical_resistance_levels": [0,0],
  "leg_start_price": 0,
  "leg_elapsed_bars": 0,
  "avg_up_leg_bars": 0,
  "avg_down_leg_bars": 0,
  "avg_up_leg_move_pct": 0.0,
  "avg_down_leg_move_pct": 0.0,
  "chart_patterns": ["pattern_a", "pattern_b"],
  "confidence": 0.0,
  "raw_features": {"note": ""}
}
只返回JSON，不要解释。
""".strip()


def _mock_parse(symbol: str, timeframe: str) -> ParsedImageSignal:
    # 基于用户样例的保守默认值，方便本地联调。
    return ParsedImageSignal(
        symbol=symbol,
        timeframe=timeframe,
        close=1180.0 if symbol.upper().startswith("SA") else 1021.0,
        ma5=1181.2 if symbol.upper().startswith("SA") else 1021.0,
        ma10=1183.5 if symbol.upper().startswith("SA") else 1023.6,
        ma20=1184.8 if symbol.upper().startswith("SA") else 1023.3,
        ma40=1189.0 if symbol.upper().startswith("SA") else 1025.9,
        ma60=1193.0 if symbol.upper().startswith("SA") else 1029.1,
        macd_diff=-2.8 if symbol.upper().startswith("SA") else -1.7,
        macd_dea=-2.6 if symbol.upper().startswith("SA") else -1.5,
        macd_hist=-0.4 if symbol.upper().startswith("SA") else -0.5,
        volume=5253.0,
        open_interest=806330.0 if symbol.upper().startswith("SA") else 1072406.0,
        support_levels=[1177.0, 1170.0] if symbol.upper().startswith("SA") else [1017.0, 1010.0],
        resistance_levels=[1189.0, 1198.0] if symbol.upper().startswith("SA") else [1024.0, 1032.0],
        swing_high=1198.0 if symbol.upper().startswith("SA") else 1048.0,
        swing_low=1177.0 if symbol.upper().startswith("SA") else 1017.0,
        historical_support_levels=[1177.0, 1170.0] if symbol.upper().startswith("SA") else [1017.0, 1010.0],
        historical_resistance_levels=[1198.0, 1204.0] if symbol.upper().startswith("SA") else [1032.0, 1048.0],
        leg_start_price=1198.0 if symbol.upper().startswith("SA") else 1048.0,
        leg_elapsed_bars=26,
        avg_up_leg_bars=20,
        avg_down_leg_bars=28,
        avg_up_leg_move_pct=0.018,
        avg_down_leg_move_pct=0.026,
        chart_patterns=["down_channel", "lower_highs"],
        confidence=0.72,
        raw_features={"source": "mock_vision"},
    )


def parse_image_with_gemini(image_bytes: bytes, symbol: str, timeframe: str) -> ParsedImageSignal:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return _mock_parse(symbol, timeframe)

    import google.generativeai as genai

    genai.configure(api_key=api_key)
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
    model = genai.GenerativeModel(model_name=model_name)
    response = model.generate_content(
        [
            {"mime_type": "image/png", "data": image_bytes},
            PROMPT,
        ],
        generation_config={"response_mime_type": "application/json", "temperature": 0.1},
    )

    text = response.text.strip()
    data: Dict[str, Any] = json.loads(text)

    # 容错：优先以请求参数覆盖symbol/timeframe
    data["symbol"] = symbol
    data["timeframe"] = timeframe
    return ParsedImageSignal(**data)


def parse_images_with_gemini(image_payloads: Sequence[Tuple[bytes, str]], symbol: str) -> List[ParsedImageSignal]:
    return [
        parse_image_with_gemini(image_bytes=image_bytes, symbol=symbol, timeframe=timeframe)
        for image_bytes, timeframe in image_payloads
    ]


def _normalize_timeframe(timeframe: str) -> str:
    return timeframe.strip().lower()


def fuse_parsed_signals(signals: Iterable[ParsedImageSignal]) -> ParsedImageSignal:
    items = list(signals)
    if not items:
        raise ValueError("signals must not be empty")

    weights = {"5m": 1.0, "15m": 1.8, "30m": 2.6, "60m": 3.4}
    normalized_frames = [_normalize_timeframe(s.timeframe) for s in items]
    total_w = sum(weights.get(tf, 1.0) for tf in normalized_frames)

    def wavg(attr: str) -> float:
        return sum(getattr(s, attr) * weights.get(tf, 1.0) for s, tf in zip(items, normalized_frames)) / total_w

    def flatten_unique(values: Iterable[List[float]]) -> List[float]:
        flattened = {float(v) for lst in values for v in lst}
        return sorted(flattened)

    dominant = max(normalized_frames, key=lambda tf: weights.get(tf, 1.0))

    return ParsedImageSignal(
        symbol=items[0].symbol,
        timeframe=dominant,
        close=wavg("close"),
        ma5=wavg("ma5"),
        ma10=wavg("ma10"),
        ma20=wavg("ma20"),
        ma40=wavg("ma40"),
        ma60=wavg("ma60"),
        macd_diff=wavg("macd_diff"),
        macd_dea=wavg("macd_dea"),
        macd_hist=wavg("macd_hist"),
        volume=wavg("volume"),
        open_interest=wavg("open_interest"),
        support_levels=flatten_unique(s.support_levels for s in items),
        resistance_levels=flatten_unique(s.resistance_levels for s in items),
        historical_support_levels=flatten_unique(s.historical_support_levels for s in items),
        historical_resistance_levels=flatten_unique(s.historical_resistance_levels for s in items),
        swing_high=max((s.swing_high for s in items if s.swing_high is not None), default=None),
        swing_low=min((s.swing_low for s in items if s.swing_low is not None), default=None),
        leg_start_price=wavg("leg_start_price") if all(s.leg_start_price is not None for s in items) else None,
        leg_elapsed_bars=round(wavg("leg_elapsed_bars")) if all(s.leg_elapsed_bars is not None for s in items) else None,
        avg_up_leg_bars=round(wavg("avg_up_leg_bars")) if all(s.avg_up_leg_bars is not None for s in items) else None,
        avg_down_leg_bars=round(wavg("avg_down_leg_bars")) if all(s.avg_down_leg_bars is not None for s in items) else None,
        avg_up_leg_move_pct=wavg("avg_up_leg_move_pct") if all(s.avg_up_leg_move_pct is not None for s in items) else None,
        avg_down_leg_move_pct=wavg("avg_down_leg_move_pct") if all(s.avg_down_leg_move_pct is not None for s in items) else None,
        chart_patterns=sorted({pattern for s in items for pattern in s.chart_patterns}),
        confidence=min(1.0, sum(s.confidence for s in items) / len(items)),
        raw_features={
            "source": "multi_image_fusion",
            "frames": ",".join(normalized_frames),
            "count": str(len(items)),
        },
    )
