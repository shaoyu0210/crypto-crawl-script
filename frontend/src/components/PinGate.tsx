// PinGate.tsx — 數字鍵盤 PIN 輸入，成功後 token 存 localStorage
import { useState } from 'preact/hooks'
import { login } from '../api'

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '', '0', '⌫']

export function PinGate({ onSuccess }: { onSuccess: () => void }) {
  const [pin, setPin] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  async function press(k: string) {
    if (busy || !k) return
    setErr('')
    if (k === '⌫') {
      setPin(pin.slice(0, -1))
      return
    }
    const next = pin + k
    setPin(next)
    if (next.length >= 4) {
      setBusy(true)
      try {
        await login(next)
        onSuccess()
      } catch (e: any) {
        setErr(e.message || 'PIN 錯誤')
        setPin('')
      } finally {
        setBusy(false)
      }
    }
  }

  return (
    <div class="pin-wrap">
      <h1>幣勢監控</h1>
      <div class="muted">輸入 PIN 碼</div>
      <div class="pin-dots">
        {[0, 1, 2, 3].map((i) => (
          <div class={`pin-dot ${i < pin.length ? 'on' : ''}`} />
        ))}
      </div>
      <div class="pin-err">{busy ? '驗證中…' : err}</div>
      <div class="pin-pad">
        {KEYS.map((k) => (
          <button onClick={() => press(k)} style={k === '' ? 'visibility:hidden' : ''}>
            {k}
          </button>
        ))}
      </div>
    </div>
  )
}
