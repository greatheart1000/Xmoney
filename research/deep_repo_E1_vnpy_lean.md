# 任务E1：深度分析仓库1-2（vnpy + LEAN）

## 0. 分析范围与方法
- 仓库1：`third_party_repos/cn_futures/vnpy`
- 仓库2：`third_party_repos/multi_asset/lean`
- 方法：基于实际源码入口、核心引擎、策略与执行路径做“代码级调用链”分析，不依赖二手总结。

---

## 1) 核心架构分层（数据 / 策略 / 执行 / 风控 / 回测 / 监控）

### 1.1 vnpy（VeighNa）

| 层 | 实现位置 | 机制要点 |
|---|---|---|
| 数据 | `vnpy/trader/gateway.py`, `vnpy/trader/datafeed.py`, `vnpy/trader/database.py`, `vnpy/trader/object.py` | `BaseGateway`统一接入交易/行情接口；`get_datafeed/get_database`按配置动态加载插件；`TickData/BarData/ContractData`等统一对象模型。 |
| 策略 | 社区核心在 `MainEngine + App` 插件，alpha回测在 `vnpy/alpha/strategy/template.py` | 策略模板定义 `on_bars/on_trade` 生命周期；目标仓位与实际仓位分离（`target_data/pos_data`）。 |
| 执行 | 交易主链在 `vnpy/trader/engine.py` + `gateway.py`；alpha回测执行在 `vnpy/alpha/strategy/backtesting.py` | 实盘由 `MainEngine.send_order -> gateway.send_order`；回测有内置限价撮合 `cross_order()`。 |
| 风控 | 核心层偏“执行与持仓一致性”，高阶风控多由 App 扩展实现 | `OffsetConverter`处理平今/平昨等中国期货偏移转换；可接入 `RiskManagerApp`。 |
| 回测 | `vnpy/alpha/strategy/backtesting.py`（本仓可见） | 回放bar、撮合、手续费、逐日盯市、统计指标（收益/回撤/夏普）。 |
| 监控 | `vnpy/event/engine.py`, `vnpy/trader/engine.py`(LogEngine), `vnpy/trader/ui/mainwindow.py` | 事件总线驱动，日志事件统一分发；GUI监控面板+无界面守护进程模式。 |

### 1.2 LEAN（QuantConnect）

| 层 | 实现位置 | 机制要点 |
|---|---|---|
| 数据 | `Engine/DataFeeds/*`, `Engine/HistoricalData/*`, `Engine/DataFeeds/UniverseSelection.cs` | 数据馈送、历史数据、宇宙选择分层解耦；回测/实盘通过不同 `Synchronizer`。 |
| 策略 | `Algorithm/QCAlgorithm*.cs`, `Algorithm.Framework/*` | Framework五段式：Universe/Alpha/Portfolio/Execution/Risk；`OnFrameworkData`负责串联。 |
| 执行 | `Algorithm/Execution/*`, `Engine/TransactionHandlers/*` | 目标仓位驱动执行模型（如 `ImmediateExecutionModel`）；交易处理器负责订单生命周期。 |
| 风控 | `Algorithm/Risk/*`, `Algorithm.Framework/Risk/*` | 风控模型输出“覆盖后的目标仓位”；例如单标的回撤触发清仓。 |
| 回测 | `Launcher/Program.cs` -> `Engine/Engine.cs` -> `Engine/AlgorithmManager.cs` | 启动、装配、数据流、算法循环、结果输出全链路标准化。 |
| 监控 | `Engine/Results/*`, `Engine/DataMonitor`, `Common/Util/PerformanceTrackingTool.cs` | 结果流、性能采样、数据请求监控、状态上报。 |

---

## 2) 关键目录与主调用链（代码路径）

### 2.1 vnpy 关键目录
- `examples/veighna_trader/run.py`
- `examples/no_ui/run.py`
- `vnpy/event/engine.py`
- `vnpy/trader/engine.py`
- `vnpy/trader/gateway.py`
- `vnpy/trader/object.py`
- `vnpy/alpha/strategy/template.py`
- `vnpy/alpha/strategy/backtesting.py`

### 2.2 vnpy 主调用链

**实盘/仿真主引擎链**
1. `examples/veighna_trader/run.py`：创建 `EventEngine`、`MainEngine`，注入 `Gateway` 与 `App`。
2. `vnpy/trader/engine.py::MainEngine`：启动事件引擎，初始化 `LogEngine/OmsEngine`。
3. `vnpy/trader/gateway.py::BaseGateway`：网关回调 `on_tick/on_order/on_trade` 推送事件。
4. `vnpy/event/engine.py::EventEngine`：按事件类型分发给已注册处理器。
5. `vnpy/trader/engine.py::OmsEngine`：维护 ticks/orders/trades/positions/contracts 全量与活动缓存。

