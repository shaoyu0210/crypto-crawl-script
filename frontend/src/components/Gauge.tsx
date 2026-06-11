// Gauge.tsx — 傾向分數儀表條（-100 ~ +100，固定附未驗證標示）
export function Gauge({ score, label }: { score: number; label: string }) {
  const pct = (score + 100) / 2   // -100..100 → 0..100
  return (
    <div>
      <div class="gauge">
        <div class="gauge-dot" style={`left:${pct}%`} />
      </div>
      <div style="display:flex; justify-content:space-between">
        <span class="muted">傾向 {score > 0 ? '+' : ''}{score}（未驗證）</span>
        <span class="muted">{label}</span>
      </div>
    </div>
  )
}
