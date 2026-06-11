// News.tsx — 經濟日曆（台北時間）+ 川普 Truth Social + 媒體新聞流
import { useEffect, useState } from 'preact/hooks'
import { api, relTime, taipeiTime } from '../api'

const MOOD: Record<string, string> = {
  positive: '😀 偏正面', negative: '😨 偏負面', neutral: '😐 中性',
}

export function News() {
  const [data, setData] = useState<any>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    api('/api/news').then(setData).catch((e) => setErr(e.message))
  }, [])

  if (err) return <div class="page"><div class="center">⚠ {err}</div></div>
  if (!data) return <div class="page"><div class="center">載入中…</div></div>

  const news = data.news ?? {}
  const trumpPosts = data.trump?.posts ?? []
  const events = data.upcoming_events ?? []

  return (
    <div class="page">
      <div class="topbar"><h1>📰 新聞與事件</h1>
        {news.market_mood && <span class="muted">市場氛圍 {MOOD[news.market_mood.label]}</span>}
      </div>

      {data.event_window && <div class="banner">⏰ {data.event_window.label}</div>}

      <div class="section-title">經濟日曆（台北時間，未來 7 天）</div>
      <div class="card">
        {events.length === 0 && <div class="muted">近期無高影響事件</div>}
        {events.map((ev: any) => (
          <div class="ev-row">
            <span class="ev-time">{taipeiTime(ev.time_utc)}</span>
            <span>
              {ev.impact === 'high' && <span class="badge red" style="margin:0 6px 0 0">高</span>}
              {ev.title}
              {ev.forecast && <span class="muted">　預期 {ev.forecast}｜前值 {ev.previous ?? '—'}</span>}
            </span>
          </div>
        ))}
        {data.calendar?.degraded && <div class="muted" style="margin-top:6px">⚠ 日曆來源降級（僅內建 FOMC 日期）</div>}
      </div>

      <div class="section-title">川普 Truth Social</div>
      <div class="card">
        {!data.trump?.available && <div class="muted">來源暫不可用</div>}
        {trumpPosts.map((p: any) => (
          <div class="news-item" style={p.market_related ? 'border-left:3px solid var(--gold); padding-left:8px' : ''}>
            <a href={p.url} target="_blank" rel="noopener">{p.title}</a>
            <div class="muted" style="margin-top:3px">
              {relTime(p.published)}
              {p.market_related && <span>　🔥 {p.hits.join(', ')}</span>}
            </div>
          </div>
        ))}
        <div class="muted" style="margin-top:6px">{data.trump?.note}</div>
      </div>

      <div class="section-title">加密媒體新聞（近 {news.window_hours ?? 6} 小時）</div>
      <div class="card">
        {(news.items ?? []).map((n: any) => (
          <div class="news-item">
            <span class="dot" style={`background:${n.sentiment.label === 'positive' ? 'var(--green)' : n.sentiment.label === 'negative' ? 'var(--red)' : 'var(--muted)'}`} />
            <a href={n.url} target="_blank" rel="noopener">{n.title}</a>
            <span class="muted">　{n.source}・{relTime(n.published)}</span>
          </div>
        ))}
        {(news.failed_sources ?? []).length > 0 && (
          <div class="muted" style="margin-top:6px">⚠ 失效來源：{news.failed_sources.join('、')}</div>
        )}
        <div class="muted" style="margin-top:6px">{news.note}</div>
      </div>
    </div>
  )
}
