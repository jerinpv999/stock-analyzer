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
import Tour from './components/Tour'
import MarketPage from './components/MarketPage'
import { DisclaimerModal, Footer, HeaderNotice } from './components/Disclaimer'
import { analyzeCsv, getHealth, getResult } from './api'
import { fmt, pct } from './format'

export default function App() {
  const [tab, setTab] = useState('market')
  const [hasBriefing, setHasBriefing] = useState(false)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [health, setHealth] = useState(null)
  const [tour, setTour] = useState(false)
  // educational-use disclaimer: shown every time the app is opened (once per browser session)
  const [accepted, setAccepted] = useState(() => {
    try { return sessionStorage.getItem('nse-disclaimer-ok') === '1' } catch { return false }
  })
  const [reread, setReread] = useState(false)
  const accept = () => {
    setAccepted(true); setReread(false)
    try { sessionStorage.setItem('nse-disclaimer-ok', '1') } catch { /* keep in memory only */ }
  }

  // open the tour automatically on the very first visit — after the disclaimer has been accepted
  useEffect(() => {
    if (!accepted) return
    try {
      if (!localStorage.getItem('nse-tour-done')) setTour(true)
    } catch { /* storage blocked: just don't auto-open */ }
  }, [accepted])
  const closeTour = () => {
    setTour(false)
    try { localStorage.setItem('nse-tour-done', '1') } catch { /* ignore */ }
  }

  // keep checking: the backend may still be starting (Docker, first model download) or restarting
  useEffect(() => {
    let alive = true
    let t
    const check = () => getHealth()
      .then((h) => { if (alive) { setHealth(h); if (!h.memory_ready) t = setTimeout(check, 5000) } })
      .catch(() => { if (alive) { setHealth(false); t = setTimeout(check, 5000) } })
    check()
    return () => { alive = false; clearTimeout(t) }
  }, [])

  const run = async (file, symbol, merge, ephemeral = false) => {
    setLoading(true); setError('')
    try {
      setResult(await analyzeCsv(file, symbol, merge, ephemeral))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  // bundled demo file: analysed but nothing saved (ephemeral)
  const loadSample = async () => {
    setTab('analyse')
    const name = 'Quote-Equity-DEMO-EQ-sample.csv'
    const blob = await fetch(`/sample/${name}`).then((r) => r.blob())
    await run(new File([blob], name, { type: 'text/csv' }), 'DEMO', false, true)
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
          <span className="muted tiny" data-tour="header-status">
            Technical analysis · ML forecast · ChromaDB memory
            {health === false && (
              <b className="down"> · backend not reachable — retrying… (Docker: <code>docker compose logs backend</code>; local: start uvicorn on port 8000)</b>
            )}
            {health && (
              <>
                {health.stored_analyses != null ? <> · {health.stored_analyses} analyses stored</> : <> · starting up…</>}
                {health.data_dir && <> · data: {health.data_dir}{health.in_docker && ' (on your computer)'}</>}
              </>
            )}
          </span>
        </div>
        <div className="row">
        <button className="ghost" onClick={() => setTour(true)} title="Guided tour of the app">Tour</button>
        <nav className="seg" data-tour="tabs">
          <button className={tab === 'market' ? 'on' : ''} onClick={() => setTab('market')}>Market</button>
          <button className={tab === 'analyse' ? 'on' : ''} onClick={() => setTab('analyse')}>Analyse</button>
          <button className={tab === 'watchlist' ? 'on' : ''} onClick={() => setTab('watchlist')}>Watchlist</button>
          <button className={tab === 'history' ? 'on' : ''} onClick={() => setTab('history')}>History & search</button>
        </nav>
        </div>
      </header>
      <HeaderNotice onOpen={() => setReread(true)} />
      <DisclaimerModal open={!accepted || reread} reread={accepted} onAccept={accept} />
      <Tour open={tour} onClose={closeTour} setTab={setTab} hasResult={!!result && !loading} hasBriefing={hasBriefing}
        onLoadSample={loadSample} loading={loading} />

      {tab === 'market' ? (
        <MarketPage onOpen={openSaved} onBriefing={setHasBriefing} />
      ) : tab === 'watchlist' ? (
        <WatchlistPanel onOpen={openSaved} onResult={(r) => { setResult(r); setTab('analyse'); window.scrollTo(0, 0) }} />
      ) : tab === 'history' ? (
        <HistoryPanel initialSymbol={m?.symbol} />
      ) : (
        <div className="stack">
          <UploadPanel onAnalyze={run} onSample={loadSample} loading={loading} />
          {error && <div className="error">{error}</div>}
          {loading && <div className="panel muted">Computing indicators, training models and recalling past analyses…</div>}

          {result && !loading && (
            <>
              <section className="panel hero" data-tour="hero">
                <div>
                  <h2>{m.symbol}</h2>
                  <span className="muted tiny">
                    {m.is_intraday ? 'Intraday' : 'Daily'} data to {m.last_date.slice(0, 16).replace('T00:00', '').replace('T', ' ')} ·{' '}
                    {m.source === 'bhavcopy' ? <>auto-synced from NSE bhavcopy{m.rows_uploaded ? ` (+${m.rows_uploaded} new)` : ''}</> : m.source === 'stored' ? <>analysed from stored data</> : m.ephemeral ? <>sample data — not saved</> : <>{m.rows_uploaded} rows uploaded</>} · {m.rows_total} rows in training history
                    {result.analysed_at && <> · analysed {result.analysed_at.replace('T', ' ').slice(0, 16)}</>}
                  </span>
                </div>
                <div className="hero-price">
                  <b>₹{fmt(m.close)}</b>
                  <span className={m.change_pct >= 0 ? 'up' : 'down'}>{pct(m.change_pct, 2)}</span>
                </div>
              </section>

              <section className="panel summary" data-tour="summary">
                <h3>Summary</h3>
                <p>{result.summary}</p>
              </section>

              <div className="tf-grid" data-tour="timeframes">
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
      <Footer onOpen={() => setReread(true)} />
    </div>
  )
}
