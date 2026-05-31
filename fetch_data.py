"""fetch_data.py — 加密貨幣資料純抓取腳本 (單檔自含)

只負責: 抓 CoinGecko 價格與歷史線 → 算技術指標 → 抓新聞 RSS + 算情緒 →
       將新聞配對到核心幣 → 將全部結構化為 JSON 印到 stdout。

不做: 分 Tier、給入場價、推 Discord、產報告、做任何判斷。
失敗來源不中斷,記入 failed_sources 並照樣輸出其餘資料。

依賴: requests, pandas, numpy, feedparser, vaderSentiment
用法: python fetch_data.py [--pretty]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser
import numpy as np
import pandas as pd
import requests
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer


# ════════════════════════════════════════════════════════════════════════
# 設定 (要增減幣種或新聞來源,改這裡)
# ════════════════════════════════════════════════════════════════════════

COINS = [
    {"symbol": "BTC", "name": "Bitcoin", "coingecko_id": "bitcoin"},
    {"symbol": "ETH", "name": "Ethereum", "coingecko_id": "ethereum"},
    {"symbol": "SOL", "name": "Solana", "coingecko_id": "solana"},
    {"symbol": "BNB", "name": "BNB", "coingecko_id": "binancecoin"},
    {"symbol": "XRP", "name": "XRP", "coingecko_id": "ripple"},
]

RSS_SOURCES = [
    {"name": "Cointelegraph", "url": "https://cointelegraph.com/rss", "lang": "en"},
    {"name": "Decrypt", "url": "https://decrypt.co/feed", "lang": "en"},
    {"name": "TheBlock", "url": "https://www.theblock.co/rss.xml", "lang": "en"},
    {"name": "BitcoinMagazine", "url": "https://bitcoinmagazine.com/.rss/full/", "lang": "en"},
    {"name": "CryptoSlate", "url": "https://cryptoslate.com/feed/", "lang": "en"},
    {"name": "Bitcoinist", "url": "https://bitcoinist.com/feed/", "lang": "en"},
    {"name": "NewsBTC", "url": "https://www.newsbtc.com/feed/", "lang": "en"},
    {"name": "Reddit_CryptoCurrency", "url": "https://www.reddit.com/r/CryptoCurrency/top.rss?t=day", "lang": "en"},
    {"name": "Reddit_Bitcoin", "url": "https://www.reddit.com/r/Bitcoin/top.rss?t=day", "lang": "en"},
]

NEWS_WINDOW_HOURS = 6
COINGECKO_DAYS = 365      # 拿一年日線,夠算 MA200
COINGECKO_SLEEP = 5.0     # 呼叫間隔
COINGECKO_RETRY_WAIT = 15.0
COINGECKO_RETRIES = 3
RSS_MAX_CHARS = 800
USER_AGENT = "crypto-fetch/1.0"


# ════════════════════════════════════════════════════════════════════════
# 幣種辨識用辭典 (短代號/常見英文字規則)
# ════════════════════════════════════════════════════════════════════════

EXTRA_ALIASES: dict[str, list[str]] = {
    "BTC": ["bitcoin"], "ETH": ["ethereum", "ether"], "SOL": ["solana"],
    "BNB": ["binance coin", "binancecoin"], "XRP": ["ripple"],
    "DOGE": ["dogecoin"], "ADA": ["cardano"], "AVAX": ["avalanche"],
    "DOT": ["polkadot"], "LINK": ["chainlink"], "MATIC": ["polygon"],
    "TRX": ["tron"], "SHIB": ["shiba inu"], "LTC": ["litecoin"], "UNI": ["uniswap"],
}

# 短代號需在原文以大寫出現才算
SHORT_OR_AMBIGUOUS = {"BTC", "ETH", "SOL", "BNB", "XRP", "DOT", "TON", "ICP", "OP", "ARB"}

# 幣名是常用英文字 → 只接受大寫代號,不可單靠 name 命中
COMMON_WORD_NAMES = {
    "JST", "JUST", "NEAR", "ONE", "ICON", "ICX", "GAS", "SAFE", "FORTH", "FIRE",
    "WAVES", "GOLD", "SILVER", "BAND", "ALPHA", "BAT", "HOT", "STEEM", "ENS",
    "ANCHOR", "RARE", "REAL", "STORM", "SWAP", "TIME", "TRUE",
}


# ════════════════════════════════════════════════════════════════════════
# 情緒判讀詞典 (VADER + 加密領域 boost)
# ════════════════════════════════════════════════════════════════════════

CRYPTO_POSITIVE = {
    "etf approved": 3.0, "approval": 1.5, "approved": 1.5, "partnership": 1.2,
    "breakthrough": 1.5, "all-time high": 2.5, "ath": 2.0, "bullish": 2.0,
    "rally": 1.5, "surge": 1.5, "adoption": 1.2, "upgrade": 1.0,
    "halving": 1.2, "institutional": 1.0, "buyback": 1.2, "listing": 1.0,
}
CRYPTO_NEGATIVE = {
    "hack": -3.0, "hacked": -3.0, "exploit": -3.0, "rug pull": -3.0,
    "lawsuit": -2.0, "sec charges": -2.5, "sec sues": -2.5, "ban": -2.0,
    "crash": -2.5, "plunge": -2.0, "dump": -1.5, "delisting": -2.0,
    "bankruptcy": -3.0, "insolvent": -3.0, "scam": -2.5, "fraud": -2.5,
    "bearish": -1.5, "liquidation": -1.5, "default": -2.0,
}
ZH_POSITIVE = {
    "上漲": 1.5, "突破": 1.5, "利多": 2.0, "創新高": 2.5, "暴漲": 2.0,
    "看好": 1.2, "通過": 1.2, "合作": 1.0, "採用": 1.0, "牛市": 2.0,
    "ETF 通過": 3.0, "升級": 1.0,
}
ZH_NEGATIVE = {
    "下跌": -1.5, "暴跌": -2.5, "崩盤": -3.0, "駭客": -3.0, "被駭": -3.0,
    "監管": -1.0, "禁令": -2.0, "起訴": -2.0, "詐騙": -2.5, "倒閉": -3.0,
    "破產": -3.0, "熊市": -2.0, "下殺": -1.5, "套牢": -1.0, "拋售": -1.5,
}

_vader = SentimentIntensityAnalyzer()


# ════════════════════════════════════════════════════════════════════════
# 資料結構
# ════════════════════════════════════════════════════════════════════════

@dataclass
class NewsItem:
    title: str
    summary: str
    source: str
    lang: str
    url: str
    published: datetime  # UTC aware


# ════════════════════════════════════════════════════════════════════════
# 技術指標 (純函式)
# ════════════════════════════════════════════════════════════════════════

def sma(close: pd.Series, period: int) -> pd.Series:
    return close.rolling(window=period, min_periods=period).mean()


def ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI。avg_loss=0 時 RSI=100。"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
    out = 100 - (100 / (1 + rs))
    return out.fillna(50.0)


def macd_full(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return line, sig, line - sig


def bollinger(close: pd.Series, period: int = 20, num_std: float = 2.0):
    mid = sma(close, period)
    std = close.rolling(window=period, min_periods=period).std()
    return mid, mid + num_std * std, mid - num_std * std


def _safe_float(x) -> float | None:
    if x is None:
        return None
    try:
        f = float(x)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def compute_indicators_dict(df: pd.DataFrame) -> dict[str, Any]:
    """從 OHLCV-ish DataFrame (需有 close) 算所有指標,回傳 dict。"""
    close = df["close"].astype(float)
    high = df.get("high", close).astype(float)
    low = df.get("low", close).astype(float)

    rsi_s = rsi_wilder(close, 14)
    ml, ms, mh = macd_full(close)
    ma20 = sma(close, 20)
    ma50 = sma(close, 50)
    ma200 = sma(close, 200)
    bb_m, bb_u, bb_l = bollinger(close, 20, 2.0)

    price = _safe_float(close.iloc[-1])
    bu = _safe_float(bb_u.iloc[-1])
    bl = _safe_float(bb_l.iloc[-1])
    bb_pos = None
    if bu is not None and bl is not None and bu - bl > 0 and price is not None:
        bb_pos = max(0.0, min(1.0, (price - bl) / (bu - bl)))

    # 近 30 期支撐/壓力
    lookback = min(30, len(high))
    sup = _safe_float(low.tail(lookback).min()) if lookback else None
    res = _safe_float(high.tail(lookback).max()) if lookback else None

    return {
        "rsi_14": _safe_float(rsi_s.iloc[-1]),
        "macd": {
            "line": _safe_float(ml.iloc[-1]),
            "signal": _safe_float(ms.iloc[-1]),
            "hist": _safe_float(mh.iloc[-1]),
        },
        "ma20": _safe_float(ma20.iloc[-1]),
        "ma50": _safe_float(ma50.iloc[-1]),
        "ma200": _safe_float(ma200.iloc[-1]),
        "bollinger": {
            "mid": _safe_float(bb_m.iloc[-1]),
            "upper": bu,
            "lower": bl,
            "position": bb_pos,
        },
        "support_30": sup,
        "resistance_30": res,
    }


# ════════════════════════════════════════════════════════════════════════
# CoinGecko (含 429 retry)
# ════════════════════════════════════════════════════════════════════════

class CoinGecko:
    BASE = "https://api.coingecko.com/api/v3"

    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._markets_cache: dict[str, dict] = {}

    def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self.BASE}{path}"
        for attempt in range(COINGECKO_RETRIES + 1):
            r = self.session.get(url, params=params, timeout=self.timeout)
            if r.status_code == 429 and attempt < COINGECKO_RETRIES:
                ra = r.headers.get("Retry-After")
                wait = float(ra) if ra and ra.replace(".", "", 1).isdigit() else COINGECKO_RETRY_WAIT
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()

    def prime_markets(self, coingecko_ids: list[str]) -> None:
        """一次性抓所有核心幣的現價/24h%/量,快取起來。"""
        if not coingecko_ids:
            return
        data = self._get(
            "/coins/markets",
            params={
                "vs_currency": "usd",
                "ids": ",".join(coingecko_ids),
                "order": "market_cap_desc",
                "per_page": len(coingecko_ids),
                "page": 1,
                "sparkline": "false",
                "price_change_percentage": "24h",
            },
        )
        for entry in data:
            self._markets_cache[entry["id"]] = entry
        time.sleep(COINGECKO_SLEEP)

    def get_market(self, cg_id: str) -> dict:
        if cg_id in self._markets_cache:
            return self._markets_cache[cg_id]
        # fallback 單抓
        data = self._get(
            "/coins/markets",
            params={"vs_currency": "usd", "ids": cg_id, "sparkline": "false",
                    "price_change_percentage": "24h"},
        )
        time.sleep(COINGECKO_SLEEP)
        if not data:
            raise RuntimeError(f"no market data for {cg_id}")
        self._markets_cache[cg_id] = data[0]
        return data[0]

    def get_daily_close(self, cg_id: str, days: int = COINGECKO_DAYS) -> pd.DataFrame:
        """用 /market_chart 拿 daily close (免費版 OHLC endpoint 給太少 K)。"""
        chart = self._get(
            f"/coins/{cg_id}/market_chart",
            params={"vs_currency": "usd", "days": days},
        )
        time.sleep(COINGECKO_SLEEP)
        prices = chart.get("prices", [])
        if not prices:
            raise RuntimeError(f"empty price series for {cg_id}")
        df = pd.DataFrame(prices, columns=["ts", "close"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        df = df.set_index("ts").sort_index()
        df = df.resample("1D").last().dropna()
        # 補成 OHLCV 風格 (high/low 用 close 近似)
        df["open"] = df["close"].shift(1).fillna(df["close"])
        df["high"] = df["close"]
        df["low"] = df["close"]
        df["volume"] = 0.0
        return df[["open", "high", "low", "close", "volume"]]


# ════════════════════════════════════════════════════════════════════════
# 新聞抓取 (RSS)
# ════════════════════════════════════════════════════════════════════════

def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def _parse_time(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                continue
    return None


def fetch_rss(source: dict, since: datetime) -> list[NewsItem]:
    feed = feedparser.parse(
        source["url"],
        request_headers={"User-Agent": USER_AGENT},
    )
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"feed parse failed: {feed.bozo_exception}")

    items: list[NewsItem] = []
    for entry in feed.entries:
        pub = _parse_time(entry)
        if pub is None or pub < since:
            continue
        title = (entry.get("title") or "").strip()
        if not title:
            continue
        summary = _strip_html((entry.get("summary") or entry.get("description") or "").strip())[:RSS_MAX_CHARS]
        items.append(NewsItem(
            title=title, summary=summary,
            source=source["name"], lang=source.get("lang", "en"),
            url=entry.get("link") or "", published=pub,
        ))
    return items


# ════════════════════════════════════════════════════════════════════════
# 情緒判讀
# ════════════════════════════════════════════════════════════════════════

def _label(c: float) -> str:
    if c >= 0.15:
        return "positive"
    if c <= -0.15:
        return "negative"
    return "neutral"


def score_text(text: str, lang: str) -> dict[str, Any]:
    if not text:
        return {"compound": 0.0, "label": "neutral", "method": "empty"}
    if lang == "zh":
        pos = sum(v for k, v in ZH_POSITIVE.items() if k in text)
        neg = sum(v for k, v in ZH_NEGATIVE.items() if k in text)
        c = max(-1.0, min(1.0, (pos + neg) * 0.1))
        return {"compound": round(c, 4), "label": _label(c), "method": "zh-keyword"}
    # 英文: VADER + crypto boost
    lower = text.lower()
    boost = 0.0
    for kw, val in CRYPTO_POSITIVE.items():
        if kw in lower:
            boost += val * 0.1
    for kw, val in CRYPTO_NEGATIVE.items():
        if kw in lower:
            boost += val * 0.1
    base = _vader.polarity_scores(text)["compound"]
    c = max(-1.0, min(1.0, base + boost))
    return {"compound": round(c, 4), "label": _label(c), "method": "vader+crypto"}


# ════════════════════════════════════════════════════════════════════════
# 幣種辨識
# ════════════════════════════════════════════════════════════════════════

def find_mentions(text: str, coin_dict: dict[str, dict]) -> list[str]:
    """辨識文字中的幣種代號。

    - 幣名是常用英文字 (COMMON_WORD_NAMES) → 只接受大寫代號
    - 短代號 (SHORT_OR_AMBIGUOUS / len<=3) → 名稱命中可,代號自身需大寫
    - 其他 → 不分大小寫
    """
    if not text:
        return []
    found: list[str] = []
    text_orig = text

    for sym, info in coin_dict.items():
        if sym in COMMON_WORD_NAMES:
            if re.search(rf"\b{re.escape(sym)}\b", text_orig):
                found.append(sym)
            continue

        # 嘗試 name 命中 (不分大小寫)
        name_hit = False
        for alias in info.get("aliases", []):
            if not alias:
                continue
            if re.search(rf"\b{re.escape(alias)}\b", text, flags=re.IGNORECASE):
                name_hit = True
                break
        if name_hit:
            found.append(sym)
            continue

        # symbol 命中
        if sym in SHORT_OR_AMBIGUOUS or len(sym) <= 3:
            if re.search(rf"\b{re.escape(sym)}\b", text_orig):
                found.append(sym)
        else:
            if re.search(rf"\b{re.escape(sym)}\b", text, flags=re.IGNORECASE):
                found.append(sym)
    return found


def build_coin_dict_for_core(core: list[dict]) -> dict[str, dict]:
    """只為核心幣建辭典 (不需 CoinGecko top 250)。"""
    d: dict[str, dict] = {}
    for c in core:
        sym = c["symbol"].upper()
        aliases = [c["name"], c.get("coingecko_id") or ""]
        aliases.extend(EXTRA_ALIASES.get(sym, []))
        d[sym] = {"name": c["name"], "aliases": [a for a in aliases if a]}
    return d


# ════════════════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════════════════

def main() -> int:
    parser = argparse.ArgumentParser(description="加密貨幣純資料抓取輸出")
    parser.add_argument("--pretty", action="store_true", help="JSON 縮排易讀格式")
    args = parser.parse_args()

    generated_at = datetime.now(timezone.utc).astimezone()
    failed_sources: list[str] = []
    source_status: dict[str, str] = {}

    # ===== 1. 抓新聞 =====
    since = datetime.now(timezone.utc) - timedelta(hours=NEWS_WINDOW_HOURS)
    all_news: list[NewsItem] = []
    for src in RSS_SOURCES:
        name = src["name"]
        try:
            t0 = time.time()
            items = fetch_rss(src, since)
            all_news.extend(items)
            source_status[name] = f"ok ({len(items)} items, {time.time()-t0:.1f}s)"
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            source_status[name] = f"failed: {msg}"
            failed_sources.append(f"{name}: {msg}")

    all_news.sort(key=lambda x: x.published, reverse=True)

    # ===== 2. CoinGecko 批量 markets =====
    cg = CoinGecko()
    try:
        cg.prime_markets([c["coingecko_id"] for c in COINS])
        source_status["CoinGecko_markets_batch"] = "ok"
    except Exception as e:
        source_status["CoinGecko_markets_batch"] = f"failed: {e}"
        failed_sources.append(f"CoinGecko_markets_batch: {e}")

    # 幣種辭典 (新聞配對用)
    coin_dict = build_coin_dict_for_core(COINS)

    # ===== 3. 每幣 OHLC + 指標 + 配對新聞 =====
    coins_out: dict[str, dict] = {}
    for coin_meta in COINS:
        sym = coin_meta["symbol"]
        entry: dict[str, Any] = {
            "symbol": sym,
            "name": coin_meta["name"],
            "coingecko_id": coin_meta["coingecko_id"],
            "price_usd": None,
            "change_pct_24h": None,
            "volume_24h_usd": None,
            "indicators": None,
            "news": [],
        }

        # market 資料
        try:
            md = cg.get_market(coin_meta["coingecko_id"])
            entry["price_usd"] = _safe_float(md.get("current_price"))
            entry["change_pct_24h"] = _safe_float(
                md.get("price_change_percentage_24h_in_currency")
                or md.get("price_change_percentage_24h")
            )
            entry["volume_24h_usd"] = _safe_float(md.get("total_volume"))
            source_status[f"CoinGecko_market_{sym}"] = "ok"
        except Exception as e:
            source_status[f"CoinGecko_market_{sym}"] = f"failed: {e}"
            failed_sources.append(f"CoinGecko_market_{sym}: {e}")

        # 日線 + 指標
        try:
            df = cg.get_daily_close(coin_meta["coingecko_id"])
            entry["indicators"] = compute_indicators_dict(df)
            source_status[f"CoinGecko_chart_{sym}"] = f"ok ({len(df)} rows)"
        except Exception as e:
            source_status[f"CoinGecko_chart_{sym}"] = f"failed: {type(e).__name__}"
            failed_sources.append(f"CoinGecko_chart_{sym}: {e}")

        # 配對新聞 + 算情緒
        for item in all_news:
            text = f"{item.title}. {item.summary}"
            single_dict = {sym: coin_dict[sym]}
            if sym in find_mentions(text, single_dict):
                entry["news"].append({
                    "title": item.title,
                    "url": item.url,
                    "source": item.source,
                    "published": item.published.isoformat(),
                    "lang": item.lang,
                    "sentiment": score_text(text, item.lang),
                })

        coins_out[sym] = entry

    # ===== 4. 組裝輸出 =====
    output = {
        "generated_at": generated_at.isoformat(),
        "news_window_hours": NEWS_WINDOW_HOURS,
        "coingecko_days": COINGECKO_DAYS,
        "data_caveats": {
            "ohlc_note": "high/low 以日收盤近似,支撐壓力為近30日收盤極值,非真實日內高低",
            "latest_candle": "最末一根日線含當日未收盤即時價,指標會浮動",
            "sentiment_note": "情緒分數主要基於標題,為粗略訊號非內文深讀",
        },
        "coins": coins_out,
        "news_total_count": len(all_news),
        "failed_sources": failed_sources,
        "source_status": source_status,
    }

    indent = 2 if args.pretty else None
    print(json.dumps(output, ensure_ascii=False, indent=indent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
