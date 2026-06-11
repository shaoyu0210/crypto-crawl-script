"""scoring.py — 三層誠實評分（純函式）

第一層 verified edge：唯一通過回測驗證的訊號（極端負費率→反彈）。
  只有這層會給「方向」；無觸發一律「觀望（無 edge）」。
第二層 傾向分數 -100~+100：多因子合成、regime 加權，固定標示未驗證。
第三層 理由清單 + 事件警示：狀態描述，非訊號。
"""
from __future__ import annotations

import math


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ── 第一層：verified edge ───────────────────────────────────────────

def verified_edge(funding_rate: float | None, is_core: bool, edge_cfg: dict) -> dict | None:
    """極端負費率→反彈。回測結論：條件性弱 edge，甜蜜點 -0.02%。"""
    if funding_rate is None or funding_rate > edge_cfg["threshold"]:
        return None
    strong = funding_rate <= edge_cfg["strong"]
    return {
        "name": "extreme_negative_funding",
        "label": f"極端負費率 {funding_rate * 100:.3f}%" + ("（強）" if strong else ""),
        "direction": "long",
        "strength": "strong" if strong else "normal",
        "scope": "verified" if is_core else "analog",  # 非核心幣標「類比參考」
        "risk_note": (f"回測預期 MFE~{edge_cfg['mfe_pct']}% / MAE~{edge_cfg['mae_pct']}%，"
                      "盈虧比薄，須自設止損"),
    }


# ── 第二層：傾向分數因子（各自正規化到 -1 ~ +1，正=偏多） ─────────────

def _s_funding(fr: float | None) -> float | None:
    if fr is None:
        return None
    return _clamp(math.tanh(fr / -0.0003))   # 負費率（空頭擁擠）→ 偏多

def _s_lsr(lsr: float | None) -> float | None:
    if lsr is None or lsr <= 0:
        return None
    return _clamp(-math.tanh((lsr - 1.0) / 0.8))   # 散戶多空比反向

def _s_taker(ratio: float | None) -> float | None:
    if ratio is None:
        return None
    return _clamp((ratio - 0.5) * 4)

def _s_oi_price(oi_chg_pct: float | None, price_chg_pct: float | None) -> float | None:
    """OI×價格四象限：增倉上漲最强多、增倉下跌最強空、縮倉=動能弱化。"""
    if oi_chg_pct is None or price_chg_pct is None:
        return None
    mag = _clamp(abs(oi_chg_pct) / 10)
    if price_chg_pct >= 0:
        return mag * 0.8 if oi_chg_pct >= 0 else mag * 0.25
    return -mag * 0.8 if oi_chg_pct >= 0 else -mag * 0.25

def _s_rsi(rsi: float | None) -> float | None:
    if rsi is None:
        return None
    if rsi <= 30:
        return _clamp((30 - rsi) / 20)
    if rsi >= 70:
        return _clamp(-(rsi - 70) / 20)
    return 0.0

def _s_channel(chan: dict) -> float | None:
    if not chan.get("available") or chan.get("position") is None:
        return None
    pos = chan["position"]
    base = _clamp((0.5 - pos) * 2)   # 貼下軌偏多、貼上軌偏空（均值回歸視角）
    tilt = 0.2 if chan.get("trend") == "up" else -0.2
    return _clamp(base + tilt)

def _s_news(avg_sentiment: float | None) -> float | None:
    if avg_sentiment is None:
        return None
    return _clamp(avg_sentiment * 2)


_FACTOR_DESCS = {
    "funding": lambda v, raw: f"資金費率 {raw * 100:.3f}%（{'空頭擁擠利反彈' if v > 0 else '多頭擁擠'}）",
    "lsr": lambda v, raw: f"多空比 {raw:.2f}（散戶{'偏多→反向看空' if v < 0 else '偏空→反向看多'}）",
    "taker": lambda v, raw: f"Taker buy {raw:.2f}（{'買壓' if v > 0 else '賣壓'}主導）",
    "oi_price": lambda v, raw: f"OI 24h {raw:+.1f}%×價格方向（{'增倉順勢' if abs(v) > 0.4 else '縮倉動能弱化'}）",
    "rsi": lambda v, raw: f"RSI {raw:.0f}（{'超賣' if v > 0 else '超買'}區）",
    "channel": lambda v, raw: f"通道位置 {raw:.2f}（{'貼近下軌' if v > 0 else '貼近上軌'}）",
    "news": lambda v, raw: f"新聞情緒 {raw:+.2f}（{'偏正面' if v > 0 else '偏負面'}）",
}

