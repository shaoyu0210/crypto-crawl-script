from backend import config
from backend.analysis import features as F


def test_rsi_in_range(df_flat):
    rsi = F.rsi_wilder(df_flat["close"])
    assert ((rsi >= 0) & (rsi <= 100)).all()


def test_atr_positive(df_flat):
    atr = F.atr(df_flat).dropna()
    assert (atr > 0).all()


def test_compute_features_keys(df_up):
    feats = F.compute_features(df_up, config.FEATURE_CFG)
    assert "error" not in feats
    assert feats["price"] is not None
    assert feats["atr"] is not None
    for key in ("rsi", "ema_state", "adx", "vwap", "taker_buy_ratio"):
        assert key in feats["objective"]
    assert "channel" in feats and "fibonacci" in feats and "cvd" in feats


def test_uptrend_ema_bull(df_up):
    feats = F.compute_features(df_up, config.FEATURE_CFG)
    assert feats["objective"]["ema_state"] == "bull"
    assert feats["channel"]["trend"] == "up"


def test_insufficient_data():
    import pandas as pd
    df = pd.DataFrame({"open": [1], "high": [1], "low": [1], "close": [1],
                       "volume": [1], "taker_buy_base": [1]},
                      index=pd.date_range("2026-01-01", periods=1, freq="1h", tz="UTC"))
    assert "error" in F.compute_features(df, config.FEATURE_CFG)


def test_cvd_divergence_structure(df_up):
    out = F.cvd_divergence(df_up)
    assert out["available"] is True
    assert out["divergence"] in (None, "bullish", "bearish")
