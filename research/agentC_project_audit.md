# 任务C：本项目改造位点审计（只读分析）

## 0. 审计范围与结论摘要

- 审计对象：当前 `FastAPI + 图像解析 + 规则/LLM决策 + SQLite日报` 项目。
- 目标：评估如何接入“多资产量化框架能力”（国内期货 + 数字货币 + 股票 + 期权）。
- 结论：当前项目已经具备“信号工厂”雏形（数据解析 -> 决策 -> 落库 -> 复盘统计），最小侵入改造路径是先做**接口抽象层**而不是重写策略逻辑。

---

## 1) 现有模块职责图

### 1.1 现状架构（调用链）

```text
[数据输入]
  A. 上传图片 API (app/main.py)
  B. 屏幕截图 API (root main.py, 独立服务)
      |
      v
[图像特征提取]
  app/vision.py
  - parse_image_with_gemini (含 mock 回退)
  - parse_images_with_gemini
  - fuse_parsed_signals (多周期融合)
      |
      v
[决策层]
  app/llm_decision.py
  - hybrid_decision: LLM(主) + rules(风控)
  app/rules.py
  - make_decision: MA/MACD/市场过滤/Fib/持仓动作
      |
      v
[信号持久化]
  app/storage.py (SQLite)
  - insert_signal/fetch/update_outcome
      |
      +--> [结果回填] PATCH /signals/{id}/outcome
      |
      v
[报表复盘]
  app/reporting.py
  - 日报统计 + 权益曲线 + HTML
```

### 1.2 模块职责清单

- `app/main.py`
  - API编排层（不做复杂业务）：请求校验、调用 vision/decision/storage/reporting。
  - 关键位点：`/api/v1/signal-from-image`、`/api/v1/signal-from-images` 将“解析+决策+落库”串成主流水线。

- `app/vision.py`
  - 图像到结构化特征（`ParsedImageSignal`）转换。
  - 支持多时间框融合，已具备“多源信号融合”模式（可推广到多资产多因子融合）。

- `app/rules.py`
  - 纯规则引擎：趋势识别、市场过滤、支撑阻力/Fib、动作输出。
  - 当前是确定性逻辑，适合作为风险闸门与可解释基线。

- `app/llm_decision.py`
  - 双模型决策与一致性处理；冲突时自动降级 `wait`。
  - 与 `rules.py` 形成“主分析 + 风控兜底”。

- `app/storage.py`
  - 单表 `signals` 存储，记录决策快照与事后收益。
  - 当前偏“日志式账本”，尚未形成订单/持仓/成交事件模型。

- `app/reporting.py`
  - 基于 `outcome_return` 做日内绩效统计与图表。
  - 本质是轻量复盘层，不是严格回测引擎。

- 根目录 `main.py`
  - 屏幕截图采集微服务（与交易决策服务解耦）。

---

## 2) 可插拔点审计（数据、策略、风险、执行、回测、监控）

以下按“现状 -> 插件位点 -> 建议接口”给出。

### 2.1 数据（Data）

- 现状
  - 仅有图像输入 -> `ParsedImageSignal`。
  - 无标准化行情对象（OHLCV、逐笔、Greeks、资金费率、期权链）。

- 可插拔位点
  - `app/vision.py:80` `parse_image_with_gemini`
  - `app/main.py:28` `/parse-image`
  - `app/main.py:70` `/signal-from-images`

- 建议接口
  - `DataAdapter`：统一输出 `MarketFeatureSnapshot`（包含 asset_class/exchange/symbol/timeframe/features）。
  - 先保留现有 `ParsedImageSignal`，新增 `from_parsed_image()` 适配器，避免改老接口。

### 2.2 策略（Strategy）

- 现状
  - 决策入口固定 `hybrid_decision(req)`；规则入口固定 `make_decision(req)`。

- 可插拔位点
  - `app/main.py:35` `/decision`
  - `app/llm_decision.py:164` `hybrid_decision`

- 建议接口
  - `Strategy` 协议：`generate_signal(context) -> DecisionResult`。
  - `StrategyRegistry`：按资产类别/策略名路由（futures/crypto/equity/options）。
  - 先把现有 `hybrid_decision` 包成默认策略 `HybridVisionStrategy`。

### 2.3 风险（Risk）

- 现状
  - 风控内嵌在规则与融合逻辑中：市场过滤、分歧降级、开仓拦截。
  - 缺少组合级风险（净敞口、相关性、VaR、保证金占用、合约乘数差异）。

- 可插拔位点
  - `app/llm_decision.py:174-187`（规则风控拦截）
  - `app/rules.py`（单品种技术面风控）

- 建议接口
  - `RiskPolicy` 链：`pre_signal` / `pre_trade` / `post_trade`。
  - 输出 `RiskVerdict(allow, adjusted_size, reason)`，不直接侵入策略核心。

