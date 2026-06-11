// Overview.tsx — 總覽：BTC 狀態列 + 事件窗口橫幅 + RS 強弱條 + 標的卡片流
import { useEffect, useState } from 'preact/hooks'
import { api, fmtPrice, fmtPct, relTime } from '../api'
import { Gauge } from '../components/Gauge'

const REGIME_BADGE: Record<string, [string, string]> = {
  trend: ['趨勢', 'blue'], range: ['盤整', 'gray'], squeeze: ['擠壓', 'purple'],
}

function SymbolCard({ b }: { b: any }) {
  const a = b.assessment
  const setup = b.setup
  const edge = a.verified_signal
  const tend = a.tendency
  const [regLabel, regCls] = REGIME_BADGE[b.regime.regime] ?? ['?', 'gray']
  const topReason = edge ? edge.label
    : setup ? `${setup.type}｜進場 ${fmtPrice(setup.entry_low)}–${fmtPrice(setup.entry_high)}｜止損 ${fmtPrice(setup.stop)}｜R/R ${setup.rr1}`
    : a.event ? a.event.label
    : tend.reasons[0] ?? b.regime.desc

  return (
    <a href={`#/symbol/${b.symbol}`} style="text-decoration:none; color:inherit">
      <div class="card clickable">
        <div class="card-head">
          <span class="sym">{b.base}{b.stale && <span class="badge red">資料延遲</span>}</span>
          <span class="price">
            {fmtPrice(b.price)}
            <span class={b.change_24h_pct >= 0 ? 'up' : 'down'}>{fmtPct(b.change_24h_pct)}</span>
          </span>
        </div>
        <div>
          {edge && <span class="badge gold">★ {edge.scope === 'verified' ? 'verified edge' : 'edge 類比'}：留意反彈</span>}
          {setup && <span class="badge purple">{setup.type}（{setup.status === 'active' ? '進場區' : setup.status === 'watch' ? '接近' : '遠'}）R/R {setup.rr1}</span>}
          {a.event && <span class={`badge ${a.event.kind === 'pump' ? 'green' : 'red'}`}>{a.event.kind === 'pump' ? '大漲' : '大跌'}事件</span>}
          {!edge && !setup && !a.event && <span class="badge gray">觀望（無 edge）</span>}
          <span class={`badge ${regCls}`}>{regLabel}</span>
        </div>
        <Gauge score={tend.score} label={tend.label} />
        <div class="muted" style="margin-top:4px">{topReason}</div>
      </div>
    </a>
  )
}

export function Overview() {
  const [snap, setSnap] = useState<any>(null)
  const [err, setErr] = useState('')

  async function load() {
    try {
      setSnap(await api('/api/snapshot'))
      setErr('')
    } catch (e: any) {
      setErr(e.message)
    }
  }
  useEffect(() => {
    load()
    const t = setInterval(load, 60_000)
    return () => clearInterval(t)
  }, [])

  if (err && !snap) return <div class="page"><div class="center">⚠ {err}</div></div>
  if (!snap) return <div class="page"><div class="center">載入中…</div></div>

  const btc = snap.btc
  const health: Record<string, string> = snap.meta.data_health ?? {}
  const failed = Object.entries(health).filter(([, v]) => String(v).startsWith('fail'))
  const nextEv = (snap.upcoming_events ?? []).find((e: any) => e.impact === 'high' && new Date(e.time_utc) > new Date())

  return (
    <div class="page">
      <div class="topbar">
        <h1>📊 幣勢監控</h1>
        <span class="muted">更新 {relTime(snap.meta.generated_at)}</span>
      </div>

      {snap.event_window && <div class="banner">⏰ {snap.event_window.label}</div>}
      {failed.length > 0 && (
        <div class="banner" style="background:rgba(241,196,15,.1); border-color:rgba(241,196,15,.4); color:var(--gold)">
          ⚠ 部分來源異常：{failed.map(([k]) => k).join('、')}
        </div>
      )}

      {btc && (
        <div class="btcbar">
          <b>BTC {fmtPrice(btc.price)}</b>
          <span class={btc.change_24h_pct >= 0 ? 'up' : 'down'}>{fmtPct(btc.change_24h_pct)}</span>
          <span class="muted">{btc.regime.desc}</span>
        </div>
      )}
      {btc?.uncertain && <div class="muted" style="margin:-4px 0 10px 4px">⚠ {btc.note}</div>}
      {nextEv && !snap.event_window && (
        <div class="muted" style="margin:0 0 10px 4px">
          📅 下個高影響事件：{nextEv.title}（{Math.round((+new Date(nextEv.time_utc) - Date.now()) / 3600000)} 小時後）
        </div>
      )}

      {snap.rs?.table?.length > 0 && (
        <div class="rs-strip">
          {snap.rs.strongest.map((r: any) => (
            <a href={`#/symbol/${r.symbol}`} class="rs-chip" style="text-decoration:none">
              <span class="up">強 {r.symbol.replace('USDT', '')}</span>
              <span class="muted"> {fmtPct(r.rel_strength)}</span>
            </a>
          ))}
          {snap.rs.weakest.map((r: any) => (
            <a href={`#/symbol/${r.symbol}`} class="rs-chip" style="text-decoration:none">
              <span class="down">弱 {r.symbol.replace('USDT', '')}</span>
              <span class="muted"> {fmtPct(r.rel_strength)}</span>
            </a>
          ))}
        </div>
      )}

      {snap.symbols.map((b: any) => <SymbolCard b={b} />)}

      <div class="muted" style="margin-top:14px; line-height:1.6">
        {snap.meta.verified_signal_note}。本平台非投資建議，交易風險自負。
      </div>
    </div>
  )
}
