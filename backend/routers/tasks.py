"""tasks.py — Cloud Scheduler 觸發的刷新端點（X-Refresh-Secret 保護）"""
from __future__ import annotations

import hmac
import threading

from fastapi import APIRouter, Header, HTTPException

from .. import config
from ..analysis import snapshot as snapshot_mod

router = APIRouter(prefix="/tasks")

_refresh_lock = threading.Lock()


@router.post("/refresh")
def refresh(x_refresh_secret: str = Header(default="")):
    if not hmac.compare_digest(x_refresh_secret, config.REFRESH_SECRET):
        raise HTTPException(403, "forbidden")
    if not _refresh_lock.acquire(blocking=False):
        return {"ok": False, "reason": "已有刷新進行中，跳過本輪"}
    try:
        snap = snapshot_mod.refresh()
        meta = snap["meta"]
        return {"ok": True, "took_ms": meta["took_ms"],
                "symbols": len(snap["symbols"]),
                "alerts_pushed": meta["alerts_pushed"],
                "discord": meta["discord"],
                "errors": meta["errors"]}
    finally:
        _refresh_lock.release()
