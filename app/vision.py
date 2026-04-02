from __future__ import annotations

import json
import os
from typing import Any, Dict

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
