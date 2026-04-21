from __future__ import annotations

import base64
import json
import os
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import DecisionRequest, DecisionResult, SignalAction, Trend
from .risk_manager import assess_full_risk
from .rules import make_decision


RULES_FILE = Path("config/user_rules.md")
STRATEGY_PROFILES_FILE = Path("config/strategy_profiles.json")

DEFAULT_STRATEGY_PROFILES: Dict[str, Dict[str, Any]] = {
    "short_term": {
        "name": "短线交易",
        "description": "15m/30m 优先，信号确认更快、止损更紧。",
        "rules": [
            "更重视15m触发与30m方向一致性。",
            "止损放在最近结构位外侧，严格执行。",
        ],
    },
    "swing": {
        "name": "波段交易",
        "description": "30m/1h 优先，持仓周期3-10天。",
        "rules": [
            "更关注MA20/MA40与MACD零轴持续性。",
            "采用分批止盈：0.618先减仓，时间窗1.0/1.618再评估。",
        ],
    },
    "long_term": {
        "name": "长线交易",
        "description": "大级别趋势优先，容忍回撤，减少频繁交易。",
        "rules": [
            "优先服从大级别方向，逆势信号仅用于风控。",
            "关注趋势失效再减仓/清仓。",
        ],
    },
}


def _load_user_rules() -> str:
    override = os.getenv("USER_RULES_TEXT")
    if override:
        return override
    if RULES_FILE.exists():
        return RULES_FILE.read_text(encoding="utf-8")
    return ""


def _load_strategy_profiles() -> Dict[str, Dict[str, Any]]:
    override = os.getenv("USER_STRATEGY_PROFILES_JSON")
    if override:
        try:
            parsed = json.loads(override)
            if isinstance(parsed, dict) and parsed:
                return parsed
        except Exception:
            pass
    if STRATEGY_PROFILES_FILE.exists():
        try:
            parsed = json.loads(STRATEGY_PROFILES_FILE.read_text(encoding="utf-8"))
            if isinstance(parsed, dict) and parsed:
                return parsed
        except Exception:
            pass
    return DEFAULT_STRATEGY_PROFILES


def _render_strategy_rules(strategy_name: str, strategy_profile: Optional[Dict[str, Any]]) -> str:
    if not strategy_profile:
        return ""
    title = strategy_profile.get("name", strategy_name)
    description = strategy_profile.get("description", "")
    rules = strategy_profile.get("rules", [])
    lines = [f"策略模式: {strategy_name}（{title}）"]
    if description:
        lines.append(f"策略描述: {description}")
    if isinstance(rules, list):
        for i, rule in enumerate(rules, start=1):
            lines.append(f"{i}. {rule}")
    return "\n".join(lines)


def _build_prompt(
    req: DecisionRequest,
    strategy_name: str = "default",
    strategy_profile: Optional[Dict[str, Any]] = None,
) -> str:
    user_rules = _load_user_rules()
    strategy_rules = _render_strategy_rules(strategy_name, strategy_profile)
    payload = req.model_dump(mode="json")
    return (
        "你是期货AI决策引擎。请严格按用户规则分析，并输出可执行JSON。"
        "分析必须覆盖："
        "1) 先看文华商品指数(30m->15m)过滤方向，再看单品种；"
        "2) MA、MACD、成交量、持仓量；"
        "3) 图形形态(chart_patterns)与关键结构位；"
        "4) 价格斐波那契回调(0.236/0.382/0.5/0.618/0.786)；"
        "5) 时间斐波那契窗(0.618/1.0/1.618)与波段空间估计；"
        "6) RSI超买超卖(>80/<20)与KDJ背离确认；"
        "7) 布林带/肯特纳通道突破与回归信号；"
        "8) ADX趋势强度(>25趋势有效,<20震荡市)。"
        "同一市场可因策略周期不同得到不同建议，请按当前策略模式输出。"
        "必须遵循以下用户规则：\n"
        f"{user_rules}\n\n"
        "必须遵循以下策略配置：\n"
        f"{strategy_rules}\n\n"
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
        '"confidence":0.0,'
        '"risk_level":"low|medium|high|extreme",'
        '"trend_strength":"strong|moderate|weak|ranging"'
        "}"
    )


