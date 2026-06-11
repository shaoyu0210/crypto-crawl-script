"""binance.py — Binance 行情/籌碼 client（多 base 輪詢 fallback）

現貨：api.binance.com → data-api.binance.vision（官方公開鏡像，較不受地理封鎖）
合約：fapi.binance.com（費率/OI/多空比/taker），失敗由 bybit.py 備援。
所有方法失敗丟例外，由 snapshot 管線決定 fallback 與 data_health 記錄。
"""
from __future__ import annotations

import time

import pandas as pd
import requests

from .. import config

SPOT_BASES = ["https://api.binance.com", "https://data-api.binance.vision"]
FAPI_BASE = "https://fapi.binance.com"

_session = requests.Session()
_session.headers.update({"User-Agent": "crypto-agent/2.0"})


def _get(url: str, params: dict | None = None) -> dict | list:
    r = _session.get(url, params=params, timeout=config.REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _spot_get(path: str, params: dict | None = None) -> dict | list:
    last_err: Exception = RuntimeError("no spot base")
    for base in SPOT_BASES:
        try:
            return _get(f"{base}{path}", params)
        except Exception as e:   # noqa: BLE001 — 換下一個 base
            last_err = e
    raise last_err


def klines(symbol: str, interval: str, limit: int = 300) -> pd.DataFrame:
    """現貨 K 線 → DataFrame(index=UTC, open/high/low/close/volume/taker_buy_base)。"""
    raw = _spot_get("/api/v3/klines",
                    {"symbol": symbol, "interval": interval, "limit": limit})
    cols = ["open_time", "open", "high", "low", "close", "volume", "close_time",
            "qav", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]
    df = pd.DataFrame(raw, columns=cols)
    df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for c in ["open", "high", "low", "close", "volume", "taker_buy_base"]:
        df[c] = df[c].astype(float)
    return df[["open", "high", "low", "close", "volume", "taker_buy_base"]]


def top_usdt_symbols(top_n: int, exclude_bases: set[str]) -> list[str]:
    """24h quote 成交額前 N 的 USDT 交易對（排除穩定幣對、槓桿代幣）。"""
    raw = _spot_get("/api/v3/ticker/24hr")
    rows = []
    for t in raw:
        s = t.get("symbol", "")
        if not s.endswith("USDT"):
            continue
        base = s[:-4]
        if base in exclude_bases:
            continue
        if base.endswith(("UP", "DOWN", "BULL", "BEAR")):   # 槓桿代幣
            continue
        try:
            rows.append((s, float(t.get("quoteVolume", 0))))
        except (TypeError, ValueError):
            continue
    rows.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in rows[:top_n]]


def depth_imbalance(symbol: str, band_pct: float = 1.0) -> dict:
    """現價 ±band_pct% 內的 bid/ask 量比（訂單簿失衡）。"""
    raw = _spot_get("/api/v3/depth", {"symbol": symbol, "limit": 500})
    bids = [(float(p), float(q)) for p, q in raw.get("bids", [])]
    asks = [(float(p), float(q)) for p, q in raw.get("asks", [])]
    if not bids or not asks:
        return {"available": False}
    mid = (bids[0][0] + asks[0][0]) / 2
    lo, hi = mid * (1 - band_pct / 100), mid * (1 + band_pct / 100)
    bid_vol = sum(q for p, q in bids if p >= lo)
    ask_vol = sum(q for p, q in asks if p <= hi)
    total = bid_vol + ask_vol
    if total <= 0:
        return {"available": False}
    return {"available": True,
            "bid_ratio": round(bid_vol / total, 4),   # >0.5 買盤厚
            "band_pct": band_pct}


# ── 合約（籌碼面） ───────────────────────────────────────────────────

def all_funding_rates() -> dict[str, float]:
    """premiumIndex 不帶 symbol 一次拿全部 lastFundingRate。"""
    raw = _get(f"{FAPI_BASE}/fapi/v1/premiumIndex")
    out = {}
    for t in raw:
        try:
            out[t["symbol"]] = float(t["lastFundingRate"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


def open_interest_hist(symbol: str, period: str = "5m", limit: int = 288) -> list[dict]:
    """OI 歷史（近 24h，5m × 288）。回傳 [{ts, oi, oi_value}]。"""
    raw = _get(f"{FAPI_BASE}/futures/data/openInterestHist",
               {"symbol": symbol, "period": period, "limit": limit})
    return [{"ts": int(r["timestamp"]),
             "oi": float(r["sumOpenInterest"]),
             "oi_value": float(r["sumOpenInterestValue"])} for r in raw]


def long_short_ratio(symbol: str, period: str = "1h", limit: int = 24) -> list[dict]:
    """散戶帳戶多空比歷史。回傳 [{ts, ratio}]。"""
    raw = _get(f"{FAPI_BASE}/futures/data/globalLongShortAccountRatio",
               {"symbol": symbol, "period": period, "limit": limit})
    return [{"ts": int(r["timestamp"]), "ratio": float(r["longShortRatio"])} for r in raw]


def taker_ratio_futures(symbol: str, period: str = "1h", limit: int = 24) -> list[dict]:
    """合約 taker 買賣量比歷史。回傳 [{ts, ratio}]（buy/sell vol ratio）。"""
    raw = _get(f"{FAPI_BASE}/futures/data/takerlongshortRatio",
               {"symbol": symbol, "period": period, "limit": limit})
    return [{"ts": int(r["timestamp"]), "ratio": float(r["buySellRatio"])} for r in raw]


def sleep_throttle() -> None:
    time.sleep(config.REQUEST_SLEEP)
