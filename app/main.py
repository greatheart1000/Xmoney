from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .models import DecisionRequest, DecisionResult, OutcomeUpdate
from .reporting import to_response
from .llm_decision import hybrid_decision
from .storage import fetch_signal, fetch_signals_by_date, init_db, insert_signal, update_outcome
from .vision import parse_image_with_gemini

app = FastAPI(title="AI Futures Decision System", version="1.0.0")


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/v1/parse-image")
async def parse_image(symbol: str, timeframe: str, image: UploadFile = File(...)) -> dict:
    data = await image.read()
    parsed = parse_image_with_gemini(data, symbol=symbol, timeframe=timeframe)
    return parsed.model_dump()


@app.post("/api/v1/decision", response_model=DecisionResult)
def decision(req: DecisionRequest) -> DecisionResult:
    return hybrid_decision(req)


@app.post("/api/v1/signal-from-image")
async def signal_from_image(
    symbol: str,
    timeframe: str,
    position: str = "flat",
    image: UploadFile = File(...),
) -> dict:
    data = await image.read()
    parsed = parse_image_with_gemini(data, symbol=symbol, timeframe=timeframe)
    req = DecisionRequest(parsed=parsed, position=position)
    result = hybrid_decision(req)

    record = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "symbol": parsed.symbol,
        "timeframe": parsed.timeframe,
        "position": position,
        "trend": result.trend.value,
        "action": result.action.value,
        "confidence": result.confidence,
        "payload": {
            "parsed": parsed.model_dump(),
            "decision": result.model_dump(),
        },
        "outcome_return": None,
    }
    signal_id = insert_signal(record)
    return {"signal_id": signal_id, "parsed": parsed, "decision": result}


@app.patch("/api/v1/signals/{signal_id}/outcome")
def patch_signal_outcome(signal_id: int, payload: OutcomeUpdate) -> dict:
    found = fetch_signal(signal_id)
    if not found:
        raise HTTPException(status_code=404, detail="Signal not found")
    ok = update_outcome(signal_id, payload.outcome_return)
    return {"updated": ok, "signal_id": signal_id, "outcome_return": payload.outcome_return}


@app.get("/api/v1/report/daily")
def daily_report(date: str) -> dict:
    rows = fetch_signals_by_date(date)
    report = to_response(date, rows)
    return report.model_dump()


@app.get("/api/v1/report/daily/html")
def daily_report_html(date: str):
    rows = fetch_signals_by_date(date)
    report = to_response(date, rows)
    return FileResponse(report.html_path)