# regime 加權：mean_reversion 因子在趨勢市歸零；盤整市 oi 順勢因子降權
_REGIME_GATES = {
    "trend":   {"rsi": 0.0, "channel": 0.0},
    "range":   {"oi_price": 0.5},
    "squeeze": {},
}


def tendency_score(facts: dict, regime: str, weights: dict) -> dict:
    """facts: {funding, lsr, taker_ratio, oi_chg_pct, price_chg_pct, rsi, channel, news_sentiment}
    回傳 {"score", "label", "reasons", "factors"}。固定標示未驗證。"""
    chan = facts.get("channel") or {}
    raw_inputs = {
        "funding": facts.get("funding"),
        "lsr": facts.get("lsr"),
        "taker": facts.get("taker_ratio"),
        "oi_price": facts.get("oi_chg_pct"),
        "rsi": facts.get("rsi"),
        "channel": chan.get("position"),
        "news": facts.get("news_sentiment"),
    }
    scores = {
        "funding": _s_funding(facts.get("funding")),
        "lsr": _s_lsr(facts.get("lsr")),
        "taker": _s_taker(facts.get("taker_ratio")),
        "oi_price": _s_oi_price(facts.get("oi_chg_pct"), facts.get("price_chg_pct")),
        "rsi": _s_rsi(facts.get("rsi")),
        "channel": _s_channel(chan),
        "news": _s_news(facts.get("news_sentiment")),
    }
    gates = _REGIME_GATES.get(regime, {})

    total_w, weighted, factors, reasons = 0.0, 0.0, {}, []
    for name, s in scores.items():
        if s is None:
            continue
        w = weights.get(name, 0) * gates.get(name, 1.0)
        if w <= 0:
            continue
        total_w += w
        weighted += w * s
        factors[name] = round(s, 3)
        if abs(s) >= 0.25 and raw_inputs[name] is not None:
            reasons.append(_FACTOR_DESCS[name](s, raw_inputs[name]))

    score = round(weighted / total_w * 100) if total_w > 0 else 0
    if regime == "squeeze":
        score = round(score * 0.5)
        reasons.append("波動擠壓環境，方向參考性低")

    a = abs(score)
    if a < 25:
        label = "中性"
    elif a < 50:
        label = "偏多傾向" if score > 0 else "偏空傾向"
    else:
        label = "明顯偏多傾向" if score > 0 else "明顯偏空傾向"

    return {
        "score": score,
        "label": label,
        "reasons": reasons,
        "factors": factors,
        "unverified": True,
        "note": "傾向分數未經回測驗證，僅供參考；有實證支撐的只有金色 edge 徽章",
    }


# ── 主入口 ──────────────────────────────────────────────────────────

def assess(symbol: str, feats_1h: dict, facts: dict, regime_info: dict,
           is_core: bool, edge_cfg: dict, weights: dict,
           event_spike_pct: float = 5.0) -> dict:
    """單一標的完整判讀。direction 只由 verified edge 決定，其餘觀望。"""
    edge = verified_edge(facts.get("funding"), is_core, edge_cfg)
    tend = tendency_score(facts, regime_info["regime"], weights)

    obj = feats_1h.get("objective") or {}
    event = None
    spike = obj.get("ret_recent_pct")
    if spike is not None and abs(spike) >= event_spike_pct:
        event = {"kind": "pump" if spike > 0 else "dump",
                 "ret_pct": spike,
                 "label": f"近3h {spike:+.1f}% {'大漲' if spike > 0 else '大跌'}事件（警示非訊號）"}

    if edge:
        scope = "" if edge["scope"] == "verified" else "（類比參考，未在回測範圍）"
        direction = f"留意反彈—做多方向{scope}"
        confidence = "條件性弱 edge" + ("（強訊號）" if edge["strength"] == "strong" else "")
    else:
        direction = "觀望（無 edge）"
        confidence = "無 edge"

    return {
        "symbol": symbol,
        "verified_signal": edge,
        "direction": direction,
        "confidence": confidence,
        "tendency": tend,
        "event": event,
        "regime": regime_info,
    }
