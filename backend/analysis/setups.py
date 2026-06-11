"""setups.py — Setup 生成引擎（純函式）

依 regime 決定打法，生成可執行的交易計畫草稿：
- trend  → 順勢回調 setup（fib/中軌/壓撐重合位回踩）
- range  → 區間邊緣反打 setup（通道上下軌 + 區間高低）
- squeeze → 不給方向

風控紀律（測試鎖死）：
- 每個 setup 必附 進場區 / 止損 / 目標 / R-R
- 止損 = 結構點 ∓ stop_atr_mult × ATR
- R/R < min_rr 直接丟棄
- 一律標 unverified=True（規則化 setup，未經回測驗證）
"""
from __future__ import annotations

import pandas as pd

from . import features as F
from .levels import nearest_levels


def _structure_low(df: pd.DataFrame, k: int = 3, lookback: int = 30) -> float | None:
    """最近 lookback 根內的最後一個 swing low（多單止損結構點）。"""
    seg = df.iloc[-lookback:]
    _, sl = F.find_swings(seg, k)
    if sl:
        return float(seg["low"].iloc[sl[-1]])
    return float(seg["low"].min()) if len(seg) else None


def _structure_high(df: pd.DataFrame, k: int = 3, lookback: int = 30) -> float | None:
    seg = df.iloc[-lookback:]
    sh, _ = F.find_swings(seg, k)
    if sh:
        return float(seg["high"].iloc[sh[-1]])
    return float(seg["high"].max()) if len(seg) else None


def _targets(levels_list: list[dict], entry_mid: float, atr_val: float, side: str) -> list[dict]:
    """目標 = 對向關鍵價位，距離須 ≥ 1×ATR（太近的不算目標），取最近兩個。"""
    if side == "long":
        cands = [lv for lv in levels_list
                 if lv["price"] >= entry_mid + atr_val and lv["strength"] >= 2.0]
        cands.sort(key=lambda x: x["price"])
    else:
        cands = [lv for lv in levels_list
                 if lv["price"] <= entry_mid - atr_val and lv["strength"] >= 2.0]
        cands.sort(key=lambda x: x["price"], reverse=True)
    return cands[:2]


def _rr(entry_mid: float, stop: float, target: float) -> float | None:
    risk = abs(entry_mid - stop)
    if risk <= 0:
        return None
    return round(abs(target - entry_mid) / risk, 2)


def _entry_anchor(price: float, atr_val: float, levels_list: list[dict],
                  side: str, max_dist_atr: float = 1.0) -> dict | None:
    """找進場錨點：當前價附近（max_dist_atr×ATR 內）的同側強價位。
    做多找下方/貼近的支撐，做空找上方/貼近的壓力。"""
    cands = []
    for lv in levels_list:
        dist = abs(price - lv["price"])
        if dist > max_dist_atr * atr_val:
            continue
        if side == "long" and lv["price"] <= price + 0.2 * atr_val:
            cands.append((dist, lv))
        elif side == "short" and lv["price"] >= price - 0.2 * atr_val:
            cands.append((dist, lv))
    if not cands:
        return None
    cands.sort(key=lambda t: (-t[1]["strength"], t[0]))
    return cands[0][1]


def generate_setup(symbol: str, df_1h: pd.DataFrame, feats_1h: dict,
                   regime_info: dict, mtf_info: dict,
                   levels_list: list[dict], cfg: dict) -> dict | None:
    """主入口。條件不滿足回 None；滿足回完整 setup dict。"""
    price = feats_1h.get("price")
    atr_val = feats_1h.get("atr")
    if not price or not atr_val or not levels_list:
        return None

    reg = regime_info["regime"]
    if reg == "squeeze":
        return None

    if reg == "trend":
        side = "long" if regime_info["trend_dir"] == "up" else "short"
        setup_type = "順勢回調多" if side == "long" else "順勢回調空"
        # 逆 4h 趨勢的回調 setup 不存在（順勢定義使然）
        counter_trend = False
    else:  # range：通道位置決定反打方向
        chan = feats_1h.get("channel") or {}
        pos = chan.get("position")
        if pos is None:
            return None
        if pos <= 0.18:
            side, setup_type = "long", "區間下緣反打多"
        elif pos >= 0.82:
            side, setup_type = "short", "區間上緣反打空"
        else:
            return None
        counter_trend = mtf_info["bias_4h"] not in ("neutral", "up" if side == "long" else "down")

    anchor = _entry_anchor(price, atr_val, levels_list, side)
    if anchor is None:
        return None

    half_zone = cfg["entry_zone_atr"] * atr_val / 2
    entry_low = anchor["price"] - half_zone
    entry_high = anchor["price"] + half_zone
    entry_mid = anchor["price"]

    if side == "long":
        struct = _structure_low(df_1h)
        if struct is None:
            return None
        stop = min(struct, entry_low) - cfg["stop_atr_mult"] * atr_val
    else:
        struct = _structure_high(df_1h)
        if struct is None:
            return None
        stop = max(struct, entry_high) + cfg["stop_atr_mult"] * atr_val

    tgts = _targets(levels_list, entry_mid, atr_val, side)
    if not tgts:
        return None
    rr1 = _rr(entry_mid, stop, tgts[0]["price"])
    if rr1 is None or rr1 < cfg["min_rr"]:
        return None   # 專業紀律：差盈虧比的機會不值得看
    rr2 = _rr(entry_mid, stop, tgts[1]["price"]) if len(tgts) > 1 else None

    # 狀態：價格已在進場區 = active；在 1×ATR 內接近 = watch；否則 far
    if entry_low <= price <= entry_high:
        status = "active"
    elif abs(price - entry_mid) <= atr_val:
        status = "watch"
    else:
        status = "far"

    confluences = [anchor["label"]]
    fib = feats_1h.get("fibonacci") or {}
    near_fib = fib.get("near_level")
    if near_fib and abs(near_fib["price"] - entry_mid) / entry_mid * 100 <= cfg["level_confluence_pct"]:
        confluences.append(f"斐波 {near_fib['level']} 重合")
    if mtf_info["trigger_ready"]:
        confluences.append("15m 觸發中")

    notes = []
    if counter_trend:
        notes.append("⚠ 逆 4h 趨勢（反打 setup，倉位宜小）")
    if not mtf_info["aligned"] and reg == "trend":
        notes.append("1h 與 4h 未完全同向，等回踩確認")

    return {
        "symbol": symbol,
        "type": setup_type,
        "side": side,
        "status": status,
        "regime": reg,
        "entry_low": round(entry_low, 8),
        "entry_high": round(entry_high, 8),
        "entry_anchor": anchor,
        "stop": round(stop, 8),
        "targets": [{"price": t["price"], "label": t["label"],
                     "rr": _rr(entry_mid, stop, t["price"])} for t in tgts],
        "rr1": rr1,
        "rr2": rr2,
        "counter_trend": counter_trend,
        "confluences": confluences,
        "mtf": mtf_info["desc"],
        "notes": notes,
        "unverified": True,
        "disclaimer": "規則化 setup，未經回測驗證，僅為交易計畫草稿",
    }
