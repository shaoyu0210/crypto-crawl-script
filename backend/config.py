"""config.py — 環境變數、監控標的與所有分析參數門檻的單一來源。"""
from __future__ import annotations

import os


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


# ── 部署 / 認證 ──────────────────────────────────────────────
PIN = _env("PIN", "0000")                      # 手機登入 PIN 碼
APP_SECRET = _env("APP_SECRET", "dev-secret-change-me")   # token HMAC 簽名金鑰
REFRESH_SECRET = _env("REFRESH_SECRET", "dev-refresh")    # Scheduler 觸發保護
GCS_BUCKET = _env("GCS_BUCKET")                # 空字串 = 本機檔模式
LOCAL_MODE = _env("LOCAL_MODE", "1" if not GCS_BUCKET else "0") == "1"
LOCAL_SNAPSHOT_PATH = _env("LOCAL_SNAPSHOT_PATH", "/tmp/crypto_snapshot.json")
DISCORD_WEBHOOK_URL = _env("DISCORD_WEBHOOK_URL")
TOKEN_TTL_DAYS = _env_int("TOKEN_TTL_DAYS", 90)

# ── 監控標的 ────────────────────────────────────────────────
CORE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
TOP_N = _env_int("TOP_N", 10)                  # 24h 量前 N 熱門 USDT 永續
STABLE_BASES = {"USDC", "FDUSD", "TUSD", "DAI", "EUR", "BUSD"}  # 排除穩定幣對

# ── K 線時間框 ──────────────────────────────────────────────
TF_TRIGGER = "15m"   # 觸發框
TF_BASE = "1h"       # 位置框（特徵計算主框）
TF_TREND = "4h"      # 方向框
KLINE_LIMITS = {"15m": 200, "1h": 300, "4h": 200}

# ── 技術特徵參數（沿用原 dashboard CFG） ─────────────────────
FEATURE_CFG = {
    "rsi_period": 14,
    "atr_period": 14,
    "volume_lookback": 20,
    "spike_lookback": 3,        # 近 3 根報酬視為 spike
    "imbalance_lookback": 6,
    "swing_k": 3,
    "fib_proximity_pct": 0.6,
    "channel_lookback": 50,
    "channel_std": 2.0,
    "ema_fast": 20,
    "ema_slow": 50,
    "adx_period": 14,
}

# ── 事件警示門檻（非訊號，沿用原系統） ────────────────────────
EVENT_SPIKE_PCT = 5.0           # 3h ±5% 標大漲大跌事件

# ── Regime 判別 ─────────────────────────────────────────────
REGIME_CFG = {
    "atr_pctile_window": 180,   # 4h K 約 30 天
    "squeeze_pctile": 20.0,     # ATR 百分位 < 20 = 擠壓
    "adx_trend": 22.0,          # ADX 高於此 + 通道斜率顯著 = 趨勢市
    "slope_sig_pct": 0.04,      # 通道斜率 |%/bar| 高於此視為顯著
}

# ── 關鍵價位引擎 ─────────────────────────────────────────────
LEVELS_CFG = {
    "cluster_pct": 0.35,        # swing 點聚類距離（% of price）
    "max_levels": 12,           # 疊圖上限，依強度取前 N
    "round_number_count": 2,    # 上下各取幾個整數關卡
}

# ── Setup 生成 ──────────────────────────────────────────────
SETUP_CFG = {
    "stop_atr_mult": 1.2,       # 止損 = 結構點 ± 1.2×ATR
    "min_rr": 1.5,              # R/R 低於此不顯示
    "alert_rr": 2.0,            # R/R 高於此才推警報
    "entry_zone_atr": 0.5,      # 進場區寬度 = 0.5×ATR
    "level_confluence_pct": 0.5,  # 價位重合判定距離 %
}

# ── Verified edge（唯一通過回測的訊號） ───────────────────────
FUNDING_EDGE = {
    "threshold": -0.0002,       # funding ≤ -0.02% 觸發
    "strong": -0.0003,          # ≤ -0.03% 標「強」
    "mfe_pct": 1.5,             # 回測 MFE 預期
    "mae_pct": 1.1,             # 回測 MAE 預期
}

# ── 傾向分數權重（regime 加權前的基準權重，總和 100） ─────────
SCORE_WEIGHTS = {
    "funding": 25,
    "lsr": 15,
    "taker": 15,
    "oi_price": 15,
    "rsi": 10,
    "channel": 10,
    "news": 10,
}

# ── 警報引擎 ────────────────────────────────────────────────
ALERT_CFG = {
    "cooldown_hours": 2,        # 同標的同類警報冷卻
    "level_proximity_atr": 0.3,  # 距關鍵價位 < 0.3×ATR 預警
    "oi_change_alert_pct": 15.0,  # OI 1h 變化 > 15% 警報
    "event_warn_min": 30,       # 高影響事件前 30 分鐘提醒
}

# ── 新聞 / 日曆刷新節流 ──────────────────────────────────────
NEWS_REFRESH_MIN = 15           # 新聞快取超過 15 分鐘才重抓
CALENDAR_REFRESH_HOURS = 6      # 日曆快取超過 6 小時才重抓
NEWS_WINDOW_HOURS = 6

# ── Vertex AI（手動 Gemini 分析） ────────────────────────────
GCP_PROJECT = _env("GCP_PROJECT")              # 空字串 = 用 ADC 偵測到的專案
VERTEX_LOCATION = _env("VERTEX_LOCATION", "global")
GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-3.5-pro")
AI_CACHE_MIN = _env_int("AI_CACHE_MIN", 5)     # 同幣分析結果快取分鐘數（省 token 費）

# ── 外部來源 ────────────────────────────────────────────────
TRUMP_FEED_URL = "https://www.trumpstruth.org/feed"
FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# 內建 FOMC 決議日（ForexFactory 掛掉時的備援；Fed 官網年初公布，每年更新一次）
FOMC_DATES_UTC = [
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
]

REQUEST_TIMEOUT = 15            # 外部 HTTP 逾時（秒）
REQUEST_SLEEP = 0.15            # 連續請求間隔，避免 rate limit
