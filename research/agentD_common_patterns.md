# 任务D：跨市场量化共性模式提炼（期货 / 加密 / 股票 / 期权）

## 0. 目标与范围
本文件只做三件事：
1. 给出可执行的“六层共性模式矩阵”（数据层、信号层、组合层、执行层、风控层、评估层）。
2. 映射到本项目（Xmoney）当前能力，列出可落地能力清单与分期优先级。
3. 明确不建议引入的复杂性（当前阶段）。

当前项目基线（已存在）：
- 图像解析：`app/vision.py`
- 信号与决策：`app/rules.py`、`app/llm_decision.py`
- API编排：`app/main.py`
- 信号存储：`app/storage.py`（SQLite）
- 绩效日报：`app/reporting.py`

---

## 1) 共性模式矩阵（跨市场通用）

| 层 | 主流框架共性（抽象） | 期货/加密/股票/期权的差异点 | 对本项目的直接含义 |
|---|---|---|---|
| 数据层 | 统一市场数据模型（K线/成交/盘口/合约元数据）+ 历史与实时同构 + 适配器模式（多交易所/多券商） + 时间对齐 | 期货有主连/移仓/交易时段与夜盘；加密7x24+资金费率；股票有停牌/T+1/复权；期权有链路（行权价/到期日/IV/Greeks） | 需要“统一行情与合约Schema + 多市场适配器接口”，先不追求全覆盖交易所 |
| 信号层 | 因子/指标与策略解耦；多周期共振；状态机化信号（开仓/加减仓/平仓） | 期权多一层波动率与Greeks信号；加密增加资金费率与基差；股票强调横截面因子 | 现有MA/MACD+形态可保留，升级为“可插拔信号节点 + 统一Signal事件” |
| 组合层 | 把“信号”转换为“目标仓位/风险预算”；仓位规模化（vol targeting、risk parity、max exposure） | 期货按保证金与合约乘数；加密可高杠杆且碎片化；股票常按资金权重；期权需Delta/Gamma/Vega约束 | 当前缺失组合层；需新增 `PortfolioTarget` 与跨资产净敞口控制 |
| 执行层 | 订单抽象（市价/限价/条件单）+ 执行策略（TWAP/VWAP/被动挂单）+ 订单状态机 + 成交回报闭环 | 不同市场订单类型与撮合规则差异极大；期货有涨跌停与最小变动价位；加密连接器差异大 | 当前只有“建议动作”无执行闭环；需新增 OMS/EMS 最小子集（下单、回报、重试、幂等） |
| 风控层 | 交易前（可交易性/仓位/杠杆）+ 交易中（滑点/异常波动）+ 交易后（回撤熔断）三层控制 | 国内期货需日内风控与保证金监控；加密需交易所/链上风险；股票需合规限制；期权需Greeks与到期风险 | 当前有规则兜底但缺资金与账户级风控；需升级为“账户级风控引擎” |
| 评估层 | 回测-仿真-实盘一致语义；统一指标（收益、回撤、夏普、卡玛、容量、换手、滑点归因）+ 归因分析 | 不同市场交易成本模型差异显著；期权需波动率面与希腊值归因 | 当前日报是单日统计；需增加“分层归因 + 回测/实盘对账” |

---

## 2) 各层原理（精炼版）

### 数据层原理
核心不是“拿到数据”，而是“把多市场数据标准化为可计算事件流”。
- 输入：多源行情、合约元信息、账户与成交回报。
- 处理：时区与交易时段归一、缺口处理、公司行为/主连处理、字段标准化。
- 输出：统一 `MarketEvent`（bar/tick/book/funding/greeks）。

### 信号层原理
将策略逻辑拆为“可组合信号函数”，避免策略与交易所耦合。
- 结构：`Feature -> Signal -> Intent`。
- 多周期一致性：高周期定方向，低周期定入场/出场（你当前“30m/15m 过滤”是正确方向）。
- 结果：输出标准化交易意图，而非直接下单。

### 组合层原理
把多个信号竞争转化为资本分配问题。
- 输入：多个标的的交易意图与置信度。
- 约束：总杠杆、品类上限、相关性、单标的风险预算。
- 输出：目标仓位（target position），而不是离散动作。

### 执行层原理
把目标仓位稳定转换成实际成交。
- 关键：订单状态机（new/partially_filled/filled/canceled/rejected）与重试幂等。
- 执行质量：滑点、冲击成本、成交率。
- 原则：策略只表达“要什么仓位”，执行层决定“怎么成交”。

### 风控层原理
风控必须独立于策略，拥有最终否决权。
- Pre-trade：交易窗口、可交易状态、仓位上限、保证金/资金占用。
- In-trade：滑点偏离、成交异常、延迟/断连熔断。
- Post-trade：日内损失阈值、连续亏损、净值回撤闸门。

### 评估层原理
评估不是只看收益，而是解释收益来源与可持续性。
- 统计层：收益、回撤、波动、胜率、盈亏比。
- 归因层：市场β、策略α、执行滑点、费用、换手、容量。
- 一致性：回测参数、仿真语义、实盘日志字段一致。

---

## 3) 映射到本项目：可落地能力清单

