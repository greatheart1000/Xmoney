# AI 辅助期货决策系统

该项目实现了你要求的一整套流程（已按“先看文华指数大盘，再看单品种”执行）：

- 图片解析接口（Gemini + Mock 回退）
- 决策接口（默认 Gemini + DeepSeek 双模型共识 80% + 规则风控 20%）
- 规则决策接口（MA/MACD/持仓量/图形形态 + 斐波那契价格与时间规则）
- 信号日志与绩效统计（SQLite）
- 可视化日报（命中率、盈亏比、回撤 + 权益曲线图 + HTML日报）

## 1. 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 运行

```bash
uvicorn app.main:app --reload --port 8000
```

## 3. Gemini 配置（可选）

如果配置了 `GEMINI_API_KEY`，系统会调用 Gemini 图像解析；否则自动使用 mock 解析，便于本地开发。

```bash
export GEMINI_API_KEY=your_key
# 可选，默认 gemini-2.5-pro
export GEMINI_MODEL=gemini-2.5-pro
```

# DeepSeek（可选）
export DEEPSEEK_API_KEY=your_key
export DEEPSEEK_MODEL=deepseek-chat
# 可选，默认 https://api.deepseek.com/chat/completions
export DEEPSEEK_BASE_URL=https://api.deepseek.com/chat/completions

### 3.1 LLM决策权重与规则注入

系统默认采用：
- **80% 双模型（Gemini + DeepSeek）分析**
- **20% 规则风控兜底**
- **双模型交叉验证分歧时自动降级为 wait（先观望）**

用户规则注入来源（优先级）：
1. 环境变量 `USER_RULES_TEXT`
2. 文件 `config/user_rules.md`

你可以把自己的交易规则持续写入 `config/user_rules.md`，LLM每次决策都会自动注入。

### 3.2 多策略配置（短线/波段/长线）

你可以通过文件配置“同一张图，输出多套策略建议”：

- 配置文件：`config/strategy_profiles.json`
- 默认内置三种策略：`short_term` / `swing` / `long_term`
- 每个策略可配置：`name`、`description`、`rules[]`

系统会在同一份图像/结构化行情输入上，分别注入不同策略规则，生成三份独立决策结果。
每份结果都包含 `ai_decision_report`（中文结构化报告），用于直接展示给交易员。
系统会强制执行高盈亏比过滤：`risk_reward_ratio < 3.0` 的开仓信号会自动降级为 `wait`。

## 4. 关键接口

### 4.1 图片解析

`POST /api/v1/parse-image?symbol=SA605&timeframe=5m`

multipart form 上传 `image`。

### 4.2 规则决策

`POST /api/v1/decision`

body 示例：

```json
{
  "parsed": {
    "symbol": "SA605",
    "timeframe": "5m",
    "close": 1180,
    "ma5": 1181,
    "ma10": 1183,
    "ma20": 1185,
    "ma40": 1189,
    "ma60": 1193,
    "macd_diff": -2.8,
    "macd_dea": -2.6,
    "macd_hist": -0.4,
    "volume": 5000,
    "open_interest": 800000,
    "support_levels": [1177, 1170],
    "resistance_levels": [1189, 1198],
    "historical_support_levels": [1172, 1168],
    "historical_resistance_levels": [1204, 1215],
    "swing_high": 1198,
    "swing_low": 1177,
    "leg_start_price": 1198,
    "leg_elapsed_bars": 26,
    "avg_up_leg_bars": 20,
    "avg_down_leg_bars": 28,
    "avg_up_leg_move_pct": 0.018,
    "avg_down_leg_move_pct": 0.026,
    "confidence": 0.75,
    "raw_features": {}
  },
  "position": "flat",
  "risk_per_trade": 0.01,
  "market_regime_30m": "bearish",
  "market_regime_15m": "bearish",
  "require_market_filter": true
}
```


### 4.2.1 市场优先过滤（文华指数）

`/api/v1/decision` 新增以下字段：

- `market_regime_30m`: `bullish | bearish | neutral | unknown`
- `market_regime_15m`: `bullish | bearish | neutral | unknown`
- `require_market_filter`: 默认 `true`

策略顺序：
1. 先用文华指数 30m 定方向；
2. 再用文华指数 15m 确认不冲突；
3. 最后才看单品种执行做多/做空/持仓。

若 `require_market_filter=true` 且大盘方向未确认，系统会直接返回 `wait`。


### 4.2.2 斐波那契回调（支撑位/压力位）

系统支持从 `swing_high` / `swing_low` 自动计算 Fibonacci 回调位（0.236/0.382/0.5/0.618/0.786），并与原有 `support_levels` / `resistance_levels` 合并用于：

- `entry_zone`（入场区）
- `stop_loss`（止损）
- `take_profit`（止盈）

当你没有直接提供支撑/压力时，系统会优先用 Fib 回调位补全。


### 4.2.3 斐波那契时间 + 波段空间估计

除了价格回调位，系统还支持时间与空间预测：

- `leg_elapsed_bars`: 当前波段已经运行的K线数量
- `avg_up_leg_bars` / `avg_down_leg_bars`: 历史上涨/下跌波段平均时长
- `avg_up_leg_move_pct` / `avg_down_leg_move_pct`: 历史上涨/下跌波段平均涨跌幅

