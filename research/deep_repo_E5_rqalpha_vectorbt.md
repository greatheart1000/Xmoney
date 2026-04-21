# 任务E5：深度分析仓库9-10（RQAlpha + vectorbt）

## 0. 分析范围与方法
- 仓库9：`third_party_repos/cn_stocks_futures/rqalpha`（commit: `1bc9a27`）
- 仓库10：`third_party_repos/research/vectorbt`（commit: `993ceca`）
- 方法：基于本地源码做代码级分析，重点提取架构分层、真实调用链、可迁移抽象与最小改造方案。

---

## 1) 架构分层与核心调用链

### 1.1 RQAlpha（事件驱动、模块化回测内核）

#### 架构分层
| 层 | 关键文件 | 职责 |
|---|---|---|
| 入口与命令层 | `rqalpha/__main__.py:20-23`, `rqalpha/cmds/run.py:27-68` | 注入 mod 命令、解析 CLI 参数与配置，进入主引擎。 |
| 引擎编排层 | `rqalpha/main.py:133-251` | 创建 `Environment`、装配数据/策略/mod、执行主循环、收尾与异常处理。 |
| 扩展模块层 | `rqalpha/mod/__init__.py:31-95`, `rqalpha/mod/utils.py:35-55` | 按配置动态加载 mod、按优先级启动与逆序 teardown。 |
| 数据抽象层 | `rqalpha/data/data_proxy.py:42-259`, `rqalpha/interface.py:184-307` | `DataProxy` 对上游数据源做统一封装，`AbstractDataSource/EventSource/...` 定义可插拔接口。 |
| 事件驱动层 | `rqalpha/core/executor.py:37-99`, `rqalpha/core/strategy.py:41-120` | 事件循环、事件拆分（PRE/ON/POST）、策略回调注册与执行阶段管理。 |
| 仿真执行层 | `rqalpha/mod/rqalpha_mod_sys_simulation/mod.py:34-78`, `simulation_event_source.py:90-202`, `simulation_broker.py:36-186` | 生成 market event、订单撮合、成交回报、订单生命周期。 |
| 分析评估层 | `rqalpha/mod/rqalpha_mod_sys_analyser/mod.py:87-249` | 收集订单/成交/组合曲线、基准收益与风险统计。 |

#### 核心调用链（代码实链）
1. `__main__.entry_point` 注入 mod 命令并启动 CLI。
2. `cmds.run.run` 解析 config 并调用 `main.run`。
3. `main.run` 创建 `Environment`，执行 `ModHandler.start_up`，由 `sys_simulation` 设置 `broker + event_source`。
4. `main.run` 装载用户策略作用域，实例化 `Strategy` 与 `Executor`。
5. `Executor.run` 从 `event_source.events(...)` 拉取事件，拆为 `PRE_* / * / POST_*` 后推入 `event_bus`。
6. `Strategy` 监听 `BAR/TICK/BEFORE_TRADING/...`，在回调中触发 API 下单。
7. `SimulationBroker` 收单、在 `on_bar/on_tick` 调用 matcher 撮合，发布订单与成交事件。
8. `sys_analyser` 监听交易与结算事件，累计绩效并在 teardown 输出结果。

结论：RQAlpha 的核心是“事件总线 + 可插拔 mod + 仿真 broker/event source”，更偏高保真事件回放架构。

---

### 1.2 vectorbt（向量化研究、批量参数搜索内核）

#### 架构分层
| 层 | 关键文件 | 职责 |
|---|---|---|
| 包装配层 | `vectorbt/__init__.py:11-37`, `vectorbt/_settings.py:117-185` | 全量子模块导入、全局 settings（broadcasting/caching/data/plotting 等）。 |
| pandas 入口层 | `vectorbt/root_accessors.py:107-136` | 在 `Series/DataFrame` 上注册 `.vbt` 访问器，统一暴露研究 API。 |
| 数据层 | `vectorbt/data/base.py:4-99` | `Data` 抽象统一多 symbol 数据下载、对齐、更新、持久化。 |
| 指标工厂层 | `vectorbt/indicators/factory.py:2194-2206`, `3096-3168` | `run/run_combs` + `from_apply_func`，面向参数网格与缓存的指标流水线。 |
| 组合回测层 | `vectorbt/portfolio/base.py:1496-1633`, `2022-2085`, `3145-3201` | `Portfolio.from_orders/from_signals/from_order_func` 三种建模入口。 |
| 计算内核层 | `vectorbt/portfolio/nb.py:2420-2451`, `3930-3968` | Numba 编译 `simulate_nb/flex_simulate_nb`，完成订单处理与状态推进。 |
| 研究评估层 | `vectorbt/base/array_wrapper.py:109-169`, `vectorbt/generic/splitters.py:21-190` | 结果包装、分组评估、walk-forward 切分与统计。