### 2.4 执行（Execution）

- 现状
  - 只有“信号建议”，无下单执行、无订单状态机。

- 可插拔位点
  - `app/main.py:40` 与 `:70` 生成信号后落库节点（此处最适合挂执行钩子）。

- 建议接口
  - `ExecutionGateway.place_order(signal)`。
  - 初期实现 `PaperExecutionGateway`（仅模拟成交+滑点），后续扩展实盘连接器（CTP/券商/交易所API/crypto exchange）。

### 2.5 回测（Backtest）

- 现状
  - 通过 `PATCH outcome_return` 事后回填；`reporting.py` 只做统计展示。

- 可插拔位点
  - `app/storage.py` 现有 `signals` 可复用为回测信号日志。
  - `app/reporting.py` 可复用为报表层。

- 建议接口
  - `BacktestRunner.run(strategy, dataset, broker_model)`。
  - 对接统一数据适配层后，能同时跑期货/币/股/期权历史回放。

### 2.6 监控（Monitoring）

- 现状
  - 健康检查 `/health`、日报HTML、文件变更脚本 `monitor.sh`。
  - 无结构化指标（延迟、决策耗时、命中率按资产维度、异常率）。

- 可插拔位点
  - `app/main.py` API入口（请求级埋点）
  - `app/llm_decision.py`（模型调用耗时/失败率）
  - `app/storage.py`（落库失败与延迟）

- 建议接口
  - `MetricsSink` + `EventLogger`。
  - 最小实现先写本地JSONL与Prometheus兼容指标。

---

## 3) 最小侵入式改造建议（按优先级）

原则：**先抽象，不重写；先并行挂载，不替换旧链路**。

### P0（必须先做，低风险高收益）

1. 增加统一领域对象，不破坏现有API
- 新增 `MarketFeatureSnapshot`、`TradingContext`、`SignalIntent`。
- 通过适配器把 `ParsedImageSignal` 映射到新对象。
- 原接口继续收/回 `DecisionRequest/DecisionResult`，外部无感。

2. 引入策略注册与路由层
- 新增 `StrategyRegistry`，默认注册当前 `hybrid_decision`。
- 可按 `asset_class` 路由到 `futures_strategy / crypto_strategy / equity_strategy / options_strategy`。

3. 引入独立风险策略链
- 把当前“规则风控拦截”抽为 `RiskPolicy` 插件链。
- 先复刻现有逻辑（行为不变），再逐步加入组合风险。

4. 扩展存储schema（兼容旧表）
- 在 `signals` 增加：`asset_class`、`exchange`、`instrument_type`、`strategy_id`、`risk_verdict`。
- 不删旧字段，保证历史数据可读。

### P1（建议紧接P0）

1. 增加执行网关抽象
- 在信号落库后挂 `ExecutionGateway`（先 paper）。
- 引入订单/成交事件表（orders/fills/positions）。

2. 增加轻量回测器
- 复用同一 `Strategy + Risk + Execution` 接口，统一“回测/仿真/实盘”三态。
- 报表层沿用 `reporting.py`，新增资产维度和策略维度统计。

3. 增强监控
- 请求耗时、模型失败率、策略分歧率、风控拦截率、执行滑点。
- 先本地指标，后接集中监控。

### P2（规模化与长时间运行）

1. 运行稳定性（>6小时）
- 将长流程拆为后台任务（队列/调度器），API只做触发与查询。
- 为外部API调用加入超时、重试、熔断、幂等键。

2. 多资产特性插件
- 期货：合约换月、保证金、乘数。
- 数字货币：资金费率、24/7时段。
- 股票：交易时段、涨跌停/停牌。
- 期权：Greeks、隐波曲面、行权日风险。

3. 数据与存储升级
- SQLite 作为单机原型可保留；多策略并发建议迁移到 PostgreSQL + 时序扩展。

---

## 4. 推荐的首批落地顺序（两周内可完成的“最小闭环”）

1. 第1-3天：`StrategyRegistry + RiskPolicy` 空壳接入（行为保持一致）。
2. 第4-6天：`MarketFeatureSnapshot` 与 `ParsedImageSignal` 适配器上线。
3. 第7-9天：扩展 `signals` 元数据字段，补资产维度统计。
4. 第10-12天：接入 `PaperExecutionGateway`，打通“信号->模拟订单->成交->绩效”。
5. 第13-14天：补监控指标与异常告警（至少覆盖模型失败与执行失败）。

---

## 5. 风险与边界说明

- 当前项目强项是“图像理解 + 可解释决策”，不是完整 OMS/回测平台。
- 最小侵入改造应避免一次性引入重型框架；优先通过接口层兼容多资产能力。
- 本文为只读审计结论，未修改任何业务代码。
