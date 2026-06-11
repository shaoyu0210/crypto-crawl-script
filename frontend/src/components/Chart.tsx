// Chart.tsx — lightweight-charts K 線封裝：疊加關鍵價位/斐波/通道/setup 區帶
import { useEffect, useRef } from 'preact/hooks'
import {
  createChart, CrosshairMode, LineStyle,
  type IChartApi, type ISeriesApi, type IPriceLine,
} from 'lightweight-charts'
import type { Kline } from '../api'

export interface Overlays {
  levels?: any[]
  fib?: any
  channel?: any
  setup?: any
}
export interface Toggles {
  levels: boolean
  fib: boolean
  channel: boolean
  setup: boolean
}

export function Chart({ data, overlays, toggles }: {
  data: Kline[]; overlays: Overlays; toggles: Toggles
}) {
  const boxRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const linesRef = useRef<IPriceLine[]>([])

  useEffect(() => {
    if (!boxRef.current) return
    const chart = createChart(boxRef.current, {
      height: Math.round(window.innerHeight * 0.45),
      layout: { background: { color: '#161b22' }, textColor: '#8b949e', fontSize: 11 },
      grid: { vertLines: { color: '#21262d' }, horzLines: { color: '#21262d' } },
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: '#2d333b' },
      rightPriceScale: { borderColor: '#2d333b' },
    })
    const series = chart.addCandlestickSeries({
      upColor: '#2ecc71', downColor: '#e74c3c',
      wickUpColor: '#2ecc71', wickDownColor: '#e74c3c',
      borderVisible: false,
    })
    chartRef.current = chart
    seriesRef.current = series
    const onResize = () => chart.applyOptions({ width: boxRef.current!.clientWidth })
    onResize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
      linesRef.current = []
    }
  }, [])

  // K 線資料更新
  useEffect(() => {
    if (!seriesRef.current || !data.length) return
    seriesRef.current.setData(data as any)
    chartRef.current?.timeScale().scrollToRealTime()
  }, [data])

  // 疊圖價位線更新
  useEffect(() => {
    const series = seriesRef.current
    if (!series) return
    for (const l of linesRef.current) series.removePriceLine(l)
    linesRef.current = []

    const add = (price: number, color: string, title: string,
                 style = LineStyle.Dashed, width: 1 | 2 = 1) => {
      if (price == null || !isFinite(price)) return
      linesRef.current.push(series.createPriceLine({
        price, color, lineWidth: width, lineStyle: style,
        axisLabelVisible: true, title,
      }))
    }

    if (toggles.levels) {
      for (const lv of overlays.levels ?? []) {
        const strong = lv.strength >= 3
        add(lv.price, strong ? '#8b949e' : '#444c56',
            lv.label.split(' +')[0], LineStyle.Dashed, strong ? 2 : 1)
      }
    }
    if (toggles.fib && overlays.fib?.available) {
      for (const [k, p] of Object.entries(overlays.fib.levels as Record<string, number>)) {
        add(p, '#f1c40f', `fib ${k}`, LineStyle.Dotted)
      }
    }
    if (toggles.channel && overlays.channel?.available) {
      add(overlays.channel.upper, '#58a6ff', '上軌')
      add(overlays.channel.mid, '#58a6ff', '中軌', LineStyle.Dotted)
      add(overlays.channel.lower, '#58a6ff', '下軌')
    }
    if (toggles.setup && overlays.setup) {
      const s = overlays.setup
      add(s.entry_low, '#bc8cff', '進場下緣', LineStyle.Solid)
      add(s.entry_high, '#bc8cff', '進場上緣', LineStyle.Solid)
      add(s.stop, '#e74c3c', '止損', LineStyle.Solid, 2)
      s.targets.forEach((t: any, i: number) =>
        add(t.price, '#2ecc71', `目標${i + 1}`, LineStyle.Solid))
    }
  }, [overlays, toggles, data])

  return <div ref={boxRef} />
}
