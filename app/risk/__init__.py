"""风控模块导出。

导出策略链以及所有新增的策略类和工具函数，
方便外部模块直接 import 使用。
"""
from .policies import (
    risk_policy_chain,
    RiskVerdict,
    RiskPolicy,
    NoOpenAgainstUnknownMarketPolicy,
    MaxConfidenceFloorPolicy,
    MaxDrawdownPolicy,
    DailyTradeLimitPolicy,
    ConsecutiveLossPolicy,
    SingleInstrumentMaxPolicy,
    RiskRewardRatioPolicy,
    RiskPolicyChain,
)

# 从 risk_manager 导出新增的工具函数和数据类
from ..risk_manager import (
    TrailingStopMode,
    ScalePlan,
    score_entry_signal,
    time_based_stop,
    select_tightest_stop,
    calculate_trailing_stop_advanced,
    create_scale_in_plan,
    create_scale_out_plan,
    check_risk_reward_ratio,
    kelly_position_size,
    calculate_var,
    monitor_drawdown,
)

__all__ = [
    # 策略链（主入口）
    "risk_policy_chain",
    # 策略链基础设施
    "RiskVerdict",
    "RiskPolicy",
    "RiskPolicyChain",
    # 原有策略
    "NoOpenAgainstUnknownMarketPolicy",
    "MaxConfidenceFloorPolicy",
    # 新增策略
    "MaxDrawdownPolicy",
    "DailyTradeLimitPolicy",
    "ConsecutiveLossPolicy",
    "SingleInstrumentMaxPolicy",
    "RiskRewardRatioPolicy",
    # 新增数据类和枚举
    "TrailingStopMode",
    "ScalePlan",
    # 新增工具函数
    "score_entry_signal",
    "time_based_stop",
    "select_tightest_stop",
    "calculate_trailing_stop_advanced",
    "create_scale_in_plan",
    "create_scale_out_plan",
    "check_risk_reward_ratio",
    "kelly_position_size",
    "calculate_var",
    "monitor_drawdown",
]