系统会输出：
- `expected_remaining_bars`: 结合斐波那契时间窗(0.618/1.0/1.618)估计的剩余时间
- `expected_total_move_pct`: 结合历史波段统计的总涨跌幅参考

同时会把 `historical_support_levels` 与 `historical_resistance_levels` 合并到当前支撑/压力分析中。

### 4.2.4 高盈亏比过滤（Risk-Reward Gate）

系统会对开仓动作执行硬性过滤：

- 计算 `risk_reward_ratio`（多头：`(TP-Entry)/(Entry-Stop)`；空头对称）
- 若开仓建议的 `risk_reward_ratio < 3.0`，则强制降级为 `wait`
- `reason` 增加：`当前价格已脱离安全区，盈亏比低于 3.0，建议等待回调。`

返回字段新增：

```json
{
  "risk_reward_ratio": 4.2,
  "is_high_quality_setup": true
}
```

### 4.2.5 多策略决策（同一输入输出三套建议）

`POST /api/v1/decision/multi`

输入同 `/api/v1/decision`，输出示例：

```json
{
  "strategies": {
    "short_term": { "action": "long", "entry_zone": [2560, 2570], "stop_loss": 2535, "take_profit": [2600], "ai_decision_report": "【AI 交易助手决策报告】..." },
    "swing": { "action": "wait", "reason": ["等待30m/15m二次确认"] },
    "long_term": { "action": "hold_long", "take_profit": [2655, 2700] }
  }
}
```

### 4.2.6 AI视觉交易助手执行范式（VQA）

当你上传 15m/30m K 线图并调用决策接口时，系统按以下固定顺序执行（右侧趋势追踪）：

1. 文华指数 30m 定方向；
2. 文华指数 15m 确认不冲突；
3. 再看单品种 MA(5/10/20/40/60) + MACD + 成交量 + 持仓量；
4. 合并历史支撑/压力与 Fib 回调位（0.236/0.382/0.5/0.618/0.786）；
5. 用 Fib 时间窗（0.618/1.0/1.618）估算 `expected_remaining_bars`；
6. 输出结构化交易动作与风控参数。

推荐将输出用于“执行参考”而非“盲目下单”，并补充一条实盘风控规则：

- 当浮盈达到 1:1 盈亏比后，将止损上移到保本位（break-even）。

建议输出模板：

```json
{
  "action": "wait|long|short|hold_long|hold_short|reduce_long|reduce_short",
  "entry_zone": [2560, 2570],
  "stop_loss": 2535,
  "take_profit": [2620, 2655],
  "expected_remaining_bars": 12,
  "expected_total_move_pct": 0.035,
  "reason": ["文华30m与15m同向", "MA/MACD/量仓共振"]
}
```

### 4.3 一步生成信号（解析+决策+落库）

`POST /api/v1/signal-from-image?symbol=SA605&timeframe=5m&position=flat`

multipart 上传 `image`。

### 4.3.1 单图多策略建议

`POST /api/v1/signal-from-image/multi?symbol=SA605&timeframe=15m&position=flat`

multipart 上传 `image`，返回：

- `parsed`：图像解析后的指标结构
- `strategies`：短线/波段/长线三套决策结果

### 4.3.2 OSS 图片直连（不上传文件）

如果你的K线图已经存放在 OSS，可以直接传 URL：

`POST /api/v1/signal-from-oss-image`

```json
{
  "symbol": "SA605",
  "timeframe": "15m",
  "image_url": "https://your-oss-domain/path/to/chart.png",
  "position": "flat"
}
```

系统会下载该图片进行解析与决策，并将 `image_url` 落库到 `signals.image_uri`，便于后续回测和审计追踪。

### 4.4 回填实际结果

`PATCH /api/v1/signals/{signal_id}/outcome`

```json
{ "outcome_return": 0.012 }
```

### 4.5 生成日报

- JSON: `GET /api/v1/report/daily?date=2026-04-02`
- HTML: `GET /api/v1/report/daily/html?date=2026-04-02`

报告输出到 `reports/`，包含：
- `equity_YYYY-MM-DD.png`
- `daily_YYYY-MM-DD.html`

### 4.6 回测校核统计（过去一天/一周/一月）

当你持续回填 `outcome_return` 后，可直接统计策略正确率：

`GET /api/v1/backtest/summary?period=1d`

支持：
- `period=1d`（过去一天）
- `period=7d`（过去一周）
- `period=30d`（过去一月）

返回包括：
- `accuracy`：总体正确率
- `long_short_accuracy`：方向性信号正确率
- `wait_accuracy`：观望信号正确率（默认按小波动阈值）
- `high_quality_accuracy`：高盈亏比 setup 的命中率

> 你的图片在 OSS 存储没有问题：只要每日用图片生成信号并回填真实结果，统计接口就能做历史回顾。若后续需要，我可以继续补一个“从 OSS 批量回放并自动回填”的任务接口。

## 5. 测试

```bash
pytest -q
```

## 6. 目录结构

```text
app/
  main.py        # FastAPI 入口
  vision.py      # Gemini/Mock 图片解析
  rules.py       # 规则引擎
  storage.py     # SQLite 存储
  reporting.py   # 日报统计与可视化
  models.py      # 数据模型
tests/
  test_rules.py
  test_api.py
reports/
data/
```
