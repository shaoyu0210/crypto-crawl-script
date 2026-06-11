// Detail.tsx — 個幣詳情：K 線疊圖 + MTF + setup + 籌碼六格 + 相關新聞
import { useEffect, useState } from 'preact/hooks'
import { api, fetchKlines, fmtPct, fmtPrice, type Kline } from '../api'
import { Chart, type Toggles } from '../components/Chart'
import { SetupCard } from '../components/SetupCard'
import { Gauge } from '../components/Gauge'

const INTERVALS = ['15m', '1h', '4h', '1d']
const BIAS: Record<string, string> = { up: '↑ 偏多', down: '↓ 偏空', neutral: '— 中性' }

export function Detail({ symbol }: { symbol: string }) {
  const [block, setBlock] = useState<any>(null)
  const [err, setErr] = useState('')
  const [interval, setIv] = useState('1h')
  const [klines, setKlines] = useState<Kline[]>([])
  const [tg, setTg] = useState<Toggles>({ levels: true, fib: false, channel: true, setup: true })

  useEffect(() => {
    api(`/api/symbol/${symbol}`).then(setBlock).catch((e) => setErr(e.message))
  }, [symbol])

  useEffect(() => {
    let alive = true
    fetchKlines(symbol, interval).then((k) => alive && setKlines(k)).catch(() => {})
    const t = setInterval(() => {
      fetchKlines(symbol, interval).then((k) => alive && setKlines(k)).catch(() => {})
    }, 30_000)
    return () => { alive = false; clearInterval(t) }
  }, [symbol, interval])

  if (err) return <div class="page"><div class="center">⚠ {err}</div></div>
  if (!block) return <div class="page"><div class="center">載入中…</div></div>

  const a = block.assessment
  const d = block.derivs
  const flip = (k: keyof Toggles) => setTg({ ...tg, [k]: !tg[k] })

  return (
    <div class="page">
      <div class="topbar">
        <span><button class="linklike" onClick={() => { location.hash = '#/' }}>← 返回</button></span>
        <h1>{block.base} <span class="price">{fmtPrice(block.price)}</span>{' '}
          <span class={block.change_24h_pct >= 0 ? 'up' : 'down'}>{fmtPct(block.change_24h_pct)}</span></h1>
        <span />
      </div>

      <div class="chart-box">
        <div class="pills">
          {INTERVALS.map((iv) => (
            <button class={`pill ${interval === iv ? 'on' : ''}`} onClick={() => setIv(iv)}>{iv}</button>
          ))}
        </div>
        <Chart data={klines}
          overlays={{ levels: block.levels, fib: block.fib, channel: block.channel, setup: block.setup }}
          toggles={tg} />
        <div class="pills">
          <button class={`pill ${tg.levels ? 'on' : ''}`} onClick={() => flip('levels')}>壓撐</button>
          <button class={`pill ${tg.fib ? 'on' : ''}`} onClick={() => flip('fib')}>斐波</button>
          <button class={`pill ${tg.channel ? 'on' : ''}`} onClick={() => flip('channel')}>通道</button>
          <button class={`pill ${tg.setup ? 'on' : ''}`} onClick={() => flip('setup')}>setup</button>
        </div>
        <div class="muted" style="padding:0 10px 8px">
          疊圖價位以 1h 框計算；K 線可切其他時間框對照
        </div>
      </div>

      {a.verified_signal && (
        <div class="card" style="border-color: rgba(241,196,15,.45)">
          <span class="badge gold">★ {a.verified_signal.scope === 'verified' ? 'Verified edge' : 'Edge（類比參考）'}</span>
          <div style="margin-top:6px">{a.verified_signal.label} → {a.direction}</div>
          <div class="muted" style="margin-top:4px">{a.verified_signal.risk_note}</div>
        </div>
      )}

      <SetupCard setup={block.setup} />

      <div class="section-title">多時間框架</div>
      <div class="card">
        <div class="grid2">
          <div class="cell">4h 方向<b>{BIAS[block.mtf.bias_4h]}</b></div>
          <div class="cell">1h 位置<b>{BIAS[block.mtf.bias_1h]}</b></div>
          <div class="cell">15m 觸發<b>{BIAS[block.mtf.bias_15m]}</b></div>
          <div class="cell">環境<b>{block.regime.desc}</b></div>
        </div>
        <div class="muted" style="margin-top:8px">{block.mtf.desc}</div>
      </div>

      <div class="section-title">傾向評分（未驗證，僅參考）</div>
      <div class="card">
        <Gauge score={a.tendency.score} label={a.tendency.label} />
        <div style="margin-top:8px">
          {a.tendency.reasons.map((r: string) => <div class="muted" style="padding:2px 0">• {r}</div>)}
          {a.tendency.reasons.length === 0 && <div class="muted">各因子皆中性</div>}
        </div>
        {a.event && <div class={`badge ${a.event.kind === 'pump' ? 'green' : 'red'}`} style="margin-top:6px">{a.event.label}</div>}
        <div class="disclaimer">{a.tendency.note}</div>
      </div>

      <div class="section-title">籌碼面</div>
      <div class="grid2">
        <div class="cell">資金費率
          <b class={d.funding != null && d.funding < 0 ? 'down' : ''}>
            {d.funding != null ? (d.funding * 100).toFixed(4) + '%' : '—'}</b>
          <span class="muted">{d.funding_trend ?? ''}</span>
        </div>
        <div class="cell">OI 變化
          <b>{fmtPct(d.oi_chg_24h_pct)} / 24h</b>
          <span class="muted">{d.oi_quadrant ?? ''}（1h {fmtPct(d.oi_chg_1h_pct)}）</span>
        </div>
        <div class="cell">多空比（散戶）
          <b>{d.lsr ?? '—'}</b>
          <span class="muted">偏離 1 越遠越擁擠（反向參考）</span>
        </div>
        <div class="cell">Taker 買占比
          <b class={d.taker_ratio > 0.52 ? 'up' : d.taker_ratio < 0.48 ? 'down' : ''}>{d.taker_ratio ?? '—'}</b>
        </div>
        <div class="cell">CVD 背離
          <b>{d.cvd?.divergence === 'bearish' ? '⚠ 看跌背離' : d.cvd?.divergence === 'bullish' ? '⚠ 看漲背離' : '無'}</b>
          <span class="muted">價量背離為短線警訊</span>
        </div>
        <div class="cell">掛單失衡（±1%）
          <b class={d.depth?.bid_ratio > 0.55 ? 'up' : d.depth?.bid_ratio < 0.45 ? 'down' : ''}>
            {d.depth?.available ? `買盤 ${(d.depth.bid_ratio * 100).toFixed(0)}%` : '—'}</b>
        </div>
      </div>
      {d.liquidation_suspect && (
        <div class="banner" style="margin-top:8px">⚡ 疑似清算掃損（OI 驟降＋長影線＋爆量，近似判定）</div>
      )}

      {block.news_top?.length > 0 && (
        <>
          <div class="section-title">相關新聞</div>
          {block.news_top.map((n: any) => (
            <div class="news-item">
              <span class={`dot`} style={`background:${n.sentiment === 'positive' ? 'var(--green)' : n.sentiment === 'negative' ? 'var(--red)' : 'var(--muted)'}`} />
              <a href={n.url} target="_blank" rel="noopener">{n.title}</a>
              <span class="muted">　{n.source}</span>
            </div>
          ))}
        </>
      )}
    </div>
  )
}