def _build_vision_decision_prompt(
    req: DecisionRequest,
    timeframe: str,
    strategy_name: str = "default",
    strategy_profile: Optional[Dict[str, Any]] = None,
) -> str:
    user_rules = _load_user_rules()
    strategy_rules = _render_strategy_rules(strategy_name, strategy_profile)
    return (
        "你是期货AI决策引擎。你将直接看K线图并按固定量化规则做交易决策。"
        "必须按以下顺序判断："
        "1) 先看文华商品指数30m，再看15m确认；"
        "2) 再看该品种图上MA/MACD/成交量/持仓量；"
        "3) 识别形态与关键结构位；"
        "4) 结合价格斐波那契回调位(0.236/0.382/0.5/0.618/0.786)；"
        "5) 结合斐波那契时间窗(0.618/1.0/1.618)估计剩余bar与波段空间。"
        "你必须给出交易动作：wait|long|short|hold_long|hold_short|reduce_long|reduce_short。"
        f"当前持仓: {req.position}。图表周期: {timeframe}。"
        f"市场过滤30m: {req.market_regime_30m.value}, 15m: {req.market_regime_15m.value}。"
        f"是否要求市场过滤: {req.require_market_filter}。"
        "必须遵循以下用户规则：\n"
        f"{user_rules}\n\n"
        "必须遵循以下策略配置：\n"
        f"{strategy_rules}\n\n"
        "只输出JSON，字段必须完整：\n"
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
        request_options={"timeout": 25},
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


def _call_gemini_vision_decision(prompt: str, image_bytes: bytes) -> Dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY")

    import google.generativeai as genai

    genai.configure(api_key=api_key)
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
    model = genai.GenerativeModel(model_name=model_name)
    resp = model.generate_content(
        [{"mime_type": "image/png", "data": image_bytes}, prompt],
        generation_config={"response_mime_type": "application/json", "temperature": 0.2},
        request_options={"timeout": 25},
    )
    return json.loads(resp.text)


def _call_deepseek_vision_decision(prompt: str, image_bytes: bytes) -> Dict[str, Any]:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("Missing DEEPSEEK_API_KEY")

    url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/chat/completions")
    model = os.getenv("DEEPSEEK_VL_MODEL", os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))
    encoded = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": "你是期货图像决策AI，请严格按规则，只输出JSON。"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
                ],
            },
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
        "risk_level": data.get("risk_level"),
        "trend_strength": data.get("trend_strength"),
    }
    return DecisionResult(**normalized)


def _with_decision_report(result: DecisionResult) -> DecisionResult:
    action = result.action.value if isinstance(result.action, SignalAction) else str(result.action)
    trend = result.trend.value if isinstance(result.trend, Trend) else str(result.trend)
    reason_lines = "\n".join(f"- {item}" for item in result.reason[:6]) if result.reason else "- 无"
    result.ai_decision_report = (
        "【AI 交易助手】\n"
        f"趋势: {trend}\n"
        f"动作: {action}\n"
        f"置信度: {result.confidence:.2f}\n"
        f"理由:\n{reason_lines}"
    )
    return result


def _collect_model_decisions(
    req: DecisionRequest,
    strategy_name: str = "default",
    strategy_profile: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, DecisionResult]]:
    prompt = _build_prompt(req, strategy_name=strategy_name, strategy_profile=strategy_profile)
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


def _collect_vision_model_decisions(
    req: DecisionRequest,
    image_payloads: List[Tuple[bytes, str]],
    strategy_name: str = "default",
    strategy_profile: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, DecisionResult]]:
    outputs: List[Tuple[str, DecisionResult]] = []
    for image_bytes, timeframe in image_payloads:
        prompt = _build_vision_decision_prompt(
            req,
            timeframe=timeframe,
            strategy_name=strategy_name,
            strategy_profile=strategy_profile,
        )
        try:
            outputs.append((f"gemini_vision_{timeframe}", _to_decision_result(_call_gemini_vision_decision(prompt, image_bytes))))
        except Exception:
            pass
        try:
            outputs.append((f"deepseek_vision_{timeframe}", _to_decision_result(_call_deepseek_vision_decision(prompt, image_bytes))))
        except Exception:
            pass
    return outputs


