"""ai.py — 手動觸發的 Gemini 總結分析（Vertex AI）

使用者在個幣詳情頁按「AI 分析」→ 把該幣的技術/籌碼/新聞/事件數據
組成 prompt → Gemini 結構化輸出：多空方向、信心 %、進場點位、目標價、理由。

定位：AI 判讀與傾向分數同級——未經回測驗證的參考意見，UI 固定附免責標示。
費用控制：手動觸發 + 同幣結果快取 AI_CACHE_MIN 分鐘。
"""
from __future__ import annotations

import json
import time

import requests

from . import config, store

_cache: dict[str, tuple[float, dict]] = {}

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "bias": {"type": "STRING", "enum": ["看多", "看空", "觀望"]},
        "confidence_pct": {"type": "INTEGER"},
        "entry": {"type": "STRING"},
        "targets": {"type": "ARRAY", "items": {"type": "STRING"}},
        "stop": {"type": "STRING"},
        "reasons": {"type": "ARRAY", "items": {"type": "STRING"}},
        "caveats": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["bias", "confidence_pct", "entry", "targets", "stop", "reasons"],
}

PROMPT_HEADER = """你是專業的加密貨幣短線交易分析師。根據以下監控系統產出的即時數據，\
對 {symbol} 給出短線（數小時～數天）交易判讀。

要求：
- bias：看多/看空/觀望 三選一。數據矛盾或事件窗口臨近時，誠實選「觀望」
- confidence_pct：0-100 的信心度，數據不一致時調低，不要超過 85
- entry：具體進場點位或條件（引用數據中的關鍵價位，標明價格數字）
- targets：1-2 個目標價（引用壓力/支撐/通道價位，附價格數字）
- stop：止損價位（結構點位下方/上方，附價格數字）
- reasons：3-5 條，每條一句話，引用具體數據（費率、OI、多空比、CVD、通道位置、新聞等）
- caveats：風險提醒（如逆 4h 趨勢、事件窗口、BTC 方向不明、清算風險）
- 全部使用繁體中文。注意系統的誠實原則：只有「極端負費率→反彈」有回測實證，\
其餘指標未經驗證，你的判讀是綜合推理而非保證。

=== 即時數據 ===
"""


def _trim_block(block: dict) -> dict:
    """去掉佔 token 又無判讀價值的欄位。"""
    keep = {k: block.get(k) for k in (
        "symbol", "price", "change_24h_pct", "ret_4h_pct", "regime", "mtf",
        "setup", "levels", "summary", "fib", "channel", "news_top")}
    derivs = dict(block.get("derivs") or {})
    derivs.pop("funding_history", None)
    keep["derivs"] = derivs
    a = block.get("assessment") or {}
    keep["assessment"] = {k: a.get(k) for k in
                          ("verified_signal", "direction", "tendency", "event")}
    return keep


def _build_prompt(symbol: str, snap: dict) -> str:
    block = next((b for b in snap.get("symbols", []) if b["symbol"] == symbol), None)
    if block is None:
        raise ValueError(f"{symbol} 不在監控清單")
    ctx = {
        "target": _trim_block(block),
        "btc_context": snap.get("btc"),
        "event_window": snap.get("event_window"),
        "upcoming_high_impact_events": [
            e for e in snap.get("upcoming_events", []) if e.get("impact") == "high"][:5],
        "market_news_mood": (snap.get("news") or {}).get("market_mood"),
        "trump_recent_market_posts": [
            p for p in (snap.get("trump") or {}).get("posts", []) if p.get("market_related")][:3],
        "relative_strength_vs_btc": next(
            (r for r in (snap.get("rs") or {}).get("table", []) if r["symbol"] == symbol), None),
    }
    return PROMPT_HEADER.format(symbol=symbol) + json.dumps(ctx, ensure_ascii=False)


def _vertex_call(prompt: str) -> dict:
    import google.auth
    import google.auth.transport.requests

    creds, detected_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    project = config.GCP_PROJECT or detected_project
    if not project:
        raise RuntimeError("找不到 GCP 專案：設 GCP_PROJECT 環境變數或設定 ADC")

    loc = config.VERTEX_LOCATION
    host = "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"
    url = (f"https://{host}/v1/projects/{project}/locations/{loc}"
           f"/publishers/google/models/{config.GEMINI_MODEL}:generateContent")

    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
        },
    }
    r = requests.post(url, json=body, timeout=60,
                      headers={"Authorization": f"Bearer {creds.token}"})
    if r.status_code != 200:
        detail = r.json().get("error", {}).get("message", r.text[:200]) if r.text else ""
        raise RuntimeError(f"Vertex AI {r.status_code}: {detail}")
    data = r.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def analyze(symbol: str) -> dict:
    """主入口：快取 → 組 prompt → 呼叫 Gemini → 結構化結果。"""
    symbol = symbol.upper()
    now = time.time()
    cached = _cache.get(symbol)
    if cached and now - cached[0] < config.AI_CACHE_MIN * 60:
        return {**cached[1], "cached": True}

    snap = store.load()
    if snap is None:
        raise RuntimeError("資料尚未就緒，請等第一輪刷新完成")

    result = _vertex_call(_build_prompt(symbol, snap))
    result.update({
        "symbol": symbol,
        "model": config.GEMINI_MODEL,
        "analyzed_at": snap["meta"]["generated_at"],
        "cached": False,
        "disclaimer": "AI 判讀為綜合推理，未經回測驗證，非投資建議；風險自負、嚴設止損",
    })
    # 信心度防呆：模型偶爾忽略上限指示
    result["confidence_pct"] = max(0, min(int(result.get("confidence_pct", 0)), 85))
    _cache[symbol] = (now, result)
    return result
