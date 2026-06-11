"""levels.py — 關鍵價位引擎（純函式）

彙整短線交易者實際會看的價位：swing 聚類壓撐、前日/前週高低、
斐波回撤位、回歸通道軌、整數心理關卡、當日 VWAP。
輸出統一結構供 setup 計算與前端疊圖使用：
  {"price", "kind", "label", "strength", "side"}
side: "support" | "resistance" | "both"（依當前價自動判定）
"""
from __future__ import annotations

import math

import pandas as pd

from . import features


def _side(price: float, level: float) -> str:
    return "support" if level <= price else "resistance"


def swing_clusters(df: pd.DataFrame, k: int, cluster_pct: float) -> list[dict]:
    """swing 高低點聚類成壓力/支撐區。觸碰次數 + 量加權 = 強度。"""
    sh, sl = features.find_swings(df, k)
    points = []
    for i in sh:
        points.append((float(df["high"].iloc[i]), float(df["volume"].iloc[i])))
    for i in sl:
        points.append((float(df["low"].iloc[i]), float(df["volume"].iloc[i])))
    if not points:
        return []
    points.sort(key=lambda p: p[0])
    vol_ma = float(df["volume"].mean()) or 1.0

    clusters: list[list[tuple[float, float]]] = []
    for p, v in points:
        if clusters and abs(p - clusters[-1][-1][0]) / p * 100 <= cluster_pct:
            clusters[-1].append((p, v))
        else:
            clusters.append([(p, v)])

    price = float(df["close"].iloc[-1])
    out = []
    for c in clusters:
        center = sum(p for p, _ in c) / len(c)
        touches = len(c)
        vol_w = sum(v for _, v in c) / (vol_ma * touches)
        strength = touches + min(vol_w, 2.0)   # 觸碰次數為主，量為輔
        out.append({
            "price": round(center, 8),
            "kind": "sr_cluster",
            "label": f"壓撐區 ×{touches}",
            "strength": round(strength, 2),
            "side": _side(price, center),
        })
    return out


def period_levels(df: pd.DataFrame) -> list[dict]:
    """前日高/低、前週高/低（UTC 日界）。短線最常被掃的流動性位。"""
    if len(df) == 0:
        return []
    price = float(df["close"].iloc[-1])
    out = []
    daily = df.resample("1D").agg({"high": "max", "low": "min"}).dropna()
    if len(daily) >= 2:
        pd_h, pd_l = float(daily["high"].iloc[-2]), float(daily["low"].iloc[-2])
        out.append({"price": round(pd_h, 8), "kind": "prev_day_high", "label": "前日高",
                    "strength": 3.0, "side": _side(price, pd_h)})
        out.append({"price": round(pd_l, 8), "kind": "prev_day_low", "label": "前日低",
                    "strength": 3.0, "side": _side(price, pd_l)})
    weekly = df.resample("1W").agg({"high": "max", "low": "min"}).dropna()
    if len(weekly) >= 2:
        pw_h, pw_l = float(weekly["high"].iloc[-2]), float(weekly["low"].iloc[-2])
        out.append({"price": round(pw_h, 8), "kind": "prev_week_high", "label": "前週高",
                    "strength": 3.5, "side": _side(price, pw_h)})
        out.append({"price": round(pw_l, 8), "kind": "prev_week_low", "label": "前週低",
                    "strength": 3.5, "side": _side(price, pw_l)})
    return out


def round_numbers(price: float, count: int = 2) -> list[dict]:
    """整數心理關卡：依價格量級取最近的上下各 count 個整數位。"""
    if price <= 0:
        return []
    magnitude = 10 ** (math.floor(math.log10(price)))
    step = magnitude / 2 if price / magnitude < 2 else magnitude
    base = math.floor(price / step) * step
    out = []
    for i in range(-count + 1, count + 1):
        lv = base + i * step
        if lv <= 0 or abs(lv - price) / price > 0.15:
            continue
        out.append({"price": round(lv, 8), "kind": "round", "label": "整數關卡",
                    "strength": 1.5, "side": _side(price, lv)})
    return out


def build_levels(df: pd.DataFrame, feats: dict, cfg: dict) -> list[dict]:
    """彙整全部價位 → 鄰近合併（保留最強）→ 依強度取前 max_levels。"""
    price = feats.get("price")
    if not price:
        return []
    levels: list[dict] = []
    levels += swing_clusters(df, cfg.get("swing_k", 3), cfg["cluster_pct"])
    levels += period_levels(df)
    levels += round_numbers(price, cfg["round_number_count"])

    fib = feats.get("fibonacci") or {}
    if fib.get("available"):
        for lv, p in fib["levels"].items():
            levels.append({"price": p, "kind": "fib", "label": f"斐波 {lv}",
                           "strength": 2.0, "side": _side(price, p)})

    chan = feats.get("channel") or {}
    if chan.get("available"):
        for key, label in (("upper", "通道上軌"), ("mid", "通道中軌"), ("lower", "通道下軌")):
            levels.append({"price": chan[key], "kind": f"channel_{key}", "label": label,
                           "strength": 2.0, "side": _side(price, chan[key])})

    vwap = (feats.get("objective") or {}).get("vwap")
    if vwap:
        levels.append({"price": vwap, "kind": "vwap", "label": "VWAP",
                       "strength": 2.0, "side": _side(price, vwap)})

    # 鄰近合併：距離 < cluster_pct% 視為同一位，保留強度高者並累加 30% 重合加成
    levels.sort(key=lambda x: x["price"])
    merged: list[dict] = []
    for lv in levels:
        if merged and abs(lv["price"] - merged[-1]["price"]) / lv["price"] * 100 <= cfg["cluster_pct"]:
            keep = max(merged[-1], lv, key=lambda x: x["strength"])
            weak = min(merged[-1], lv, key=lambda x: x["strength"])
            keep = dict(keep)
            keep["strength"] = round(keep["strength"] + weak["strength"] * 0.3, 2)
            if weak["label"] not in keep["label"]:
                keep["label"] += f" +{weak['label']}"
            merged[-1] = keep
        else:
            merged.append(dict(lv))

    merged.sort(key=lambda x: x["strength"], reverse=True)
    top = merged[: cfg["max_levels"]]
    top.sort(key=lambda x: x["price"])
    return top


def nearest_levels(levels: list[dict], price: float) -> dict:
    """回傳當前價上下最近的強價位（setup 目標/止損計算用）。"""
    above = [lv for lv in levels if lv["price"] > price]
    below = [lv for lv in levels if lv["price"] <= price]
    return {
        "resistance": min(above, key=lambda x: x["price"]) if above else None,
        "support": max(below, key=lambda x: x["price"]) if below else None,
    }