#### 核心调用链（代码实链）
1. 用户从 `pd.DataFrame.vbt` 进入访问器体系。
2. 指标侧通过 `IndicatorFactory.run/run_combs` 进入 `run_pipeline`，返回参数展开后的输出对象。
3. 回测侧通过 `Portfolio.from_signals/from_order_func` 做广播与参数对齐。
4. `Portfolio` 根据模式选择 `nb.simulate_nb` 或 `nb.flex_simulate_nb`。
5. Numba 内核返回 `order_records/log_records`，构造成不可变 `Portfolio` 对象。
6. 再通过 returns/signals/stats/splitters 做批量评估、参数筛选与 walk-forward。

结论：vectorbt 的核心是“数组广播 + Numba 内核 + 参数网格批量研究”，更偏高吞吐研究架构。

---

## 2) 回测/研究能力的共性抽象

虽然实现路径不同（事件驱动 vs 向量化），两者可抽象为同一套量化最小内核：

| 抽象能力 | RQAlpha体现 | vectorbt体现 | 可统一接口 |
|---|---|---|---|
| 数据规范化 | `DataProxy` + `AbstractDataSource` | `Data` + broadcasting | `MarketDataAdapter` |
| 时间推进 | `EventSource.events` + `Executor` | 时间轴矩阵迭代（Numba循环） | `Clock/Timeline` |
| 策略表达 | `init/before_trading/handle_bar/tick` | 信号矩阵 / `order_func_nb` | `StrategyKernel` |
| 执行建模 | `SimulationBroker + matcher` | `simulate_nb`中的 fee/slippage/order rules | `ExecutionModel` |
| 风控注入 | `sys_risk` / validator / mod动作 | 信号约束+订单限制+组合规则 | `RiskPolicyChain` |
| 绩效归因 | `sys_analyser` 事件采集 | `Portfolio` records + returns/stats | `MetricsEngine` |
| 参数研究 | 依赖外部批跑 | `run_combs`/splitters 原生强项 | `ResearchRunner` |

### 共性结论（用于你的项目）
1. 两者都可分解为：`Data -> Signal -> Risk -> Execution -> Portfolio -> Metrics`。
2. 差异不在“有没有这些模块”，而在“状态推进方式”：
- RQAlpha：逐事件推进，保真强。
- vectorbt：向量批推进，研究效率高。
3. 最优实践不是二选一，而是“双引擎协同”：
- 用 vectorbt 做参数搜索与策略筛选。
- 用 RQAlpha 风格事件回放做执行可行性验证。

---

## 3) 可迁移到本项目的最小改造方案

结合你当前项目（`FastAPI + 图像信号 + 决策 + SQLite`）与既有审计结果，建议做最小侵入“研究-回放双引擎”改造。

### P0（最小闭环，优先）
1. 新增统一领域对象，不改旧 API
- 新增：`MarketSnapshot`, `SignalIntent`, `OrderIntent`, `FillEvent`, `PortfolioSnapshot`。
- 现有 `ParsedImageSignal` 通过 adapter 映射为 `MarketSnapshot`。

2. 增加双运行模式接口（先接空实现）
- `ResearchEngine`（vectorbt风格）：批参数评估。
- `ReplayEngine`（RQAlpha风格）：事件序列回放与订单状态机。
- `app/main.py` 保持原路由，仅在决策后增加可选引擎调用。

3. 风控链前置并可审计
- 复用你已有规则风控，抽为 `RiskPolicyChain`。
- 风控输出结构化 `RiskVerdict`（allow/reason/adjusted_size）。

4. 存储层扩展最小字段
- 在 `signals` 旁新增或扩展：`orders/fills/portfolio_snapshots/research_runs`。
- 先 SQLite 即可，保证“建议-下单-成交-绩效”可追溯。

### P1（增强研究到执行的一致性）
1. 引入参数实验流水
- 用 vectorbt 生成候选参数集（Top-K）。
- 候选参数进入 ReplayEngine 做事件保真回放。

2. 统一成本模型
- fee/slippage/杠杆/保证金从一个配置源读取，研究与回放共享。

