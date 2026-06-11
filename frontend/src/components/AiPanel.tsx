// AiPanel.tsx — 手動觸發 Gemini 總結分析（多空/信心/進場/目標/理由）
import { useState } from 'preact/hooks'
import { apiPost } from '../api'

const BIAS_CLS: Record<string, string> = { 看多: 'green', 看空: 'red', 觀望: 'gray' }

export function AiPanel({ symbol }: { symbol: string }) {
  const [result, setResult] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function run() {
    setBusy(true)
    setErr('')
    try {
      setResult(await apiPost(`/api/ai/analyze/${symbol}`))
    } catch (e: any) {
      setErr(e.message || 'AI 分析失敗')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div class="section-title">AI 總結分析（Gemini）</div>
      <div class="card">
        {!result && (
          <button class="ai-btn" onClick={run} disabled={busy}>
            {busy ? '🤖 分析中…（約 10 秒）' : '🤖 AI 分析'}
          </button>
        )}
        {err && <div class="pin-err" style="margin-top:8px">⚠ {err}</div>}

        {result && (
          <>
            <div class="card-head">
              <span>
                <span class={`badge ${BIAS_CLS[result.bias] ?? 'gray'}`} style="font-size:14px">
                  {result.bias}
                </span>
                {result.cached && <span class="badge gray">快取結果</span>}
              </span>
              <span class="muted">信心 {result.confidence_pct}%</span>
            </div>
            <div class="gauge" style="background:linear-gradient(90deg,#444c56,var(--blue))">
              <div class="gauge-dot" style={`left:${result.confidence_pct}%`} />
            </div>
            <div style="margin-top:10px">
              <div class="setup-line"><span class="muted">進場</span><span style="text-align:right; max-width:70%">{result.entry}</span></div>
              {result.targets?.map((t: string, i: number) => (
                <div class="setup-line"><span class="muted">目標{i + 1}</span><span class="up" style="text-align:right; max-width:70%">{t}</span></div>
              ))}
              {result.stop && <div class="setup-line"><span class="muted">止損</span><span class="down" style="text-align:right; max-width:70%">{result.stop}</span></div>}
            </div>
            <div style="margin-top:8px">
              {result.reasons?.map((r: string) => <div class="muted" style="padding:2px 0">• {r}</div>)}
            </div>
            {result.caveats?.length > 0 && (
              <div style="margin-top:8px">
                {result.caveats.map((c: string) => <div class="muted" style="padding:2px 0; color:var(--gold)">⚠ {c}</div>)}
              </div>
            )}
            <div class="disclaimer">
              {result.model}・基於 {new Date(result.analyzed_at).toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })} 快照・{result.disclaimer}
            </div>
            <button class="linklike" style="margin-top:8px" onClick={run} disabled={busy}>
              {busy ? '分析中…' : '↻ 重新分析'}
            </button>
          </>
        )}
      </div>
    </>
  )
}
