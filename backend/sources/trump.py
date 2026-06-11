"""trump.py — 川普 Truth Social 發文追蹤（trumpstruth.org 免費 RSS 鏡像）

定位：事件提示，非情緒訊號。VADER 對發文文體準度低，
只做加密/總經關鍵字偵測 + 高亮，命中關鍵字者由警報引擎推播。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import rss
from .. import config

# 加密/總經市場相關關鍵字（命中 = 可能影響行情的發文）
MARKET_KEYWORDS = [
    "bitcoin", "btc", "crypto", "cryptocurrency", "digital asset", "stablecoin",
    "ethereum", "sec", "fed", "federal reserve", "powell", "interest rate",
    "rate cut", "rate hike", "tariff", "tariffs", "trade deal", "trade war",
    "china", "inflation", "dollar", "treasury", "debt ceiling", "shutdown",
]


def fetch_trump_posts(window_hours: int = 48, limit: int = 10) -> dict:
    """回傳 {available, posts: [{title, url, published, market_related, hits}]}。"""
    try:
        entries = rss.fetch(config.TRUMP_FEED_URL)
    except Exception as ex:   # noqa: BLE001
        return {"available": False, "error": type(ex).__name__, "posts": []}

    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    posts = []
    for e in entries:
        pub = rss.parse_time(e.get("published_str"))
        if pub is None or pub < since:
            continue
        text = rss.strip_html(f"{e.get('title') or ''} {e.get('summary') or ''}")
        low = text.lower()
        hits = [kw for kw in MARKET_KEYWORDS if kw in low]
        posts.append({
            "title": text.strip()[:280] or "(無文字內容)",
            "url": e.get("link") or "",
            "published": pub.isoformat(),
            "market_related": bool(hits),
            "hits": hits,
        })
    posts.sort(key=lambda p: p["published"], reverse=True)
    return {"available": True, "posts": posts[:limit],
            "note": "Truth Social 鏡像（trumpstruth.org），事件提示非情緒訊號"}
