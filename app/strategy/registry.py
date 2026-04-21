"""策略注册表 - 将资产类别映射到对应策略实现。

支持以下资产类别的差异化策略:
- cn_futures: 期货专用策略（趋势强度分级 + MA发散度 + Dual Thrust）
- crypto: 数字货币策略（7x24市场适配 + 波动率自适应 + 布林带回归）
- equity: 股票策略（量价关系 + 涨跌停处理 + 行业动量）
- options: 期权策略（波动率状态 + Covered Call/Protective Put + 价差策略）
- multi: 默认混合策略（HybridVisionStrategy）
"""
from __future__ import annotations

from typing import Dict

from app.models import AssetClass, DecisionRequest, DecisionResult
from app.strategy.base import Strategy
from app.strategy.crypto import CryptoStrategy
from app.strategy.default import HybridVisionStrategy
from app.strategy.futures import FuturesStrategy
from app.strategy.options import OptionsStrategy
from app.strategy.stock import StockStrategy


class StrategyRegistry:
    """策略注册表：根据资产类别选择对应的策略实现。"""

    def __init__(self) -> None:
        # 为每种资产类别注册对应的策略
        self._strategies: Dict[AssetClass, Strategy] = {
            AssetClass.cn_futures: FuturesStrategy(),    # 中国期货专用策略
            AssetClass.crypto: CryptoStrategy(),         # 数字货币专用策略
            AssetClass.equity: StockStrategy(),           # 股票专用策略
            AssetClass.options: OptionsStrategy(),        # 期权专用策略
            AssetClass.multi: HybridVisionStrategy(),     # 混合策略（默认）
        }

    def register(self, asset_class: AssetClass, strategy: Strategy) -> None:
        """注册或替换某个资产类别的策略。"""
        self._strategies[asset_class] = strategy

    def decide(self, req: DecisionRequest) -> DecisionResult:
        """根据请求中的资产类别选择策略并执行决策。"""
        strategy = self._strategies.get(req.asset_class, self._strategies[AssetClass.multi])
        return strategy.decide(req)


registry = StrategyRegistry()
