# Xmoney 项目改造落地记录（集百家之长）

生成时间：2026-04-17

## 1. 本次已改造内容（代码已落地）

### 1.1 多资产元数据
- `DecisionRequest` 新增：`asset_class`, `exchange`, `instrument_type`, `strategy_id`
- `DecisionResult` 新增：`risk_verdict`

### 1.2 策略路由层
- 新增 `app/strategy/base.py`
- 新增 `app/strategy/default.py`
- 新增 `app/strategy/registry.py`
- 能力：按资产类别路由到策略实现（当前默认复用 hybrid strategy）

### 1.3 独立风控策略链
- 新增 `app/risk/policies.py`
- 能力：在策略后、执行前进行统一风控裁决；拦截后强制 `wait`

### 1.4 执行层抽象（paper）
- 新增 `app/execution/paper.py`
- 能力：把 action 映射为 paper execution 结果，形成执行闭环元数据

### 1.5 运行时管线
- 新增 `app/runtime/engine.py`
- 能力：`strategy -> risk -> execution` 编排，返回 `runtime` 元信息

### 1.6 API 与存储扩展
- `app/main.py` 已接入新 pipeline，返回 `runtime`
- `app/storage.py` 扩展 signals 字段并包含在线迁移逻辑

### 1.7 测试
- 新增 `tests/test_runtime_pipeline.py`
- 更新 `tests/test_multi_image.py`
- 本地验证：`pytest -q tests` 通过（13 passed）

## 2. 为什么这些改造是“共性能力”

- 对齐了主流框架的三段式核心：策略、风险、执行。
- 为跨市场（国内期货/加密/股票/期权）保留统一入口，不再把逻辑写死在单一规则函数。
- 不破坏现有接口能力，采用最小侵入式升级。

## 3. 长时间运行（>6小时）

已提供可直接使用脚本：`tools/run_long_analysis.sh`

### 3.1 一键后台运行（至少6小时）
```bash
MIN_TOTAL_RUNTIME_SECONDS=21600 \
  tools/run_long_analysis.sh start -- \
  "python -m pytest -q tests && sleep 120"
```

说明：
- supervisor 会在任务提前结束时自动重启，直到达到最小运行时长。
- 失败自动重试并记录日志。

### 3.2 查看状态与日志
```bash
tools/run_long_analysis.sh status
tools/run_long_analysis.sh tail
```

### 3.3 停止
```bash
tools/run_long_analysis.sh stop
```

## 4. 后续建议（最小风险顺序）

1. 接入真实执行网关（先一个市场一个通道）。
2. 新增 `orders/fills/positions` 查询 API。
3. 增加资产类别回测基准与交易成本模型。
4. 引入组合层风险预算（品类限额 + 总杠杆限制）。