## 3.1 现状评估（Xmoney）
- 已具备：
  - 信号解析与决策闭环（图片->结构化特征->动作建议）
  - 基础规则风控（趋势过滤、形态、Fib、多模型分歧降级）
  - 信号落库与日报
- 缺失关键：
  - 真正的多市场数据层与账户层
  - 组合层（跨品种仓位分配）
  - 执行层（下单/回报/对账）
  - 账户级风控与回测-实盘一致评估

## 3.2 建议分期（可执行）

### P0（1-2周）：统一领域模型，打基础
1. 统一事件与对象模型
- `Instrument`（asset_class, exchange, multiplier, tick_size, margin, trading_session）
- `MarketEvent`（bar/tick/book/funding/greeks）
- `SignalIntent`（direction, confidence, horizon, ttl）
- `PortfolioTarget`（target_qty / target_notional / risk_budget）
- `OrderIntent`（type, tif, price, qty, reduce_only）

2. 把当前 `DecisionResult` 升级为“意图+约束”
- 在 `app/models.py` 新增：`max_slippage_bps`, `valid_until`, `risk_tag`。
- 继续保留你现有 `wait/long/short/...`，但作为高层语义。

3. 数据存储最小升级
- 现有 SQLite 增加三表：`orders`, `fills`, `positions_snapshots`。
- 信号、订单、成交建立可追踪ID链路（signal_id -> order_id -> fill_id）。

### P1（2-4周）：最小可用执行与风控
1. 执行层最小闭环
- 新增 `ExecutionAdapter` 抽象：`submit/cancel/query`。
- 先接一个加密交易所 sandbox（或模拟撮合），再扩展国内期货/股票券商接口。

2. 账户级风控引擎
- 规则：单笔风险上限、单品种上限、总杠杆上限、日内亏损熔断。
- 位置：在 `hybrid_decision` 后、下单前强制拦截。

3. 回测/仿真一致化
- 用与实盘相同 `SignalIntent -> PortfolioTarget -> OrderIntent` 链路跑仿真。

### P2（4-8周）：跨市场能力增强
1. 市场特有因子插件
- 期货：主连切换、基差、库存/期限结构。
- 加密：资金费率、永续基差、链上拥堵/转账费用。
- 股票：行业中性、财报事件窗口。
- 期权：IV曲面、Greeks暴露与到期风险。

2. 组合层上线
- 先做“分层预算”：市场->品类->标的。
- 再做简单相关性惩罚（避免同向拥挤仓位）。

3. 评估层升级
- 新增周/月维度报告、策略归因和执行归因（滑点/手续费）。

---

## 4) 明确不建议引入的复杂性（当前阶段）

1. 不建议立刻上“全功能高频撮合内核”
- 例如纳秒级事件总线、复杂撮合回放、全订单簿仿真。
- 原因：你的当前瓶颈在策略工程化与风控闭环，不在微秒级延迟。

2. 不建议立刻做“跨语言重构”（Rust/C++核心重写）
- 原因：当前 Python 架构还未形成稳定领域模型，过早重写会放大维护成本。

3. 不建议立刻引入“重型AutoML/多Agent自动挖因子”用于实盘
- 原因：样本泄露、过拟合与稳定性验证成本极高。
- 可用于研究环境，但不应直接接实盘执行。

4. 不建议一次性接入过多交易所/券商
- 原因：执行差异与风控差异会造成调试爆炸。
- 建议：每个资产类别先 1 个主通道打通。

5. 不建议先上复杂期权组合引擎（全Greeks实时对冲）
- 原因：需要高质量波动率面与高频风险重估基础，目前项目未具备。
- 建议：先做方向性期权策略或Delta约束版本。

---

## 5) 适配你项目的“最小通用架构”建议图

```text
Data Adapters (Futures/Crypto/Stocks/Options)
        |
Unified MarketEvent Bus
        |
Feature & Signal Layer (rule + LLM + factors)
        |
Portfolio Layer (risk budget -> target position)
        |
Execution Layer (order state machine)
        |
Risk Engine (pre/in/post trade veto)
        |
Storage + Evaluation (signals/orders/fills/positions/reports)
```

关键原则：
- 先统一“对象与事件语义”，再扩市场与策略。
- 先做“可解释稳定闭环”，再追求复杂模型。
- 先保证回测/仿真/实盘字段一致，再追求性能。

---

## 6) 参考框架与证据来源（用于本次共性提炼）
- QuantConnect LEAN: https://github.com/QuantConnect/Lean
- vn.py (VeighNa): https://github.com/vnpy/vnpy
- Freqtrade: https://github.com/freqtrade/freqtrade
- Hummingbot: https://github.com/hummingbot/hummingbot
- Microsoft Qlib: https://github.com/microsoft/qlib
- NautilusTrader: https://github.com/nautechsystems/nautilus_trader
- Backtrader: https://github.com/mementum/backtrader
- Zipline Reloaded: https://github.com/stefan-jansen/zipline-reloaded
- Zipline (legacy): https://github.com/quantopian/zipline
- VectorBT: https://github.com/polakowo/vectorbt

注：本文件提炼的是“跨框架稳定共性”，不是逐项目功能清单。
