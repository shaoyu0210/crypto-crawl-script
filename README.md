# crypto-agent — 短線交易手機監控平台

手機網站，從**新聞面 / 技術面 / 籌碼面**三個角度監控幣安熱門標的的做多做空時機。
單一 Cloud Run 服務（FastAPI + Preact SPA），Cloud Scheduler 每 5 分鐘刷新，月成本 < $1。

```
手機瀏覽器 (PIN 登入)
   │  GET /api/snapshot…          K線直打 Binance（失敗自動降級 proxy）
   ▼
Cloud Run asia-east1 ◄── Cloud Scheduler (*/5min) POST /tasks/refresh
   │  行情/籌碼 (Binance→Bybit fallback)
   │  新聞 RSS×5 + 川普 Truth Social + ForexFactory 經濟日曆
   │  特徵 → regime → 關鍵價位 → setup → 評分 → 警報(Discord)
   ▼
GCS snapshot.json（快取層）
```

---

## 誠實原則（系統的靈魂，測試鎖死）

| 層級 | 內容 | 實證狀態 |
|---|---|---|
| 🟡 **Verified edge** | 極端負費率 ≤ -0.02% → 留意反彈 | ✅ 唯一通過回測（條件性弱 edge，MFE~1.5%/MAE~1.1%）|
| 🟣 **Setup 卡** | 進場區/止損/目標/R-R 完整交易計畫草稿 | ⚠ 規則化推導，未經回測 |
| 📊 **傾向分數** | -100~+100 多因子合成 | ⚠ 未驗證，僅參考 |

- 只有 verified edge 會給「方向」；其餘一律「觀望（無 edge）」
- 非核心幣觸發 edge 標「類比參考」（回測只在主流幣驗證）
- R/R < 1.5 的 setup 直接不顯示（差盈虧比的機會不值得看）
- 大漲大跌 ±5%/3h 標「事件警示」，明確非進場訊號
- `tests/test_scoring.py`、`tests/test_setups.py` 鎖死以上規則，防止日後改壞

## 分析引擎

- **多時間框架共振**：4h 定方向（EMA20/50 + 通道斜率）、1h 找位置、15m 定觸發
- **Regime 判別**：趨勢市（只給順勢回調 setup）/ 盤整市（只給區間反打）/ 擠壓（不給方向）；均值回歸因子在趨勢市權重歸零
- **關鍵價位引擎**：swing 聚類壓撐（觸碰×量加權）、前日/週高低、斐波回撤、回歸通道、整數關卡、VWAP，鄰近合併後依強度取前 12
- **籌碼面**：費率＋趨勢、OI×價格四象限、散戶多空比（反向）、taker 買占比、CVD 背離、±1% 掛單失衡、疑似清算偵測（OI 驟降＋長影線＋爆量近似）
- **相對強弱**：對 BTC 的 4h/24h 超額報酬排名，總覽顯示最強/最弱 3；BTC 方向不明時全站加註
- **事件風險窗口**：高影響事件前 30 分～後 15 分全站橫幅警示

## 新聞面來源（全免費）

| 來源 | 用途 |
|---|---|
| Cointelegraph/Decrypt/CryptoSlate/Bitcoinist/NewsBTC RSS | VADER+加密關鍵字情緒（僅背景氛圍）|
| [trumpstruth.org/feed](https://trumpstruth.org) | 川普 Truth Social 鏡像；市場關鍵字命中即推警報 |
| ForexFactory 週日曆 JSON | CPI/FOMC/非農時間＋impact；掛掉退回內建 FOMC 日期表 |

## 警報（Discord 推播）

每輪刷新檢查：新 setup（R/R≥2）、進場區觸及、verified edge、OI 1h ±15%、疑似清算、接近強價位、川普市場發文、高影響事件前 30 分。指紋去重＋2 小時冷卻防轟炸。

---

## 目錄結構

```
backend/
  main.py             FastAPI 入口（API + 靜態 SPA）
  config.py           所有參數門檻單一來源
  auth.py             PIN + HMAC token
  store.py            GCS / 本機檔 + 記憶體快取
  alerts.py           警報引擎（去重冷卻 + Discord）
  sources/            binance / bybit / rss / news / trump / econ_calendar
  analysis/           features / levels / regime / mtf / setups / scoring / snapshot
  routers/            api / tasks / auth_routes
frontend/             Preact + Vite + TS（build 進 backend/static）
  src/pages/          Overview（卡片流）/ Detail（K線疊圖）/ News
  src/components/     Chart（lightweight-charts）/ SetupCard / Gauge / PinGate
tests/                風控與誠實原則鎖死測試
Dockerfile            multi-stage（node build → python slim）
deploy.sh             一鍵部署（Cloud Run + GCS + Scheduler）
```

## 本機開發

```bash
# 後端
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests/            # 測試
PIN=1234 LOCAL_MODE=1 REFRESH_SECRET=dev .venv/bin/uvicorn backend.main:app --reload

# 跑一輪刷新（生成 /tmp/crypto_snapshot.json）
curl -X POST localhost:8000/tasks/refresh -H "X-Refresh-Secret: dev"

# 前端（另開終端；Vite 會 proxy /api 到 8000）
cd frontend && npm install && npm run dev
```

## 部署 GCP

```bash
cp .env.example .env   # 填 PIN / APP_SECRET / REFRESH_SECRET / DISCORD_WEBHOOK_URL
gcloud auth login && gcloud config set project <PROJECT_ID>
./deploy.sh
```

完成後手機開啟 Cloud Run 網址、輸入 PIN（token 存 localStorage，免重複輸入）。

**區域**：asia-east1（台灣），避開 Binance 對美國雲端 IP 的封鎖；現貨另有 data-api.binance.vision 鏡像與 Bybit 三層 fallback，實際來源記錄在 `data_health`，前端異常時顯示警示。

## 環境變數

| 變數 | 必要 | 說明 |
|---|---|---|
| `PIN` | ✅ | 手機登入 PIN |
| `APP_SECRET` | ✅ | token HMAC 金鑰（隨機 32+ 字元）|
| `REFRESH_SECRET` | ✅ | Scheduler 觸發保護 |
| `DISCORD_WEBHOOK_URL` | 建議 | 警報推播 |
| `GCS_BUCKET` | 雲端 | deploy.sh 自動設定 |
| `TOP_N` | — | 熱門標的數，預設 10 |
| `LOCAL_MODE` | — | 1 = snapshot 存本機檔（開發用）|

---

## 風險聲明

本系統僅「極端負費率→反彈」具回測實證且為**條件性弱 edge**；setup 與傾向分數為規則化推導、**未經回測驗證**。不構成投資建議，加密貨幣風險極高，任何進出場與資金控管請自行判斷、嚴設止損、風險自負。
