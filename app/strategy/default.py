from __future__ import annotations

from app.models import DecisionRequest, DecisionResult
from app.llm_decision import hybrid_decision


class HybridVisionStrategy:
    def decide(self, req: DecisionRequest) -> DecisionResult:
        return hybrid_decision(req)
