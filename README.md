# AI 辅助期货决策系统

该项目实现了你要求的一整套流程：

- 图片解析接口（支持 Gemini + Mock 回退）
- 规则决策接口（MA/MACD/持仓量风格规则）
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
    "confidence": 0.75,
    "raw_features": {}
  },
  "position": "flat",
  "risk_per_trade": 0.01
}
```

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