**alpha回测闭环链（本仓可见）**
1. `vnpy/alpha/strategy/backtesting.py::run_backtesting()` 回放时间轴。
2. `new_bars()` 先执行 `cross_order()` 撮合，再调用策略 `on_bars()`。
3. 策略在 `template.py::execute_trading()` 根据 `target - pos` 生成买卖动作。
4. `send_order()` 生成限价委托，写入 `active_limit_orders`。
5. 下一轮 `cross_order()` 根据bar高低价撮合，生成 `TradeData`，回写仓位与现金。

### 2.3 LEAN 关键目录
- `Launcher/Program.cs`
- `Engine/Engine.cs`
- `Engine/AlgorithmManager.cs`
- `Engine/LeanEngineAlgorithmHandlers.cs`
- `Algorithm/QCAlgorithm.Framework.cs`
- `Algorithm.Framework/Alphas/*`
- `Algorithm.Framework/Portfolio/*`
- `Algorithm.Framework/Execution/*`
- `Algorithm.Framework/Risk/*`
- `Algorithm.CSharp/BasicTemplateFrameworkAlgorithm.cs`

### 2.4 LEAN 主调用链

**引擎装配链**
1. `Launcher/Program.cs::Main()` 读取配置与任务，初始化引擎。
2. `Engine/Engine.cs::Run()` 创建算法实例、Brokerage、DataManager、HistoryProvider、DataFeed、Realtime、Transactions。
3. `AlgorithmHandlers.Setup.Setup(...)` 执行用户 `Initialize()`。
4. `AlgorithmManager.Run(...)` 启动主循环，处理 time slice。

**策略执行链（Framework模式）**
1. 算法 `Initialize()`（如 `BasicTemplateFrameworkAlgorithm.cs`）设置 `SetUniverseSelection/SetAlpha/SetPortfolioConstruction/SetExecution/SetRiskManagement`。
2. `AlgorithmManager` 循环中调用 `algorithm.OnFrameworkData(slice)`。
3. `QCAlgorithm.Framework.cs::ProcessInsights()`：
   - `PortfolioConstruction.CreateTargets()` 产出目标仓位；
   - `RiskManagement.ManageRisk()` 生成覆盖目标；
   - `Execution.Execute()` 执行目标。
4. 例如 `ImmediateExecutionModel` 内部按未完成目标计算下单数量并发起 `MarketOrder()`。
5. 成交/订单状态由 `TransactionHandler` 与结果处理器汇总回流。

---

## 3) 代表策略逻辑与信号-执行闭环

### 3.1 vnpy 代表闭环（目标仓位驱动）
- 位置：`vnpy/alpha/strategy/template.py` + `vnpy/alpha/strategy/backtesting.py`
- 逻辑：
1. 策略在 `on_bars()` 读取信号并设置 `set_target(vt_symbol, target)`。
2. `execute_trading()` 计算 `diff = target - pos`。
3. 根据多空差额拆分为 `cover/buy/sell/short` 订单。
4. 回测引擎 `send_order()` 生成限价委托，下一bar由 `cross_order()`按高低价撮合。
5. `update_trade()` 更新仓位，形成“信号->委托->成交->仓位->下一次信号”的闭环。

特点：
- 交易意图与撮合引擎分离；
- 能覆盖多合约组合（`vt_symbols`）；
- 对国内期货“价位最小变动、涨跌停约束”有内置考虑。

### 3.2 LEAN 代表闭环（Framework五段式）
- 位置：`Algorithm.CSharp/BasicTemplateFrameworkAlgorithm.cs` + `QCAlgorithm.Framework.cs`
- 逻辑：
1. `AlphaModel.Update()` 产生 `Insight`（如 `EmaCrossAlphaModel` 在快慢均线交叉时给出 Up/Down）。
2. `PortfolioConstructionModel.CreateTargets()` 将 insight 映射为仓位目标（如等权）。
3. `RiskManagementModel.ManageRisk()` 覆盖高风险目标（如回撤超阈值直接 target=0）。
4. `ExecutionModel.Execute()` 将目标转换为真实订单（如 `ImmediateExecutionModel` 直接市价下单）。
5. `AlgorithmManager` 持续处理成交、分红拆股、宇宙变化和时间调度，形成稳定事件闭环。

