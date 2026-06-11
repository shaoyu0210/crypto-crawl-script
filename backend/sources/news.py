"""news.py — 加密媒體新聞情緒（背景資訊，非交易訊號）

移植自原 news_sentiment.py：5 家英文加密媒體 RSS → VADER + 加密關鍵字情緒
→ 配對核心幣 → 結構化摘要。

⚠ 定位：標題級情緒未經回測驗證，僅作「背景氛圍」展示，不構成方向依據。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from . import rss

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _vader = SentimentIntensityAnalyzer()
    _HAS_VADER = True
except Exception:   # noqa: BLE001
    _HAS_VADER = False

RSS_SOURCES = [
    {"name": "Cointelegraph", "url": "https://cointelegraph.com/rss"},
    {"name": "Decrypt", "url": "https://decrypt.co/feed"},
    {"name": "CryptoSlate", "url": "https://cryptoslate.com/feed/"},
    {"name": "Bitcoinist", "url": "https://bitcoinist.com/feed/"},
    {"name": "NewsBTC", "url": "https://www.newsbtc.com/feed/"},
]

CRYPTO_POS = {"etf approved": 3.0, "approval": 1.5, "approved": 1.5, "partnership": 1.2,
              "all-time high": 2.5, "ath": 2.0, "bullish": 2.0, "rally": 1.5, "surge": 1.5,
              "adoption": 1.2, "breakthrough": 1.5, "institutional": 1.0, "listing": 1.0}
CRYPTO_NEG = {"hack": -3.0, "hacked": -3.0, "exploit": -3.0, "rug pull": -3.0,
              "lawsuit": -2.0, "sec charges": -2.5, "ban": -2.0, "crash": -2.5, "plunge": -2.0,
              "dump": -1.5, "bankruptcy": -3.0, "scam": -2.5, "bearish": -1.5, "liquidation": -1.5}

COIN_ALIASES = {
    "BTC": ["bitcoin"], "ETH": ["ethereum", "ether"], "SOL": ["solana"],
    "BNB": ["binance coin", "binancecoin"], "XRP": ["ripple"],
    "DOGE": ["dogecoin"], "ADA": ["cardano"], "AVAX": ["avalanche"],
    "LINK": ["chainlink"], "SUI": ["sui network"], "PEPE": ["pepe coin"],
}


def _label(c: float) -> str:
    return "positive" if c >= 0.15 else ("negative" if c <= -0.15 else "neutral")


def score(text: str) -> dict:
    if not _HAS_VADER or not text:
        return {"compound": 0.0, "label": "neutral", "method": "unavailable"}
    low = text.lower()
    boost = sum(v * 0.1 for k, v in CRYPTO_POS.items() if k in low)
    boost += sum(v * 0.1 for k, v in CRYPTO_NEG.items() if k in low)
    base = _vader.polarity_scores(text)["compound"]
    c = max(-1.0, min(1.0, base + boost))
    return {"compound": round(c, 4), "label": _label(c), "method": "vader+crypto"}


def _mentions(text: str, symbol: str) -> bool:
    if not text:
        return False
    for alias in COIN_ALIASES.get(symbol, []):
        if re.search(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE):
            return True
    return bool(re.search(rf"\b{re.escape(symbol)}\b", text))


def fetch_news_sentiment(symbols_base: list[str], window_hours: int = 6) -> dict:
    """symbols_base: 幣代號清單（不含 USDT）。回傳每幣新聞摘要 + 整體氛圍。"""
    result = {
        "available": _HAS_VADER,
        "window_hours": window_hours,
        "per_coin": {s: {"count": 0, "avg_sentiment": None, "top": []} for s in symbols_base},
        "market_mood": None,
        "total_news": 0,
        "items": [],
        "failed_sources": [],
        "note": "情緒未經回測驗證，僅背景資訊，不構成交易方向依據",
    }
    if not result["available"]:
        result["error"] = "vaderSentiment 不可用"
        return result

    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    all_items = []
    for src in RSS_SOURCES:
        try:
            for e in rss.fetch(src["url"]):
                pub = rss.parse_time(e.get("published_str"))
                if pub is None or pub < since:
                    continue
                title = (e.get("title") or "").strip()
                if not title:
                    continue
                summary = rss.strip_html(e.get("summary") or "")[:400]
                text = f"{title}. {summary}"
                all_items.append({"title": title, "url": e.get("link") or "",
                                  "source": src["name"], "text": text,
                                  "published": pub.isoformat(),
                                  "sentiment": score(text)})
        except Exception as ex:   # noqa: BLE001 — 單一來源掛掉不影響整體
            result["failed_sources"].append(f"{src['name']}: {type(ex).__name__}")

    all_items.sort(key=lambda x: x["published"], reverse=True)
    result["total_news"] = len(all_items)
    result["items"] = [{k: v for k, v in it.items() if k != "text"}
                       for it in all_items[:30]]

    all_compounds = []
    for item in all_items:
        all_compounds.append(item["sentiment"]["compound"])
        for s in symbols_base:
            if _mentions(item["text"], s):
                pc = result["per_coin"][s]
                pc["count"] += 1
                title_sent = score(item["title"])
                pc["top"].append({"title": item["title"][:120], "url": item["url"],
                                  "source": item["source"],
                                  "sentiment": title_sent["label"],
                                  "_compound": title_sent["compound"]})

    for s in symbols_base:
        pc = result["per_coin"][s]
        if pc["count"]:
            comps = [t["_compound"] for t in pc["top"]]
            pc["avg_sentiment"] = round(float(sum(comps) / len(comps)), 4)
            pc["top"] = pc["top"][:3]
            for t in pc["top"]:
                t.pop("_compound", None)

    if all_compounds:
        avg = sum(all_compounds) / len(all_compounds)
        result["market_mood"] = {"avg_compound": round(avg, 4), "label": _label(avg)}
    return result
