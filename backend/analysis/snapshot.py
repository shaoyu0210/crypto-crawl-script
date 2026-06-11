"""snapshot.py — 刷新管線 orchestrator

Cloud Scheduler 每 5 分鐘觸發一次：
  標的清單 → 行情/籌碼抓取 → 特徵/regime/MTF/levels/setup/評分
  → RS 排名 → 新聞/川普/日曆（節流）→ 事件窗口 → 警報 → 存 snapshot。

韌性原則：單一標的或單一來源失敗只記入 data_health，不讓整輪刷新失敗。
"""
from __future__ import annotations

import time
import traceback
from datetime import datetime, timezone

import pandas as pd

from .. import alerts, config, store
from ..sources import binance, bybit, econ_calendar, news, trump
from . import features, levels, mtf, regime, scoring, setups


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base_of(symbol: str) -> str:
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def _ret_pct(close: pd.Series, bars: int) -> float | None:
    if len(close) <= bars:
        return None
    prev = close.iloc[-1 - bars]
    return round((float(close.iloc[-1]) / float(prev) - 1) * 100, 2) if prev else None


# ── 籌碼抓取（Binance → Bybit fallback） ─────────────────────────────

def _fetch_funding(health: dict) -> dict[str, float]:
    try:
        rates = binance.all_funding_rates()
        health["funding"] = "ok(binance)"
        return rates
    except Exception:   # noqa: BLE001
        try:
            rates = bybit.all_funding_rates()
            health["funding"] = "ok(bybit)"
            return rates
        except Exception as ex:   # noqa: BLE001
            health["funding"] = f"fail({type(ex).__name__})"
            return {}


def _fetch_oi(symbol: str) -> tuple[list[dict], str]:
    try:
        return binance.open_interest_hist(symbol), "binance"
    except Exception:   # noqa: BLE001
        try:
            return bybit.open_interest_hist(symbol), "bybit"
        except Exception:   # noqa: BLE001
            return [], "fail"


def _fetch_lsr(symbol: str) -> float | None:
    try:
        rows = binance.long_short_ratio(symbol)
    except Exception:   # noqa: BLE001
        try:
            rows = bybit.long_short_ratio(symbol)
        except Exception:   # noqa: BLE001
            return None
    return rows[-1]["ratio"] if rows else None


def _fetch_taker(symbol: str) -> float | None:
    """合約 taker buy/sell ratio → 轉成 buy 占比（0~1）對齊現貨口徑。"""
    try:
        rows = binance.taker_ratio_futures(symbol)
        if rows:
            r = rows[-1]["ratio"]
            return round(r / (1 + r), 4)
    except Exception:   # noqa: BLE001
        pass
    return None


# ── 籌碼衍生計算 ─────────────────────────────────────────────────────

def _oi_changes(oi_hist: list[dict]) -> tuple[float | None, float | None]:
    """回傳 (24h 變化%, 1h 變化%)。oi_hist 為 5m 粒度、舊到新。"""
    if len(oi_hist) < 13:
        return None, None
    last = oi_hist[-1]["oi"]
    chg_24h = None
    if oi_hist[0]["oi"]:
        chg_24h = round((last / oi_hist[0]["oi"] - 1) * 100, 2)
    chg_1h = None
    if oi_hist[-13]["oi"]:
        chg_1h = round((last / oi_hist[-13]["oi"] - 1) * 100, 2)
    return chg_24h, chg_1h


def _oi_quadrant(oi_chg: float | None, price_chg: float | None) -> str | None:
    if oi_chg is None or price_chg is None:
        return None
    if price_chg >= 0:
        return "增倉上漲（多頭進場）" if oi_chg >= 0 else "縮倉上漲（空頭回補）"
    return "增倉下跌（空頭進場）" if oi_chg >= 0 else "縮倉下跌（多頭離場）"


def _liquidation_suspect(oi_hist: list[dict], df_15m: pd.DataFrame) -> bool:
    """OI 15 分鐘驟降 >2.5% + 最近 15m K 長影線 + 爆量 → 疑似清算掃損。"""
    if len(oi_hist) < 4 or len(df_15m) < 30:
        return False
    last, prev3 = oi_hist[-1]["oi"], oi_hist[-4]["oi"]
    if not prev3 or (last / prev3 - 1) * 100 > -2.5:
        return False
    bar = df_15m.iloc[-1]
    rng = bar["high"] - bar["low"]
    body = abs(bar["close"] - bar["open"])
    atr15 = features.atr(df_15m, 14).iloc[-1]
    vol_ma = df_15m["volume"].iloc[-21:-1].mean()
    long_wick = rng > 0 and body / rng < 0.5 and atr15 and rng > 1.8 * atr15
    vol_spike = vol_ma and bar["volume"] > 2.0 * vol_ma
    return bool(long_wick and vol_spike)


