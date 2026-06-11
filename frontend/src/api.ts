// api.ts — fetch 包裝：token 管理、401 導回 PIN、K 線直打 Binance + proxy 降級

const TOKEN_KEY = 'ca_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(t: string) {
  localStorage.setItem(TOKEN_KEY, t)
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

export async function api<T = any>(path: string): Promise<T> {
  const r = await fetch(path, {
    headers: { Authorization: `Bearer ${getToken() ?? ''}` },
  })
  if (r.status === 401) {
    clearToken()
    location.reload()
    throw new Error('未授權')
  }
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    throw new Error(body.detail || `HTTP ${r.status}`)
  }
  return r.json()
}

export async function apiPost<T = any>(path: string): Promise<T> {
  const r = await fetch(path, {
    method: 'POST',
    headers: { Authorization: `Bearer ${getToken() ?? ''}` },
  })
  if (r.status === 401) {
    clearToken()
    location.reload()
    throw new Error('未授權')
  }
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    throw new Error(body.detail || `HTTP ${r.status}`)
  }
  return r.json()
}

export async function login(pin: string): Promise<void> {
  const r = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pin }),
  })
  const body = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(body.detail || 'PIN 驗證失敗')
  setToken(body.token)
}

// ── K 線：直打 Binance（CORS 開放、最即時），失敗自動降級後端 proxy ──

export interface Kline {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

const BINANCE_BASES = ['https://api.binance.com', 'https://data-api.binance.vision']
let directBroken = false   // 一旦直打失敗，本次 session 都走 proxy

export async function fetchKlines(
  symbol: string, interval: string, limit = 300,
): Promise<Kline[]> {
  if (!directBroken) {
    for (const base of BINANCE_BASES) {
      try {
        const r = await fetch(
          `${base}/api/v3/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`,
        )
        if (!r.ok) continue
        const raw: any[][] = await r.json()
        return raw.map((k) => ({
          time: Math.floor(k[0] / 1000),
          open: +k[1], high: +k[2], low: +k[3], close: +k[4], volume: +k[5],
        }))
      } catch { /* 換下一個 base */ }
    }
    directBroken = true
  }
  return api<Kline[]>(`/api/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`)
}

// ── 顯示工具 ──

export function fmtPrice(p: number | null | undefined): string {
  if (p == null) return '—'
  if (p >= 1000) return p.toLocaleString('en-US', { maximumFractionDigits: 1 })
  if (p >= 10) return p.toFixed(2)
  if (p >= 0.1) return p.toFixed(4)
  return p.toPrecision(4)
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v == null) return '—'
  return `${v > 0 ? '+' : ''}${v.toFixed(digits)}%`
}

export function relTime(iso: string): string {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return '剛剛'
  if (mins < 60) return `${mins} 分鐘前`
  const h = Math.floor(mins / 60)
  if (h < 24) return `${h} 小時前`
  return `${Math.floor(h / 24)} 天前`
}

export function taipeiTime(iso: string): string {
  return new Date(iso).toLocaleString('zh-TW', {
    timeZone: 'Asia/Taipei', month: 'numeric', day: 'numeric',
    hour: '2-digit', minute: '2-digit', weekday: 'short',
  })
}
