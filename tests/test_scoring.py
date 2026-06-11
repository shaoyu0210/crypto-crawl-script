"""評分引擎測試 — 鎖死誠實原則：
無 verified signal 時 direction 必為觀望；傾向分數永遠標 unverified；
regime 加權生效（趨勢市 RSI/通道因子歸零）。"""
from backend import config
from backend.analysis import features as F
from backend.analysis import scoring as SC

REG_RANGE = {"regime": "range", "trend_dir": None, "desc": "t", "atr_pctile": 50.0, "adx": 15.0}
REG_TREND = {"regime": "trend", "trend_dir": "up", "desc": "t", "atr_pctile": 60.0, "adx": 30.0}


def _facts(**over):
    base = {"funding": 0.0001, "lsr": 1.2, "taker_ratio": 0.55,
            "oi_chg_pct": 3.0, "price_chg_pct": 1.5, "rsi": 25.0,
            "channel": {"available": True, "position": 0.1, "trend": "up"},
            "news_sentiment": 0.2}
    base.update(over)
    return base


def test_no_edge_means_watch(df_flat):
    feats = F.compute_features(df_flat, config.FEATURE_CFG)
    out = SC.assess("BTCUSDT", feats, _facts(funding=0.0001), REG_RANGE, True,
                    config.FUNDING_EDGE, config.SCORE_WEIGHTS)
    assert out["verified_signal"] is None
    assert "觀望" in out["direction"]
    assert out["confidence"] == "無 edge"


def test_extreme_negative_funding_edge(df_flat):
    feats = F.compute_features(df_flat, config.FEATURE_CFG)
    out = SC.assess("BTCUSDT", feats, _facts(funding=-0.00025), REG_RANGE, True,
                    config.FUNDING_EDGE, config.SCORE_WEIGHTS)
    assert out["verified_signal"] is not None
    assert out["verified_signal"]["scope"] == "verified"
    assert "反彈" in out["direction"]


def test_non_core_edge_marked_analog(df_flat):
    feats = F.compute_features(df_flat, config.FEATURE_CFG)
    out = SC.assess("PEPEUSDT", feats, _facts(funding=-0.00035), REG_RANGE, False,
                    config.FUNDING_EDGE, config.SCORE_WEIGHTS)
    assert out["verified_signal"]["scope"] == "analog"
    assert "類比參考" in out["direction"]
    assert out["verified_signal"]["strength"] == "strong"


def test_tendency_always_unverified():
    t = SC.tendency_score(_facts(), "range", config.SCORE_WEIGHTS)
    assert t["unverified"] is True
    assert "未經回測" in t["note"]
    assert -100 <= t["score"] <= 100


def test_trend_regime_zeroes_mean_reversion():
    """趨勢市：RSI 超賣 + 貼下軌不得貢獻分數。"""
    facts = _facts(funding=None, lsr=None, taker_ratio=None,
                   oi_chg_pct=None, news_sentiment=None, rsi=15.0)
    t_range = SC.tendency_score(facts, "range", config.SCORE_WEIGHTS)
    t_trend = SC.tendency_score(facts, "trend", config.SCORE_WEIGHTS)
    assert t_range["score"] > 0            # 盤整市：超賣 + 下軌 → 偏多
    assert t_trend["score"] == 0           # 趨勢市：均值回歸因子歸零
    assert "rsi" not in t_trend["factors"]
    assert "channel" not in t_trend["factors"]


def test_event_flag(df_flat):
    feats = F.compute_features(df_flat, config.FEATURE_CFG)
    feats["objective"]["ret_recent_pct"] = 7.5
    out = SC.assess("BTCUSDT", feats, _facts(), REG_RANGE, True,
                    config.FUNDING_EDGE, config.SCORE_WEIGHTS)
    assert out["event"] is not None
    assert out["event"]["kind"] == "pump"
    assert "非訊號" in out["event"]["label"]
    # 大漲事件不改變方向判定
    assert "觀望" in out["direction"]


def test_missing_factors_degrade_gracefully():
    t = SC.tendency_score({"funding": None, "lsr": None, "taker_ratio": None,
                           "oi_chg_pct": None, "price_chg_pct": None, "rsi": None,
                           "channel": {}, "news_sentiment": None},
                          "range", config.SCORE_WEIGHTS)
    assert t["score"] == 0
    assert t["label"] == "中性"
