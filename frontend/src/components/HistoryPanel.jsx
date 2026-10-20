import { useEffect, useState } from 'react'
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine, CartesianGrid } from 'recharts'
import { getHistory, getSymbols, searchMemory, deleteHistory } from '../api'
import { fmt, verdictClass, SERIES } from '../format'

export default function HistoryPanel({ initialSymbol }) {
  const [symbols, setSymbols] = useState([])
  const [sym, setSym] = useState(initialSymbol || '')
  const [rows, setRows] = useState([])
  const [q, setQ] = useState('')
  const [hits, setHits] = useState(null)
  const [err, setErr] = useState('')

  const loadSymbols = () => getSymbols().then(setSymbols).catch((e) => setErr(e.message))
  useEffect(() => { loadSymbols() }, [])
  useEffect(() => {
    if (!sym && symbols.length) setSym(symbols[0].symbol)
  }, [symbols, sym])
  useEffect(() => {
    if (sym) getHistory(sym).then(setRows).catch((e) => setErr(e.message))
  }, [sym])

  const series = [...rows].reverse().map((r) => ({
    date: r.created_at?.slice(0, 16).replace('T', ' '),
    day: r.day_trading_score, short: r.short_term_score, long: r.long_term_score,
  }))

  const remove = async () => {
    if (!window.confirm(`Delete all stored analyses for ${sym}?`)) return
    await deleteHistory(sym)
    setRows([]); setSym(''); loadSymbols()
  }

  return (
    <div className="stack">
      {err && <div className="error">{err}</div>}
      <section className="panel" data-tour="hist-stored">
        <div className="panel-head">
          <h3>Stored analyses</h3>
          <div className="row">
            <select value={sym} onChange={(e) => setSym(e.target.value)}>
              {symbols.map((s) => <option key={s.symbol} value={s.symbol}>{s.symbol} ({s.analyses})</option>)}
            </select>
            {sym && <button className="ghost" onClick={remove}>Delete</button>}
          </div>
        </div>
        {series.length > 1 && (
          <>
            <div className="mini-legend">
              <span><i style={{ background: SERIES.sma20 }} />Day trading</span>
              <span><i style={{ background: SERIES.sma50 }} />Short term</span>
              <span><i style={{ background: SERIES.sma200 }} />Long term</span>
            </div>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={series} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                <CartesianGrid stroke="var(--grid)" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} tickLine={false} axisLine={false} minTickGap={40} />
                <YAxis domain={[-100, 100]} ticks={[-100, -25, 0, 25, 100]} tick={{ fontSize: 11, fill: 'var(--text-muted)' }} tickLine={false} axisLine={false} />
                <ReferenceLine y={0} stroke="var(--text-muted)" />
                <Tooltip />
                <Line dataKey="day" name="Day trading" stroke={SERIES.sma20} strokeWidth={2} dot={{ r: 4 }} isAnimationActive={false} />
                <Line dataKey="short" name="Short term" stroke={SERIES.sma50} strokeWidth={2} dot={{ r: 4 }} isAnimationActive={false} />
                <Line dataKey="long" name="Long term" stroke={SERIES.sma200} strokeWidth={2} dot={{ r: 4 }} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </>
        )}
        <div className="table-wrap">
          <table className="tbl">
            <thead>
              <tr><th>Analysed</th><th>Data to</th><th className="num">Close</th><th>Day</th><th>Short</th><th>Long</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} title={r.summary}>
                  <td>{r.created_at?.replace('T', ' ')}</td>
                  <td>{r.last_date?.slice(0, 16).replace('T00:00', '')}</td>
                  <td className="num">₹{fmt(r.close)}</td>
                  {['day_trading', 'short_term', 'long_term'].map((k) => (
                    <td key={k}><span className={`badge sm ${verdictClass(r[`${k}_verdict`])}`}>{r[`${k}_verdict`]}</span></td>
                  ))}
                </tr>
              ))}
              {!rows.length && <tr><td colSpan={6} className="muted">No analyses stored yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel" data-tour="hist-search">
        <h3>Semantic search across all analyses</h3>
        <form className="row" onSubmit={(e) => { e.preventDefault(); searchMemory(q).then(setHits).catch((x) => setErr(x.message)) }}>
          <input className="grow" value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. oversold bounce near support with bullish engulfing" />
          <button className="primary" disabled={!q}>Search</button>
        </form>
        {hits && (
          <ul className="similar">
            {hits.map((h) => (
              <li key={h.id}>
                <b>{h.symbol}</b> <span className="muted tiny">· {h.created_at?.replace('T', ' ')} · similarity {(h.similarity * 100).toFixed(0)}%</span>
                <div className="tiny">{h.summary}</div>
              </li>
            ))}
            {!hits.length && <li className="muted">No matches.</li>}
          </ul>
        )}
      </section>
    </div>
  )
}
