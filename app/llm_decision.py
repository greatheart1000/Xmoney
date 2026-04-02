from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from .models import DecisionRequest, DecisionResult, SignalAction, Trend
from .rules import make_decision


RULES_FILE = Path("config/user_rules.md")


def _load_user_rules() -> str:
    override = os.getenv("USER_RULES_TEXT")
    if override:
        return override
    if RULES_FILE.exists():
        return RULES_FILE.read_text(encoding="utf-8")
    return ""


def _build_prompt(req: DecisionRequest) -> str:
    user_rules = _load_user_rules()
    payload = req.model_dump(mode="json")
    return (
        "你是期货AI决策引擎。请以80%权重执行大模型分析，20%交给规则风控。"
        "必须遵循以下用户规则：\n"
        f"{user_rules}\n\n"
        "输入JSON如下：\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n\n"
        "请直接输出JSON，字段必须完整：\n"
        "{"
        '"trend":"bullish|bearish|neutral",'
        '"action":"wait|long|short|hold_long|hold_short|reduce_long|reduce_short",'
        '"reason":["..."],'
        '"entry_zone":[0,0],'
        '"stop_loss":0,'
        '"take_profit":[0,0],'
        '"expected_remaining_bars":0,'
        '"expected_total_move_pct":0.0,'
        '"confidence":0.0'
        "}"
    )


def _call_gemini(prompt: str) -> Dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY")

    import google.generativeai as genai

    genai.configure(api_key=api_key)
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
    model = genai.GenerativeModel(model_name=model_name)
    resp = model.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json", "temperature": 0.2},
    )
    return json.loads(resp.text)


def _to_decision_result(data: Dict[str, Any]) -> DecisionResult:
    normalized = {
        "trend": data.get("trend", "neutral"),
        "action": data.get("action", "wait"),
        "reason": data.get("reason", ["LLM未返回原因"]),
        "entry_zone": data.get("entry_zone"),
        "stop_loss": data.get("stop_loss"),
        "take_profit": data.get("take_profit"),
        "expected_remaining_bars": data.get("expected_remaining_bars"),
        "expected_total_move_pct": data.get("expected_total_move_pct"),
        "confidence": float(data.get("confidence", 0.6)),
    }
    return DecisionResult(**normalized)


def hybrid_decision(req: DecisionRequest) -> DecisionResult:
    rule_result = make_decision(req)

    try:
        llm_raw = _call_gemini(_build_prompt(req))
        llm_result = _to_decision_result(llm_raw)
    except Exception:
        fallback_reason = ["LLM不可用，回退到规则引擎"] + rule_result.reason
        return DecisionResult(**{**rule_result.model_dump(), "reason": fallback_reason})

    # 20%规则风控：若规则要求观望，不允许LLM逆向强开仓
    risky_open = llm_result.action in {SignalAction.long, SignalAction.short}
    if rule_result.action == SignalAction.wait and risky_open:
        return DecisionResult(
            trend=Trend.neutral,
            action=SignalAction.wait,
            reason=["规则风控拦截：LLM开仓信号未通过20%风控层"] + llm_result.reason + rule_result.reason,
            entry_zone=None,
            stop_loss=None,
            take_profit=None,
            expected_remaining_bars=llm_result.expected_remaining_bars,
            expected_total_move_pct=llm_result.expected_total_move_pct,
            confidence=min(llm_result.confidence, rule_result.confidence),
        )

    # 80% LLM + 20%规则校验说明
    merged_reason = ["决策权重：LLM 80% + 规则风控 20%"] + llm_result.reason
    if rule_result.action != llm_result.action:
        merged_reason.append(f"规则引擎建议: {rule_result.action.value}")

    return DecisionResult(**{**llm_result.model_dump(), "reason": merged_reason})
