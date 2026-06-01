# crypto-agent

一支可被排程呼叫的加密貨幣分析程式。每次執行會:

1. 從 CoinGecko 抓核心幣種 OHLCV
2. 自行計算技術指標 (RSI、MACD、MA20/50/200、布林通道、支撐/壓力)
3. 從多個 RSS 來源抓近 6 小時新聞並做情緒判讀 (VADER + 加密領域關鍵字)
4. 綜合算 0–100 信心分數,輸出:
   - **Tier A (≥ 80)**: 完整進出場建議 (入場區、出場、止損、依據)
   - **Tier B (< 80)**: 可觀察資訊 (指標讀數、相關新聞、距達標關鍵缺口、後續觀察訊號)
5. 額外從新聞中辨識**前 5 名被熱議的幣種** (獨立於核心清單)
6. 產出 Markdown 報告 + 純文字版,並推送到 Discord webhook (含圖表附件)

> **重要聲明**:本系統的「信心分數」是訊號強弱的**主觀量化評估**,並非經回測驗證之勝率,不代表獲利保證。
> 加密貨幣風險極高,所有進出場與資金控管請自行判斷自負風險。

---

## 安裝

```bash
cd /path/to/crypto-agent
python3 -m venv .venv          # 已存在則略過
source .venv/bin/activate
pip install -r requirements.txt
```

## 設定金鑰

```bash
cp .env.example .env
# 編輯 .env, 填入 DISCORD_WEBHOOK_URL
```

金鑰一律由環境變數讀取,絕不寫死也不入 git (`.env` 已在 `.gitignore`)。

### 必要

- `DISCORD_WEBHOOK_URL` — Discord 頻道 → 編輯頻道 → 整合 → Webhook → 新增,複製 URL

### 可選 (預設關閉)

- `COINGECKO_API_KEY` — CoinGecko Pro 金鑰 (免費版不需要)
- `CRYPTOPANIC_API_TOKEN` — 啟用 CryptoPanic 聚合 (需在 `config/news_sources.yaml` 改 `enabled: true`)
- `X_API_BEARER_TOKEN` — 啟用 X (Twitter) API Basic tier ($200/月)

## 設定檔

三份 YAML 全部可調:

| 檔案 | 用途 |
|---|---|
| `config/coins.yaml` | 核心追蹤幣種清單 (預設 BTC/ETH/SOL/BNB/XRP) |
| `config/news_sources.yaml` | 新聞 RSS 來源開關、權重、時間窗 |
| `config/scoring.yaml` | 信心分數因子權重、Tier A 門檻、入場/出場/止損 % |

中文新聞來源 (BlockTempo / ABMedia) 已預備但**預設關閉** (VADER 對中文準確度有限,只用簡單關鍵字規則)。

## 本機執行

```bash
.venv/bin/python src/main.py                # 完整流程
.venv/bin/python src/main.py --no-notify    # 不推 Discord,只產報告檔
.venv/bin/python src/main.py --no-charts    # 不產圖表
```

報告會落地到 `reports/2026-MM-DD_HH-MM.md` 與 `.txt`,圖表在 `reports/charts/<時間戳>/<幣>.png`。

## 測試

```bash
.venv/bin/python -m pytest tests/ -q
```

(全部離線,不打外網。)

## 排程一天 10 次

### macOS (launchd) — 推薦

建立 `~/Library/LaunchAgents/com.crypto-agent.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.crypto-agent</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/YOU/Desktop/crypto-agent/.venv/bin/python</string>
    <string>/Users/YOU/Desktop/crypto-agent/src/main.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/YOU/Desktop/crypto-agent</string>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>5</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>19</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>23</integer><key>Minute</key><integer>0</integer></dict>
  </array>
  <key>StandardOutPath</key>
  <string>/Users/YOU/Desktop/crypto-agent/reports/launchd.out</string>
  <key>StandardErrorPath</key>
  <string>/Users/YOU/Desktop/crypto-agent/reports/launchd.err</string>
</dict>
</plist>
```

載入:

```bash
launchctl load ~/Library/LaunchAgents/com.crypto-agent.plist
launchctl list | grep crypto-agent
```

### Linux (cron)

`crontab -e`,加入:

```cron
0 5,7,9,11,13,15,17,19,21,23 * * * cd /path/to/crypto-agent && .venv/bin/python src/main.py >> reports/cron.log 2>&1
```

(10 個整點,5 點到 23 點偶數時。)

## 錯誤處理

- 個別 RSS 或價格 API 失敗會降級,不中斷流程
- 缺漏會列在報告「資料來源狀態」(✅ / ⚠️)
- Tier A 幣種若 OHLCV 抓不到會自動跳過

## 之後想加新通知管道?

```python
# src/notifiers/telegram.py
from .base import BaseNotifier

class TelegramNotifier(BaseNotifier):
    name = "Telegram"
    def send(self, summary_text, attachments=None):
        # POST 到 Telegram Bot API
        ...
```

在 `main.py` 多 instantiate 一個即可。

## 專案結構

```
crypto-agent/
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
├── config/
│   ├── coins.yaml
│   ├── news_sources.yaml
│   └── scoring.yaml
├── src/
│   ├── main.py
│   ├── config_loader.py
│   ├── data_sources/      # CoinGecko / Binance stub
│   ├── indicators/        # 自行實作的 TA
│   ├── news/              # fetcher / sentiment / coin extractor
│   ├── analysis/          # scorer + 新聞驅動 Top 5
│   ├── reporting/         # markdown + plain text
│   ├── notifiers/         # Discord + 抽象介面
│   ├── charts/            # matplotlib
│   └── utils/             # logging
├── tests/
├── reports/               # 產出 (gitignore)
└── data/                  # 快取 (gitignore)
```
