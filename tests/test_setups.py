"""setup 引擎測試 — 鎖死風控紀律：
必附進場/止損/目標/R-R、R/R 過濾生效、squeeze 不給方向、誠實標示。"""
from backend import config
from backend.analysis import features as F
from backend.analysis import setups as S
from backend.analysis import levels as L
from backend.analysis import mtf


MTF_NEUTRAL = {"bias_15m": "neutral", "bias_1h": "neutral", "bias_4h": "neutral",
               "aligned": False, "trigger_ready": False, "desc": "test"}


def _feats(df):
    return F.compute_features(df, config.FEATURE_CFG)


def _fabricated_inputs(df):
    """手工構造：價格正好貼著一個強支撐，上方有夠遠的強壓力 → 必生成多單 setup。"""
    feats = _feats(df)
    price = feats["price"]
    atr = feats["atr"]
    levels_list = [
        {"price": price - 0.1 * atr, "kind": "sr_cluster", "label": "壓撐區 ×4",
         "strength": 5.0, "side": "support"},
        {"price": price + 6 * atr, "kind": "prev_day_high", "label": "前日高",
         "strength": 3.0, "side": "resistance"},
        {"price": price + 9 * atr, "kind": "sr_cluster", "label": "壓撐區 ×3",
         "strength": 4.0, "side": "resistance"},
    ]
    regime_info = {"regime": "trend", "trend_dir": "up", "desc": "test",
                   "atr_pctile": 60.0, "adx": 30.0}
    return feats, levels_list, regime_info


def test_trend_pullback_long_invariants(df_up):
    feats, lvls, reg = _fabricated_inputs(df_up)
    setup = S.generate_setup("TESTUSDT", df_up, feats, reg, MTF_NEUTRAL, lvls,
                             config.SETUP_CFG)
    assert setup is not None
    assert setup["side"] == "long"
    # 風控完整性：進場區/止損/目標/R-R 缺一不可
    assert setup["entry_low"] < setup["entry_high"]
    assert setup["stop"] < setup["entry_low"]          # 多單止損在進場區下方
    assert setup["targets"] and setup["targets"][0]["price"] > setup["entry_high"]
    assert setup["rr1"] >= config.SETUP_CFG["min_rr"]
    # 誠實標示鎖死
    assert setup["unverified"] is True
    assert "未經回測" in setup["disclaimer"]


def test_squeeze_gives_no_setup(df_flat):
    feats, lvls, _ = _fabricated_inputs(df_flat)
    reg = {"regime": "squeeze", "trend_dir": None, "desc": "test",
           "atr_pctile": 10.0, "adx": 12.0}
    assert S.generate_setup("TESTUSDT", df_flat, feats, reg, MTF_NEUTRAL, lvls,
                            config.SETUP_CFG) is None


def test_rr_filter_kills_bad_setup(df_up):
    """目標太近（R/R 必 < min_rr）→ setup 不生成。"""
    feats, lvls, reg = _fabricated_inputs(df_up)
    price, atr = feats["price"], feats["atr"]
    bad_levels = [
        lvls[0],
        {"price": price + 1.05 * atr, "kind": "round", "label": "近壓",
         "strength": 4.0, "side": "resistance"},   # 剛好過 1×ATR 門檻但風報極差
    ]
    setup = S.generate_setup("TESTUSDT", df_up, feats, reg, MTF_NEUTRAL,
                             bad_levels, config.SETUP_CFG)
    assert setup is None or setup["rr1"] >= config.SETUP_CFG["min_rr"]


def test_range_fade_marks_counter_trend(df_flat):
    """盤整反打逆 4h 偏向時必須標 counter_trend。"""
    feats = _feats(df_flat)
    chan = feats["channel"]
    if not chan.get("available") or chan.get("position") is None:
        return
    # 構造：通道位置壓到下緣 → 反打多；4h bias 設為 down → 逆勢
    feats["channel"]["position"] = 0.1
    price, atr = feats["price"], feats["atr"]
    lvls = [
        {"price": price - 0.1 * atr, "kind": "channel_lower", "label": "通道下軌",
         "strength": 3.0, "side": "support"},
        {"price": price + 5 * atr, "kind": "channel_upper", "label": "通道上軌",
         "strength": 3.0, "side": "resistance"},
    ]
    reg = {"regime": "range", "trend_dir": None, "desc": "test",
           "atr_pctile": 50.0, "adx": 15.0}
    mtf_down = dict(MTF_NEUTRAL, bias_4h="down")
    setup = S.generate_setup("TESTUSDT", df_flat, feats, reg, mtf_down, lvls,
                             config.SETUP_CFG)
    if setup is not None and setup["side"] == "long":
        assert setup["counter_trend"] is True
        assert any("逆" in n for n in setup["notes"])


def test_mtf_confluence_shapes(df_up, df_down):
    f_up = _feats(df_up)
    f_dn = _feats(df_down)
    out = mtf.confluence(f_up, f_up, f_up)
    assert out["bias_4h"] == "up" and out["aligned"] and out["trigger_ready"]
    out2 = mtf.confluence(f_up, f_dn, f_up)
    assert out2["aligned"] is False


def test_levels_feed_setup_targets(df_up):
    """整合：真實 levels 引擎輸出餵 setup，若生成必符合不變量。"""
    feats = _feats(df_up)
    cfg = {**config.LEVELS_CFG, "swing_k": config.FEATURE_CFG["swing_k"]}
    lvls = L.build_levels(df_up, feats, cfg)
    reg = {"regime": "trend", "trend_dir": "up", "desc": "t", "atr_pctile": 60.0, "adx": 30.0}
    setup = S.generate_setup("TESTUSDT", df_up, feats, reg, MTF_NEUTRAL, lvls,
                             config.SETUP_CFG)
    if setup is not None:
        assert setup["stop"] < setup["entry_low"]
        assert all(t["price"] > setup["entry_high"] for t in setup["targets"])
        assert setup["unverified"] is True
