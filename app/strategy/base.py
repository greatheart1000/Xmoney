from __future__ import annotations

from typing import Protocol

from app.models import DecisionRequest, DecisionResult


class Strategy(Protocol):
    def decide(self, req: DecisionRequest) -> DecisionResult:
        ...
