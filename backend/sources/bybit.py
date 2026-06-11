"""bybit.py — Bybit v5 公開端點備援（Binance fapi 被擋時的籌碼面後備）

費率/OI/多空比有對應端點；taker ratio 無對應 → 缺就回 None，評分自動降權。
"""
from __future__ import annotations

import requests

from .. import config

BASE = "https://api.bybit.com"

_session = requests.Session()
_session.headers.update({"User-Agent": "crypto-agent/2.0"})


def _get(path: str, params: dict) -> dict:
    r = _session.get(f"{BASE}{path}", params=params, timeout=config.REQUEST_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if data.get("retCode") != 0:
        raise RuntimeError(f"bybit retCode={data.get('retCode')}: {data.get('retMsg')}")
    return data["result"]


def all_funding_rates() -> dict[str, float]:
    """linear tickers 一次拿全部 fundingRate。symbol 格式與 Binance 相同（如 BTCUSDT）。"""
    res = _get("/v5/market/tickers", {"category": "linear"})
    out = {}
    for t in res.get("list", []):
        try:
            out[t["symbol"]] = float(t["fundingRate"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def open_interest_hist(symbol: str, interval: str = "5min", limit: int = 200) -> list[dict]:
    res = _get("/v5/market/open-interest",
               {"category": "linear", "symbol": symbol,
                "intervalTime": interval, "limit": limit})
    rows = [{"ts": int(r["timestamp"]), "oi": float(r["openInterest"]), "oi_value": None}
            for r in res.get("list", [])]
    rows.reverse()   # Bybit 回傳新到舊，統一成舊到新
    return rows


def long_short_ratio(symbol: str, period: str = "1h", limit: int = 24) -> list[dict]:
    res = _get("/v5/market/account-ratio",
               {"category": "linear", "symbol": symbol, "period": period, "limit": limit})
    rows = []
    for r in res.get("list", []):
        try:
            buy, sell = float(r["buyRatio"]), float(r["sellRatio"])
            if sell > 0:
                rows.append({"ts": int(r["timestamp"]), "ratio": round(buy / sell, 4)})
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
    rows.reverse()
    return rows
