import { useEffect, useRef, useState } from 'react'
import { createChart, CrosshairMode, LineStyle } from 'lightweight-charts'
import { SERIES, UP, DOWN, fmt } from '../format'

const OVERLAYS = [
  { key: 'sma20', label: 'SMA 20' },
  { key: 'sma50', label: 'SMA 50' },
  { key: 'sma200', label: 'SMA 200' },
  { key: 'ema9', label: 'EMA 9' },
  { key: 'ema21', label: 'EMA 21' },
  { key: 'vwap', label: 'VWAP' },
  { key: 'bb', label: 'Bollinger' },
  { key: 'supertrend', label: 'Supertrend' },
  { key: 'levels', label: 'S/R levels' },
  { key: 'patterns', label: 'Candle patterns' },
]

export default function PriceChart({ data, levels, intraday, patterns = [] }) {
  const ref = useRef(null)
  const [on, setOn] = useState({ sma50: true, ema21: true, supertrend: true, levels: true, patterns: true })
  const [hover, setHover] = useState(null)

  useEffect(() => {
    if (!ref.current || !data?.length) return
    const dark = window.matchMedia('(prefers-color-scheme: dark)').matches
    const ink = dark ? '#c3c2b7' : '#52514e'
    const grid = dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'
    const chart = createChart(ref.current, {
      height: ref.current.clientHeight || 440,
      width: ref.current.clientWidth,
      layout: { background: { color: 'transparent' }, textColor: ink, fontFamily: 'inherit' },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      crosshair: { mode: CrosshairMode.Normal },
      localization: { locale: 'en-IN', priceFormatter: (p) => p.toFixed(2) },
      rightPriceScale: { scaleMargins: { top: 0.06, bottom: 0.24 }, borderVisible: false },
      timeScale: { timeVisible: intraday, borderVisible: false, rightOffset: 4 },
    })

    // daily bars use calendar dates (clean axis labels); intraday uses IST clock timestamps
    const T = (d) => (intraday ? d.ts : d.date)
    const key = (t) => (t && typeof t === 'object' ? `${t.year}-${String(t.month).padStart(2, '0')}-${String(t.day).padStart(2, '0')}` : t)

    const candles = chart.addCandlestickSeries({
      upColor: UP, downColor: DOWN, borderVisible: false, wickUpColor: UP, wickDownColor: DOWN,
    })
    candles.setData(data.map((d) => ({ time: T(d), open: d.open, high: d.high, low: d.low, close: d.close })))

    const vol = chart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: 'vol', lastValueVisible: false, priceLineVisible: false })
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })
    vol.setData(data.map((d) => ({ time: T(d), value: d.volume, color: d.close >= d.open ? UP + '66' : DOWN + '66' })))

    const line = (key, color, opts = {}) => {
      const s = chart.addLineSeries({ color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, ...opts })
      s.setData(data.filter((d) => d[key] != null).map((d) => ({ time: T(d), value: d[key] })))
      return s
    }
    for (const k of ['sma20', 'sma50', 'sma200', 'ema9', 'ema21', 'vwap']) if (on[k]) line(k, SERIES[k])
    if (on.bb) {
      const c = dark ? '#8d8c86' : '#9a9993'
      line('bb_upper', c, { lineWidth: 1, lineStyle: LineStyle.Dashed })
      line('bb_mid', c, { lineWidth: 1, lineStyle: LineStyle.Dotted })
      line('bb_lower', c, { lineWidth: 1, lineStyle: LineStyle.Dashed })
    }
    if (on.supertrend) {
      const s = chart.addLineSeries({ lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
      s.setData(data.filter((d) => d.supertrend != null).map((d) => ({ time: T(d), value: d.supertrend, color: d.st_dir > 0 ? UP : DOWN })))
    }
    if (on.levels && levels) {
      levels.supports?.slice(0, 3).forEach((l, i) =>
        candles.createPriceLine({ price: l.price, color: UP, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: `S${i + 1}` }))
      levels.resistances?.slice(0, 3).forEach((l, i) =>
        candles.createPriceLine({ price: l.price, color: DOWN, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: `R${i + 1}` }))
    }

    if (on.patterns && patterns.length) {
      const first = data[0]
      candles.setMarkers(
        patterns
          .filter((p) => (intraday ? p.ts >= first.ts : p.date >= first.date))
          .map((p) => ({
            time: intraday ? p.ts : p.date,
            position: p.bias > 0 ? 'belowBar' : 'aboveBar',
            shape: p.bias > 0 ? 'arrowUp' : 'arrowDown',
            color: p.bias > 0 ? UP : DOWN,
            text: p.short,
          }))
      )
    }

    const byTs = new Map(data.map((d) => [T(d), d]))
    chart.subscribeCrosshairMove((p) => setHover(p?.time ? byTs.get(key(p.time)) : null))

    // default view: last ~6 months
    const n = data.length
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - (intraday ? 300 : 130)), to: n + 3 })

    const ro = new ResizeObserver(() => chart.applyOptions({ width: ref.current.clientWidth, height: ref.current.clientHeight }))
    ro.observe(ref.current)
    return () => { ro.disconnect(); chart.remove() }
  }, [data, levels, intraday, on, patterns])

  const last = hover || data[data.length - 1]
  const patternsByDate = new Map(patterns.map((p) => [p.date, p.patterns]))
  return (
    <section className="panel">
      <div className="panel-head">
        <h3>Price chart</h3>
        <div className="legend">
          {OVERLAYS.map((o) => (
            <button key={o.key} className={`chip ${on[o.key] ? 'on' : ''}`} onClick={() => setOn({ ...on, [o.key]: !on[o.key] })}>
              {SERIES[o.key] && <i style={{ background: SERIES[o.key] }} />}
              {o.label}
            </button>
          ))}
        </div>
      </div>
      {last && (
        <div className="ohlc">
          <span>{last.date}</span>
          <span>O {fmt(last.open)}</span><span>H {fmt(last.high)}</span>
          <span>L {fmt(last.low)}</span><span>C <b>{fmt(last.close)}</b></span>
          <span>Vol {fmt(last.volume, 0)}</span>
          {patternsByDate.get(last.date) && <span className="pat-tag">{patternsByDate.get(last.date).join(', ')}</span>}
        </div>
      )}
      <div ref={ref} className="chart-box" />
    </section>
  )
}
