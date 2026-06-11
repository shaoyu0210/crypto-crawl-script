"""auth.py — PIN 驗證 + HMAC token（stdlib，免 JWT 套件）

token 格式: "<expiry_epoch>.<hmac_sha256(secret, expiry)>"
手機輸入 PIN 一次 → 拿 token 存 localStorage → 之後每個 API 請求帶上。
"""
from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import Header, HTTPException

from . import config

# PIN 暴力嘗試保護（記憶體計數；scale-to-zero 重啟歸零可接受——個人工具）
_fail_count = 0
_lock_until = 0.0
MAX_FAILS = 5
LOCK_SECONDS = 300


def _sign(expiry: int) -> str:
    return hmac.new(config.APP_SECRET.encode(), str(expiry).encode(),
                    hashlib.sha256).hexdigest()


def issue_token() -> str:
    expiry = int(time.time()) + config.TOKEN_TTL_DAYS * 86400
    return f"{expiry}.{_sign(expiry)}"


def verify_token(token: str) -> bool:
    try:
        expiry_str, sig = token.split(".", 1)
        expiry = int(expiry_str)
    except (ValueError, AttributeError):
        return False
    if expiry < time.time():
        return False
    return hmac.compare_digest(sig, _sign(expiry))


def login_with_pin(pin: str) -> str:
    """PIN 正確回傳 token；錯誤丟 401；連錯 5 次鎖 5 分鐘。"""
    global _fail_count, _lock_until
    now = time.time()
    if now < _lock_until:
        raise HTTPException(429, f"嘗試次數過多，{int(_lock_until - now)} 秒後再試")
    if hmac.compare_digest(pin.strip(), config.PIN):
        _fail_count = 0
        return issue_token()
    _fail_count += 1
    if _fail_count >= MAX_FAILS:
        _lock_until = now + LOCK_SECONDS
        _fail_count = 0
    raise HTTPException(401, "PIN 碼錯誤")


def require_auth(authorization: str = Header(default="")) -> None:
    """FastAPI dependency：檢查 Authorization: Bearer <token>。"""
    token = authorization.removeprefix("Bearer ").strip()
    if not token or not verify_token(token):
        raise HTTPException(401, "未授權，請重新輸入 PIN")
