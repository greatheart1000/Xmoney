# AI 辅助期货决策系统

该项目实现了你要求的一整套流程（已按“先看文华指数大盘，再看单品种”执行）：

- 图片解析接口（Gemini + Mock 回退）
- 决策接口（默认 Gemini + DeepSeek 双模型共识 80% + 规则风控 20%）
- 规则决策接口（MA/MACD/持仓量 + 斐波那契回调 支撑/压力规则）
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

用户规则注入来源（优先级）：
1. 环境变量 `USER_RULES_TEXT`
2. 文件 `config/user_rules.md`

你可以把自己的交易规则持续写入 `config/user_rules.md`，LLM每次决策都会自动注入。

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

### 4.3 一步生成信号（解析+决策+落库）

`POST /api/v1/signal-from-image?symbol=SA605&timeframe=5m&position=flat`

multipart 上传 `image`。

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
