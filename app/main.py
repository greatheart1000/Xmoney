from __future__ import annotations

from typing import Annotated
from datetime import datetime, timezone
import ipaddress
import os
import socket
from urllib.parse import urljoin, urlparse
import urllib.request
from urllib.error import HTTPError

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from .models import DecisionRequest, DecisionResult, OssImageSignalRequest, OutcomeUpdate
from .reporting import to_response
from .llm_decision import (
    hybrid_decision,
    hybrid_decision_from_images,
    hybrid_decision_from_images_multi,
    hybrid_decision_multi,
)
from .storage import fetch_signal, fetch_signals_by_date, init_db, insert_signal, update_outcome
from .vision import (
    fuse_parsed_signals,
    parse_image_with_parallel_vision_models,
    parse_images_with_parallel_vision_models,
)

app = FastAPI(title="AI Futures Decision System", version="1.0.0")


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


@app.post("/api/v1/parse-image")
async def parse_image(symbol: str, timeframe: str, image: UploadFile = File(...)) -> dict:
    data = await image.read()
    parsed = parse_image_with_parallel_vision_models(data, symbol=symbol, timeframe=timeframe)
    return parsed.model_dump()


@app.post("/api/v1/decision", response_model=DecisionResult)
def decision(req: DecisionRequest) -> DecisionResult:
    return hybrid_decision(req)


@app.post("/api/v1/decision/multi")
def decision_multi(req: DecisionRequest) -> dict:
    decisions = hybrid_decision_multi(req)
    return {"strategies": {k: v.model_dump() for k, v in decisions.items()}}




@app.post("/api/v1/signal-from-oss-image")
async def signal_from_oss_image(req: OssImageSignalRequest) -> dict:
    image_data = _download_image_from_url(req.image_url)
    parsed = parse_image_with_parallel_vision_models(image_data, symbol=req.symbol, timeframe=req.timeframe)
    decision_req = DecisionRequest(parsed=parsed, position=req.position)
    result = hybrid_decision_from_images(decision_req, image_payloads=[(image_data, req.timeframe)])

    record = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "symbol": parsed.symbol,
        "timeframe": parsed.timeframe,
        "position": req.position,
        "trend": result.trend.value,
        "action": result.action.value,
        "confidence": result.confidence,
        "payload": {
            "parsed": parsed.model_dump(),
            "decision": result.model_dump(),
        },
        "image_uri": req.image_url,
        "outcome_return": None,
    }
    signal_id = insert_signal(record)
    return {"signal_id": signal_id, "parsed": parsed, "decision": result}


@app.post("/api/v1/signal-from-image")
async def signal_from_image(
    symbol: str,
    timeframe: str,
    position: Annotated[str, Query(pattern="^(flat|long|short)$")] = "flat",
    image: UploadFile = File(...),
) -> dict:
    data = await image.read()
    parsed = parse_image_with_parallel_vision_models(data, symbol=symbol, timeframe=timeframe)
    req = DecisionRequest(parsed=parsed, position=position)
    result = hybrid_decision_from_images(req, image_payloads=[(data, timeframe)])

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
        "image_uri": None,
        "outcome_return": None,
    }
    signal_id = insert_signal(record)
    return {"signal_id": signal_id, "parsed": parsed, "decision": result}


@app.post("/api/v1/signal-from-image/multi")
async def signal_from_image_multi(
    symbol: str,
    timeframe: str,
    position: Annotated[str, Query(pattern="^(flat|long|short)$")] = "flat",
    image: UploadFile = File(...),
) -> dict:
    data = await image.read()
    parsed = parse_image_with_parallel_vision_models(data, symbol=symbol, timeframe=timeframe)
    req = DecisionRequest(parsed=parsed, position=position)
    decisions = hybrid_decision_from_images_multi(req, image_payloads=[(data, timeframe)])
    return {"parsed": parsed, "strategies": {k: v.model_dump() for k, v in decisions.items()}}


@app.post("/api/v1/signal-from-images")
async def signal_from_images(
    symbol: str,
    timeframes: str,
    position: str = "flat",
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
    req = DecisionRequest(parsed=fused_parsed, position=position)
    result = hybrid_decision_from_images(req, image_payloads=payloads)

    record = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "timeframe": f"fusion({','.join(frames)})",
        "position": position,
        "trend": result.trend.value,
        "action": result.action.value,
        "confidence": result.confidence,
        "payload": {
            "parsed_list": [p.model_dump() for p in parsed_list],
            "fused_parsed": fused_parsed.model_dump(),
            "decision": result.model_dump(),
        },
        "outcome_return": None,
    }
    signal_id = insert_signal(record)
    return {
        "signal_id": signal_id,
        "parsed_list": parsed_list,
        "fused_parsed": fused_parsed,
        "decision": result,
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
