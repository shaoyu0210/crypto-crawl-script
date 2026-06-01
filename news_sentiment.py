"""news_sentiment.py — 新聞面與市場情緒模組 (背景資訊,非交易訊號)

⚠️ 定位: 此模組提供的情緒分數「未經回測驗證」,在量化上不構成方向依據。
   標題級 VADER 情緒能否預測幣價,學術結論分歧、多認為 edge 微弱或無。
   因此 dashboard 僅將其作為「背景資訊」呈現 —— 讓你知道有無重大新聞、
   整體氛圍偏正偏負,但不依此進場。

做什麼: 抓加密新聞 RSS (近 N 小時) → VADER+加密關鍵字情緒 → 配對到核心幣
       → 回傳結構化摘要 (每幣相關新聞數、平均情緒、重點標題)。

依賴: feedparser, vaderSentiment (或退化為 stdlib;見 fetch)
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

try:
    import feedparser
    _HAS_FEEDPARSER = True
except Exception:
    _HAS_FEEDPARSER = False

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _vader = SentimentIntensityAnalyzer()
    _HAS_VADER = True
except Exception:
    _HAS_VADER = False


RSS_SOURCES = [
    {"name": "Cointelegraph", "url": "https://cointelegraph.com/rss"},
    {"name": "Decrypt", "url": "https://decrypt.co/feed"},
    {"name": "CryptoSlate", "url": "https://cryptoslate.com/feed/"},
    {"name": "Bitcoinist", "url": "https://bitcoinist.com/feed/"},
    {"name": "NewsBTC", "url": "https://www.newsbtc.com/feed/"},
]

NEWS_WINDOW_HOURS = 6
UA = "Mozilla/5.0 (compatible; dashboard-news/1.0)"

CRYPTO_POS = {"etf approved":3.0,"approval":1.5,"approved":1.5,"partnership":1.2,
    "all-time high":2.5,"ath":2.0,"bullish":2.0,"rally":1.5,"surge":1.5,
    "adoption":1.2,"breakthrough":1.5,"institutional":1.0,"listing":1.0}
CRYPTO_NEG = {"hack":-3.0,"hacked":-3.0,"exploit":-3.0,"rug pull":-3.0,
    "lawsuit":-2.0,"sec charges":-2.5,"ban":-2.0,"crash":-2.5,"plunge":-2.0,
    "dump":-1.5,"bankruptcy":-3.0,"scam":-2.5,"bearish":-1.5,"liquidation":-1.5}

# 幣種辨識 (核心幣 + 別名)
COIN_ALIASES = {
    "BTC": ["bitcoin"], "ETH": ["ethereum","ether"], "SOL": ["solana"],
    "BNB": ["binance coin","binancecoin"], "XRP": ["ripple"],
}


def _strip(t): return re.sub(r"<[^>]+>", "", t or "")

def _ptime(e):
    for k in ("published_parsed","updated_parsed"):
        t = e.get(k)
        if t:
            try: return datetime(*t[:6], tzinfo=timezone.utc)
            except: pass
    return None

def _label(c):
    return "positive" if c>=0.15 else ("negative" if c<=-0.15 else "neutral")

def _score(text):
    if not _HAS_VADER or not text:
        return {"compound":0.0,"label":"neutral","method":"unavailable"}
    low = text.lower()
    boost = sum(v*0.1 for k,v in CRYPTO_POS.items() if k in low)
    boost += sum(v*0.1 for k,v in CRYPTO_NEG.items() if k in low)
    base = _vader.polarity_scores(text)["compound"]
    c = max(-1.0, min(1.0, base+boost))
    return {"compound":round(c,4),"label":_label(c),"method":"vader+crypto"}

def _mentions(text, symbol):
    """判斷文字是否提及該幣 (全名不分大小寫;代號需大寫)。"""
    if not text: return False
    for alias in COIN_ALIASES.get(symbol, []):
        if re.search(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE):
            return True
    return bool(re.search(rf"\b{re.escape(symbol)}\b", text))  # 代號大寫


def fetch_news_sentiment(symbols_base, window_hours=NEWS_WINDOW_HOURS):
    """回傳每幣的新聞情緒摘要 + 整體市場氛圍。
    symbols_base: 幣代號清單 (如 ['BTC','ETH',...],不含 USDT)。"""
    result = {
        "available": _HAS_FEEDPARSER and _HAS_VADER,
        "window_hours": window_hours,
        "per_coin": {s: {"count":0,"avg_sentiment":None,"top":[]} for s in symbols_base},
        "market_mood": None,
        "total_news": 0,
        "failed_sources": [],
        "note": "情緒未經回測驗證,僅背景資訊,不構成交易方向依據",
    }
    if not result["available"]:
        result["error"] = "feedparser 或 vaderSentiment 不可用"
        return result

    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    all_items = []
    for src in RSS_SOURCES:
        try:
            feed = feedparser.parse(src["url"], request_headers={"User-Agent": UA})
            for e in feed.entries:
                pub = _ptime(e)
                if pub is None or pub < since: continue
                title = (e.get("title") or "").strip()
                if not title: continue
                summary = _strip(e.get("summary") or e.get("description") or "")[:400]
                text = f"{title}. {summary}"
                all_items.append({"title":title,"url":e.get("link") or "",
                    "source":src["name"],"text":text,"sentiment":_score(text)})
        except Exception as ex:
            result["failed_sources"].append(f"{src['name']}: {type(ex).__name__}")

    result["total_news"] = len(all_items)
    all_compounds = []
    for item in all_items:
        all_compounds.append(item["sentiment"]["compound"])
        for s in symbols_base:
            if _mentions(item["text"], s):
                pc = result["per_coin"][s]
                pc["count"] += 1
                # label 與 compound 用同一輸入(title)計算,確保一致
                title_sent = _score(item["title"])
                pc["top"].append({"title":item["title"][:120],"url":item["url"],
                    "source":item["source"],
                    "sentiment":title_sent["label"],
                    "_compound":title_sent["compound"]})

    for s in symbols_base:
        pc = result["per_coin"][s]
        if pc["count"]:
            comps = [t["_compound"] for t in pc["top"]]
            pc["avg_sentiment"] = round(float(sum(comps)/len(comps)),4)
            pc["top"] = pc["top"][:3]   # 最多留3則
            for t in pc["top"]:         # 清掉內部欄位
                t.pop("_compound", None)

    if all_compounds:
        avg = sum(all_compounds)/len(all_compounds)
        result["market_mood"] = {"avg_compound":round(avg,4),"label":_label(avg)}
    return result