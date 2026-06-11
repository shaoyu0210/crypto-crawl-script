"""alerts.py — 警報引擎

刷新管線每輪呼叫 check_and_push()：
  比對本輪 snapshot 狀態 → 生成警報 → 指紋去重 + 冷卻 → 推 Discord。

指紋狀態存在 snapshot["alert_state"]（{fingerprint: expiry_epoch}），
跨輪由管線從上一份 snapshot 帶入，scale-to-zero 也不丟失。
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import requests

from . import config

COLORS = {"gold": 0xF1C40F, "red": 0xE74C3C, "green": 0x2ECC71,
          "blue": 0x3498DB, "purple": 0x9B59B6, "gray": 0x95A5A6}


def _fp_alive(state: dict, fp: str, now_ts: float) -> bool:
    return state.get(fp, 0) > now_ts


def _mark(state: dict, fp: str, now_ts: float, hours: float) -> None:
    state[fp] = now_ts + hours * 3600


def collect_alerts(snapshot: dict, alert_state: dict) -> list[dict]:
    """回傳 [{fingerprint, title, body, color}]，已過濾冷卻中的。"""
    cfg = config.ALERT_CFG
    now_ts = time.time()
    cooldown = cfg["cooldown_hours"]
    out = []

    def add(fp: str, title: str, body: str, color: str, hours: float = cooldown):
        if _fp_alive(alert_state, fp, now_ts):
            return
        _mark(alert_state, fp, now_ts, hours)
        out.append({"fingerprint": fp, "title": title, "body": body, "color": color})

    for sym in snapshot.get("symbols", []):
        s = sym["symbol"]
        assess = sym.get("assessment") or {}
        setup = sym.get("setup")
        derivs = sym.get("derivs") or {}

        edge = assess.get("verified_signal")
        if edge:
            add(f"edge:{s}", f"🟡 {s} verified edge：{edge['label']}",
                f"{assess['direction']}\n{edge['risk_note']}", "gold")

        if setup and setup["rr1"] >= config.SETUP_CFG["alert_rr"]:
            if setup["status"] == "active":
                t1 = setup["targets"][0]
                add(f"setup_active:{s}:{setup['side']}",
                    f"🎯 {s} 進場區觸及：{setup['type']}",
                    (f"進場 {setup['entry_low']:g}–{setup['entry_high']:g}｜"
                     f"止損 {setup['stop']:g}｜目標1 {t1['price']:g} (R/R {setup['rr1']})\n"
                     f"{setup['mtf']}\n⚠ {setup['disclaimer']}"),
                    "purple")
            elif setup["status"] == "watch":
                add(f"setup_new:{s}:{setup['side']}",
                    f"👀 {s} 新 setup：{setup['type']}（接近中）",
                    (f"進場 {setup['entry_low']:g}–{setup['entry_high']:g}｜"
                     f"R/R {setup['rr1']}｜{'、'.join(setup['confluences'])}\n"
                     f"⚠ {setup['disclaimer']}"),
                    "blue")

        event = assess.get("event")
        if event:
            add(f"event:{s}:{event['kind']}", f"{'🟢' if event['kind'] == 'pump' else '🔴'} {s} {event['label']}",
                f"近 3h {event['ret_pct']:+.1f}%，事件警示非進場訊號",
                "green" if event["kind"] == "pump" else "red")

        oi_1h = derivs.get("oi_chg_1h_pct")
        if oi_1h is not None and abs(oi_1h) >= cfg["oi_change_alert_pct"]:
            add(f"oi:{s}:{'up' if oi_1h > 0 else 'dn'}",
                f"📊 {s} OI 1h {oi_1h:+.1f}% 異動",
                f"未平倉量急{'增' if oi_1h > 0 else '減'}，留意行情發動或平倉潮", "blue")

        if derivs.get("liquidation_suspect"):
            add(f"liq:{s}", f"⚡ {s} 疑似清算掃損",
                "OI 驟降 + 長影線 + 爆量（免費數據近似判定，標示為「疑似」）", "red")

        prox = sym.get("level_proximity")
        if prox:
            add(f"level:{s}:{prox['label']}:{prox['side']}",
                f"📍 {s} 接近{prox['label']}",
                f"現價 {sym['price']:g} 距 {prox['price']:g} 約 {prox['dist_pct']:.2f}%", "gray")

    for post in (snapshot.get("trump") or {}).get("posts", []):
        if post.get("market_related"):
            add(f"trump:{post['url']}", "🦅 川普市場相關發文",
                f"{post['title'][:200]}\n關鍵字：{', '.join(post['hits'])}\n{post['url']}",
                "gold", hours=24)

    now = datetime.now(timezone.utc)
    for ev in snapshot.get("upcoming_events", []):
        try:
            dt = datetime.fromisoformat(ev["time_utc"])
        except (KeyError, ValueError):
            continue
        mins = (dt - now).total_seconds() / 60
        if ev.get("impact") == "high" and 0 <= mins <= cfg["event_warn_min"]:
            add(f"econ:{ev['title']}:{ev['time_utc']}",
                f"⏰ {int(mins)} 分鐘後：{ev['title']}",
                "高影響事件窗口，慎入場、留意滑點與插針", "red", hours=3)

    return out


def push_discord(alerts: list[dict]) -> str:
    """合併推送一則訊息（多 embed），避免 webhook rate limit。"""
    if not alerts:
        return "no_alerts"
    if not config.DISCORD_WEBHOOK_URL:
        return "no_webhook"
    embeds = [{"title": a["title"][:256], "description": a["body"][:2000],
               "color": COLORS.get(a["color"], COLORS["gray"])}
              for a in alerts[:10]]
    try:
        r = requests.post(config.DISCORD_WEBHOOK_URL, json={"embeds": embeds},
                          timeout=config.REQUEST_TIMEOUT)
        return "ok" if r.status_code in (200, 204) else f"http_{r.status_code}"
    except Exception as ex:   # noqa: BLE001
        return f"error_{type(ex).__name__}"


def prune_state(alert_state: dict) -> dict:
    """清掉過期指紋，控制 snapshot 大小。"""
    now_ts = time.time()
    return {fp: exp for fp, exp in alert_state.items() if exp > now_ts}
