"""features.py — 純技術特徵計算模組 (偵測器與回測共用)

所有函式皆為純函式: 輸入 OHLCV DataFrame,輸出可重現的數值。
不含任何 IO、不推 Discord、不做決策。這是「真相來源」——
即時偵測器和歷史回測都呼叫同一套函式,確保兩邊邏輯一致,
回測結果才能真正代表即時行為。

DataFrame 規格: index 為 UTC 時間,欄位含 open/high/low/close/volume/taker_buy_base。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _f(x, ndigits: int = 8) -> float | None:
    try:
        v = float(x)
        return None if (np.isnan(v) or np.isinf(v)) else round(v, ndigits)
    except (TypeError, ValueError):
        return None


# ════════════════════════════════════════════════════════════════════
# 基礎指標 (客觀、可重現)
# ════════════════════════════════════════════════════════════════════

def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    ag = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    al = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = ag / al
    return (100 - 100 / (1 + rs)).fillna(50.0)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


# ════════════════════════════════════════════════════════════════════
# 擺動點偵測 (pivot/fractal) — 斐波與通道的基礎
# ════════════════════════════════════════════════════════════════════

def find_swings(df: pd.DataFrame, k: int = 3) -> tuple[list[int], list[int]]:
    """找局部極值。swing high: 某根 high 高於左右各 k 根。swing low 同理。
    回傳 (swing_high_indices, swing_low_indices),以位置索引表示。
    注意: 這是近似演算法,選出的擺動點不一定等同肉眼判讀,屬可重現但帶規則性近似。
    """
    highs, lows = df["high"].values, df["low"].values
    n = len(df)
    sh, sl = [], []
    for i in range(k, n - k):
        window_h = highs[i - k:i + k + 1]
        window_l = lows[i - k:i + k + 1]
        if highs[i] == window_h.max() and (window_h == highs[i]).sum() == 1:
            sh.append(i)
        if lows[i] == window_l.min() and (window_l == lows[i]).sum() == 1:
            sl.append(i)
    return sh, sl


# ════════════════════════════════════════════════════════════════════
# 斐波那契回撤 (帶主觀性: 依賴擺動點選擇)
# ════════════════════════════════════════════════════════════════════

FIB_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786]


def fib_retracement(df: pd.DataFrame, k: int = 3, proximity_pct: float = 0.6) -> dict:
    """以最近一段顯著擺動 (最近 swing high 與 swing low) 計算斐波回撤位,
    並判斷當前價是否貼近某一回撤位。

    proximity_pct: 當前價距某斐波位 < 此 % 視為「正測試該位」。
    這是『候選位』,帶主觀性 (擺動點選擇影響結果),未經回測驗證。
    """
    sh, sl = find_swings(df, k)
    if not sh or not sl:
        return {"available": False, "reason": "擺動點不足"}

    last_h_idx, last_l_idx = sh[-1], sl[-1]
    swing_high = float(df["high"].iloc[last_h_idx])
    swing_low = float(df["low"].iloc[last_l_idx])
    if swing_high <= swing_low:
        return {"available": False, "reason": "擺動高低無效"}

    # 判斷趨勢方向: 高點在後 → 近期上漲,回撤往下量;低點在後 → 近期下跌,反彈往上量
    uptrend = last_h_idx > last_l_idx
    diff = swing_high - swing_low
    levels = {}
    for lv in FIB_LEVELS:
        if uptrend:
            price_at = swing_high - diff * lv  # 上漲後的回撤支撐
        else:
            price_at = swing_low + diff * lv   # 下跌後的反彈壓力
        levels[str(lv)] = round(price_at, 8)

    price = float(df["close"].iloc[-1])
    near = None
    for lv, p in levels.items():
        if p > 0 and abs(price - p) / p * 100 <= proximity_pct:
            near = {"level": lv, "price": p,
                    "dist_pct": round(abs(price - p) / p * 100, 3)}
            break

    return {
        "available": True,
        "direction": "uptrend_pullback" if uptrend else "downtrend_bounce",
        "swing_high": round(swing_high, 8),
        "swing_low": round(swing_low, 8),
        "levels": levels,
        "near_level": near,  # None 表示當前價未貼近任何斐波位
        "note": "候選位,依擺動點選擇,帶主觀性,未經回測",
    }


# ════════════════════════════════════════════════════════════════════
# 線性回歸平行通道 (較客觀: 回歸算出,不需手選點)
# ════════════════════════════════════════════════════════════════════

def regression_channel(df: pd.DataFrame, lookback: int = 50, num_std: float = 2.0) -> dict:
    """對近 lookback 根收盤做線性回歸,中軸 ± num_std 標準差成平行通道。
    判斷當前價在通道內的位置 (0=下軌,1=上軌) 與斜率方向。
    """
    if len(df) < lookback:
        return {"available": False, "reason": "資料不足"}
    y = df["close"].iloc[-lookback:].values.astype(float)
    x = np.arange(lookback)
    slope, intercept = np.polyfit(x, y, 1)
    fit = slope * x + intercept
    resid = y - fit
    std = resid.std()
    mid_now = slope * (lookback - 1) + intercept
    upper = mid_now + num_std * std
    lower = mid_now - num_std * std
    price = float(y[-1])
    pos = (price - lower) / (upper - lower) if upper > lower else None
    # 斜率正規化 (每根變動 % )
    slope_pct = slope / (intercept if intercept else price) * 100
    return {
        "available": True,
        "mid": round(mid_now, 8),
        "upper": round(upper, 8),
        "lower": round(lower, 8),
        "position": round(pos, 4) if pos is not None else None,  # <0 跌破下軌, >1 突破上軌
        "slope_pct_per_bar": round(slope_pct, 5),
        "trend": "up" if slope > 0 else "down",
    }


# ════════════════════════════════════════════════════════════════════
# 單幣完整特徵 (客觀部分 + 主觀候選位)
# ════════════════════════════════════════════════════════════════════

def compute_features(df: pd.DataFrame, cfg: dict) -> dict:
    """對單一幣的 K 線算所有特徵。cfg 提供各門檻參數。"""
    need = max(cfg["volume_lookback"], cfg["atr_period"], cfg["rsi_period"],
               cfg["channel_lookback"]) + 5
    if len(df) < need:
        return {"error": f"資料不足 (需 {need} 根, 有 {len(df)})"}

    close = df["close"]
    price = _f(close.iloc[-1])

    ret_1 = _f((close.iloc[-1] / close.iloc[-2] - 1) * 100)
    lb = cfg["spike_lookback"]
    spike_ret = _f((close.iloc[-1] / close.iloc[-1 - lb] - 1) * 100)

    vol = df["volume"]
    vol_ma = vol.iloc[-(cfg["volume_lookback"] + 1):-1].mean()
    vol_mult = _f(vol.iloc[-1] / vol_ma) if vol_ma and vol_ma > 0 else None

    atr_s = atr(df, cfg["atr_period"])
    atr_ref = atr_s.iloc[-(cfg["atr_period"] + 1):-1].mean()
    atr_mult = _f(atr_s.iloc[-1] / atr_ref) if atr_ref and atr_ref > 0 else None
    atr_pct = _f(atr_s.iloc[-1] / close.iloc[-1] * 100)

    rsi_s = rsi_wilder(close, cfg["rsi_period"])
    rsi_now = _f(rsi_s.iloc[-1])

    ilb = cfg["imbalance_lookback"]
    recent = df.iloc[-ilb:]
    tv = recent["volume"].sum()
    buy_ratio = _f(recent["taker_buy_base"].sum() / tv) if tv and tv > 0 else None

    last, prev = df.iloc[-1], df.iloc[-2]
    bull_engulf = bool(
        last["close"] > last["open"] and last["close"] > prev["open"]
        and last["open"] <= prev["close"]
        and vol_mult is not None and vol_mult >= 1.5
    )

    fib = fib_retracement(df, cfg["swing_k"], cfg["fib_proximity_pct"])
    chan = regression_channel(df, cfg["channel_lookback"], cfg["channel_std"])

    return {
        "price": price,
        "objective": {  # 客觀、可重現
            "ret_last_bar_pct": ret_1,
            "ret_recent_pct": spike_ret,
            "volume_mult": vol_mult,
            "atr_mult": atr_mult,
            "atr_pct_of_price": atr_pct,
            "rsi": rsi_now,
            "taker_buy_ratio": buy_ratio,
            "bullish_engulfing": bull_engulf,
        },
        "channel": chan,        # 較客觀 (回歸算出)
        "fibonacci": fib,       # 帶主觀性 (擺動點選擇)
    }