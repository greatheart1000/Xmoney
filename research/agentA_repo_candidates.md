# 任务A：2026热门量化仓库候选清单（期货/加密/股票/期权）

> 数据快照时间：2026-04-16（UTC）  
> 口径：优先 GitHub Star + 最近活跃时间 + 生态代表性（国内期货/加密/股票/期权）  
> 说明：`最近活跃度` 以仓库最近 push/commit 时间为准；存在少数仓库“高 Star 但停更”的历史项目，已在风险里明确标注。

## 候选仓库（20个）

| # | Repo | Stars | 最近活跃度(UTC) | 主要市场覆盖 | 入选理由 | 潜在风险 |
|---|---|---:|---|---|---|---|
| 1 | https://github.com/vnpy/vnpy | 39.5k | 2026-04-13 | 国内期货/股票/期权/加密 | 国内量化主流框架，CTP与多市场实盘生态成熟 | 框架较大，上手和运维复杂 |
| 2 | https://github.com/wondertrader/wondertrader | 6k | 2025-09-30 | 国内期货/股票 | C++内核+多引擎（CTA/HFT/UFT），偏机构级 | 学习曲线陡，Python生态不如纯Py框架 |
| 3 | https://github.com/shinnytech/tqsdk-python | 4.6k | 2026-04-16 | 国内期货 | 天勤生态完善，实盘+回测接口一致性好 | 市场覆盖偏单一（期货为主） |
| 4 | https://github.com/openctp/openctp-ctp-python | 210 | 2025-10-16 | 国内期货 | CTP Python接口，适合做底层交易接入 | 不是完整策略框架，需要二次封装 |
| 5 | https://github.com/ctpbee/ctpbee | 988 | 2026-01-13 | 国内期货 | 国内CTP事件驱动框架，轻量实用 | 社区体量中等，长期维护不确定 |
| 6 | https://github.com/ricequant/rqalpha | 6.3k | 2026-04-15 | 股票/期货/基金（以A股研究见长） | 经典研究回测框架，组件化程度高 | 实盘能力依赖外部集成 |
| 7 | https://github.com/QuantConnect/Lean | 18.4k | 2026-04-15 | 期货/股票/期权/外汇/加密 | 多资产统一引擎，研究-回测-实盘链路完整 | 体系庞大，二次开发成本高 |
| 8 | https://github.com/nautechsystems/nautilus_trader | 22k | 2026-04-16 | 期货/股票/加密（多交易所） | 生产级事件驱动架构，低延迟导向 | Rust+Python混合栈，门槛较高 |
| 9 | https://github.com/freqtrade/freqtrade | 48.8k | 2026-04-16 | 加密（现货/部分衍生） | 加密策略社区最活跃之一，实盘工具链成熟 | 偏加密场景，跨市场能力有限 |
| 10 | https://github.com/hummingbot/hummingbot | 18.2k | 2026-04-16 | 加密（做市/套利） | 交易所连接器丰富，做市策略生态强 | 策略偏微结构，非通用CTA框架 |
| 11 | https://github.com/jesse-ai/jesse | 7.7k | 2026-04-09 | 加密 | 策略开发体验好，回测/优化/实盘一体 | 偏加密，跨资产扩展成本较高 |
| 12 | https://github.com/mementum/backtrader | 21.2k | 2024-08-19 | 股票/期货/期权（研究回测） | Python回测经典，资料丰富 | 维护活跃度下降，部分组件偏旧 |
| 13 | https://github.com/kernc/backtesting.py | 8.2k | 2025-12-20 | 股票/期货（研究回测） | 轻量、学习成本低，适合快速验证策略想法 | 主要是回测层，不是完整实盘平台 |
| 14 | https://github.com/polakowo/vectorbt | 7.2k | 2026-04-15 | 股票/加密/期货（研究） | 向量化批量回测能力强，参数搜索效率高 | 实盘执行能力弱，需外接交易层 |
| 15 | https://github.com/microsoft/qlib | 40.8k | 2026-04-15 | 股票（AI量化） | AI量化研究平台标杆，因子/模型/实验管理完善 | 偏研究侧，生产交易链路需自建 |
| 16 | https://github.com/goldspanlabs/optopsy | 1.3k | 2026-04-15 | 期权 | 专注期权回测研究，填补“期权专用工具”空缺 | 社区规模较小，生态不如主流通用框架 |
| 17 | https://github.com/Lumiwealth/lumibot | 1.3k | 2026-04-15 | 股票/期权/加密 | 中小型一体化框架，API友好 | 生态与连接器广度有限 |
| 18 | https://github.com/stefan-jansen/zipline-reloaded | 1.7k | 2026-01-06 | 股票/期货（研究） | Zipline现代化分支，学术/研究可用 | 历史包袱较重，生产化改造成本高 |
| 19 | https://github.com/pmorissette/bt | 2.8k | 2026-03-31 | 股票（组合层） | 组合构建与再平衡表达简洁，适合资产配置策略 | 更偏组合研究，非交易执行框架 |
| 20 | https://github.com/ccxt/ccxt | 41.9k | 2026-04-16 | 加密（交易所接入层） | 加密交易所统一API事实标准，适合做执行层基础设施 | 不是策略框架；需自己做风控/回测/调度 |

## 高风险但可参考的“历史高Star项目”

| Repo | Stars | 最近活跃度(UTC) | 风险说明 |
|---|---:|---|---|
| https://github.com/quantopian/zipline | 19.6k | 2020-10-05 | 长期停更，依赖栈老化，适合读架构不适合直接用于新生产 |
| https://github.com/gbeced/pyalgotrade | 4.6k | 2023-03-05 | 仓库已明确 deprecated，不建议作为新项目核心 |

## 推荐 Top10（优先用于后续下载与深度分析）

1. https://github.com/vnpy/vnpy
2. https://github.com/QuantConnect/Lean
3. https://github.com/nautechsystems/nautilus_trader
4. https://github.com/wondertrader/wondertrader
5. https://github.com/shinnytech/tqsdk-python
6. https://github.com/freqtrade/freqtrade
7. https://github.com/hummingbot/hummingbot
8. https://github.com/microsoft/qlib
9. https://github.com/polakowo/vectorbt
10. https://github.com/goldspanlabs/optopsy

## Top10 选择逻辑（简版）

- 覆盖完整：国内期货（vn.py / WonderTrader / TqSdk）+ 加密（Freqtrade / Hummingbot）+ 股票/多资产（LEAN / Qlib / Vectorbt）+ 期权（Optopsy）。
- 工程可迁移性：优先保留“可落地到你当前项目”的架构（事件总线、回测-实盘一致、风控分层、连接器抽象）。
- 活跃度约束：优先 2025-2026 持续活跃仓库；历史高Star但停更项目只作参考，不作为核心依赖。

