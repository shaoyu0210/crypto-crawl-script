from backend import config
from backend.analysis import features as F
from backend.analysis import levels as L


def _levels(df):
    feats = F.compute_features(df, config.FEATURE_CFG)
    cfg = {**config.LEVELS_CFG, "swing_k": config.FEATURE_CFG["swing_k"]}
    return feats, L.build_levels(df, feats, cfg)


def test_build_levels_basic(df_flat):
    feats, lvls = _levels(df_flat)
    assert len(lvls) > 0
    assert len(lvls) <= config.LEVELS_CFG["max_levels"]
    prices = [lv["price"] for lv in lvls]
    assert prices == sorted(prices)   # 依價格排序輸出
    price = feats["price"]
    for lv in lvls:
        assert lv["side"] == ("support" if lv["price"] <= price else "resistance")
        assert lv["strength"] > 0
        assert lv["label"]


def test_nearest_levels(df_flat):
    feats, lvls = _levels(df_flat)
    near = L.nearest_levels(lvls, feats["price"])
    if near["support"]:
        assert near["support"]["price"] <= feats["price"]
    if near["resistance"]:
        assert near["resistance"]["price"] > feats["price"]


def test_round_numbers():
    out = L.round_numbers(98765.0)
    assert all(abs(lv["price"] - 98765) / 98765 <= 0.15 for lv in out)
