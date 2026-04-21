# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI-assisted Chinese futures (期货) trading decision system. Uses a dual LLM (Gemini + DeepSeek) consensus engine combined with rule-based risk control to generate trading signals from chart screenshots. Includes a separate screenshot capture service that feeds into the main decision API.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run main decision API (port 8000)
uvicorn app.main:app --reload --port 8000

# Run screenshot capture service (port 8999)
python main.py

# Run all tests
pytest -q

# Run a single test file
pytest tests/test_rules.py -q

# Run a specific test
pytest tests/test_rules.py::test_bearish_short_signal_with_market_confirmed -v
```

## Architecture

Two separate FastAPI services:

1. **Decision API** (`app/main.py`, port 8000) - Core trading signal pipeline
2. **Screenshot Service** (`main.py` at root, port 8999) - Captures screen via `mss`, returns JPEG

### Decision Pipeline Flow

```
Image Upload → Vision Parser (Gemini/mock) → Multi-timeframe Fusion → Hybrid Decision → SQLite Storage → Daily Report
```

**Key modules:**

- `app/vision.py` - Gemini image parsing with mock fallback; `fuse_parsed_signals()` does weighted-average fusion across timeframes (weights: 5m=1.0, 15m=1.8, 30m=2.6, 60m=3.4). Dominant timeframe picked by cumulative weight.
- `app/rules.py` - Pure rule engine: MA排列 → trend inference, MACD momentum, Fibonacci price retracement (0.236-0.786), Fibonacci time windows (0.618/1.0/1.618), market regime filter (Wenhua Index 30m→15m).
- `app/llm_decision.py` - `hybrid_decision()`: calls both Gemini and DeepSeek, ensembles via `_ensemble_decision()` (disagreement → wait), then applies 80% LLM / 20% rule risk-control veto. User rules injected from `config/user_rules.md` or `USER_RULES_TEXT` env var.
- `app/models.py` - All Pydantic v2 models: `ParsedImageSignal`, `DecisionRequest`, `DecisionResult`, `SignalAction` enum, `DailyStats`.
- `app/storage.py` - SQLite persistence at `data/signals.db`. Signal CRUD + outcome tracking.
- `app/reporting.py` - Daily performance stats (win rate, profit factor, max drawdown), equity curve PNG via matplotlib, HTML report.

### API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v1/parse-image` | POST | Parse chart screenshot to structured data |
| `/api/v1/decision` | POST | Rule+LLM decision from parsed data |
| `/api/v1/signal-from-image` | POST | One-shot: parse + decide + store |
| `/api/v1/signal-from-images` | POST | Multi-timeframe images → fusion → decision |
| `/api/v1/signals/{id}/outcome` | PATCH | Backfill actual trade outcome |
| `/api/v1/report/daily` | GET | Daily stats JSON |
| `/api/v1/report/daily/html` | GET | Daily HTML report with equity chart |
| `/api/screenshot` (port 8999) | GET | Screen capture as JPEG |

## Environment Variables

- `GEMINI_API_KEY` - Required for image parsing and LLM decision; without it, mock data is used
- `GEMINI_MODEL` - Default: `gemini-2.5-pro`
- `DEEPSEEK_API_KEY` - Required for second LLM opinion
- `DEEPSEEK_BASE_URL` - Default: `https://api.deepseek.com/chat/completions`
- `DEEPSEEK_MODEL` - Default: `deepseek-chat`
- `USER_RULES_TEXT` - Override user trading rules (falls back to `config/user_rules.md`)

## Testing

Tests use `pytest` with `monkeypatch` for mocking LLM calls. Key test patterns:

- `test_rules.py` - Tests rule engine directly with constructed `ParsedImageSignal`
- `test_llm_decision.py` - Mocks `_collect_model_decisions` to test ensemble logic (consensus, disagreement fallback)
- `test_api.py` - FastAPI `TestClient` health check
- `test_multi_image.py` - Tests `fuse_parsed_signals` weight logic and multi-image endpoint

## Domain Concepts

- **Wenhua Index (文华指数)**: Market-wide commodity index used as directional filter before individual symbol analysis. 30m sets direction, 15m confirms.
- **Signal actions**: wait, long, short, hold_long, hold_short, reduce_long, reduce_short
- **Market regime filter**: When `require_market_filter=true`, the system won't open positions unless the broad market direction is confirmed. Disagreement between 30m and 15m → wait.
- **Fibonacci analysis**: Price retracement levels for entry/stop-loss/take-profit; time windows for estimating trend remaining duration.
