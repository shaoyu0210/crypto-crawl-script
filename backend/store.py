"""store.py — snapshot 存取層

三層：記憶體（60s TTL）→ GCS（生產）或本機檔（LOCAL_MODE 開發）。
讀取永遠不打外部 API；snapshot 只由 /tasks/refresh 管線寫入。
"""
from __future__ import annotations

import json
import os
import threading
import time

from . import config

_lock = threading.Lock()
_mem: dict | None = None
_mem_at: float = 0.0
MEM_TTL = 60


def _gcs_blob():
    from google.cloud import storage   # 延遲 import，本機模式不需安裝憑證
    client = storage.Client()
    return client.bucket(config.GCS_BUCKET).blob("snapshot.json")


def save(snapshot: dict) -> None:
    global _mem, _mem_at
    payload = json.dumps(snapshot, ensure_ascii=False)
    if config.LOCAL_MODE:
        tmp = config.LOCAL_SNAPSHOT_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, config.LOCAL_SNAPSHOT_PATH)
    else:
        _gcs_blob().upload_from_string(payload, content_type="application/json")
    with _lock:
        _mem = snapshot
        _mem_at = time.time()


def load(allow_stale_mem: bool = False) -> dict | None:
    """讀取順序：記憶體（<60s 或 allow_stale）→ GCS / 本機檔。"""
    global _mem, _mem_at
    with _lock:
        if _mem is not None and (allow_stale_mem or time.time() - _mem_at < MEM_TTL):
            return _mem
    data: dict | None = None
    try:
        if config.LOCAL_MODE:
            if os.path.exists(config.LOCAL_SNAPSHOT_PATH):
                with open(config.LOCAL_SNAPSHOT_PATH, encoding="utf-8") as f:
                    data = json.load(f)
        else:
            blob = _gcs_blob()
            if blob.exists():
                data = json.loads(blob.download_as_text())
    except Exception:   # noqa: BLE001 — 讀不到視為尚無快照
        data = None
    if data is not None:
        with _lock:
            _mem = data
            _mem_at = time.time()
    return data
