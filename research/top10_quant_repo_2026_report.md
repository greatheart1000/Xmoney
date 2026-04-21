# 2026 热门量化仓库 Top10 报告（期货/加密/股票/期权）

生成时间：2026-04-17

## 1. Top10 仓库（已下载到 `third_party_repos/`）

1. https://github.com/vnpy/vnpy
2. https://github.com/QuantConnect/Lean
3. https://github.com/freqtrade/freqtrade
4. https://github.com/nautechsystems/nautilus_trader
5. https://github.com/mementum/backtrader
6. https://github.com/hummingbot/hummingbot
7. https://github.com/StockSharp/StockSharp
8. https://github.com/AI4Finance-Foundation/FinRL
9. https://github.com/ricequant/rqalpha
10. https://github.com/polakowo/vectorbt

## 2. 各项目原理（简版）

- vn.py：事件驱动交易框架，核心是“网关适配 + 策略引擎 + 回测引擎 + 风控扩展”，适合国内期货/CTP 场景。
- LEAN：统一资产语义下的研究-回测-实盘一体化引擎，强调同一算法代码跨环境复用。
- Freqtrade：以策略接口 + 交易所适配（CCXT）为核心，内置保护器与实盘运行工具链。
- NautilusTrader：生产级事件驱动架构，策略/风控/执行分层清晰，回测与实盘节点同构。
- Backtrader：经典 Python 回测框架，数据流和策略开发体验成熟，适合策略原型验证。
- Hummingbot：偏执行层与做市/套利，连接器生态丰富，强调订单执行与市场微结构策略。
- StockSharp：平台化交易系统，执行与风险控制模块化程度高，适合作为工程架构参考。
- FinRL：强化学习量化框架，本质是“金融环境 + RL agent + 训练/测试/交易流程”。
- RQAlpha：国内研究回测框架，API 简洁，适合策略研究与回测流程标准化。
- VectorBT：向量化研究引擎，优势在高速参数扫描和批量策略实验。

## 3. 共性模式（跨仓库抽象）

1. 统一领域对象：行情、信号、目标仓位、订单、成交、持仓。
2. 策略与执行解耦：策略输出意图，执行层负责落单细节。
3. 风控独立成层：交易前/交易中/交易后规则链式拦截。
4. 回测与实盘同构：尽量复用同一策略接口与配置模型。
5. 可观测与可回放：日志、事件、指标可追踪以支持复盘与审计。

## 4. 对你项目（Xmoney）的落地方向

- P0（已完成）：
  - 多资产策略路由（`asset_class`）
  - 独立风险策略链（RiskPolicyChain）
  - Paper 执行网关（ExecutionGateway）
  - 运行管线编排（strategy -> risk -> execution）
  - 存储元数据扩展（asset_class/exchange/instrument_type/strategy_id/risk_verdict）
- P1（下一步）：
  - 真实交易网关（CTP/交易所 API）
  - 订单/成交/持仓明细报表
  - 按市场的交易成本与滑点模型
- P2（规模化）：
  - 组合层风险预算
  - 多策略调度与隔离
  - 回测/仿真/实盘一致性验证与回放

## 5. 深度分析文档索引

- `research/deep_repo_E1_vnpy_lean.md`
- `research/deep_repo_E2_freqtrade_nautilus.md`
- `research/deep_repo_E3_backtrader_hummingbot.md`
- `research/deep_repo_E4_stocksharp_finrl.md`
- `research/deep_repo_E5_rqalpha_vectorbt.md`
