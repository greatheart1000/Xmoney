from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple

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
        "你是期货AI决策引擎。请严格按用户规则分析，并输出可执行JSON。"
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


def _call_deepseek(prompt: str) -> Dict[str, Any]:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("Missing DEEPSEEK_API_KEY")

    url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/chat/completions")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": "你是专业期货分析AI，请只输出JSON。"},
            {"role": "user", "content": prompt},
        ],
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    content = body["choices"][0]["message"]["content"]
    return json.loads(content)


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


def _collect_model_decisions(req: DecisionRequest) -> List[Tuple[str, DecisionResult]]:
    prompt = _build_prompt(req)
    outputs: List[Tuple[str, DecisionResult]] = []

    try:
        outputs.append(("gemini", _to_decision_result(_call_gemini(prompt))))
    except Exception:
        pass

    try:
        outputs.append(("deepseek", _to_decision_result(_call_deepseek(prompt))))
    except Exception:
        pass

    return outputs


def _ensemble_decision(model_outputs: List[Tuple[str, DecisionResult]]) -> DecisionResult:
    # 先按action投票；平票时取最高置信度
    vote: Dict[SignalAction, int] = {}
    for _, d in model_outputs:
        vote[d.action] = vote.get(d.action, 0) + 1

    best_action = max(vote, key=vote.get)
    candidates = [d for _, d in model_outputs if d.action == best_action]
    chosen = max(candidates, key=lambda x: x.confidence)

    model_names = ", ".join(name for name, _ in model_outputs)
    merged_reason = [f"模型共识来源: {model_names}"] + chosen.reason
    avg_conf = sum(d.confidence for _, d in model_outputs) / len(model_outputs)

    return DecisionResult(**{**chosen.model_dump(), "reason": merged_reason, "confidence": avg_conf})


def hybrid_decision(req: DecisionRequest) -> DecisionResult:
    rule_result = make_decision(req)

    model_outputs = _collect_model_decisions(req)
    if not model_outputs:
        fallback_reason = ["LLM不可用（Gemini/DeepSeek均不可用），回退到规则引擎"] + rule_result.reason
        return DecisionResult(**{**rule_result.model_dump(), "reason": fallback_reason})

    llm_result = _ensemble_decision(model_outputs)

    # 双模型主分析（80%）+规则风控（20%）
    risky_open = llm_result.action in {SignalAction.long, SignalAction.short}
    if rule_result.action == SignalAction.wait and risky_open:
        return DecisionResult(
            trend=Trend.neutral,
            action=SignalAction.wait,
            reason=["规则风控拦截：双模型开仓信号未通过20%风控层"] + llm_result.reason + rule_result.reason,
            entry_zone=None,
            stop_loss=None,
            take_profit=None,
            expected_remaining_bars=llm_result.expected_remaining_bars,
            expected_total_move_pct=llm_result.expected_total_move_pct,
            confidence=min(llm_result.confidence, rule_result.confidence),
        )

    merged_reason = ["决策权重：双模型(80%) + 规则风控(20%)"] + llm_result.reason
    if rule_result.action != llm_result.action:
        merged_reason.append(f"规则引擎建议: {rule_result.action.value}")

    return DecisionResult(**{**llm_result.model_dump(), "reason": merged_reason})