def _funding_history(prev_block: dict | None, rate: float | None) -> tuple[list, str | None]:
    """跨輪累積費率序列（零額外請求），給趨勢方向。"""
    hist = list(((prev_block or {}).get("derivs") or {}).get("funding_history") or [])
    if rate is not None:
        hist.append({"ts": int(time.time()), "rate": rate})
        hist = hist[-12:]   # 保留近 1 小時（5min × 12）
    trend = None
    if len(hist) >= 4:
        delta = hist[-1]["rate"] - hist[-4]["rate"]
        if abs(delta) >= 0.00003:
            neg = hist[-1]["rate"] < 0
            if delta < 0:
                trend = "擁擠加劇（更負）" if neg else "降溫"
            else:
                trend = "擁擠緩解" if neg else "多頭擁擠升溫"
        else:
            trend = "穩定"
    return hist, trend


# ── 單一標的完整建構 ─────────────────────────────────────────────────

def build_symbol_block(symbol: str, funding_map: dict, prev_block: dict | None,
                       news_data: dict | None) -> dict:
    dfs: dict[str, pd.DataFrame] = {}
    for tf, limit in config.KLINE_LIMITS.items():
        dfs[tf] = binance.klines(symbol, tf, limit)
        binance.sleep_throttle()

    fcfg = config.FEATURE_CFG
    feats = {tf: features.compute_features(dfs[tf], fcfg) for tf in dfs}
    for tf, f in feats.items():
        if "error" in f:
            raise RuntimeError(f"{symbol} {tf} 特徵失敗: {f['error']}")

    reg = regime.detect_regime(dfs[config.TF_TREND], feats[config.TF_TREND], config.REGIME_CFG)
    conf = mtf.confluence(feats[config.TF_TRIGGER], feats[config.TF_BASE], feats[config.TF_TREND])
    lv_cfg = {**config.LEVELS_CFG, "swing_k": fcfg["swing_k"]}
    lvls = levels.build_levels(dfs[config.TF_BASE], feats[config.TF_BASE], lv_cfg)

    funding = funding_map.get(symbol)
    funding_hist, funding_trend = _funding_history(prev_block, funding)

    oi_hist, oi_src = _fetch_oi(symbol)
    binance.sleep_throttle()
    lsr = _fetch_lsr(symbol)
    binance.sleep_throttle()
    taker_fut = _fetch_taker(symbol)
    binance.sleep_throttle()
    try:
        depth = binance.depth_imbalance(symbol)
    except Exception:   # noqa: BLE001
        depth = {"available": False}

    close_1h = dfs[config.TF_BASE]["close"]
    price_chg_24h = _ret_pct(close_1h, 24)
    oi_chg_24h, oi_chg_1h = _oi_changes(oi_hist)

    base = _base_of(symbol)
    news_sent = None
    if news_data and news_data.get("available"):
        pc = (news_data.get("per_coin") or {}).get(base)
        if pc and pc.get("count"):
            news_sent = pc.get("avg_sentiment")

    obj_1h = feats[config.TF_BASE]["objective"]
    facts = {
        "funding": funding,
        "lsr": lsr,
        "taker_ratio": taker_fut if taker_fut is not None else obj_1h.get("taker_buy_ratio"),
        "oi_chg_pct": oi_chg_24h,
        "price_chg_pct": price_chg_24h,
        "rsi": obj_1h.get("rsi"),
        "channel": feats[config.TF_BASE]["channel"],
        "news_sentiment": news_sent,
    }
    is_core = symbol in config.CORE_SYMBOLS
    assessment = scoring.assess(symbol, feats[config.TF_BASE], facts, reg, is_core,
                                config.FUNDING_EDGE, config.SCORE_WEIGHTS,
                                config.EVENT_SPIKE_PCT)
    setup = setups.generate_setup(symbol, dfs[config.TF_BASE], feats[config.TF_BASE],
                                  reg, conf, lvls, config.SETUP_CFG)

    price = feats[config.TF_BASE]["price"]
    atr_val = feats[config.TF_BASE]["atr"]
    level_prox = None
    if price and atr_val:
        for lv in lvls:
            if lv["strength"] >= 3.0 and abs(price - lv["price"]) <= config.ALERT_CFG["level_proximity_atr"] * atr_val:
                level_prox = {"label": lv["label"], "price": lv["price"], "side": lv["side"],
                              "dist_pct": abs(price - lv["price"]) / price * 100}
                break

    return {
        "symbol": symbol,
        "base": base,
        "is_core": is_core,
        "price": price,
        "atr": atr_val,
        "change_24h_pct": price_chg_24h,
        "ret_4h_pct": _ret_pct(close_1h, 4),
        "assessment": assessment,
        "setup": setup,
        "levels": lvls,
        "mtf": conf,
        "regime": reg,
        "level_proximity": level_prox,
        "summary": {
            "rsi": obj_1h.get("rsi"),
            "atr_pct": obj_1h.get("atr_pct_of_price"),
            "vwap": obj_1h.get("vwap"),
            "ema_state": obj_1h.get("ema_state"),
            "volume_mult": obj_1h.get("volume_mult"),
        },
        "derivs": {
            "funding": funding,
            "funding_trend": funding_trend,
            "funding_history": funding_hist,
            "oi_chg_24h_pct": oi_chg_24h,
            "oi_chg_1h_pct": oi_chg_1h,
            "oi_quadrant": _oi_quadrant(oi_chg_24h, price_chg_24h),
            "oi_source": oi_src,
            "lsr": lsr,
            "taker_ratio": facts["taker_ratio"],
            "depth": depth,
            "cvd": feats[config.TF_BASE].get("cvd"),
            "liquidation_suspect": _liquidation_suspect(oi_hist, dfs[config.TF_TRIGGER]),
        },
        "fib": feats[config.TF_BASE]["fibonacci"],
        "channel": feats[config.TF_BASE]["channel"],
        "news_top": ((news_data or {}).get("per_coin") or {}).get(base, {}).get("top", []),
    }


