"""api.py — 前端資料 API（皆需 Bearer token）"""
from __future__ import annotations

import requests as rq
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .. import auth, store
from ..sources import binance

router = APIRouter(prefix="/api", dependencies=[Depends(auth.require_auth)])

ALLOWED_INTERVALS = {"15m", "1h", "4h", "1d"}


@router.get("/snapshot")
def get_snapshot():
    snap = store.load()
    if snap is None:
        raise HTTPException(503, "資料尚未就緒，請稍候（等待第一輪刷新）")
    return snap


@router.get("/symbol/{symbol}")
def get_symbol(symbol: str):
    snap = store.load()
    if snap is None:
        raise HTTPException(503, "資料尚未就緒")
    for b in snap.get("symbols", []):
        if b["symbol"] == symbol.upper():
            return b
    raise HTTPException(404, f"{symbol} 不在監控清單")


@router.get("/news")
def get_news():
    snap = store.load()
    if snap is None:
        raise HTTPException(503, "資料尚未就緒")
    return {
        "news": snap.get("news"),
        "trump": snap.get("trump"),
        "calendar": snap.get("calendar"),
        "upcoming_events": snap.get("upcoming_events"),
        "event_window": snap.get("event_window"),
    }


@router.get("/klines")
def get_klines(symbol: str = Query(...), interval: str = Query("1h"),
               limit: int = Query(300, le=1000), response: Response = None):
    """K 線 proxy 備援：前端直打 Binance 失敗時降級走這裡。"""
    if interval not in ALLOWED_INTERVALS:
        raise HTTPException(400, f"interval 須為 {ALLOWED_INTERVALS}")
    try:
        df = binance.klines(symbol.upper(), interval, limit)
    except rq.RequestException as ex:
        raise HTTPException(502, f"上游K線抓取失敗: {type(ex).__name__}") from ex
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=30"
    return [
        {"time": int(ts.timestamp()), "open": r["open"], "high": r["high"],
         "low": r["low"], "close": r["close"], "volume": r["volume"]}
        for ts, r in df.iterrows()
    ]
