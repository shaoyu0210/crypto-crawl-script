"""econ_calendar.py — 經濟指標日曆

主來源：ForexFactory 週日曆 JSON（免 key，含 impact 等級）。
備援：程式內建 FOMC 年度日期表（Fed 官網年初公布）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from .. import config

# 短線加密交易者真正在意的高影響事件關鍵字
KEY_EVENTS = ["cpi", "fomc", "federal funds rate", "non-farm", "nonfarm",
              "unemployment rate", "pce", "gdp", "ppi", "retail sales",
              "fed chair", "powell"]


def _ff_events(days_ahead: int = 7) -> list[dict]:
    r = requests.get(config.FF_CALENDAR_URL, timeout=config.REQUEST_TIMEOUT,
                     headers={"User-Agent": "crypto-agent/2.0"})
    r.raise_for_status()
    now = datetime.now(timezone.utc)
    until = now + timedelta(days=days_ahead)
    out = []
    for ev in r.json():
        try:
            dt = datetime.fromisoformat(ev["date"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone(timezone.utc)
        except (KeyError, ValueError):
            continue
        if dt < now - timedelta(hours=1) or dt > until:
            continue
        title = ev.get("title", "")
        impact = (ev.get("impact") or "").lower()
        country = ev.get("country", "")
        is_key = any(k in title.lower() for k in KEY_EVENTS) and country == "USD"
        if impact != "high" and not is_key:
            continue
        out.append({
            "title": title,
            "country": country,
            "time_utc": dt.isoformat(),
            "impact": impact or ("high" if is_key else "medium"),
            "forecast": ev.get("forecast") or None,
            "previous": ev.get("previous") or None,
        })
    out.sort(key=lambda e: e["time_utc"])
    return out


def _fomc_fallback(days_ahead: int = 30) -> list[dict]:
    now = datetime.now(timezone.utc)
    until = now + timedelta(days=days_ahead)
    out = []
    for d in config.FOMC_DATES_UTC:
        # FOMC 決議固定 18:00 UTC（美東 14:00）公布
        dt = datetime.fromisoformat(d + "T18:00:00+00:00")
        if now - timedelta(hours=3) <= dt <= until:
            out.append({"title": "FOMC 利率決議（內建備援日期）", "country": "USD",
                        "time_utc": dt.isoformat(), "impact": "high",
                        "forecast": None, "previous": None})
    return out


def fetch_calendar(days_ahead: int = 7) -> dict:
    """回傳 {available, source, events}。主來源失敗時退回內建 FOMC 表。"""
    try:
        events = _ff_events(days_ahead)
        return {"available": True, "source": "forexfactory", "events": events}
    except Exception as ex:   # noqa: BLE001
        return {"available": True, "source": f"fomc_fallback ({type(ex).__name__})",
                "events": _fomc_fallback(max(days_ahead, 30)),
                "degraded": True}
