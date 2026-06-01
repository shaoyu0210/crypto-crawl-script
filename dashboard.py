"""dashboard.py — 量化交易監控儀表板 (定稿, routine 每小時跑)

這是完整量化研究流程後的定稿。研究結論 (回測+樣本外+穩健性驗證):
  ✓ 唯一通過驗證的訊號: 「極端負費率→反彈」(主流幣,條件性弱edge,
     -0.02%為甜蜜點,保守edge約0.09,盈虧比薄,需自設風控)
  ✗ 其餘技術訊號(RSI/斐波/通道/暴漲暴跌爆量)在主流幣1h均無穩定edge,
     僅作「當前狀態描述」,不構成方向依據。

設計原則 (誠實對齊證據):
  - 有 edge 時 (極端負費率) 才給明確方向建議,並附真實份量。
  - 沒 edge 時誠實說「無明確 edge,觀望」,不假裝能預測。
  - 大漲大跌用顏色標記為「事件/風險警示」,非進場訊號。

依賴: requests, pandas, numpy, features.py (同目錄)
環境變數: DISCORD_WEBHOOK_URL
用法: python dashboard.py [--pretty] [--no-discord] [--top N]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

import features as F

try:
    import news_sentiment as NS
    _HAS_NEWS = True
except Exception:
    _HAS_NEWS = False


# ════════════════════════════════════════════════════════════════════
# 設定
# ════════════════════════════════════════════════════════════════════

INTERVAL = "1h"
KLINES_LIMIT = 300
TOP_N = 8                    # 預設監控前 8 大主流 (量大、訊號較可信)

# 固定核心主流幣 (一定監控,不受熱門榜變動影響)
CORE = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

SPOT_BASES = ["https://api.binance.com", "https://data-api.binance.vision",
              "https://api-gcp.binance.com"]
FAPI_BASES = [
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
    "https://fapi3.binance.com",
]
# 幣安期貨被地理封鎖時的資金費率備援來源 (Bybit 公開 API,不需 key)
# 資金費率各交易所高度相關,用 Bybit 替代幣安偏差小,可接受
BYBIT_BASES = ["https://api.bybit.com", "https://api.bytick.com"]
TIMEOUT = 15
SLEEP = 0.25

STABLE = {"USDC","FDUSD","TUSD","BUSD","DAI","USDP","EUR","USDT","AEUR","USD1"}

CFG = dict(volume_lookback=20, atr_period=14, rsi_period=14, channel_lookback=60,
           spike_lookback=3, imbalance_lookback=3, swing_k=3,
           fib_proximity_pct=0.6, channel_std=2.0)

# ── 大漲大跌標記門檻 (事件警示用,非進場訊號) ──
BIG_MOVE_UP = 5.0           # 近3根(3h) +5% 標記大漲
BIG_MOVE_DOWN = -5.0        # 近3根 -5% 標記大跌

# ── 唯一驗證過的訊號: 極端負費率 (甜蜜點 -0.02%) ──
FR_SWEET = -0.0002          # -0.02%: 回測 edge 峰值
FR_STRONG = -0.0003         # -0.03%: 更極端
FR_POS_EXTREME = 0.0005     # 多頭極端擁擠(回測樣本少,僅標記不建議)

# Discord 顏色
C_RED = 15158332       # 大跌 / 危險
C_GREEN = 3066993      # 大漲
C_GOLD = 15844367      # 驗證過的訊號 (極端負費率)
C_GRAY = 9807270       # 中性 / 免責
C_BLUE = 3447003       # 資訊


# ════════════════════════════════════════════════════════════════════
# 幣安 (現貨 + 期貨)
# ════════════════════════════════════════════════════════════════════

KCOLS = ["open_time","open","high","low","close","volume","close_time",
         "quote_volume","trades","taker_buy_base","taker_buy_quote","ignore"]


class Binance:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "dashboard/1.0"})
        self.spot_base = None
        self.fapi_base = None
        self.bybit_base = None
        self.funding_source = None   # 記錄資金費率最終來源
        self.status = {}

    def _get(self, bases_attr, bases, path, params):
        cur = getattr(self, bases_attr)
        order = ([cur] if cur else []) + [b for b in bases if b != cur]
        last = None
        for b in order:
            try:
                r = self.s.get(f"{b}{path}", params=params, timeout=TIMEOUT)
                r.raise_for_status()
                setattr(self, bases_attr, b)
                return r.json()
            except Exception as e:
                last = e
        raise RuntimeError(f"{path} all bases failed: {last}")

    def top_symbols(self, n):
        data = self._get("spot_base", SPOT_BASES, "/api/v3/ticker/24hr", {})
        rows = []
        for d in data:
            sym = d.get("symbol","")
            if not sym.endswith("USDT"): continue
            base = sym[:-4]
            if base in STABLE: continue
            if any(base.endswith(h) for h in ("UP","DOWN","BULL","BEAR")): continue
            try: qv = float(d.get("quoteVolume",0))
            except: continue
            rows.append((sym, qv))
        rows.sort(key=lambda x: x[1], reverse=True)
        top = [s for s,_ in rows[:n]]
        # 確保核心幣一定在內
        for c in CORE:
            if c not in top:
                top.append(c)
        return top

    def klines(self, symbol):
        data = self._get("spot_base", SPOT_BASES, "/api/v3/klines",
                         {"symbol":symbol,"interval":INTERVAL,"limit":KLINES_LIMIT})
        df = pd.DataFrame(data, columns=KCOLS)
        for c in ["open","high","low","close","volume","taker_buy_base"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        return df.set_index("open_time").sort_index().iloc[:-1]

    def _get_bybit(self, path, params):
        """Bybit 公開端點,輪流試備援網域。"""
        order = ([self.bybit_base] if self.bybit_base else []) + \
                [b for b in BYBIT_BASES if b != self.bybit_base]
        last = None
        for b in order:
            try:
                r = self.s.get(f"{b}{path}", params=params, timeout=TIMEOUT)
                r.raise_for_status()
                j = r.json()
                self.bybit_base = b
                return j
            except Exception as e:
                last = e
        raise RuntimeError(f"bybit {path} all bases failed: {last}")

    def funding_now(self, symbol):
        """抓最近一筆已公布的資金費率。
        順序:幣安 fundingRate → 幣安 premiumIndex → Bybit ticker(備援)。"""
        # 方法1: 幣安 fundingRate
        try:
            data = self._get("fapi_base", FAPI_BASES, "/fapi/v1/fundingRate",
                             {"symbol":symbol,"limit":1})
            if isinstance(data, list) and data and "fundingRate" in data[-1]:
                self.status[f"funding_{symbol}"] = "ok(binance)"
                self.funding_source = "binance"
                return float(data[-1]["fundingRate"])
            else:
                self.status[f"funding_{symbol}"] = f"幣安fundingRate異常: {str(data)[:80]}"
        except Exception as e:
            self.status[f"funding_{symbol}"] = f"幣安fundingRate失敗: {type(e).__name__}"

        # 方法2: 幣安 premiumIndex
        try:
            data = self._get("fapi_base", FAPI_BASES, "/fapi/v1/premiumIndex",
                             {"symbol":symbol})
            if isinstance(data, dict) and "lastFundingRate" in data:
                self.status[f"funding_{symbol}"] = "ok(binance premiumIndex)"
                self.funding_source = "binance"
                return float(data["lastFundingRate"])
        except Exception:
            pass

        # 方法3: Bybit ticker 備援 (幣安被地理封鎖時)
        try:
            data = self._get_bybit("/v5/market/tickers",
                                    {"category":"linear","symbol":symbol})
            if (isinstance(data, dict) and data.get("retCode") == 0
                    and data.get("result", {}).get("list")):
                fr = data["result"]["list"][0].get("fundingRate")
                if fr is not None and fr != "":
                    self.status[f"funding_{symbol}"] = "ok(bybit備援)"
                    self.funding_source = "bybit"
                    return float(fr)
            self.status[f"funding_{symbol}"] += f" | bybit異常: {str(data)[:80]}"
        except Exception as e:
            self.status[f"funding_{symbol}"] += f" | bybit失敗: {type(e).__name__}"
        return None


# ════════════════════════════════════════════════════════════════════
# 評估單一幣 + 產生「大師視角」判讀
# ════════════════════════════════════════════════════════════════════

def assess(sym, feat, funding, is_core=True):
    """整合特徵 + 資金費率,產生狀態標記與誠實的方向建議。
    is_core: 是否為回測驗證過的主流幣。非核心幣的訊號僅類比,須標註。"""
    if "error" in feat:
        return {"symbol": sym, "error": feat["error"]}

    o = feat["objective"]
    price = feat["price"]
    spike = o.get("ret_recent_pct")
    rsi = o.get("rsi")
    vmult = o.get("volume_mult")

    # ── 事件標記 (大漲大跌, 顏色用) ──
    event = None
    if spike is not None and spike >= BIG_MOVE_UP:
        event = "big_up"
    elif spike is not None and spike <= BIG_MOVE_DOWN:
        event = "big_down"

    # ── 唯一驗證過的訊號判定 ──
    verified_signal = None     # 有 edge 的訊號
    direction = "觀望 (無明確 edge)"
    rationale = []
    confidence = "無 edge"     # 誠實:預設沒有可交易 edge

    if funding is not None:
        if funding <= FR_STRONG:
            verified_signal = "極端負費率(強)"
            direction = "偏多 / 留意反彈"
            confidence = "弱 edge (條件性, 回測支撐)"
            rationale.append(
                f"資金費率 {funding*100:.4f}% 達極端負值(≤-0.03%),空頭高度擁擠。"
                f"回測顯示此位置反彈機率顯著高於基準(全期edge約0.19~0.24,"
                f"後半段保守edge約0.09)。")
        elif funding <= FR_SWEET:
            verified_signal = "極端負費率(甜蜜點)"
            direction = "偏多 / 留意反彈"
            confidence = "弱 edge (條件性, 回測支撐)"
            rationale.append(
                f"資金費率 {funding*100:.4f}% 達甜蜜點(≤-0.02%),空頭擁擠。"
                f"此為唯一通過樣本外+穩健性驗證的訊號(全期edge約0.24,"
                f"後半段保守約0.09)。盈虧比薄(MFE~1.5%/MAE~1.1%),須自設止損。")
        elif funding >= FR_POS_EXTREME:
            direction = "偏空傾向 (證據不足)"
            rationale.append(
                f"資金費率 {funding*100:.4f}% 偏高,多頭擁擠。"
                f"但「極端正費率→回落」回測樣本不足,未通過驗證,僅供參考。")

    # 非核心幣:訊號僅「類比」,因 edge 是在主流幣上驗證的,此幣未驗證
    if verified_signal and not is_core:
        confidence = "類比參考 (此幣未在回測範圍)"
        rationale.append(
            "⚠️ 注意:此 edge 是在主流幣(BTC/ETH/SOL/BNB/XRP)上驗證,"
            "本幣不在回測範圍。小幣資金費率波動大、雜訊多,此訊號僅類比參考,"
            "可信度低於主流幣。")

    # ── 未驗證的狀態描述 (僅供參考, 不構成方向) ──
    status_desc = []
    if rsi is not None:
        zone = "超賣區" if rsi <= 30 else ("超買區" if rsi >= 70 else "中性")
        status_desc.append(f"RSI {rsi:.0f}({zone})")
    ch = feat.get("channel", {})
    if ch.get("available") and ch.get("position") is not None:
        status_desc.append(f"通道位置 {ch['position']}")
    if vmult is not None:
        status_desc.append(f"量 {vmult:.1f}x")
    if event == "big_up":
        status_desc.append(f"⚡近3h大漲 +{spike:.1f}%")
    elif event == "big_down":
        status_desc.append(f"⚡近3h大跌 {spike:.1f}%")

    return {
        "symbol": sym,
        "price": price,
        "funding_rate": funding,
        "event": event,
        "verified_signal": verified_signal,
        "direction": direction,
        "confidence": confidence,
        "rationale": rationale,
        "status_desc": status_desc,          # 未驗證,僅描述
        "ret_recent_pct": spike,
        "rsi": rsi,
    }


# ════════════════════════════════════════════════════════════════════
# 大師總結 (跨幣彙整建議)
# ════════════════════════════════════════════════════════════════════

def master_summary(assessments):
    """以誠實量化視角,彙整全市場該注意什麼、有無可行動 edge。"""
    verified = [a for a in assessments if a.get("verified_signal")]
    big_down = [a for a in assessments if a.get("event") == "big_down"]
    big_up = [a for a in assessments if a.get("event") == "big_up"]

    lines = []
    # 1. 市場級事件
    if len(big_down) >= 3:
        lines.append(f"🔴 市場級下殺:{len(big_down)}幣近3h大跌"
                     f"({', '.join(a['symbol'].replace('USDT','') for a in big_down)})。"
                     f"風險警示,非進場訊號 —— 暴跌後方向在主流幣無穩定edge。")
    elif len(big_up) >= 3:
        lines.append(f"🟢 市場級拉升:{len(big_up)}幣近3h大漲。"
                     f"同樣為事件標記,延續性無回測支撐,勿追高。")

    # 2. 唯一可行動的 edge
    if verified:
        syms = ", ".join(a["symbol"].replace("USDT","") for a in verified)
        lines.append(f"🟡 可留意:{syms} 出現極端負費率(唯一通過驗證的訊號)。"
                     f"空頭擁擠、統計上反彈機率高於平時。建議:若要參與,"
                     f"做多偏向、嚴設止損(MAE約1%~1.5%)、目標保守(MFE約1.5%)、"
                     f"勿重倉 —— 這是弱edge,行情不配合時優勢有限。")
    else:
        lines.append("⚪ 目前無通過驗證的可行動訊號。其餘技術指標(RSI/通道等)"
                     "在回測中無edge,僅供描述狀態,不建議據以進場。觀望為主。")

    # 3. 大師的固定提醒
    lines.append("📌 量化提醒:本系統僅「極端負費率→反彈」具實證支撐且為條件性弱edge;"
                 "其餘皆未通過回測。沒有訊號時,『不交易』本身就是正確決策。")
    return lines


# ════════════════════════════════════════════════════════════════════
# Discord
# ════════════════════════════════════════════════════════════════════

def push_discord(webhook, assessments, summary_lines, ts, news=None, master_note=None):
    # 排序: 驗證訊號 > 大跌 > 大漲 > 其他
    def rank(a):
        if a.get("verified_signal"): return 0
        if a.get("event") == "big_down": return 1
        if a.get("event") == "big_up": return 2
        return 3
    ordered = sorted([a for a in assessments if "error" not in a], key=rank)

    head = f"📊 **量化監控** {ts}"
    embeds = []

    # Opus 大師總結 embed (最置頂,由 routine 中的 Claude 撰寫)
    # 支援第一行顏色標記 [LEVEL:RED/GOLD/GREEN/GRAY] → 決定色條,顯示時移除該行
    if master_note:
        note_color = C_GOLD  # 預設
        note_text = master_note
        first_nl = master_note.find("\n")
        first_line = (master_note[:first_nl] if first_nl >= 0 else master_note).strip()
        m = re.match(r"\[LEVEL:(RED|GOLD|GREEN|GRAY)\]", first_line)
        if m:
            level = m.group(1)
            note_color = {"RED": C_RED, "GOLD": C_GOLD,
                          "GREEN": C_GREEN, "GRAY": C_GRAY}[level]
            note_text = master_note[first_nl+1:].lstrip() if first_nl >= 0 else ""
        embeds.append({
            "title": "🎙️ Opus 大師判讀",
            "description": note_text[:4000],
            "color": note_color,
        })

    # 大師總結 embed (置頂)
    embeds.append({
        "title": "🧭 量化視角總結",
        "description": "\n\n".join(summary_lines)[:4000],
        "color": C_BLUE,
    })

    # 各幣 embed (只詳列:有驗證訊號的、或有大漲大跌事件的)
    highlight = [a for a in ordered if a.get("verified_signal") or a.get("event")]
    for a in highlight[:7]:
        if a.get("verified_signal"):
            color = C_GOLD
            tag = f"🟡 {a['verified_signal']}"
        elif a["event"] == "big_down":
            color = C_RED
            tag = "🔴 大跌事件"
        else:
            color = C_GREEN
            tag = "🟢 大漲事件"
        fr_txt = f"{a['funding_rate']*100:.4f}%" if a["funding_rate"] is not None else "—"
        desc = (
            f"**{tag}** ｜ 方向: **{a['direction']}** ｜ 強度: {a['confidence']}\n\n"
            + ("**依據**\n" + "\n".join(f"• {r}" for r in a["rationale"]) + "\n\n"
               if a["rationale"] else "")
            + f"價格 `${a['price']}` ｜ 資金費率 `{fr_txt}` ｜ "
              f"近3h `{a['ret_recent_pct']}%`\n"
            + f"狀態(未驗證,僅參考): {' / '.join(a['status_desc']) or '—'}"
        )
        embeds.append({"title": f"{a['symbol'].replace('USDT','')} ${a['price']}",
                       "description": desc[:4000], "color": color})

    # 其餘幣彙整成一個灰色 embed (一行一幣)
    rest = [a for a in ordered if not (a.get("verified_signal") or a.get("event"))]
    if rest:
        lines = []
        for a in rest:
            fr = f"{a['funding_rate']*100:.3f}%" if a["funding_rate"] is not None else "—"
            lines.append(f"**{a['symbol'].replace('USDT','')}** "
                         f"${a['price']} ｜ 費率{fr} ｜ RSI{a['rsi']:.0f} "
                         f"｜ {a['direction']}" if a['rsi'] is not None else
                         f"**{a['symbol'].replace('USDT','')}** ${a['price']}")
        embeds.append({"title": "其餘標的 (無 edge,觀望)",
                       "description": "\n".join(lines)[:4000], "color": C_GRAY})

    # 新聞背景 embed (背景資訊,未驗證,不構成方向)
    if news and news.get("available"):
        mood = news.get("market_mood") or {}
        mood_emoji = {"positive":"🟢","negative":"🔴","neutral":"⚪"}.get(
            mood.get("label"), "⚪")
        lines = [f"整體氛圍: {mood_emoji} {mood.get('label','—')} "
                 f"(平均情緒 {mood.get('avg_compound','—')}, "
                 f"近{news.get('window_hours')}h 共 {news.get('total_news',0)} 則)"]
        for sym_base, pc in news.get("per_coin", {}).items():
            if pc["count"] > 0:
                top = pc["top"][0] if pc["top"] else None
                head_news = (f" — [{top['title'][:60]}]({top['url']})"
                             if top and top.get("url") else "")
                lines.append(f"**{sym_base}** {pc['count']}則 "
                             f"情緒{pc.get('avg_sentiment','—')}{head_news}")
        embeds.append({"title": "📰 新聞背景 (未驗證,僅供參考)",
                       "description": "\n".join(lines)[:4000], "color": C_BLUE})
    elif news and not news.get("available"):
        embeds.append({"title": "📰 新聞背景",
                       "description": f"新聞模組不可用: {news.get('error','—')}",
                       "color": C_GRAY})

    # 免責 embed
    embeds.append({"color": C_GRAY, "description":
        "⚠️ 本報告基於歷史回測,僅「極端負費率→反彈」具實證支撐且為**條件性弱edge**,"
        "其餘指標與新聞情緒均未通過驗證。**不構成投資建議**,過去表現不代表未來。"
        "加密貨幣風險極高,任何進出場與資金控管請自行判斷、自負風險、嚴設止損。"})

    payload = {"content": head[:1900], "embeds": embeds[:10]}
    r = requests.post(webhook, json=payload, timeout=TIMEOUT)
    return "ok" if r.status_code < 300 else f"failed: HTTP {r.status_code} {r.text[:150]}"


# ════════════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pretty", action="store_true")
    p.add_argument("--no-discord", action="store_true")
    p.add_argument("--top", type=int, default=TOP_N)
    p.add_argument("--no-news", action="store_true", help="略過新聞抓取")
    p.add_argument("--include-hot", action="store_true",
                   help="納入動態熱門幣(預設只監控回測驗證過的主流幣)")
    p.add_argument("--master-note-file", type=str, default="",
                   help="讀取一個文字檔作為 Opus 大師判讀,置於報告最前")
    args = p.parse_args()

    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook and not args.no_discord:
        print("DISCORD_WEBHOOK_URL 未設定", file=sys.stderr)
        return 1

    bz = Binance()
    failed = []
    if args.include_hot:
        try:
            symbols = bz.top_symbols(args.top)
        except Exception as e:
            print(f"取 top symbols 失敗,改用核心幣: {e}", file=sys.stderr)
            symbols = list(CORE)
    else:
        # 預設:只監控回測驗證過的主流幣,確保每個訊號都在驗證範圍內
        symbols = list(CORE)

    assessments = []
    rel_input = {}
    for sym in symbols:
        try:
            df = bz.klines(sym)
            feat = F.compute_features(df, CFG)
            funding = bz.funding_now(sym)
            a = assess(sym, feat, funding, is_core=(sym in CORE))
            assessments.append(a)
            if "error" not in a and a.get("ret_recent_pct") is not None:
                rel_input[sym] = a["ret_recent_pct"]
            time.sleep(SLEEP)
        except Exception as e:
            failed.append(f"{sym}: {type(e).__name__}: {e}")
            assessments.append({"symbol": sym, "error": str(e)})

    summary_lines = master_summary([a for a in assessments if "error" not in a])
    ts = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")

    # 新聞背景 (未驗證,僅背景資訊)
    news = None
    if not args.no_news and _HAS_NEWS:
        try:
            bases = [s.replace("USDT","") for s in symbols if s in CORE]
            news = NS.fetch_news_sentiment(bases)
        except Exception as e:
            news = {"available": False, "error": f"{type(e).__name__}: {e}"}

    # 讀取 Opus 大師判讀 (由 routine 中的 Claude 寫入檔案)
    master_note = None
    if args.master_note_file:
        try:
            with open(args.master_note_file, "r", encoding="utf-8") as f:
                master_note = f.read().strip()
        except Exception as e:
            print(f"讀取 master-note-file 失敗: {e}", file=sys.stderr)

    discord = "skipped"
    if not args.no_discord:
        try:
            discord = push_discord(webhook, assessments, summary_lines, ts, news,
                                   master_note=master_note)
        except Exception as e:
            discord = f"failed: {type(e).__name__}: {e}"

    out = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "interval": INTERVAL, "symbols": symbols,
            "spot_base": bz.spot_base, "fapi_base": bz.fapi_base,
            "bybit_base": bz.bybit_base, "funding_source": bz.funding_source,
            "failed": failed,
            "funding_diagnostics": bz.status,
            "verified_signal_note": "唯一通過驗證:極端負費率→反彈(條件性弱edge,-0.02%甜蜜點)",
        },
        "master_summary": summary_lines,
        "assessments": assessments,
        "news_background": news,
        "discord": discord,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2 if args.pretty else None))
    n_verified = sum(1 for a in assessments if a.get("verified_signal"))
    print(f"\n掃描 {len(symbols)} 幣, 驗證訊號 {n_verified} 個, "
          f"Discord {discord}, 失敗 {failed or '無'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())