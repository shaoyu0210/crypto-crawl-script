// SetupCard.tsx — 交易計畫草稿卡（進場區/止損/目標/R-R + 誠實標示）
import { fmtPrice } from '../api'

const STATUS_LABEL: Record<string, string> = {
  active: '🎯 進場區內', watch: '👀 接近中', far: '⏳ 距離尚遠',
}

export function SetupCard({ setup, compact }: { setup: any; compact?: boolean }) {
  if (!setup) return null
  const sideCls = setup.side === 'long' ? 'green' : 'red'
  return (
    <div class="card" style="border-color: rgba(188,140,255,.35)">
      <div class="card-head">
        <span>
          <span class={`badge ${sideCls}`}>{setup.type}</span>
          <span class="badge purple">{STATUS_LABEL[setup.status] ?? setup.status}</span>
          {setup.counter_trend && <span class="badge red">逆勢</span>}
        </span>
        <span class="muted">R/R {setup.rr1}</span>
      </div>
      <div style="margin-top:8px">
        <div class="setup-line">
          <span class="muted">進場區</span>
          <span>{fmtPrice(setup.entry_low)} – {fmtPrice(setup.entry_high)}</span>
        </div>
        <div class="setup-line">
          <span class="muted">止損</span>
          <span class="down">{fmtPrice(setup.stop)}</span>
        </div>
        {setup.targets.map((t: any, i: number) => (
          <div class="setup-line">
            <span class="muted">目標{i + 1}（{t.label}）</span>
            <span class="up">{fmtPrice(t.price)}　R/R {t.rr}</span>
          </div>
        ))}
      </div>
      {!compact && (
        <>
          <div class="muted" style="margin-top:6px">共振：{setup.confluences.join('、')}</div>
          <div class="muted">{setup.mtf}</div>
          {setup.notes.map((n: string) => <div class="muted">{n}</div>)}
        </>
      )}
      <div class="disclaimer">⚠ {setup.disclaimer}</div>
    </div>
  )
}
