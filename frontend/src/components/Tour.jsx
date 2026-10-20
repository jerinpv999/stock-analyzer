import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

/*
  Guided UI tour — no dependencies.
  Each step can switch tab, then spotlights an element marked with data-tour="<id>"
  and shows a card next to it. Steps that need an analysis on screen are skipped
  automatically when none is loaded (the "Try sample data" step offers to load one).
*/
export const TOUR_STEPS = [
  { tab: 'analyse', title: 'Welcome to NSE Stock Analyzer', center: true,
    body: 'A quick tour of every screen — about two minutes. Use the arrow keys or the buttons below; press Esc to leave at any time.' },
  { tab: 'analyse', target: 'tabs', title: 'Three screens',
    body: 'Analyse shows one stock in depth. Watchlist keeps your stocks updated from NSE automatically. History & search lets you look back over every analysis the app has stored.' },
  { tab: 'analyse', target: 'upload', title: 'Upload a CSV',
    body: 'Drop an NSE "Historical Data" CSV here (or an index file such as NIFTY 50). Keep "Merge with stored history" ticked so each upload adds to the training data — after the first year, a one-day file is enough.' },
  { tab: 'analyse', target: 'sample', title: 'No file handy? Use the sample', action: 'sample',
    body: 'Load a bundled demo stock to see a full analysis. It is analysed but nothing is saved to your history or memory.' },
  { tab: 'analyse', target: 'hero', needsResult: true, title: 'The stock at a glance',
    body: 'Symbol, latest close and day change, where the data came from (upload, auto-sync or stored data) and how many sessions the models were trained on.' },
  { tab: 'analyse', target: 'summary', needsResult: true, title: 'Plain-English summary',
    body: 'Everything below condensed into a paragraph. This is also the text stored in ChromaDB memory and used for similarity search.' },
  { tab: 'analyse', target: 'timeframes', needsResult: true, title: 'Three timeframes',
    body: 'Day trading (next session), short term (1–4 weeks) and long term (months). Each has a verdict and a score from −100 to +100. The combined score blends the technical rules with the ML model — the model only gets real weight when its tested accuracy beats a simple baseline.' },
  { tab: 'analyse', target: 'plan', needsResult: true, title: 'Trade plan',
    body: 'Bias, entry, stop-loss, targets and risk:reward, derived from ATR, pivots and support/resistance. Treat it as a starting point for your own judgement — not advice.' },
  { tab: 'analyse', target: 'signals', needsResult: true, title: 'Why this verdict?',
    body: 'Expand to see every indicator that voted: ▲ bullish, ▼ bearish, ● neutral, with the reading and a one-line reason.' },
  { tab: 'analyse', target: 'price-chart', needsResult: true, title: 'Price chart',
    body: 'Candles and volume. Toggle overlays with the chips (moving averages, VWAP, Bollinger, Supertrend, support/resistance). Arrows mark candlestick patterns — hover a candle to see its pattern names. Scroll to zoom, drag to pan.' },
  { tab: 'analyse', target: 'patterns', needsResult: true, title: 'Candlestick patterns',
    body: "Today's patterns with an estimated chance of working over the next 3 sessions, how each pattern has performed on this stock before, and recent signals with their outcomes (✓ / ✗)." },
  { tab: 'analyse', target: 'indicators', needsResult: true, title: 'Indicator panels',
    body: 'RSI, MACD, Stochastic and ADX, synced on hover. Switch the range with 3M / 6M / 1Y / All.' },
  { tab: 'analyse', target: 'levels', needsResult: true, title: 'Levels & model probabilities',
    body: "Pivot points and CPR for the next session, swing support/resistance with how often each was tested, and the ML model's probability of a rise for each timeframe." },
  { tab: 'analyse', target: 'memory', needsResult: true, title: 'Memory',
    body: 'Compares with the previous analysis of the same stock, scores earlier Bullish/Bearish calls against what prices actually did, and finds similar setups in other stocks.' },
  { tab: 'watchlist', target: 'wl-add', title: 'Watchlist: add stocks',
    body: 'Type NSE symbols (RELIANCE, M&M, BAJAJ-AUTO) or indices (NIFTY 50). New symbols are backfilled from NSE bhavcopy files; ones you already uploaded continue from their last date.' },
  { tab: 'watchlist', target: 'wl-sync', title: 'Sync and analyse',
    body: 'Sync now downloads any missing days. Analyse all re-runs the analysis on data already stored, without downloading. A sync also runs automatically every weekday at 18:45 IST while the server is running.' },
  { tab: 'watchlist', target: 'wl-table', title: 'Your stocks',
    body: 'Latest close and verdicts for each symbol. Analyse runs a fresh analysis, Open shows the last saved one, ↻ syncs just that symbol and ✕ stops tracking it (its data is kept).' },
  { tab: 'history', target: 'hist-stored', title: 'History',
    body: 'Every stored analysis for a symbol, with how its timeframe scores have moved over time.' },
  { tab: 'history', target: 'hist-search', title: 'Semantic search',
    body: 'Search all past analyses in plain words — e.g. "oversold bounce near support" — powered by ChromaDB embeddings.' },
  { tab: 'analyse', target: 'header-status', title: "That's the tour!",
    body: 'Your data lives in the folder shown here, outside the project, so updating the app never deletes it. Replay this tour any time from the "Tour" button.' },
]

