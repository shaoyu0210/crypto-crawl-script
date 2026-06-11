"""mtf.py — 多時間框架共振判定（純函式）

4h 定方向偏好、1h 找位置、15m 定觸發。
每框輸出 bias: "up" | "down" | "neutral"，三框彙整成共振結論。
"""
from __future__ import annotations


def frame_bias(feats: dict) -> str:
    """單一時間框的方向偏好：EMA 排列為主，通道斜率佐證。"""
    obj = feats.get("objective") or {}
    chan = feats.get("channel") or {}
    ema_state = obj.get("ema_state")
    trend = chan.get("trend") if chan.get("available") else None
    if ema_state == "bull" and trend == "up":
        return "up"
    if ema_state == "bear" and trend == "down":
        return "down"
    return "neutral"


def confluence(feats_15m: dict, feats_1h: dict, feats_4h: dict) -> dict:
    """三框共振判定。aligned: 1h 與 4h 同向（核心條件）；
    trigger_ready: 15m 也同向（進場觸發訊號）。"""
    b15 = frame_bias(feats_15m)
    b1h = frame_bias(feats_1h)
    b4h = frame_bias(feats_4h)

    aligned = b4h != "neutral" and b1h == b4h
    trigger_ready = aligned and b15 == b4h

    if trigger_ready:
        desc = f"三框共振{'看多' if b4h == 'up' else '看空'}（4h/1h/15m 同向）"
    elif aligned:
        desc = f"4h/1h 同向{'偏多' if b4h == 'up' else '偏空'}，15m 未觸發"
    elif b4h != "neutral":
        desc = f"4h {'偏多' if b4h == 'up' else '偏空'}，低框未跟上"
    else:
        desc = "各框方向不一致，無共振"

    return {
        "bias_15m": b15,
        "bias_1h": b1h,
        "bias_4h": b4h,
        "aligned": aligned,
        "trigger_ready": trigger_ready,
        "desc": desc,
    }
