import { useEffect, useState } from 'react'
import UploadPanel from './components/UploadPanel'
import PriceChart from './components/PriceChart'
import IndicatorCharts from './components/IndicatorCharts'
import TimeframeCard from './components/TimeframeCard'
import LevelsPanel from './components/LevelsPanel'
import PatternPanel from './components/PatternPanel'
import MemoryPanel from './components/MemoryPanel'
import HistoryPanel from './components/HistoryPanel'
import WatchlistPanel from './components/WatchlistPanel'
import { analyzeCsv, getHealth, getResult } from './api'
import { fmt, pct } from './format'

export default function App() {
  const [tab, setTab] = useState('analyse')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [health, setHealth] = useState(null)

  useEffect(() => { getHealth().then(setHealth).catch(() => setHealth(false)) }, [])

  const run = async (file, symbol, merge) => {
    setLoading(true); setError('')
    try {
      setResult(await analyzeCsv(file, symbol, merge))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const openSaved = async (symbol) => {
    setError('')
    try {
      setResult(await getResult(symbol))
      setTab('analyse')
      window.scrollTo(0, 0)
    } catch (e) {
      setError(e.message)
    }
  }

  const m = result?.meta
  return (
    <div className="app">
      <header className="top">
        <div>
          <h1>NSE Stock Analyzer</h1>
          <span className="muted tiny">
            Technical analysis · ML forecast · ChromaDB memory
            {health === false && <b className="down"> · backend offline (start uvicorn on :8000)</b>}
            {health && <> · {health.stored_analyses} analyses stored</>}
          </span>
        </div>
        <nav className="seg">
          <button className={tab === 'analyse' ? 'on' : ''} onClick={() => setTab('analyse')}>Analyse</button>
          <button className={tab === 'watchlist' ? 'on' : ''} onClick={() => setTab('watchlist')}>Watchlist</button>
          <button className={tab === 'history' ? 'on' : ''} onClick={() => setTab('history')}>History & search</button>
        </nav>
      </header>

      {tab === 'watchlist' ? (
        <WatchlistPanel onOpen={openSaved} />
      ) : tab === 'history' ? (
        <HistoryPanel initialSymbol={m?.symbol} />
      ) : (
        <div className="stack">
          <UploadPanel onAnalyze={run} loading={loading} />
          {error && <div className="error">{error}</div>}
          {loading && <div className="panel muted">Computing indicators, training models and recalling past analyses…</div>}

          {result && !loading && (
            <>
              <section className="panel hero">
                <div>
                  <h2>{m.symbol}</h2>
                  <span className="muted tiny">
                    {m.is_intraday ? 'Intraday' : 'Daily'} data to {m.last_date.slice(0, 16).replace('T00:00', '').replace('T', ' ')} ·{' '}
                    {m.source === 'bhavcopy' ? <>auto-synced from NSE bhavcopy{m.rows_uploaded ? ` (+${m.rows_uploaded} new)` : ''}</> : <>{m.rows_uploaded} rows uploaded</>} · {m.rows_total} rows in training history
                    {result.analysed_at && <> · analysed {result.analysed_at.replace('T', ' ').slice(0, 16)}</>}
                  </span>
                </div>
                <div className="hero-price">
                  <b>₹{fmt(m.close)}</b>
                  <span className={m.change_pct >= 0 ? 'up' : 'down'}>{pct(m.change_pct, 2)}</span>
                </div>
              </section>

              <section className="panel summary">
                <h3>Summary</h3>
                <p>{result.summary}</p>
              </section>

              <div className="tf-grid">
                {['day_trading', 'short_term', 'long_term'].map((k) => (
                  <TimeframeCard key={k} tfKey={k} tf={result.timeframes[k]} />
                ))}
              </div>

              <PriceChart data={result.chart} levels={result.levels} intraday={m.is_intraday} patterns={result.patterns?.occurrences} />
              <PatternPanel patterns={result.patterns} />
              <IndicatorCharts data={result.chart} intraday={m.is_intraday} />
              <LevelsPanel levels={result.levels} close={m.close} timeframes={result.timeframes} />
              <MemoryPanel memory={result.memory} backend={m.embedding_backend} />
              <p className="disclaimer">{result.disclaimer}</p>
            </>
          )}
        </div>
      )}
    </div>
  )
}