const PAD = 8

export default function Tour({ open, onClose, setTab, hasResult, onLoadSample, loading }) {
  const steps = TOUR_STEPS.filter((s) => !s.needsResult || hasResult)
  const [i, setI] = useState(0)
  const [rect, setRect] = useState(null)
  const [missing, setMissing] = useState(false)
  const card = useRef(null)
  const [cardPos, setCardPos] = useState(null)
  const step = steps[Math.min(i, steps.length - 1)]

  useEffect(() => { if (open) setI(0) }, [open])

  // keep the index valid if the step list changes (e.g. after the sample loads)
  useEffect(() => { if (i > steps.length - 1) setI(steps.length - 1) }, [steps.length, i])

  const measure = useCallback(() => {
    if (!step || step.center || !step.target) { setRect(null); setMissing(false); return }
    const el = document.querySelector(`[data-tour="${step.target}"]`)
    if (!el) { setRect(null); setMissing(true); return }
    setMissing(false)
    const r = el.getBoundingClientRect()
    setRect({ top: r.top - PAD, left: r.left - PAD, width: r.width + 2 * PAD, height: r.height + 2 * PAD })
  }, [step])

  // switch tab, wait for the target to render, scroll it into view
  useEffect(() => {
    if (!open || !step) return
    if (step.tab) setTab(step.tab)
    let tries = 0
    let t
    const find = () => {
      const el = step.target && document.querySelector(`[data-tour="${step.target}"]`)
      if (el || step.center || tries++ > 30) {
        if (el) {
          const r = el.getBoundingClientRect()
          const fits = r.height < window.innerHeight * 0.6
          el.scrollIntoView({ block: fits ? 'center' : 'start', behavior: 'smooth' })
        }
        setTimeout(measure, 380)
      } else t = setTimeout(find, 60)
    }
    find()
    return () => clearTimeout(t)
  }, [open, step, setTab, measure])

  useEffect(() => {
    if (!open) return
    const on = () => measure()
    window.addEventListener('resize', on)
    window.addEventListener('scroll', on, true)
    return () => { window.removeEventListener('resize', on); window.removeEventListener('scroll', on, true) }
  }, [open, measure])

  // place the card below the target, else above, else pinned to the bottom
  useLayoutEffect(() => {
    if (!open || !card.current) return
    const vw = window.innerWidth
    const vh = window.innerHeight
    const c = card.current.getBoundingClientRect()
    if (!rect || vw < 640) { setCardPos(null); return }
    let top = rect.top + rect.height + 12
    if (top + c.height > vh - 12) top = rect.top - c.height - 12
    if (top < 12) top = Math.max(12, vh - c.height - 12)
    const left = Math.min(Math.max(12, rect.left), vw - c.width - 12)
    setCardPos({ top, left })
  }, [rect, open, i])

  const next = useCallback(() => (i < steps.length - 1 ? setI(i + 1) : onClose()), [i, steps.length, onClose])
  const back = useCallback(() => setI(Math.max(0, i - 1)), [i])

  useEffect(() => {
    if (!open) return
    const key = (e) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowRight') next()
      if (e.key === 'ArrowLeft') back()
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [open, next, back, onClose])

  if (!open || !step) return null
  const centered = step.center || !rect
  const isSample = step.action === 'sample'

  return (
    <div className="tour" role="dialog" aria-modal="true" aria-label="Guided tour">
      {rect ? (
        <div className="tour-spot" style={{ top: rect.top, left: rect.left, width: rect.width, height: rect.height }} />
      ) : (
        <div className="tour-dim" />
      )}
      <div
        ref={card}
        className={`tour-card ${centered ? 'center' : ''} ${!cardPos && !centered ? 'pinned' : ''}`}
        style={cardPos && !centered ? { top: cardPos.top, left: cardPos.left } : undefined}
      >
        <div className="tour-step tiny muted">Step {i + 1} of {steps.length}</div>
        <h3>{step.title}</h3>
        <p>{step.body}</p>
        {missing && !step.center && <p className="tiny muted">(This part appears once there is data to show.)</p>}
        {isSample && !hasResult && (
          <button className="primary" disabled={loading} onClick={() => onLoadSample().then(() => setI(i + 1))}>
            {loading ? 'Loading sample…' : 'Load sample & continue'}
          </button>
        )}
        <div className="tour-nav">
          <button className="link" onClick={onClose}>Skip tour</button>
          <div className="row">
            {i > 0 && <button onClick={back}>Back</button>}
            <button className="primary" onClick={next}>{i === steps.length - 1 ? 'Finish' : 'Next'}</button>
          </div>
        </div>
        <div className="tour-dots">
          {steps.map((_, n) => <i key={n} className={n === i ? 'on' : ''} />)}
        </div>
      </div>
    </div>
  )
}