def _ensemble_decision(model_outputs: List[Tuple[str, DecisionResult]]) -> DecisionResult:
    vote: Dict[SignalAction, int] = {}
    for _, d in model_outputs:
        vote[d.action] = vote.get(d.action, 0) + 1

    best_action = max(vote, key=vote.get)
    candidates = [d for _, d in model_outputs if d.action == best_action]
    chosen = max(candidates, key=lambda x: x.confidence)

    model_names = ", ".join(name for name, _ in model_outputs)
    merged_reason = [f"模型共识来源: {model_names}"] + chosen.reason
    avg_conf = sum(d.confidence for _, d in model_outputs) / len(model_outputs)

    actions = {d.action for _, d in model_outputs}
    if len(actions) > 1:
        return _with_decision_report(
            DecisionResult(
                trend=chosen.trend,
                action=SignalAction.wait,
                reason=["多模型交叉验证存在分歧，先观望等待二次确认"] + merged_reason,
                expected_remaining_bars=chosen.expected_remaining_bars,
                expected_total_move_pct=chosen.expected_total_move_pct,
                confidence=max(0.35, avg_conf - 0.15),
            )
        )

    return _with_decision_report(
        DecisionResult(**{**chosen.model_dump(), "reason": merged_reason, "confidence": avg_conf})
    )


def hybrid_decision(
    req: DecisionRequest,
    strategy_name: str = "default",
    strategy_profile: Optional[Dict[str, Any]] = None,
) -> DecisionResult:
    rule_result = make_decision(req)
    risk = assess_full_risk(req)

    model_outputs = _collect_model_decisions(req, strategy_name=strategy_name, strategy_profile=strategy_profile)
    if not model_outputs:
        fallback_reason = [f"策略[{strategy_name}] LLM不可用（Gemini/DeepSeek均不可用），回退到规则引擎"] + rule_result.reason
        result = _with_decision_report(DecisionResult(**{**rule_result.model_dump(), "reason": fallback_reason}))
        result.risk_level = risk.risk_level.value
        if risk.position_sizing:
            result.position_sizing = risk.position_sizing.suggested_lots
        if risk.stop_config:
            result.trailing_stop = risk.stop_config.trailing_stop
        if risk.warnings and not result.trend_strength:
            result.trend_strength = risk.warnings[0]
        return result

    llm_result = _ensemble_decision(model_outputs)
    risky_open = llm_result.action in {SignalAction.long, SignalAction.short}
    if rule_result.action == SignalAction.wait and risky_open:
        return _with_decision_report(
            DecisionResult(
                trend=Trend.neutral,
                action=SignalAction.wait,
                reason=[f"策略[{strategy_name}] 规则风控拦截：双模型开仓信号未通过20%风控层"]
                + llm_result.reason
                + rule_result.reason,
                entry_zone=None,
                stop_loss=None,
                take_profit=None,
                expected_remaining_bars=llm_result.expected_remaining_bars,
                expected_total_move_pct=llm_result.expected_total_move_pct,
                confidence=min(llm_result.confidence, rule_result.confidence),
                risk_level=risk.risk_level.value,
                risk_verdict="blocked_by_rules",
            )
        )

    merged_reason = [f"策略[{strategy_name}] 决策权重：双模型(80%) + 规则风控(20%)"] + llm_result.reason
    if rule_result.action != llm_result.action:
        merged_reason.append(f"规则引擎建议: {rule_result.action.value}")
    if risk.warnings:
        merged_reason.extend(risk.warnings)

    result = _with_decision_report(DecisionResult(**{**llm_result.model_dump(), "reason": merged_reason}))
    result.risk_level = risk.risk_level.value
    if risk.position_sizing:
        result.position_sizing = risk.position_sizing.suggested_lots
    if risk.stop_config and risky_open:
        result.trailing_stop = risk.stop_config.trailing_stop
        if risk.stop_config.initial_stop and not result.stop_loss:
            result.stop_loss = risk.stop_config.initial_stop
    return result


