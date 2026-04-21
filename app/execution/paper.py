from __future__ import annotations

from dataclasses import dataclass

from app.models import DecisionRequest, DecisionResult, SignalAction


@dataclass
class PaperExecutionResult:
    status: str
    side: str
    qty: float
    note: str


class PaperExecutionGateway:
    def execute(self, req: DecisionRequest, decision: DecisionResult) -> PaperExecutionResult:
        if decision.action in {SignalAction.wait, SignalAction.hold_long, SignalAction.hold_short}:
            return PaperExecutionResult(status="noop", side="none", qty=0.0, note="no execution required")

        side = "buy" if decision.action in {SignalAction.long, SignalAction.reduce_short} else "sell"
        qty = max(1.0, round(100 * req.risk_per_trade, 2))
        return PaperExecutionResult(status="filled", side=side, qty=qty, note="paper execution simulated")


paper_execution_gateway = PaperExecutionGateway()
