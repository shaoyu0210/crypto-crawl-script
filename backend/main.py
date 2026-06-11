"""main.py — FastAPI 入口：API + 靜態 SPA 同一服務

開發：uvicorn backend.main:app --reload（前端另跑 npm run dev，Vite proxy /api）
生產：Dockerfile 把前端 build 產物放進 backend/static/，由本服務直接 serve。
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import store
from .routers import api, auth_routes, tasks

app = FastAPI(title="crypto-agent", docs_url=None, redoc_url=None)

app.include_router(auth_routes.router)
app.include_router(api.router)
app.include_router(tasks.router)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.on_event("startup")
def warm_snapshot():
    """冷啟動先從 GCS/本機檔載入上次快照，手機開頁面立即有資料。"""
    store.load()


STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.api_route("/{path:path}", methods=["GET", "HEAD"])
    def spa(path: str):
        """SPA fallback：非 API 路徑一律回 index.html。"""
        full = os.path.join(STATIC_DIR, path)
        if path and os.path.isfile(full):
            if path.endswith(".webmanifest"):
                return FileResponse(full, media_type="application/manifest+json")
            return FileResponse(full)
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
