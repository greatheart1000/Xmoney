from __future__ import annotations

from app.execution.paper import paper_execution_gateway
from app.models import DecisionRequest, DecisionResult
from app.risk.policies import risk_policy_chain
from app.strategy.registry import registry


def run_decision_pipeline(req: DecisionRequest) -> tuple[DecisionResult, dict]:
    strategy_result = registry.decide(req)
    risked = risk_policy_chain.apply(req, strategy_result)
    exec_result = paper_execution_gateway.execute(req, risked)
    return risked, {
        "strategy": req.strategy_id,
        "execution": {
            "status": exec_result.status,
            "side": exec_result.side,
            "qty": exec_result.qty,
            "note": exec_result.note,
        },
        "risk_verdict": risked.risk_verdict,
    }
