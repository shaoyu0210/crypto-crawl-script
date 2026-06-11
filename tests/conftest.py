"""共用測試資料：合成 OHLCV（無網路、可重現）"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def make_df(n: int = 300, trend: float = 0.0, base: float = 100.0,
            noise: float = 0.6, seed: int = 42) -> pd.DataFrame:
    """合成 1h OHLCV。trend: 每根漂移 %；noise: 隨機波動幅度。"""
    rng = np.random.default_rng(seed)
    closes = [base]
    for _ in range(n - 1):
        drift = closes[-1] * trend / 100
        closes.append(max(1e-6, closes[-1] + drift + rng.normal(0, noise)))
    close = np.array(closes)
    spread = np.abs(rng.normal(0.4, 0.2, n)) + 0.1
    high = close + spread
    low = close - spread
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    volume = np.abs(rng.normal(1000, 200, n))
    taker = volume * rng.uniform(0.4, 0.6, n)
    idx = pd.date_range("2026-05-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": volume, "taker_buy_base": taker}, index=idx)


@pytest.fixture
def df_flat():
    return make_df(trend=0.0)


@pytest.fixture
def df_up():
    return make_df(trend=0.15, noise=0.4)


@pytest.fixture
def df_down():
    return make_df(trend=-0.15, noise=0.4)
