"""regime.py — 波動率環境判別（純函式）

短線第一過濾器：先判斷市場環境，再決定用哪種打法。
- trend: 趨勢市 → 只給順勢回調 setup，均值回歸因子降權
- range: 盤整市 → 只給區間邊緣反打 setup，追突破因子降權
- squeeze: 擠壓 → 醞釀突破，不給方向

判別依據（4h 框）：ATR 百分位（對比近 30 天）+ ADX + 通道斜率顯著性。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import features


def detect_regime(df_4h: pd.DataFrame, feats_4h: dict, cfg: dict) -> dict:
    """回傳 {"regime", "atr_pctile", "adx", "trend_dir", "desc"}。"""
    obj = feats_4h.get("objective") or {}
    chan = feats_4h.get("channel") or {}
    adx_now = obj.get("adx") or 0.0

    atr_s = features.atr(df_4h, 14).dropna()
    window = min(cfg["atr_pctile_window"], len(atr_s))
    atr_pctile = None
    if window >= 30:
        recent = atr_s.iloc[-window:]
        atr_pctile = round(float((recent < atr_s.iloc[-1]).mean() * 100), 1)

    slope = abs(chan.get("slope_pct_per_bar") or 0.0)
    slope_sig = slope >= cfg["slope_sig_pct"]
    trend_dir = chan.get("trend")
    ema_state = obj.get("ema_state")

    if atr_pctile is not None and atr_pctile < cfg["squeeze_pctile"]:
        regime = "squeeze"
        desc = f"波動擠壓（ATR 百分位 {atr_pctile}），醞釀突破，等方向"
    elif adx_now >= cfg["adx_trend"] and slope_sig and ema_state in ("bull", "bear"):
        regime = "trend"
        d = "上升" if trend_dir == "up" else "下降"
        desc = f"4h {d}趨勢市（ADX {adx_now:.0f}，EMA {'多頭' if ema_state == 'bull' else '空頭'}排列）"
    else:
        regime = "range"
        desc = f"盤整市（ADX {adx_now:.0f}），區間邊緣打法"

    return {
        "regime": regime,
        "atr_pctile": atr_pctile,
        "adx": adx_now,
        "trend_dir": trend_dir if regime == "trend" else None,
        "desc": desc,
    }