# ── 排序、RS、事件窗口 ───────────────────────────────────────────────

def _sort_key(block: dict) -> tuple:
    a = block["assessment"]
    setup = block.get("setup")
    if a.get("verified_signal"):
        group = 0
    elif setup and setup["status"] == "active":
        group = 1
    elif setup and setup["status"] == "watch":
        group = 2
    elif a.get("event"):
        group = 3
    else:
        group = 4
    rr = -(setup["rr1"] if setup else 0)
    tend = -abs(a["tendency"]["score"])
    return (group, rr, tend)


def _rs_ranking(blocks: list[dict]) -> dict:
    btc = next((b for b in blocks if b["symbol"] == "BTCUSDT"), None)
    btc_4h = (btc or {}).get("ret_4h_pct") or 0.0
    btc_24h = (btc or {}).get("change_24h_pct") or 0.0
    table = []
    for b in blocks:
        if b["symbol"] == "BTCUSDT":
            continue
        r4, r24 = b.get("ret_4h_pct"), b.get("change_24h_pct")
        if r4 is None or r24 is None:
            continue
        rel = round((r4 - btc_4h) * 0.5 + (r24 - btc_24h) * 0.5, 2)
        table.append({"symbol": b["symbol"], "rel_strength": rel,
                      "ret_4h_pct": r4, "ret_24h_pct": r24})
    table.sort(key=lambda x: x["rel_strength"], reverse=True)
    return {
        "vs": "BTC",
        "strongest": table[:3],
        "weakest": table[-3:][::-1] if len(table) >= 3 else [],
        "table": table,
        "note": "做多看最強、做空看最弱；相對強弱 = 對 BTC 的 4h/24h 超額報酬均值",
    }


def _event_window(events: list[dict]) -> dict | None:
    now = datetime.now(timezone.utc)
    for ev in events:
        if ev.get("impact") != "high":
            continue
        try:
            dt = datetime.fromisoformat(ev["time_utc"])
        except (KeyError, ValueError):
            continue
        mins = (dt - now).total_seconds() / 60
        if -15 <= mins <= 30:
            return {"active": True, "event": ev["title"],
                    "minutes": round(mins),
                    "label": (f"{ev['title']} {abs(round(mins))} 分鐘"
                              f"{'後公布' if mins >= 0 else '前已公布'}，事件窗口慎入場")}
    return None


def _maybe_refresh(prev_data: dict | None, prev_at: str | None,
                   max_age_min: float, fetch_fn) -> tuple[dict, str]:
    """節流：快取未過期直接沿用上一輪結果。"""
    if prev_data and prev_at:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(prev_at)).total_seconds() / 60
            if age < max_age_min:
                return prev_data, prev_at
        except ValueError:
            pass
    return fetch_fn(), _now_iso()


