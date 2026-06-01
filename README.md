# crypto-agent

加密貨幣量化監控系統。根目錄三個 Python 檔案各司其職:

```
features.py        ── 純技術特徵計算 (即時偵測與回測共用的「真相來源」)
news_sentiment.py  ── 新聞情緒抓取 (背景資訊,未經回測驗證)
dashboard.py       ── 主程式 (整合特徵 + 費率 + 新聞 → 報告 → 推 Discord)
```

---

## 設計核心

**只在有實證 edge 時給方向建議,其餘誠實標示「無 edge,觀望」。**

研究結論 (回測 + 樣本外 + 穩健性驗證):

| 訊號 | 結論 |
|---|---|
| ✅ **極端負費率 → 反彈** | 唯一通過驗證,主流幣條件性弱 edge,甜蜜點 `-0.02%`,盈虧比薄須自設止損 |
| ❌ RSI、斐波那契、回歸通道、暴漲暴跌爆量 | 主流幣 1h 線無穩定 edge,僅作「當前狀態描述」 |
| ❌ 標題級新聞情緒 | 學術結論分歧,本系統僅作背景氛圍展示,不據以進場 |

對齊以上證據,`dashboard.py` 的判讀策略:
- 有驗證訊號 → 給明確方向 + 真實份量描述 (含 MFE/MAE 預期)
- 無驗證訊號 → 顯示「無 edge」,描述狀態但不建議進場
- 大漲大跌 → 標記為「事件警示」,不是進場訊號

---

## 三個檔案

### `features.py` — 技術特徵庫 (純函式)

對單一幣的 OHLCV DataFrame 算所有可重現的特徵。**不做 IO、不做決策。** 即時偵測與回測呼叫同一份函式,確保邏輯一致。

提供的函式:

| 函式 | 用途 |
|---|---|
| `rsi_wilder(close, period=14)` | Wilder RSI |
| `atr(df, period=14)` | Average True Range |
| `find_swings(df, k=3)` | Pivot/fractal 擺動點 |
| `fib_retracement(df, k, proximity_pct)` | 斐波回撤位 + 是否貼近 (帶主觀性) |
| `regression_channel(df, lookback=50, num_std=2.0)` | 線性回歸平行通道 (較客觀) |
| `compute_features(df, cfg)` | 上面全部彙整為一個 dict |

輸出區分:
- **`objective`**: 客觀可重現的數字 (RSI、量倍、ATR、報酬率、taker buy 比率、看漲吞噬)
- **`channel`**: 較客觀 (回歸算出)
- **`fibonacci`**: 帶主觀性 (擺動點選擇影響結果),會標 `note` 提醒

### `news_sentiment.py` — 新聞情緒 (背景)

抓 5 個英文加密媒體 RSS (Cointelegraph / Decrypt / CryptoSlate / Bitcoinist / NewsBTC),近 6 小時內的標題用 **VADER + 加密關鍵字** 算情緒分。

**重要定位**: 標題級情緒未經回測驗證,在量化上不構成方向依據。本模組僅輸出「整體氛圍」與「每幣相關新聞」作背景。

對外只有一個入口:

```python
fetch_news_sentiment(symbols_base, window_hours=6)
# symbols_base = ['BTC','ETH','SOL','BNB','XRP']  # 不含 USDT
```

回傳結構:
```json
{
  "available": true,
  "window_hours": 6,
  "per_coin": {"BTC": {"count": 3, "avg_sentiment": -0.12, "top": [...]}},
  "market_mood": {"avg_compound": 0.08, "label": "neutral"},
  "total_news": 28,
  "failed_sources": [],
  "note": "情緒未經回測驗證,僅背景資訊,不構成交易方向依據"
}
```

實作細節:
- RSS 解析用 stdlib (`urllib` + `xml.etree`),不依賴 feedparser → 雲端環境更好部署
- VADER 不可用時整個模組標 `available: false`,dashboard 會顯示「模組不可用」而非崩潰

### `dashboard.py` — 主程式

每小時跑一次的入口。流程:

1. **Binance 現貨 klines** (1h, 300 根) — 預設只監控核心 5 主流幣 (BTCUSDT/ETHUSDT/SOLUSDT/BNBUSDT/XRPUSDT)
2. **資金費率** — 三層 fallback:
   - Cloud Run proxy (如設 `FUNDING_PROXY_URL`)
   - 幣安 fapi: `fundingRate` → `premiumIndex`
   - Bybit `/v5/market/tickers` 備援 (幣安被地理封鎖時)
3. **算特徵** — 呼叫 `features.compute_features()`
4. **抓新聞背景** — 呼叫 `news_sentiment.fetch_news_sentiment()`
5. **產判讀** — `assess()` 對每幣產 verified_signal / direction / confidence / rationale
6. **大師總結** — `master_summary()` 跨幣彙整 (市場級事件 + 可行動 edge + 固定提醒)
7. **推 Discord** — 彩色 embed:
   - 🎙️ Opus 大師判讀 (若有 `--master-note-file`,讀檔內容置頂)
   - 🧭 量化視角總結 (藍色)
   - 各幣 embed (金色=驗證訊號 / 紅色=大跌 / 綠色=大漲)
   - 其餘標的 (灰色,無 edge 觀望)
   - 📰 新聞背景 (藍色)
   - 免責 (灰色)