3. 监控最小集
- 决策耗时、风控拒绝率、订单拒绝率、滑点偏离、PnL 回撤。

### P2（面向跨市场与长运行）
1. 跨市场适配器分层
- CN期货、加密、股票、期权分别实现 `MarketDataAdapter + ExecutionAdapter`。

2. 长稳运行
- supervisor + 幂等恢复（重启后重建未完成订单与持仓状态）。

3. 期权专属风险
- Greeks 限额、到期风险、波动率异常阈值作为独立 `RiskPolicy`。

---

## 4) 示例接口设计（Python伪代码）

```python
from dataclasses import dataclass
from typing import Protocol, List, Dict, Any, Iterable
from datetime import datetime

# ---------- Domain ----------
@dataclass
class MarketSnapshot:
    ts: datetime
    symbol: str
    asset_class: str      # futures / crypto / stock / option
    timeframe: str        # 1m / 5m / 1d
    fields: Dict[str, float]

@dataclass
class SignalIntent:
    symbol: str
    side: str             # long / short / flat
    strength: float
    meta: Dict[str, Any]

@dataclass
class OrderIntent:
    symbol: str
    side: str             # buy / sell
    qty: float
    order_type: str       # market / limit
    limit_price: float | None = None

@dataclass
class RiskVerdict:
    allow: bool
    adjusted_qty: float
    reason: str = ""

@dataclass
class FillEvent:
    ts: datetime
    symbol: str
    qty: float
    price: float
    fee: float


# ---------- Protocols ----------
class StrategyKernel(Protocol):
    def on_snapshot(self, snapshot: MarketSnapshot) -> SignalIntent: ...

class RiskPolicy(Protocol):
    def check(self, intent: OrderIntent, state: Dict[str, Any]) -> RiskVerdict: ...

class ExecutionModel(Protocol):
    def place(self, intent: OrderIntent) -> List[FillEvent]: ...

class ResearchEngine(Protocol):
    def run_grid(self, data: Any, param_grid: Dict[str, list]) -> Any: ...

class ReplayEngine(Protocol):
    def replay(self, events: Iterable[MarketSnapshot], strategy: StrategyKernel) -> Dict[str, Any]: ...


# ---------- vectorbt-style research ----------
class VectorbtResearchEngine:
    def run_grid(self, data, param_grid):
        # pseudo:
        # 1) indicator = IndicatorFactory(...).from_apply_func(...)
        # 2) signals = indicator.run_combs(...)
        # 3) pf = Portfolio.from_signals(...)
        # 4) return ranked metrics dataframe
        pass


# ---------- rqalpha-style event replay ----------
class EventReplayEngine:
    def __init__(self, execution: ExecutionModel, risk_policies: List[RiskPolicy]):
        self.execution = execution
        self.risk_policies = risk_policies

    def replay(self, events, strategy):
        state = {"positions": {}, "cash": 1_000_000.0, "equity": []}
        for snap in events:
            sig = strategy.on_snapshot(snap)
            intent = self._signal_to_order(sig)
            if intent is None:
                continue

            verdict = self._apply_risk(intent, state)
            if not verdict.allow:
                continue

            intent.qty = verdict.adjusted_qty
            fills = self.execution.place(intent)
            self._apply_fills(state, fills)
            self._mark_to_market(state, snap)

        return state

    def _apply_risk(self, intent, state):
        v = RiskVerdict(True, intent.qty, "")
        for p in self.risk_policies:
            v = p.check(intent, state)
            if not v.allow:
                return v
            intent.qty = v.adjusted_qty
        return v


# ---------- Coordinator ----------
class HybridWorkflow:
    """
    先向量化研究（快）筛参数，再事件回放（真）验执行可行性。
    """
    def __init__(self, research: ResearchEngine, replay: ReplayEngine):
        self.research = research
        self.replay = replay

    def run(self, data, param_grid, events, strategy_factory):
        candidates = self.research.run_grid(data, param_grid)
        best_params = candidates.iloc[0].to_dict()
        strategy = strategy_factory(best_params)
        return self.replay.replay(events, strategy)
```

---

## 5) E5结论
1. RQAlpha 适合做高保真事件回放与执行一致性验证；vectorbt 适合做大规模参数研究与策略筛选。
2. 你的项目应采用“双引擎”而不是单引擎：`vectorbt筛选 -> RQAlpha风格回放校验 -> 再进入执行`。
3. 以最小改造优先把“可追溯订单状态机 + 风控链 + 研究流水”建立起来，再扩到期货/加密/股票/期权全市场统一。
