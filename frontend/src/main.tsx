// main.tsx — 進入點：PIN gate + hash 路由 + 底部 tab
import { render } from 'preact'
import { useEffect, useState } from 'preact/hooks'
import { getToken } from './api'
import { PinGate } from './components/PinGate'
import { Overview } from './pages/Overview'
import { Detail } from './pages/Detail'
import { News } from './pages/News'
import './styles.css'

type Route = { page: 'overview' } | { page: 'news' } | { page: 'symbol'; symbol: string }

function parseHash(): Route {
  const h = location.hash.replace(/^#\/?/, '')
  if (h.startsWith('symbol/')) return { page: 'symbol', symbol: h.slice(7).toUpperCase() }
  if (h === 'news') return { page: 'news' }
  return { page: 'overview' }
}

function App() {
  const [authed, setAuthed] = useState(!!getToken())
  const [route, setRoute] = useState<Route>(parseHash())

  useEffect(() => {
    const onHash = () => setRoute(parseHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  if (!authed) return <PinGate onSuccess={() => setAuthed(true)} />

  return (
    <>
      {route.page === 'overview' && <Overview />}
      {route.page === 'news' && <News />}
      {route.page === 'symbol' && <Detail symbol={route.symbol} />}
      <nav class="tabbar">
        <a href="#/" class={route.page !== 'news' ? 'active' : ''}>📊 監控</a>
        <a href="#/news" class={route.page === 'news' ? 'active' : ''}>📰 新聞事件</a>
      </nav>
    </>
  )
}

render(<App />, document.getElementById('app')!)