def hybrid_decision_from_images(
    req: DecisionRequest,
    image_payloads: List[Tuple[bytes, str]],
    strategy_name: str = "default",
    strategy_profile: Optional[Dict[str, Any]] = None,
) -> DecisionResult:
    rule_result = make_decision(req)
    risk = assess_full_risk(req)
    model_outputs = _collect_vision_model_decisions(
        req,
        image_payloads=image_payloads,
        strategy_name=strategy_name,
        strategy_profile=strategy_profile,
    )
    if not model_outputs:
        fallback_reason = [f"策略[{strategy_name}] 视觉LLM不可用（Gemini/DeepSeek均不可用），回退到规则引擎"] + rule_result.reason
        result = _with_decision_report(DecisionResult(**{**rule_result.model_dump(), "reason": fallback_reason}))
        result.risk_level = risk.risk_level.value
        if risk.position_sizing:
            result.position_sizing = risk.position_sizing.suggested_lots
        if risk.stop_config:
            result.trailing_stop = risk.stop_config.trailing_stop
        if risk.warnings and not result.trend_strength:
            result.trend_strength = risk.warnings[0]
        return result

    llm_result = _ensemble_decision(model_outputs)
    risky_open = llm_result.action in {SignalAction.long, SignalAction.short}
    if rule_result.action == SignalAction.wait and risky_open:
        return _with_decision_report(
            DecisionResult(
                trend=Trend.neutral,
                action=SignalAction.wait,
                reason=[f"策略[{strategy_name}] 规则风控拦截：视觉双模型开仓信号未通过20%风控层"]
                + llm_result.reason
                + rule_result.reason,
                entry_zone=None,
                stop_loss=None,
                take_profit=None,
                expected_remaining_bars=llm_result.expected_remaining_bars,
                expected_total_move_pct=llm_result.expected_total_move_pct,
                confidence=min(llm_result.confidence, rule_result.confidence),
                risk_level=risk.risk_level.value,
                risk_verdict="blocked_by_rules",
            )
        )

    merged_reason = [f"策略[{strategy_name}] 决策来源：视觉双模型按固定量化规则判断(80%) + 规则风控(20%)"] + llm_result.reason
    if rule_result.action != llm_result.action:
        merged_reason.append(f"规则引擎建议: {rule_result.action.value}")
    if risk.warnings:
        merged_reason.extend(risk.warnings)

    result = _with_decision_report(DecisionResult(**{**llm_result.model_dump(), "reason": merged_reason}))
    result.risk_level = risk.risk_level.value
    if risk.position_sizing:
        result.position_sizing = risk.position_sizing.suggested_lots
    if risk.stop_config and risky_open:
        result.trailing_stop = risk.stop_config.trailing_stop
        if risk.stop_config.initial_stop and not result.stop_loss:
            result.stop_loss = risk.stop_config.initial_stop
    return result


def hybrid_decision_multi(req: DecisionRequest) -> Dict[str, DecisionResult]:
    profiles = _load_strategy_profiles()
    results: Dict[str, DecisionResult] = {}
    for strategy_name, profile in profiles.items():
        results[strategy_name] = hybrid_decision(req, strategy_name=strategy_name, strategy_profile=profile)
    return results


def hybrid_decision_from_images_multi(
    req: DecisionRequest,
    image_payloads: List[Tuple[bytes, str]],
) -> Dict[str, DecisionResult]:
    profiles = _load_strategy_profiles()
    results: Dict[str, DecisionResult] = {}
    for strategy_name, profile in profiles.items():
        results[strategy_name] = hybrid_decision_from_images(
            req,
            image_payloads=image_payloads,
            strategy_name=strategy_name,
            strategy_profile=profile,
        )
    return results
