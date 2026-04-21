"""风控策略链模块。

提供可插拔的风控策略，按顺序执行，任一策略否决则信号被拦截。

现有策略:
- NoOpenAgainstUnknownMarketPolicy: 市场方向未知时禁止开仓
- MaxConfidenceFloorPolicy: 置信度低于阈值时禁止开仓

新增策略:
- MaxDrawdownPolicy: 最大回撤超过阈值清仓
- DailyTradeLimitPolicy: 日内最大交易次数限制
- ConsecutiveLossPolicy: 连续亏损后降仓策略
- SingleInstrumentMaxPolicy: 单品种最大持仓限制
- RiskRewardRatioPolicy: 盈亏比不达标拒绝进场
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Protocol

from app.models import DecisionRequest, DecisionResult, SignalAction


@dataclass
class RiskVerdict:
    allow: bool
    reason: str


class RiskPolicy(Protocol):
    def evaluate(self, req: DecisionRequest, decision: DecisionResult) -> RiskVerdict:
        ...


# ---------------------------------------------------------------------------
# 原有策略 —— 全部保留
# ---------------------------------------------------------------------------

class NoOpenAgainstUnknownMarketPolicy:
    """市场方向未知时禁止开仓。

    当文华指数（大盘）方向未提供时，不应进行方向性开仓操作，
    避免在不确定的市场环境中承担不必要的风险。
    """
    def evaluate(self, req: DecisionRequest, decision: DecisionResult) -> RiskVerdict:
        risky_open = decision.action in {SignalAction.long, SignalAction.short}
        if risky_open and req.require_market_filter and req.market_regime_30m.value == "unknown":
            return RiskVerdict(False, "risk_policy:block_open_when_market_unknown")
        return RiskVerdict(True, "risk_policy:ok")


class MaxConfidenceFloorPolicy:
    """置信度低于阈值时禁止开仓。

    当信号置信度低于设定阈值时，说明判断依据不够充分，
    此时应观望而非开仓。
    """
    def __init__(self, min_confidence: float = 0.35) -> None:
        self._min_confidence = min_confidence

    def evaluate(self, req: DecisionRequest, decision: DecisionResult) -> RiskVerdict:
        if decision.action in {SignalAction.long, SignalAction.short} and decision.confidence < self._min_confidence:
            return RiskVerdict(False, "risk_policy:block_open_low_confidence")
        return RiskVerdict(True, "risk_policy:ok")


# ---------------------------------------------------------------------------
# 新增策略
# ---------------------------------------------------------------------------

class MaxDrawdownPolicy:
    """最大回撤超过阈值时强制清仓/禁止开仓。

    当账户最大回撤达到设定阈值时，说明当前策略在市场中的
    表现已偏离预期，应停止开新仓并将现有持仓减仓或清仓。

    用法：需要通过 set_drawdown 方法或构造函数传入当前回撤数据。
    """
    def __init__(
        self,
        max_drawdown_pct: float = 0.10,
        current_drawdown_pct: float = 0.0,
    ) -> None:
        """
        Args:
            max_drawdown_pct: 允许的最大回撤比例，默认10%
            current_drawdown_pct: 当前回撤比例，可后续通过 set_drawdown 更新
        """
        self._max_drawdown_pct = max_drawdown_pct
        self._current_drawdown_pct = current_drawdown_pct

    def set_drawdown(self, current_dd_pct: float) -> None:
        """更新当前回撤比例（由外部风控模块调用）。"""
        self._current_drawdown_pct = current_dd_pct

    def evaluate(self, req: DecisionRequest, decision: DecisionResult) -> RiskVerdict:
        if self._current_drawdown_pct >= self._max_drawdown_pct:
            # 回撤已超阈值：禁止新开仓
            if decision.action in {SignalAction.long, SignalAction.short}:
                return RiskVerdict(
                    False,
                    f"risk_policy:max_drawdown_exceeded:{self._current_drawdown_pct:.2%}>={self._max_drawdown_pct:.2%}",
                )
            # 持仓操作也建议减仓
            if decision.action in {SignalAction.hold_long, SignalAction.hold_short}:
                return RiskVerdict(
                    False,
                    f"risk_policy:max_drawdown_reduce_position:{self._current_drawdown_pct:.2%}",
                )
        return RiskVerdict(True, "risk_policy:ok")


class DailyTradeLimitPolicy:
    """日内最大交易次数限制。

    防止在震荡行情中被频繁止损（反复开平仓），
    限制每日最大开仓次数。达到上限后当日不再允许新的开仓信号。

    用法：通过构造函数或 set_trade_count 传入当日已开仓次数。
    """
    def __init__(
        self,
        max_daily_trades: int = 5,
        today_trade_count: int = 0,
    ) -> None:
        """
        Args:
            max_daily_trades: 每日最大允许开仓次数，默认5次
            today_trade_count: 当日已开仓次数
        """
        self._max_daily_trades = max_daily_trades
        self._today_trade_count = today_trade_count

    def set_trade_count(self, count: int) -> None:
        """更新当日已交易次数（每日开盘前应重置为0）。"""
        self._today_trade_count = count

    def increment_trade_count(self) -> None:
        """交易次数加1（开仓成功后调用）。"""
        self._today_trade_count += 1

    def evaluate(self, req: DecisionRequest, decision: DecisionResult) -> RiskVerdict:
        is_open = decision.action in {SignalAction.long, SignalAction.short}
        if is_open and self._today_trade_count >= self._max_daily_trades:
            return RiskVerdict(
                False,
                f"risk_policy:daily_trade_limit:{self._today_trade_count}>={self._max_daily_trades}",
            )
        return RiskVerdict(True, "risk_policy:ok")


class ConsecutiveLossPolicy:
    """连续亏损后降仓策略。

    当连续亏损达到设定次数时，自动降低后续交易的仓位比例，
    避免在不利时段继续承担过大风险。连续亏损次数越多，
    仓位缩减比例越大。

    用法：通过构造函数或 set_consecutive_losses 传入当前连续亏损次数。
    """
    def __init__(
        self,
        trigger_count: int = 3,
        reduction_factor: float = 0.5,
        max_consecutive_losses: int = 6,
        consecutive_losses: int = 0,
    ) -> None:
        """
        Args:
            trigger_count: 触发降仓的连续亏损次数，默认3次
            reduction_factor: 每次触发后的仓位缩减因子，默认0.5（减半）
                实际缩减 = reduction_factor ^ (连续亏损次数 - trigger_count + 1)
            max_consecutive_losses: 达到此次数后完全禁止开仓
            consecutive_losses: 当前连续亏损次数
        """
        self._trigger_count = trigger_count
        self._reduction_factor = reduction_factor
        self._max_consecutive_losses = max_consecutive_losses
        self._consecutive_losses = consecutive_losses

    def set_consecutive_losses(self, count: int) -> None:
        """更新当前连续亏损次数。"""
        self._consecutive_losses = count

    def get_position_multiplier(self) -> float:
        """获取当前仓位乘数。

        Returns:
            float: 仓位乘数，范围 0 ~ 1
                - 1.0 表示正常仓位
                - 0.5 表示半仓
                - 0.0 表示禁止开仓
        """
        if self._consecutive_losses < self._trigger_count:
            return 1.0
        if self._consecutive_losses >= self._max_consecutive_losses:
            return 0.0
        # 按指数缩减
        excess = self._consecutive_losses - self._trigger_count + 1
        return max(0.0, self._reduction_factor ** excess)

    def evaluate(self, req: DecisionRequest, decision: DecisionResult) -> RiskVerdict:
        is_open = decision.action in {SignalAction.long, SignalAction.short}
        if not is_open:
            return RiskVerdict(True, "risk_policy:ok")

        multiplier = self.get_position_multiplier()
        if multiplier <= 0.0:
            return RiskVerdict(
                False,
                f"risk_policy:consecutive_loss_ban:{self._consecutive_losses}losses>={self._max_consecutive_losses}",
            )
        if multiplier < 1.0:
            # 允许但建议降仓（通过 reason 传递信息，不阻止交易）
            return RiskVerdict(
                True,
                f"risk_policy:consecutive_loss_reduce_position:multiplier={multiplier:.2f}",
            )
        return RiskVerdict(True, "risk_policy:ok")


class SingleInstrumentMaxPolicy:
    """单品种最大持仓限制。

    限制单个品种的持仓占总资金的最大比例，
    避免过度集中在单一品种上。
    需要传入当前持仓信息。

    用法：通过构造函数或 set_current_positions 传入各品种的持仓占比。
    """
    def __init__(
        self,
        max_single_ratio: float = 0.20,
        current_positions: dict | None = None,
    ) -> None:
        """
        Args:
            max_single_ratio: 单品种最大持仓占比，默认20%
            current_positions: 字典 {品种代码: 当前持仓占比}，
                例如 {"rb2510": 0.15, "au2512": 0.10}
        """
        self._max_single_ratio = max_single_ratio
        self._current_positions: dict = current_positions or {}

    def set_current_positions(self, positions: dict) -> None:
        """更新当前持仓信息。"""
        self._current_positions = positions

    def evaluate(self, req: DecisionRequest, decision: DecisionResult) -> RiskVerdict:
        is_open = decision.action in {SignalAction.long, SignalAction.short}
        if not is_open:
            return RiskVerdict(True, "risk_policy:ok")

        symbol = req.parsed.symbol
        current_ratio = self._current_positions.get(symbol, 0.0)

        if current_ratio >= self._max_single_ratio:
            return RiskVerdict(
                False,
                f"risk_policy:single_instrument_max:{symbol}={current_ratio:.2%}>={self._max_single_ratio:.2%}",
            )
        return RiskVerdict(True, "risk_policy:ok")


class RiskRewardRatioPolicy:
    """盈亏比不达标拒绝进场。

    在开仓前检查预期盈利与预期亏损的比值，
    只有当盈亏比达到最低要求时才允许进场。
    这确保了每次交易都有足够的正期望。

    要求 decision 中包含 stop_loss 和 take_profit 信息。
    """
    def __init__(
        self,
        min_ratio: float = 1.5,
    ) -> None:
        """
        Args:
            min_ratio: 最低盈亏比要求，默认1.5
        """
        self._min_ratio = min_ratio

    def evaluate(self, req: DecisionRequest, decision: DecisionResult) -> RiskVerdict:
        is_open = decision.action in {SignalAction.long, SignalAction.short}
        if not is_open:
            return RiskVerdict(True, "risk_policy:ok")

        # 需要止损和止盈信息
        if decision.stop_loss is None:
            # 无止损信息，保守处理：拒绝
            return RiskVerdict(False, "risk_policy:no_stop_loss_provided")

        entry = req.parsed.close
        stop = decision.stop_loss

        # 获取止盈价格（优先使用第一个止盈目标）
        if decision.take_profit and len(decision.take_profit) > 0:
            tp = decision.take_profit[0]
        else:
            return RiskVerdict(False, "risk_policy:no_take_profit_provided")

        risk = abs(entry - stop)
        if risk <= 0:
            return RiskVerdict(False, "risk_policy:zero_risk_distance")

        reward = abs(tp - entry)
        ratio = reward / risk

        if ratio < self._min_ratio:
            return RiskVerdict(
                False,
                f"risk_policy:risk_reward_ratio_insufficient:{ratio:.2f}<{self._min_ratio:.1f}",
            )
        return RiskVerdict(True, "risk_policy:ok")


# ---------------------------------------------------------------------------
# 策略链
# ---------------------------------------------------------------------------

class RiskPolicyChain:
    """风控策略链：按顺序执行所有注册的策略。

    任一策略返回 allow=False 时，信号即被拦截，
    动作改为 wait，开仓/止盈/止损价位被清空。
    """
    def __init__(self, policies: List[RiskPolicy]) -> None:
        self._policies = policies

    def apply(self, req: DecisionRequest, decision: DecisionResult) -> DecisionResult:
        for policy in self._policies:
            verdict = policy.evaluate(req, decision)
            if not verdict.allow:
                blocked = decision.model_copy(deep=True)
                blocked.action = SignalAction.wait
                blocked.entry_zone = None
                blocked.stop_loss = None
                blocked.take_profit = None
                blocked.reason = [f"风控策略拦截: {verdict.reason}"] + blocked.reason
                blocked.risk_verdict = verdict.reason
                return blocked

        accepted = decision.model_copy(deep=True)
        accepted.risk_verdict = "risk_policy:ok"
        return accepted


# 默认策略链：包含原有策略和新增策略
risk_policy_chain = RiskPolicyChain(
    policies=[
        NoOpenAgainstUnknownMarketPolicy(),
        MaxConfidenceFloorPolicy(min_confidence=0.35),
        MaxDrawdownPolicy(max_drawdown_pct=0.10),
        DailyTradeLimitPolicy(max_daily_trades=5),
        ConsecutiveLossPolicy(trigger_count=3, reduction_factor=0.5, max_consecutive_losses=6),
        SingleInstrumentMaxPolicy(max_single_ratio=0.20),
        RiskRewardRatioPolicy(min_ratio=1.5),
    ]
)