# ── 主入口 ──────────────────────────────────────────────────────────

def refresh() -> dict:
    t0 = time.time()
    prev = store.load(allow_stale_mem=True) or {}
    prev_symbols = {b["symbol"]: b for b in prev.get("symbols", [])}
    health: dict[str, str] = {}
    errors: list[str] = []

    funding_map = _fetch_funding(health)

    try:
        tops = binance.top_usdt_symbols(config.TOP_N, config.STABLE_BASES)
        health["top_symbols"] = "ok"
    except Exception as ex:   # noqa: BLE001
        tops = []
        health["top_symbols"] = f"fail({type(ex).__name__})"
    # 只留有永續合約的熱門標的（在費率表中 = 有永續）
    if funding_map:
        tops = [s for s in tops if s in funding_map]
    symbols = config.CORE_SYMBOLS + [s for s in tops if s not in config.CORE_SYMBOLS]

    meta_prev = prev.get("meta") or {}
    news_data, news_at = _maybe_refresh(
        prev.get("news"), meta_prev.get("news_at"), config.NEWS_REFRESH_MIN,
        lambda: news.fetch_news_sentiment(
            [_base_of(s) for s in symbols], config.NEWS_WINDOW_HOURS))
    trump_data, trump_at = _maybe_refresh(
        prev.get("trump"), meta_prev.get("trump_at"), config.NEWS_REFRESH_MIN,
        trump.fetch_trump_posts)
    cal_data, cal_at = _maybe_refresh(
        prev.get("calendar"), meta_prev.get("calendar_at"),
        config.CALENDAR_REFRESH_HOURS * 60, econ_calendar.fetch_calendar)
    health["news"] = "ok" if news_data.get("available") else "fail"
    health["trump"] = "ok" if trump_data.get("available") else f"fail({trump_data.get('error')})"
    health["calendar"] = cal_data.get("source", "fail")

    blocks: list[dict] = []
    for sym in symbols:
        try:
            blocks.append(build_symbol_block(sym, funding_map, prev_symbols.get(sym), news_data))
            health[f"symbol:{sym}"] = "ok"
        except Exception as ex:   # noqa: BLE001 — 單標的失敗不毀全局
            health[f"symbol:{sym}"] = f"fail({type(ex).__name__})"
            errors.append(f"{sym}: {ex}\n{traceback.format_exc(limit=2)}")
            stale = prev_symbols.get(sym)
            if stale:
                stale = dict(stale)
                stale["stale"] = True
                blocks.append(stale)

    blocks.sort(key=_sort_key)

    btc = next((b for b in blocks if b["symbol"] == "BTCUSDT"), None)
    btc_ctx = None
    if btc:
        btc_ctx = {
            "price": btc["price"],
            "change_24h_pct": btc["change_24h_pct"],
            "regime": btc["regime"],
            "bias_4h": btc["mtf"]["bias_4h"],
            "uncertain": btc["mtf"]["bias_4h"] == "neutral",
            "note": "BTC 方向不明時，山寨 setup 可信度下降" if btc["mtf"]["bias_4h"] == "neutral" else None,
        }

    events = cal_data.get("events", [])
    ev_window = _event_window(events)

    snapshot = {
        "meta": {
            "generated_at": _now_iso(),
            "took_ms": None,   # 最後補
            "symbols": [b["symbol"] for b in blocks],
            "data_health": health,
            "errors": errors[:5],
            "news_at": news_at,
            "trump_at": trump_at,
            "calendar_at": cal_at,
            "verified_signal_note": "唯一通過驗證：極端負費率→反彈（條件性弱edge，-0.02%甜蜜點）；"
                                    "setup 與傾向分數均為規則化推導，未經回測",
        },
        "btc": btc_ctx,
        "event_window": ev_window,
        "upcoming_events": events,
        "rs": _rs_ranking(blocks),
        "symbols": blocks,
        "news": news_data,
        "trump": trump_data,
        "calendar": cal_data,
        "alert_state": alerts.prune_state(prev.get("alert_state") or {}),
    }

    alert_state = snapshot["alert_state"]
    new_alerts = alerts.collect_alerts(snapshot, alert_state)
    snapshot["meta"]["alerts_pushed"] = len(new_alerts)
    snapshot["meta"]["discord"] = alerts.push_discord(new_alerts)
    snapshot["meta"]["took_ms"] = int((time.time() - t0) * 1000)

    store.save(snapshot)
    return snapshot
