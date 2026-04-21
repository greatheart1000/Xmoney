from __future__ import annotations

import ipaddress
import os
import socket
import traceback
import urllib.request
from datetime import datetime, timezone
from typing import Annotated
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from .llm_decision import (
    hybrid_decision_from_images,
    hybrid_decision_from_images_multi,
    hybrid_decision_multi,
)
from .models import AssetClass, DecisionRequest, DecisionResult, OssImageSignalRequest, OutcomeUpdate
from .reporting import backtest_summary, resolve_period_window, to_response
from .runtime.engine import run_decision_pipeline
from .storage import (
    fetch_signal,
    fetch_signals_between,
    fetch_signals_by_date,
    init_db,
    insert_signal,
    update_outcome,
)
from .vision import (
    fuse_parsed_signals,
    parse_image_with_parallel_vision_models,
    parse_images_with_parallel_vision_models,
)

app = FastAPI(title="AI Futures Decision System", version="1.0.0")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": str(exc),
            "detail": traceback.format_exc(),
            "timestamp": datetime.now().isoformat(),
        },
    )


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


_ALLOWED_IMAGE_HOSTS = {
    h.strip().lower() for h in os.getenv("OSS_IMAGE_ALLOWED_HOSTS", "").split(",") if h.strip()
}


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _is_private_or_local_host(hostname: str) -> bool:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return True

    for family, _, _, _, sockaddr in infos:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return True
    return False


def _validate_external_image_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="image_url must use https")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="image_url host is required")

    host = parsed.hostname.lower()
    if _ALLOWED_IMAGE_HOSTS and host not in _ALLOWED_IMAGE_HOSTS:
        raise HTTPException(status_code=400, detail="image_url host is not allowlisted")
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        raise HTTPException(status_code=400, detail="image_url host is not allowed")
    if _is_private_or_local_host(host):
        raise HTTPException(status_code=400, detail="image_url resolves to a private/local address")
    return url


def _download_image_from_url(url: str) -> bytes:
    opener = urllib.request.build_opener(_NoRedirectHandler())
    next_url = _validate_external_image_url(url)

    for _ in range(5):
        req = urllib.request.Request(next_url, method="GET")
        try:
            with opener.open(req, timeout=25) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if not content_type.startswith("image/"):
                    raise HTTPException(status_code=400, detail="image_url must return image content")
                return resp.read()
        except HTTPError as exc:
            if exc.code not in {301, 302, 303, 307, 308}:
                raise
            location = exc.headers.get("Location")
            if not location:
                raise HTTPException(status_code=400, detail="redirect response missing Location header")
            next_url = _validate_external_image_url(urljoin(next_url, location))

    raise HTTPException(status_code=400, detail="too many redirects for image_url")


def _build_signal_record(
    req: DecisionRequest,
    result: DecisionResult,
    payload: dict,
    *,
    image_uri: str | None = None,
) -> dict:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "symbol": req.parsed.symbol,
        "timeframe": req.parsed.timeframe,
        "position": req.position,
        "asset_class": req.asset_class.value,
        "exchange": req.exchange,
        "instrument_type": req.instrument_type,
        "strategy_id": req.strategy_id,
        "risk_verdict": result.risk_verdict,
        "trend": result.trend.value,
        "action": result.action.value,
        "confidence": result.confidence,
        "payload": payload,
        "image_uri": image_uri,
        "outcome_return": None,
    }


@app.post("/api/v1/parse-image")
async def parse_image(symbol: str, timeframe: str, image: UploadFile = File(...)) -> dict:
    data = await image.read()
    parsed = parse_image_with_parallel_vision_models(data, symbol=symbol, timeframe=timeframe)
    return parsed.model_dump()


@app.post("/api/v1/decision", response_model=DecisionResult)
def decision(req: DecisionRequest) -> DecisionResult:
    result, _ = run_decision_pipeline(req)
    return result


@app.post("/api/v1/decision/multi")
def decision_multi(req: DecisionRequest) -> dict:
    decisions = hybrid_decision_multi(req)
    return {"strategies": {k: v.model_dump() for k, v in decisions.items()}}


