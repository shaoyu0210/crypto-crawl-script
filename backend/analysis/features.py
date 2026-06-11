"""features.py — 純技術特徵計算模組（移植自原專案並擴充）

所有函式皆為純函式：輸入 OHLCV DataFrame，輸出可重現的數值。
不含任何 IO、不做決策。即時管線與測試呼叫同一套函式確保一致。

DataFrame 規格: index 為 UTC 時間，欄位含 open/high/low/close/volume/taker_buy_base。
擴充：EMA、簡版 ADX、當日 VWAP、CVD（累積成交量差）。
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


def ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False, min_periods=period).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """簡版 Wilder ADX：衡量趨勢強度（不分方向）。"""
    h, l, c = df["high"], df["low"], df["close"]
    up = h.diff()
    dn = -l.diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    alpha = 1 / period
    atr_s = tr.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100 * plus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean() / atr_s
        minus_di = 100 * minus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean() / atr_s
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.ewm(alpha=alpha, adjust=False, min_periods=period).mean().fillna(0.0)


def session_vwap(df: pd.DataFrame) -> float | None:
    """當日（UTC 日界）VWAP，用典型價 × 量累計近似。"""
    if len(df) == 0:
        return None
    last_day = df.index[-1].normalize()
    day = df[df.index >= last_day]
    if len(day) == 0:
        return None
    tp = (day["high"] + day["low"] + day["close"]) / 3
    vol = day["volume"]
    tv = vol.sum()
    if not tv or tv <= 0:
        return None
    return _f((tp * vol).sum() / tv)


def cvd_series(df: pd.DataFrame) -> pd.Series:
    """CVD：每根 (taker買量 - taker賣量) 的累計，單位為 base 量。"""
    buy = df["taker_buy_base"]
    sell = df["volume"] - buy
    return (buy - sell).cumsum()


def cvd_divergence(df: pd.DataFrame, lookback: int = 20) -> dict:
    """偵測近 lookback 根的價格 vs CVD 背離（短線警訊）。
    價創高但 CVD 未創高 = 看跌背離；價創低但 CVD 未創低 = 看漲背離。"""
    if len(df) < lookback + 5:
        return {"available": False}
    seg = df.iloc[-lookback:]
    cvd = cvd_series(df).iloc[-lookback:]
    half = lookback // 2
    price_hh = seg["close"].iloc[-half:].max() > seg["close"].iloc[:-half].max()
    price_ll = seg["close"].iloc[-half:].min() < seg["close"].iloc[:-half].min()
    cvd_hh = cvd.iloc[-half:].max() > cvd.iloc[:-half].max()
    cvd_ll = cvd.iloc[-half:].min() < cvd.iloc[:-half].min()
    div = None
    if price_hh and not cvd_hh:
        div = "bearish"   # 價漲量能不跟 → 慎多
    elif price_ll and not cvd_ll:
        div = "bullish"   # 價跌賣壓衰竭 → 慎空
    return {"available": True, "divergence": div,
            "cvd_change": _f(cvd.iloc[-1] - cvd.iloc[0], 4)}


# ════════════════════════════════════════════════════════════════════
# 擺動點偵測 (pivot/fractal) — 斐波、通道、壓撐的基礎
# ════════════════════════════════════════════════════════════════════

def find_swings(df: pd.DataFrame, k: int = 3) -> tuple[list[int], list[int]]:
    """找局部極值。swing high: 某根 high 高於左右各 k 根。swing low 同理。
    回傳 (swing_high_indices, swing_low_indices)，以位置索引表示。"""
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
    """以最近一段顯著擺動計算斐波回撤位，並判斷當前價是否貼近某回撤位。
    這是『候選位』，帶主觀性（擺動點選擇影響結果），未經回測驗證。"""
    sh, sl = find_swings(df, k)
    if not sh or not sl:
        return {"available": False, "reason": "擺動點不足"}

    last_h_idx, last_l_idx = sh[-1], sl[-1]
    swing_high = float(df["high"].iloc[last_h_idx])
    swing_low = float(df["low"].iloc[last_l_idx])
    if swing_high <= swing_low:
        return {"available": False, "reason": "擺動高低無效"}

    uptrend = last_h_idx > last_l_idx
    diff = swing_high - swing_low
    levels = {}
    for lv in FIB_LEVELS:
        if uptrend:
            price_at = swing_high - diff * lv   # 上漲後的回撤支撐
        else:
            price_at = swing_low + diff * lv    # 下跌後的反彈壓力
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
        "near_level": near,
        "note": "候選位，依擺動點選擇，帶主觀性，未經回測",
    }


# ════════════════════════════════════════════════════════════════════
# 線性回歸平行通道 (較客觀: 回歸算出，不需手選點)
# ════════════════════════════════════════════════════════════════════

def regression_channel(df: pd.DataFrame, lookback: int = 50, num_std: float = 2.0) -> dict:
    """近 lookback 根收盤線性回歸，中軸 ± num_std 標準差成平行通道。"""
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
               cfg["channel_lookback"], cfg["ema_slow"]) + 5
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
    atr_now = float(atr_s.iloc[-1]) if not np.isnan(atr_s.iloc[-1]) else None
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

    ema_f = ema(close, cfg["ema_fast"])
    ema_s = ema(close, cfg["ema_slow"])
    ema_state = None
    if not (np.isnan(ema_f.iloc[-1]) or np.isnan(ema_s.iloc[-1])):
        if ema_f.iloc[-1] > ema_s.iloc[-1] and close.iloc[-1] > ema_f.iloc[-1]:
            ema_state = "bull"      # 多頭排列
        elif ema_f.iloc[-1] < ema_s.iloc[-1] and close.iloc[-1] < ema_f.iloc[-1]:
            ema_state = "bear"      # 空頭排列
        else:
            ema_state = "mixed"

    adx_s = adx(df, cfg["adx_period"])
    adx_now = _f(adx_s.iloc[-1], 2)

    fib = fib_retracement(df, cfg["swing_k"], cfg["fib_proximity_pct"])
    chan = regression_channel(df, cfg["channel_lookback"], cfg["channel_std"])

    return {
        "price": price,
        "atr": _f(atr_now),
        "objective": {  # 客觀、可重現
            "ret_last_bar_pct": ret_1,
            "ret_recent_pct": spike_ret,
            "volume_mult": vol_mult,
            "atr_mult": atr_mult,
            "atr_pct_of_price": atr_pct,
            "rsi": rsi_now,
            "taker_buy_ratio": buy_ratio,
            "bullish_engulfing": bull_engulf,
            "ema_state": ema_state,
            "ema_fast": _f(ema_f.iloc[-1]),
            "ema_slow": _f(ema_s.iloc[-1]),
            "adx": adx_now,
            "vwap": session_vwap(df),
        },
        "channel": chan,        # 較客觀 (回歸算出)
        "fibonacci": fib,       # 帶主觀性 (擺動點選擇)
        "cvd": cvd_divergence(df),
    }
