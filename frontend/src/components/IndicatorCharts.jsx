import { useMemo, useState } from 'react'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine, CartesianGrid,
  ComposedChart, Bar, Cell,
} from 'recharts'
import { SERIES, UP, DOWN, fmt } from '../format'

const RANGES = [
  { k: '3M', n: 63 }, { k: '6M', n: 126 }, { k: '1Y', n: 252 }, { k: 'All', n: Infinity },
]

const axis = { fontSize: 11, fill: 'var(--text-muted)' }

function Tip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="tip">
      <div className="tip-date">{label}</div>
      {payload.filter((p) => p.value != null).map((p) => (
        <div key={p.dataKey}><i style={{ background: p.color || p.payload?.fill }} />{p.name}: <b>{fmt(p.value)}</b></div>
      ))}
    </div>
  )
}

function Card({ title, children, legend }) {
  return (
    <div className="mini">
      <div className="mini-head">
        <h4>{title}</h4>
        {legend && <div className="mini-legend">{legend.map(([c, l]) => <span key={l}><i style={{ background: c }} />{l}</span>)}</div>}
      </div>
      <ResponsiveContainer width="100%" height={180}>{children}</ResponsiveContainer>
    </div>
  )
}

export default function IndicatorCharts({ data, intraday }) {
  const [range, setRange] = useState('6M')
  const rows = useMemo(() => {
    const n = RANGES.find((r) => r.k === range).n * (intraday ? 4 : 1)
    return data.slice(Number.isFinite(n) ? -n : 0)
  }, [data, range, intraday])

  const common = { data: rows, margin: { top: 6, right: 8, left: -12, bottom: 0 }, syncId: 'ind' }
  const grid = <CartesianGrid stroke="var(--grid)" vertical={false} />
  const x = <XAxis dataKey="date" tick={axis} minTickGap={40} tickLine={false} axisLine={false} />

  return (
    <section className="panel">
      <div className="panel-head">
        <h3>Indicators</h3>
        <div className="seg">
          {RANGES.map((r) => (
            <button key={r.k} className={range === r.k ? 'on' : ''} onClick={() => setRange(r.k)}>{r.k}</button>
          ))}
        </div>
      </div>
      <div className="grid2">
        <Card title="RSI (14)">
          <LineChart {...common}>
            {grid}{x}
            <YAxis domain={[0, 100]} ticks={[30, 50, 70]} tick={axis} tickLine={false} axisLine={false} />
            <ReferenceLine y={70} stroke={DOWN} strokeDasharray="4 4" />
            <ReferenceLine y={30} stroke={UP} strokeDasharray="4 4" />
            <Tooltip content={<Tip />} />
            <Line dataKey="rsi" name="RSI" stroke={SERIES.sma20} strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </Card>
        <Card title="MACD (12, 26, 9)" legend={[[SERIES.sma20, 'MACD'], [SERIES.sma50, 'Signal']]}>
          <ComposedChart {...common}>
            {grid}{x}
            <YAxis tick={axis} tickLine={false} axisLine={false} />
            <ReferenceLine y={0} stroke="var(--text-muted)" />
            <Tooltip content={<Tip />} />
            <Bar dataKey="macd_hist" name="Histogram" isAnimationActive={false}>
              {rows.map((r, i) => <Cell key={i} fill={(r.macd_hist ?? 0) >= 0 ? UP : DOWN} fillOpacity={0.55} />)}
            </Bar>
            <Line dataKey="macd" name="MACD" stroke={SERIES.sma20} strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line dataKey="macd_signal" name="Signal" stroke={SERIES.sma50} strokeWidth={2} dot={false} isAnimationActive={false} />
          </ComposedChart>
        </Card>
        <Card title="Stochastic (14, 3)" legend={[[SERIES.sma20, '%K'], [SERIES.sma50, '%D']]}>
          <LineChart {...common}>
            {grid}{x}
            <YAxis domain={[0, 100]} ticks={[20, 50, 80]} tick={axis} tickLine={false} axisLine={false} />
            <ReferenceLine y={80} stroke={DOWN} strokeDasharray="4 4" />
            <ReferenceLine y={20} stroke={UP} strokeDasharray="4 4" />
            <Tooltip content={<Tip />} />
            <Line dataKey="stoch_k" name="%K" stroke={SERIES.sma20} strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line dataKey="stoch_d" name="%D" stroke={SERIES.sma50} strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </Card>
        <Card title="ADX / DMI (14)" legend={[[SERIES.sma200, 'ADX'], [UP, '+DI'], [DOWN, '−DI']]}>
          <LineChart {...common}>
            {grid}{x}
            <YAxis tick={axis} tickLine={false} axisLine={false} />
            <ReferenceLine y={25} stroke="var(--text-muted)" strokeDasharray="4 4" />
            <Tooltip content={<Tip />} />
            <Line dataKey="adx" name="ADX" stroke={SERIES.sma200} strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line dataKey="plus_di" name="+DI" stroke={UP} strokeWidth={1.5} dot={false} isAnimationActive={false} />
            <Line dataKey="minus_di" name="−DI" stroke={DOWN} strokeWidth={1.5} dot={false} isAnimationActive={false} />
          </LineChart>
        </Card>
      </div>
    </section>
  )
}