特点：
- 模块职责边界极清晰，可替换组件；
- 回测/实盘同一抽象语义；
- 组合层与风控层是一等公民，不是策略内嵌逻辑。

---

## 4) 适合迁移到本项目的能力（按P0/P1/P2）

> 面向你当前项目（`app/main.py + vision/rules/llm + sqlite reporting`）的最小侵入迁移。

### P0（先做，低风险高收益）
1. 统一领域对象与事件语义（借鉴 vnpy `object.py` + LEAN 框架对象分层）
- 引入 `Instrument / MarketEvent / SignalIntent / PortfolioTarget / OrderIntent`。
- 保留现有 `DecisionResult`，新增适配层，避免破坏现有 API。

2. 明确策略流水线分层（借鉴 LEAN：Alpha->Portfolio->Risk->Execution）
- 将现有 `hybrid_decision` 视作 Alpha；
- 新增轻量 `PortfolioConstruction`（至少支持等权/按置信度）；
- 新增独立 `RiskPolicy` 拦截层，不再散落在策略逻辑中。

3. 订单状态机最小实现（借鉴 vnpy OmsEngine + BacktestingEngine）
- 引入订单状态：`submitting/not_traded/part_filled/filled/cancelled/rejected`。
- 数据库增加 `orders/fills`，建立 `signal_id -> order_id -> fill_id` 链路。

### P1（形成交易闭环）
1. Paper Execution 引擎
- 复用 vnpy 回测撮合思想：先处理已有订单撮合，再处理新信号。
- 建立可配置滑点/手续费模型（市场类别可插拔）。

2. 统一回测-仿真-实盘接口
- 参考 LEAN 的 handler 分层：DataFeed/Execution/Risk/Result 分离。
- 同一策略接口在三种模式下可复用。

3. 多市场适配器抽象
- 借鉴 vnpy `get_datafeed/get_database` 的插件加载方式；
- 先接 1 个加密 + 1 个国内期货数据/交易通道，避免一次性铺太大。

### P2（规模化与稳定运行）
1. 宇宙选择与调度系统
- 参考 LEAN UniverseSelection + Scheduled 机制，做统一“选池+刷新频率”。

2. 组合级风控与风险预算
- 引入跨资产净敞口、相关性约束、单市场/单策略限额。

3. 长时间运行治理（>6h）
- 参考 LEAN 引擎与 vnpy 无界面守护模式：
- 增加 supervisor、健康检查、断线重连、任务隔离与可恢复状态。

---

## 5) 不适合直接迁移的部分与原因

### 5.1 vnpy 不宜直接搬运部分
1. Qt GUI 主体（`vnpy/trader/ui/*`）
- 你的项目是 API/服务化方向，直接迁移 GUI 价值低且维护成本高。

2. 强中国期货语义的细节默认值
- 如涨跌停10%假设、特定交易时段判断（`examples/no_ui/run.py`）不适用于加密/美股/期权全场景。

3. 整体 App 生态耦合
- 多功能依赖外部扩展包（如 `vnpy_ctastrategy` 等），直接拼装会引入大量运行依赖。

### 5.2 LEAN 不宜直接搬运部分
1. 全量引擎/Composer 体系
- LEAN 是完整 C# 交易操作系统级框架，直接内嵌到当前 Python 项目会导致技术栈和部署复杂度陡增。

2. 全套 Handler/Packet/Cloud 任务模型
- 你当前目标是快速吸收能力并落地，不需要一次性引入其完整任务编排与基础设施。

3. 框架级重量特性
- 如完整企业级数据权限、全类型资产企业回测栈；短期会拖慢交付，不符合最小侵入原则。

### 5.3 两者共同“不要直接抄”的点
1. 不要先做“平台重写”，先做“接口抽象+能力迁移”。
2. 不要在策略层混入执行与风控细节，避免后续不可维护。
3. 不要跳过事件与状态建模直接接交易所，否则后续无法稳定运行6小时以上。

---

## 6) 结论（E1）
- `vnpy` 的长处在于：事件驱动主引擎、网关插件化、国内期货交易细节与实战化回测闭环。
- `LEAN` 的长处在于：策略五段式架构、回测/实盘统一语义、组合与风控的一等分层设计。
- 对你项目最优路径：
1. 先吸收 LEAN 的分层思想（Alpha/Portfolio/Risk/Execution）。
2. 再吸收 vnpy 的对象模型与订单状态机落地方式。
3. 以最小侵入方式改造现有 API 项目，而不是重建一个新交易平台。
