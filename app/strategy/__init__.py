"""策略模块 - 提供差异化的资产类别策略。

导出:
- registry: 策略注册表（按资产类别自动选择策略）
- FuturesStrategy: 期货专用策略
- CryptoStrategy: 数字货币专用策略
- StockStrategy: 股票专用策略
- OptionsStrategy: 期权专用策略
- HybridVisionStrategy: 默认混合策略
"""
from .registry import registry
from .futures import FuturesStrategy
from .crypto import CryptoStrategy
from .stock import StockStrategy
from .options import OptionsStrategy
from .default import HybridVisionStrategy

__all__ = [
    "registry",
    "FuturesStrategy",
    "CryptoStrategy",
    "StockStrategy",
    "OptionsStrategy",
    "HybridVisionStrategy",
]