@app.post("/api/v1/signal-from-oss-image")
async def signal_from_oss_image(req: OssImageSignalRequest) -> dict:
    image_data = _download_image_from_url(req.image_url)
    parsed = parse_image_with_parallel_vision_models(image_data, symbol=req.symbol, timeframe=req.timeframe)
    decision_req = DecisionRequest(parsed=parsed, position=req.position, asset_class=req.asset_class)
    result = hybrid_decision_from_images(decision_req, image_payloads=[(image_data, req.timeframe)])

    record = _build_signal_record(
        decision_req,
        result,
        {
            "parsed": parsed.model_dump(),
            "decision": result.model_dump(),
        },
        image_uri=req.image_url,
    )
    signal_id = insert_signal(record)
    return {"signal_id": signal_id, "parsed": parsed, "decision": result}


@app.post("/api/v1/signal-from-image")
async def signal_from_image(
    symbol: str,
    timeframe: str,
    position: Annotated[str, Query(pattern="^(flat|long|short)$")] = "flat",
    asset_class: AssetClass = AssetClass.cn_futures,
    image: UploadFile = File(...),
) -> dict:
    data = await image.read()
    parsed = parse_image_with_parallel_vision_models(data, symbol=symbol, timeframe=timeframe)
    req = DecisionRequest(parsed=parsed, position=position, asset_class=asset_class)
    result, runtime_meta = run_decision_pipeline(req)

    record = _build_signal_record(
        req,
        result,
        {
            "parsed": parsed.model_dump(),
            "decision": result.model_dump(),
            "runtime": runtime_meta,
        },
    )
    signal_id = insert_signal(record)
    return {"signal_id": signal_id, "parsed": parsed, "decision": result, "runtime": runtime_meta}


@app.post("/api/v1/signal-from-image/multi")
async def signal_from_image_multi(
    symbol: str,
    timeframe: str,
    position: Annotated[str, Query(pattern="^(flat|long|short)$")] = "flat",
    asset_class: AssetClass = AssetClass.cn_futures,
    image: UploadFile = File(...),
) -> dict:
    data = await image.read()
    parsed = parse_image_with_parallel_vision_models(data, symbol=symbol, timeframe=timeframe)
    req = DecisionRequest(parsed=parsed, position=position, asset_class=asset_class)
    decisions = hybrid_decision_from_images_multi(req, image_payloads=[(data, timeframe)])
    return {"parsed": parsed, "strategies": {k: v.model_dump() for k, v in decisions.items()}}


@app.post("/api/v1/signal-from-images")
async def signal_from_images(
    symbol: str,
    timeframes: str,
    position: str = "flat",
    asset_class: AssetClass = AssetClass.cn_futures,
    images: list[UploadFile] = File(...),
) -> dict:
    frames = [f.strip() for f in timeframes.split(",") if f.strip()]
    if not frames:
        raise HTTPException(status_code=400, detail="timeframes is required, e.g. 5m,15m,30m")
    if len(frames) != len(images):
        raise HTTPException(status_code=400, detail="timeframes count must match images count")

    payloads = []
    for frame, image in zip(frames, images):
        payloads.append((await image.read(), frame))

    parsed_list = parse_images_with_parallel_vision_models(payloads, symbol=symbol)
    fused_parsed = fuse_parsed_signals(parsed_list)
    req = DecisionRequest(parsed=fused_parsed, position=position, asset_class=asset_class)
    result, runtime_meta = run_decision_pipeline(req)

    record = _build_signal_record(
        req,
        result,
        {
            "parsed_list": [p.model_dump() for p in parsed_list],
            "fused_parsed": fused_parsed.model_dump(),
            "decision": result.model_dump(),
            "runtime": runtime_meta,
        },
    )
    signal_id = insert_signal(record)
    return {
        "signal_id": signal_id,
        "parsed_list": parsed_list,
        "fused_parsed": fused_parsed,
        "decision": result,
        "runtime": runtime_meta,
    }


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


@app.get("/api/v1/backtest/summary")
def backtest_summary_api(period: str = "1d") -> dict:
    start_dt, end_dt = resolve_period_window(period=period)
    rows = fetch_signals_between(start_dt.isoformat(), end_dt.isoformat())
    summary = backtest_summary(rows, period_start=start_dt, period_end=end_dt)
    return summary.model_dump()
