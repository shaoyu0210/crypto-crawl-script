"""rss.py — 通用 RSS/Atom 解析器（stdlib，雲端零依賴）

移植自原 news_sentiment.py 的 _fetch_rss / _ptime。
"""
from __future__ import annotations

import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

UA = "Mozilla/5.0 (compatible; crypto-agent/2.0)"


def strip_html(t: str | None) -> str:
    return re.sub(r"<[^>]+>", "", t or "")


def parse_time(date_str: str | None) -> datetime | None:
    """解析 RFC822（RSS pubDate）或 ISO（Atom updated）為 UTC datetime。"""
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:   # noqa: BLE001
        pass
    try:
        s = date_str.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:   # noqa: BLE001
        return None


def fetch(url: str, timeout: int = 15) -> list[dict]:
    """抓取並解析 RSS 2.0 / Atom，回傳 [{title, link, summary, published_str}]。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    root = ET.fromstring(raw)
    items = []
    for it in root.iter("item"):
        items.append({
            "title": (it.findtext("title") or "").strip(),
            "link": (it.findtext("link") or "").strip(),
            "summary": it.findtext("description") or "",
            "published_str": it.findtext("pubDate") or "",
        })
    if not items:   # Atom
        ns = "{http://www.w3.org/2005/Atom}"
        for e in root.iter(f"{ns}entry"):
            link_el = e.find(f"{ns}link")
            items.append({
                "title": (e.findtext(f"{ns}title") or "").strip(),
                "link": (link_el.get("href") if link_el is not None else "") or "",
                "summary": e.findtext(f"{ns}summary") or e.findtext(f"{ns}content") or "",
                "published_str": e.findtext(f"{ns}updated") or e.findtext(f"{ns}published") or "",
            })
    return items
