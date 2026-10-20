import { useCallback, useEffect, useRef, useState } from 'react'
import { addWatchlist, getWatchlist, removeWatchlist, syncNow } from '../api'
import { fmt, pct, verdictClass } from '../format'

const SHORT = { day_trading: 'Day', short_term: 'Short', long_term: 'Long' }

export default function WatchlistPanel({ onOpen }) {
  const [data, setData] = useState(null)
  const [symbols, setSymbols] = useState('')
  const [kind, setKind] = useState('')
  const [days, setDays] = useState(365)
  const [err, setErr] = useState('')
  const [showLog, setShowLog] = useState(false)
  const timer = useRef(null)

  const load = useCallback(() => getWatchlist().then(setData).catch((e) => setErr(e.message)), [])

  // poll quickly while a sync is running, slowly otherwise
  useEffect(() => {
    load()
    return () => clearTimeout(timer.current)
  }, [load])
  useEffect(() => {
    clearTimeout(timer.current)
    timer.current = setTimeout(load, data?.sync?.running ? 1500 : 30000)
  }, [data, load])

  const add = async (e) => {
    e.preventDefault()
    setErr('')
    try {
      await addWatchlist(symbols, kind, days)
      setSymbols('')
      setShowLog(true)
      load()
    } catch (x) { setErr(x.message) }
  }
  const sync = async (syms) => {
    setErr('')
    try { await syncNow(syms); setShowLog(true); load() } catch (x) { setErr(x.message) }
  }
  const remove = async (s) => {
    if (!window.confirm(`Stop tracking ${s}? Stored history and past analyses are kept.`)) return
    await removeWatchlist(s); load()
  }

  const job = data?.sync
  const prog = job?.progress
  const sched = data?.scheduler

  return (
    <div className="stack">
      {err && <div className="error">{err}</div>}
      <section className="panel">
        <div className="panel-head">
          <div>
            <h3>Watchlist · auto-sync from NSE bhavcopy</h3>
            <span className="muted tiny">
              {sched?.enabled
                ? <>Runs automatically Mon–Fri at {sched.time_ist} IST · next run {sched.next_run?.replace('T', ' ').slice(0, 16)}</>
                : 'Automatic schedule is off (AUTO_SYNC=false) — use Sync now.'}
            </span>
          </div>
          <button className="primary" disabled={job?.running || !data?.items?.length} onClick={() => sync()}>
            {job?.running ? 'Syncing…' : 'Sync now'}
          </button>
        </div>

        <form className="wl-add" onSubmit={add}>
          <input className="grow" value={symbols} onChange={(e) => setSymbols(e.target.value.toUpperCase())}
            placeholder="NSE symbols, comma-separated — e.g. RELIANCE, TCS, M&M, NIFTY 50" />
          <select value={kind} onChange={(e) => setKind(e.target.value)} title="Stock or index">
            <option value="">Auto-detect</option>
            <option value="equity">Stock</option>
            <option value="index">Index</option>
          </select>
          <select value={days} onChange={(e) => setDays(+e.target.value)} title="History to backfill for new symbols">
            <option value={180}>Backfill 6 months</option>
            <option value={365}>Backfill 1 year</option>
            <option value={730}>Backfill 2 years</option>
          </select>
          <button className="primary" disabled={!symbols.trim() || job?.running}>Add & sync</button>
        </form>
        <p className="tiny muted">
          New symbols are backfilled from daily bhavcopy files (≈250 files per year; cached and shared across symbols, so the
          first backfill takes a few minutes and later ones are instant). Symbols you already uploaded by CSV just continue from their last date.
        </p>

        {(job?.running || (showLog && job?.log?.length > 0)) && (
          <div className="sync-box">
            {job.running && prog && (
              <>
                <div className="row tiny"><span>Fetching {prog.date}</span><span className="muted">{prog.done} / {prog.total} days</span></div>
                <div className="progress"><b style={{ width: `${(prog.done / prog.total) * 100}%` }} /></div>
              </>
            )}
            {!job.running && job.finished_at && (
              <div className="tiny">
                Last sync finished {job.finished_at.replace('T', ' ').slice(0, 19)} ({job.trigger}){job.error && <b className="down"> · {job.error}</b>}
              </div>
            )}
            <button className="link tiny" onClick={() => setShowLog(!showLog)}>{showLog ? 'Hide' : 'Show'} log</button>
            {showLog && <pre className="log">{job.log.join('\n')}</pre>}
          </div>
        )}
      </section>

      <section className="panel">
        <div className="table-wrap">
          <table className="tbl wl">
            <thead>
              <tr>
                <th>Symbol</th><th>Data to</th><th className="num">Close</th><th className="num">Chg</th>
                <th>Day</th><th>Short</th><th>Long</th><th>Pattern</th><th />
              </tr>
            </thead>
            <tbody>
              {data?.items?.map((it) => (
                <tr key={it.symbol}>
                  <td>
                    <b>{it.symbol}</b>
                    <div className="tiny muted">{it.kind === 'index' ? 'Index' : 'Stock'} · {it.rows} sessions</div>
                  </td>
                  <td>{it.last_date || <span className="muted">—</span>}</td>
                  <td className="num">{it.close != null ? fmt(it.close) : '—'}</td>
                  <td className={`num ${it.change_pct >= 0 ? 'up' : 'down'}`}>{it.change_pct != null ? pct(it.change_pct, 2) : ''}</td>
                  {['day_trading', 'short_term', 'long_term'].map((k) => (
                    <td key={k}>
                      {it.verdicts ? <span className={`badge sm ${verdictClass(it.verdicts[k])}`} title={SHORT[k]}>{it.verdicts[k]}</span> : <span className="muted">—</span>}
                    </td>
                  ))}
                  <td className="tiny wl-pat" title={it.pattern || ''}>{it.pattern || <span className="muted">—</span>}</td>
                  <td className="wl-actions">
                    <button disabled={!it.verdicts} onClick={() => onOpen(it.symbol)}>Open</button>
                    <button className="ghost" disabled={job?.running} onClick={() => sync([it.symbol])} title="Sync this symbol">↻</button>
                    <button className="ghost" onClick={() => remove(it.symbol)} title="Remove">✕</button>
                  </td>
                </tr>
              ))}
              {data && !data.items.length && (
                <tr><td colSpan={9} className="muted">No symbols yet. Add a few above — e.g. your NIFTY 50 history continues automatically if you add NIFTY50.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