8. **印 JSON 到 stdout** — 完整結果含 meta、assessments、news_background、discord 狀態

---

## 安裝

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install requests pandas numpy vaderSentiment
```

注意 `dashboard.py` 不依賴 feedparser (用 stdlib 解 RSS)。

## 環境變數

```bash
# 必要
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/XXX/YYY

# 選用:routine 雲環境連不到交易所時的資金費率代抓 proxy
FUNDING_PROXY_URL=https://your-cloud-run-proxy.run.app/funding
```

## 用法

```bash
# 標準:跑全套並推 Discord
python dashboard.py

# 易讀 JSON 輸出
python dashboard.py --pretty

# 只跑、不推 Discord (本機驗證用)
python dashboard.py --no-discord --pretty

# 略過新聞抓取 (新聞 RSS 來源都掛時)
python dashboard.py --no-news

# 納入動態熱門幣 (預設只監控回測驗證過的 5 主流幣)
python dashboard.py --include-hot --top 10

# 在 Discord 報告最前加一段 Opus 大師判讀 (從檔讀)
python dashboard.py --master-note-file /tmp/opus_note.txt
```

### `--master-note-file` 格式

文字檔。可選地以 `[LEVEL:RED/GOLD/GREEN/GRAY]` 開頭,決定 embed 顏色:

```
[LEVEL:GOLD]
BTC 出現極端負費率訊號,且新聞氛圍轉中性回穩...
[後面是 Opus 寫的判讀]
```

未指定 LEVEL 時預設金色。

---

## 輸出範例 (stdout JSON)

```json
{
  "meta": {
    "generated_at": "2026-06-01T18:00:00+08:00",
    "interval": "1h",
    "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"],
    "spot_base": "https://api.binance.com",
    "fapi_base": "https://fapi.binance.com",
    "bybit_base": null,
    "funding_source": "binance",
    "failed": [],
    "funding_diagnostics": { "funding_BTCUSDT": "ok(binance)", ... },
    "verified_signal_note": "唯一通過驗證:極端負費率→反彈(條件性弱edge,-0.02%甜蜜點)"
  },
  "master_summary": [
    "⚪ 目前無通過驗證的可行動訊號。...",
    "📌 量化提醒:本系統僅..."
  ],
  "assessments": [
    {
      "symbol": "BTCUSDT",
      "price": 73516.0,
      "funding_rate": -0.00005,
      "event": null,
      "verified_signal": null,
      "direction": "觀望 (無明確 edge)",
      "confidence": "無 edge",
      "rationale": [],
      "status_desc": ["RSI 42(中性)", "通道位置 0.31", "量 0.9x"],
      "ret_recent_pct": -0.4,
      "rsi": 42.1
    }
  ],
  "news_background": {
    "available": true,
    "window_hours": 6,
    "per_coin": {"BTC": {"count": 5, "avg_sentiment": -0.12, "top": [...]}},
    "market_mood": {"avg_compound": 0.04, "label": "neutral"},
    "total_news": 28,
    "failed_sources": [],
    "note": "情緒未經回測驗證,僅背景資訊,不構成交易方向依據"
  },
  "discord": "ok"
}
```

---

## 排程

設計成每小時跑一次。三種部署方式:

### 1. macOS launchd (本機,需電腦開著)

```bash
# ~/Library/LaunchAgents/com.crypto-dashboard.plist
# StartCalendarInterval 設整點
```

### 2. Linux cron

```cron
0 * * * * cd /path/to/crypto-agent && .venv/bin/python dashboard.py >> /var/log/crypto-dashboard.log 2>&1
```

### 3. Claude Code Routine (雲端,可由 Claude Opus 寫 master-note)

雲端 routine 環境連不到 Binance fapi 時,需另外部署一個 Cloud Run proxy 並設 `FUNDING_PROXY_URL`。

---

## 設計取捨

- **單檔自含 vs 模組化**:`features.py` 與 `news_sentiment.py` 拆出來是為了讓回測腳本能直接 import 同一套邏輯,確保兩邊算出來的數字一致。
- **預設只監控核心 5 幣**:回測 edge 是在主流幣上驗證,小幣資金費率波動大、雜訊多,訊號可信度低。`--include-hot` 開了會把熱門榜納入但判讀會標「類比參考」。
- **新聞情緒只當背景**:標題級 VADER 在學術上 edge 微弱,本系統明確不用它當方向依據,只顯示氛圍。
- **資金費率三層 fallback**:Binance 在某些地區會被擋,Bybit 與 Cloud Run proxy 確保訊號不漏掉。
- **JSON 同時印到 stdout**:方便 piped 到其他工具或排程器留存歷史。

---

## 風險聲明

本系統基於歷史回測,僅「極端負費率 → 反彈」具實證支撐且為**條件性弱 edge**;其餘指標與新聞情緒**均未通過驗證**。**不構成投資建議**,過去表現不代表未來。加密貨幣風險極高,任何進出場與資金控管請自行判斷、自負風險、嚴設止損。
