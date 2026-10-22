import { useCallback, useEffect, useRef, useState } from 'react'
import { ResponsiveContainer, XAxis, YAxis, Tooltip, ReferenceLine, LineChart, Line, CartesianGrid, BarChart, Bar, Cell, Legend } from 'recharts'
import { getBriefing, getBriefingLatest, getBriefingList, getBriefingStatus, refreshBriefing } from '../api'
import { fmt, pct, UP, DOWN, SERIES } from '../format'

// ------------------------------------------------------------ helpers

const dayName = (iso) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
const shortDay = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
const timeOf = (iso) => (iso ? iso.slice(11, 16) : '')

function ago(iso) {
  if (!iso) return ''
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (m < 60) return `${Math.max(m, 1)}m ago`
  if (m < 48 * 60) return `${Math.round(m / 60)}h ago`
  return `${Math.round(m / 1440)}d ago`
}

// probabilities are shown between 1% and 99% — the model is never certain
const probPct = (p) => Math.round(Math.min(Math.max(p, 0.01), 0.99) * 100)

const toneClass = (v, eps = 0) => (v == null ? '' : v > eps ? 'up' : v < -eps ? 'down' : '')
const arrow = (v) => (v == null ? '' : v > 0 ? '▲ ' : v < 0 ? '▼ ' : '')

function Change({ v, d = 2 }) {
  if (v == null) return <span className="muted">—</span>
  return <span className={toneClass(v)}>{arrow(v)}{pct(v, d)}</span>
}

function SentTag({ s, label }) {
  const l = label || (s > 0.15 ? 'positive' : s < -0.15 ? 'negative' : 'neutral')
  return <span className={`badge sm ${l === 'positive' ? 'bull' : l === 'negative' ? 'bear' : 'neutral'}`}>{l}</span>
}

function SentDot({ s }) {
  const c = s > 0.15 ? 'bull' : s < -0.15 ? 'bear' : 'neutral'
  return <span className={`dot ${c}`} aria-label={c === 'bull' ? 'positive' : c === 'bear' ? 'negative' : 'neutral'}>{s > 0.15 ? '▲' : s < -0.15 ? '▼' : '●'}</span>
}

function Spark({ data, w = 84, h = 24 }) {
  const pts = (data || []).filter((x) => x != null)
  if (pts.length < 2) return null
  const lo = Math.min(...pts), hi = Math.max(...pts), span = hi - lo || 1
  const xy = pts.map((v, i) => [(i / (pts.length - 1)) * (w - 4) + 2, h - 2 - ((v - lo) / span) * (h - 4)])
  const up = pts[pts.length - 1] >= pts[0]
  return (
    <svg width={w} height={h} className="spark" aria-hidden="true">
      <polyline points={xy.map((p) => p.join(',')).join(' ')} fill="none" stroke="var(--text-muted)" strokeWidth="1.5" />
      <circle cx={xy[xy.length - 1][0]} cy={xy[xy.length - 1][1]} r="2.5" fill={up ? UP : DOWN} />
    </svg>
  )
}

// sector moves: zero in the middle, gains right, losses left, value in its own column (no label collisions)
function DivergingBars({ data }) {
  const max = Math.max(...data.map((d) => Math.abs(d.v)), 0.01)
  return (
    <div className="dbars" role="list">
      {data.map((d) => (
        <div className="dbar" role="listitem" key={d.name} title={`${d.name}: ${pct(d.v, 2)}`}>
          <span className="dbar-name">{d.name}</span>
          <span className="dbar-track">
            <span className="dbar-zero" />
            <b style={{ [d.v >= 0 ? 'left' : 'right']: '50%', width: `${(Math.abs(d.v) / max) * 50}%`, background: d.v >= 0 ? UP : DOWN }} />
          </span>
          <span className={`dbar-val ${toneClass(d.v)}`}>{arrow(d.v)}{pct(d.v, 2)}</span>
        </div>
      ))}
    </div>
  )
}

const fmtLast = (r) => {
  if (r.last == null) return '—'
  if (r.kind === 'yield') return `${fmt(r.last, 3)}%`
  return fmt(r.last, r.last < 10 ? 4 : 2)
}

// ------------------------------------------------------------ daily sections

function MoodTiles({ b }) {
  const g = b.mood.global_cues
  const india = b.news.regions.india || {}, world = b.news.regions.world || {}
  const o = b.outlook || {}
  const gap = o.targets?.gap_up, cl = o.targets?.close_up
  const [open, setOpen] = useState(false)
  return (
    <div className="mood-grid" data-tour="mk-mood">
      <div className="tile">
        <span className="muted tiny">Global cues</span>
        <b className={`tile-big ${toneClass(g.score, 0.1)}`}>{g.label}</b>
        <span className="tiny muted">Average overnight move of US &amp; Asian indices: {pct(g.score, 2)}</span>
      </div>
      <div className="tile">
        <span className="muted tiny">News mood</span>
        <div className="row tile-row">
          <div><span className="tiny muted">India</span><div><SentTag label={india.label} /></div></div>
          <div><span className="tiny muted">World</span><div><SentTag label={world.label} /></div></div>
        </div>
        <span className="tiny muted">{b.mood.news.count} stories scored offline · {pct(b.mood.news.score * 100, 0).replace('%', '')} on a −100…+100 scale</span>
      </div>
      <div className="tile outlook">
        <span className="muted tiny">Pre-market outlook · Nifty 50</span>
        {gap?.available ? (
          <>
            <div className="row tile-row">
              <div>
                <b className={`tile-big ${gap.prob_up >= 0.5 ? 'up' : 'down'}`}>{probPct(gap.prob_up)}%</b>
                <div className="tiny">chance it opens higher</div>
              </div>
              {cl?.available && (
                <div>
                  <b className={`tile-mid ${cl.prob_up >= 0.5 ? 'up' : 'down'}`}>{probPct(cl.prob_up)}%</b>
                  <div className="tiny">closes higher</div>
                </div>
              )}
            </div>
            <span className="tiny muted">
              Tested accuracy {(gap.cv_accuracy * 100).toFixed(0)}% vs {(gap.baseline_accuracy * 100).toFixed(0)}% naive guess —{' '}
              {gap.has_edge ? <b>has an edge</b> : 'no reliable edge, indicative only'}.{' '}
              <button className="link tiny" onClick={() => setOpen(!open)}>{open ? 'Hide' : 'Why?'}</button>
            </span>
            {open && (
              <ul className="drivers">
                {gap.drivers.map((d) => (
                  <li key={d.input}>
                    <span>{d.input} <Change v={d.move_pct} /></span>
                    <span className={d.push > 0 ? 'up' : 'down'}>{d.push > 0 ? 'pushes up' : 'pushes down'}</span>
                  </li>
                ))}
              </ul>
            )}
          </>
        ) : <span className="tiny muted">{o.reason || o.targets?.gap_up?.reason || 'Model not available yet.'}</span>}
      </div>
    </div>
  )
}

function GlobalMarkets({ rows }) {
  const groups = ['Americas', 'Europe', 'Asia-Pacific', 'Commodities & FX']
  return (
    <section className="panel" data-tour="mk-global">
      <div className="panel-head">
        <h3>World markets</h3>
        <span className="muted tiny">Yahoo Finance · last close (Asia may be live) · 1-month trend</span>
      </div>
      <div className="grid2">
        {groups.map((g) => (
          <div key={g}>
            <h4>{g}</h4>
            <table className="tbl mk-tbl">
              <tbody>
                {rows.filter((r) => r.group === g).map((r) => (
                  <tr key={r.symbol} className={r.stale ? 'stale' : ''} title={r.error ? `Unavailable: ${r.error}` : `As of ${r.date}`}>
                    <td>{r.name}{r.stale && <span className="tiny muted"> · {r.date}</span>}</td>
                    <td className="num">{fmtLast(r)}</td>
                    <td className="num"><Change v={r.change_pct} /></td>
                    <td className="spark-cell"><Spark data={r.spark} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </section>
  )
}

function IndiaMarkets({ india }) {
  const broad = india.indices.filter((r) => r.group === 'Broad')
  const sectors = india.indices.filter((r) => r.group === 'Sector' && r.change_pct != null)
    .map((r) => ({ name: r.name.replace('Nifty ', ''), v: r.change_pct })).sort((a, b) => b.v - a.v)
  const br = india.breadth
  const total = br ? br.advances + br.declines + br.unchanged : 0
  const session = broad[0]?.date || india.session_date
  return (
    <section className="panel" data-tour="mk-india">
      <div className="panel-head">
        <h3>Indian markets <span className="muted tiny">· last session {session ? shortDay(session) : ''}</span></h3>
        <span className="muted tiny">NSE · Yahoo Finance · NSE bhavcopy</span>
      </div>
      <div className="grid3 mk-india">
        <div>
          <h4>Benchmarks</h4>
          <table className="tbl mk-tbl">
            <tbody>
              {broad.map((r) => (
                <tr key={r.symbol} title={r.error ? `Unavailable: ${r.error}` : `Source: ${r.source}`}>
                  <td>{r.name}</td>
                  <td className="num">{fmt(r.last)}</td>
                  <td className="num"><Change v={r.change_pct} /></td>
                  <td className="spark-cell"><Spark data={r.spark} w={64} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {br ? (
            <div className="breadth">
              <h4>Market breadth (all NSE stocks)</h4>
              <div className="breadth-bar" role="img" aria-label={`${br.advances} advances, ${br.declines} declines`}>
                <b style={{ width: `${(br.advances / total) * 100}%`, background: UP }} />
                <b style={{ width: `${(br.unchanged / total) * 100}%`, background: 'var(--neutral-bg)' }} />
                <b style={{ width: `${(br.declines / total) * 100}%`, background: DOWN }} />
              </div>
              <div className="row tiny breadth-legend">
                <span className="up">▲ {br.advances.toLocaleString('en-IN')} advances</span>
                <span className="down">▼ {br.declines.toLocaleString('en-IN')} declines</span>
              </div>
            </div>
          ) : <p className="tiny muted">Breadth unavailable{india.breadth_error ? `: ${india.breadth_error}` : ''}.</p>}
        </div>
        <div>
          <h4>Sectors</h4>
          {sectors.length ? <DivergingBars data={sectors} /> : <p className="tiny muted">No sector data.</p>}
        </div>
        <div>
          <h4>Top movers <span className="muted tiny">(turnover ≥ ₹25 cr)</span></h4>
          {india.gainers?.length ? (
            <table className="tbl mk-tbl">
              <tbody>
                {india.gainers.slice(0, 5).map((g) => (
                  <tr key={'g' + g.symbol}><td>{g.symbol}</td><td className="num">{fmt(g.close)}</td><td className="num"><Change v={g.change_pct} /></td></tr>
                ))}
                <tr className="sep"><td colSpan={3} /></tr>
                {india.losers.slice(0, 5).map((g) => (
                  <tr key={'l' + g.symbol}><td>{g.symbol}</td><td className="num">{fmt(g.close)}</td><td className="num"><Change v={g.change_pct} /></td></tr>
                ))}
              </tbody>
            </table>
          ) : <p className="tiny muted">Unavailable.</p>}
        </div>
      </div>
    </section>
  )
}

// every NSE index (broad, sectoral, thematic, strategy, fixed income) for the last session or week
const GROUPS = ['All', 'Broad market', 'Sectoral', 'Thematic', 'Strategy', 'Fixed income']

function RangeBar({ lo, hi, v }) {
  if (lo == null || hi == null || v == null || hi <= lo) return null
  const p = Math.min(100, Math.max(0, ((v - lo) / (hi - lo)) * 100))
  return (
    <span className="range" title={`52-week range ${fmt(lo)} – ${fmt(hi)}`}>
      <span className="range-track"><i style={{ left: `${p}%` }} /></span>
    </span>
  )
}

function AllIndices({ rows, source, weekly = false }) {
  const [group, setGroup] = useState('All')
  const [q, setQ] = useState('')
  const [sort, setSort] = useState('change')
  const [all, setAll] = useState(false)
  if (!rows?.length) {
    return (
      <section className="panel" data-tour="mk-allidx">
        <h3>All NSE indices</h3>
        <p className="tiny muted">Unavailable right now{source ? ` (${source})` : ''}.</p>
      </section>
    )
  }
  const present = GROUPS.filter((g) => g === 'All' || rows.some((r) => r.group === g))
  const eq = rows.filter((r) => r.change_pct != null && r.group !== 'Fixed income' && !/VIX/i.test(r.name))
  const up = eq.filter((r) => r.change_pct > 0).length
  let list = rows.filter((r) => (group === 'All' || r.group === group) && r.name.toLowerCase().includes(q.toLowerCase()))
  list = [...list].sort((a, b) => (sort === 'name' ? a.name.localeCompare(b.name) : (b.change_pct ?? -1e9) - (a.change_pct ?? -1e9)))
  const shown = all || q ? list : list.slice(0, 15)
  const hasRange = rows.some((r) => r.year_high != null)
  const hasBreadth = rows.some((r) => r.advances != null)
  return (
    <section className="panel" data-tour="mk-allidx">
      <div className="panel-head">
        <h3>All NSE indices {weekly ? <span className="muted tiny">· change over the week</span> : <span className="muted tiny">· last session</span>}</h3>
        <span className="muted tiny">{up} of {eq.length} equity indices {weekly ? 'gained this week' : 'rose'}{source ? ` · ${source}` : ''}</span>
      </div>
      <div className="row allidx-controls">
        <nav className="seg seg-sm">
          {present.map((g) => (
            <button key={g} className={group === g ? 'on' : ''} onClick={() => setGroup(g)}>
              {g}{g !== 'All' && <span className="muted"> {rows.filter((r) => r.group === g).length}</span>}
            </button>
          ))}
        </nav>
        <input className="grow" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find an index, e.g. defence, PSU, midcap" />
        <select value={sort} onChange={(e) => setSort(e.target.value)} title="Sort">
          <option value="change">Sort: biggest gain first</option>
          <option value="name">Sort: A–Z</option>
        </select>
      </div>
      <div className="table-wrap">
        <table className="tbl mk-tbl allidx">
          <thead>
            <tr>
              <th>Index</th><th className="num">{weekly ? 'Close' : 'Last'}</th><th className="num">{weekly ? 'Week' : 'Change'}</th>
              <th className="num">P/E</th>
              {hasRange && <th>52-week range</th>}
              {hasBreadth && <th className="num">Adv / Dec</th>}
              {!weekly && rows.some((r) => r.change_365d != null) && <th className="num">1 year</th>}
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.name}>
                <td>{r.name}{group === 'All' && <span className="tiny muted"> · {r.group}</span>}</td>
                <td className="num">{fmt(weekly ? r.close : r.last)}</td>
                <td className="num"><Change v={r.change_pct} /></td>
                <td className="num">{r.pe != null ? fmt(r.pe, 1) : <span className="muted">—</span>}</td>
                {hasRange && <td><RangeBar lo={r.year_low} hi={r.year_high} v={r.last} /></td>}
                {hasBreadth && <td className="num tiny">{r.advances != null ? <><span className="up">{r.advances}</span> / <span className="down">{r.declines}</span></> : ''}</td>}
                {!weekly && rows.some((x) => x.change_365d != null) && <td className="num"><Change v={r.change_365d} d={1} /></td>}
              </tr>
            ))}
            {!shown.length && <tr><td colSpan={7} className="muted">No index matches “{q}”.</td></tr>}
          </tbody>
        </table>
      </div>
      {!q && list.length > 15 && (
        <button className="link tiny" onClick={() => setAll(!all)}>{all ? 'Show top 15' : `Show all ${list.length}`}</button>
      )}
    </section>
  )
}

// ------------------------------------------------------------ FII / DII and F&O participants

const crore = (v) => (v == null ? '—' : `₹${Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })} cr`)
const signedCr = (v) => (v == null ? '—' : `${v >= 0 ? '+' : '−'}${crore(v)}`)
const contracts = (v) => (v == null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(Math.round(v)).toLocaleString('en-IN')}`)
const PCOLORS = { FII: SERIES.sma20, CLIENT: SERIES.sma50, PRO: SERIES.sma200, DII: SERIES.ema9 }
const PNAMES = { FII: 'FII / FPI', CLIENT: 'Retail (Client)', PRO: 'Pro traders', DII: 'DII' }
const axisTick = { fontSize: 11, fill: 'var(--text-muted)' }

function Signed({ v, fmtFn = contracts }) {
  if (v == null) return <span className="muted">—</span>
  return <span className={toneClass(v)}>{fmtFn(v)}</span>
}

function LongShort({ pct: p }) {
  if (p == null) return <span className="muted">—</span>
  return (
    <span className="ls" title={`${p.toFixed(1)}% of index-futures contracts are long, ${(100 - p).toFixed(1)}% short`}>
      <span className="ls-bar"><b style={{ width: `${p}%`, background: UP }} /><b style={{ width: `${100 - p}%`, background: DOWN }} /></span>
      <span className="ls-txt">{p.toFixed(0)}% long</span>
    </span>
  )
}

function CashFlows({ fd, history }) {
  const data = (history || []).map((h) => ({ day: shortDay(h.date), FII: h.fii, DII: h.dii }))
  return (
    <div>
      <h4>FII / DII in the cash market <span className="tiny muted">{fd?.date ? `· ${shortDay(fd.date)} · provisional` : ''}</span></h4>
      {fd ? (
        <div className="flow-cards">
          {[['fii', 'FII / FPI'], ['dii', 'DII']].map(([k, lab]) => {
            const x = fd[k]
            return (
              <div className="flow-card" key={k}>
                <span className="muted tiny">{lab}</span>
                <b className={`tile-mid ${toneClass(x?.net)}`}>{x ? signedCr(x.net) : '—'}</b>
                <span className="tiny muted">{x ? <>Buy {crore(x.buy)} · Sell {crore(x.sell)}</> : 'not reported'}</span>
                <span className="tiny">{x?.net == null ? '' : x.net >= 0 ? 'net buyers' : 'net sellers'}</span>
              </div>
            )
          })}
        </div>
      ) : <p className="tiny muted">NSE didn&apos;t return FII/DII figures this morning (it sometimes blocks automated requests). Try Refresh now later.</p>}
      {data.length > 1 && (
        <>
          <div className="tiny muted chart-cap">Net flow, last {data.length} sessions (₹ crore)</div>
          <ResponsiveContainer width="100%" height={170}>
            <BarChart data={data} margin={{ top: 4, right: 8, left: -6, bottom: 0 }} barGap={2}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="day" tick={axisTick} tickLine={false} axisLine={false} />
              <YAxis tick={axisTick} tickLine={false} axisLine={false} tickFormatter={(v) => v.toLocaleString('en-IN')} />
              <ReferenceLine y={0} stroke="var(--text-muted)" />
              <Tooltip formatter={(v) => signedCr(v)} cursor={{ fill: 'var(--grid)' }} />
              <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="FII" fill={PCOLORS.FII} radius={[3, 3, 0, 0]} isAnimationActive={false} />
              <Bar dataKey="DII" fill={PCOLORS.CLIENT} radius={[3, 3, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </>
      )}
    </div>
  )
}

function ParticipantTable({ part, changeLabel = 'Day change' }) {
  if (!part?.available) return <p className="tiny muted">{part?.reason || 'Participant-wise positions unavailable.'}</p>
  return (
    <div className="table-wrap">
      <table className="tbl mk-tbl ptable">
        <thead>
          <tr>
            <th>Participant</th><th>Index futures</th><th className="num">Net</th><th className="num">{changeLabel}</th>
            <th className="num">Index calls</th><th className="num">Index puts</th><th className="num">Stock futures</th>
          </tr>
        </thead>
        <tbody>
          {part.rows.map((r) => (
            <tr key={r.code}>
              <td><i className="swatch" style={{ background: PCOLORS[r.code] }} />{r.label}</td>
              <td><LongShort pct={r.index_fut.long_pct} /></td>
              <td className="num"><Signed v={r.index_fut.net} /></td>
              <td className="num"><Signed v={r.change?.index_fut_net} /></td>
              <td className="num"><Signed v={r.index_calls.net} /></td>
              <td className="num"><Signed v={r.index_puts.net} /></td>
              <td className="num"><Signed v={r.stock_fut.net} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Flows({ fl }) {
  const part = fl?.participants
  const trend = (part?.trend || []).map((t) => ({ day: shortDay(t.date), ...Object.fromEntries(
    ['FII', 'CLIENT', 'PRO', 'DII'].map((c) => [PNAMES[c], t[`${c.toLowerCase()}_fut_long_pct`]])) }))
  return (
    <section className="panel" data-tour="mk-flows">
      <div className="panel-head">
        <h3>Who&apos;s buying &amp; selling</h3>
        <span className="muted tiny">NSE · FII/DII provisional data · participant-wise open interest{part?.session_date ? ` as of ${shortDay(part.session_date)}` : ''}</span>
      </div>
      <div className="grid2">
        <CashFlows fd={fl?.fii_dii} history={fl?.fii_dii_history} />
        <div>
          <h4>Index futures: % of positions that are long</h4>
          {trend.length > 1 ? (
            <ResponsiveContainer width="100%" height={210}>
              <LineChart data={trend} margin={{ top: 4, right: 12, left: -14, bottom: 0 }}>
                <CartesianGrid stroke="var(--grid)" vertical={false} />
                <XAxis dataKey="day" tick={axisTick} tickLine={false} axisLine={false} minTickGap={20} />
                <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tick={axisTick} tickLine={false} axisLine={false} unit="%" />
                <ReferenceLine y={50} stroke="var(--text-muted)" strokeDasharray="4 4" />
                <Tooltip formatter={(v) => `${v}% long`} />
                <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
                {['FII', 'CLIENT', 'PRO', 'DII'].map((c) => (
                  <Line key={c} dataKey={PNAMES[c]} stroke={PCOLORS[c]} strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} connectNulls />
                ))}
              </LineChart>
            </ResponsiveContainer>
          ) : <p className="tiny muted">Builds up as daily files are collected.</p>}
        </div>
      </div>
      <h4>Futures &amp; options positions by participant <span className="tiny muted">(open contracts; net = long − short)</span></h4>
      <ParticipantTable part={part} />
      <p className="tiny muted">
        Retail (Client) = individual and other non-institutional clients · Pro = brokers trading their own money · FII = foreign
        portfolio investors · DII = domestic institutions. Index calls/puts show net long (+) or net short (−) option contracts.
        Positions are a snapshot of the last session, not a forecast.
      </p>
    </section>
  )
}

function AdvanceDecline({ ad, weekly = false }) {
  if (!ad?.available) {
    return (
      <section className="panel" data-tour="mk-ad">
        <h3>Advance / decline</h3><p className="tiny muted">{ad?.reason || 'Not available yet.'}</p>
      </section>
    )
  }
  const x = ad.latest
  const total = x.advances + x.declines + x.unchanged
  const hist = ad.history.map((h) => ({ day: shortDay(h.date), net: h.advances - h.declines, adv: h.advances, dec: h.declines }))
  const idx = (ad.by_index || []).filter((r) => !/VIX/i.test(r.name)).slice(0, 12)
  return (
    <section className="panel" data-tour="mk-ad">
      <div className="panel-head">
        <h3>Advance / decline {weekly ? <span className="muted tiny">· sessions this week</span> : <span className="muted tiny">· {shortDay(x.date)}</span>}</h3>
        <span className="muted tiny">All NSE equity (EQ) stocks, from the bhavcopy</span>
      </div>
      <div className="grid3 mk-ad">
        <div>
          <div className="ad-nums">
            <div><b className="tile-mid up">▲ {x.advances.toLocaleString('en-IN')}</b><span className="tiny muted">advances</span></div>
            <div><b className="tile-mid down">▼ {x.declines.toLocaleString('en-IN')}</b><span className="tiny muted">declines</span></div>
            <div><b className="tile-mid">{x.ratio ?? '—'}</b><span className="tiny muted">A/D ratio</span></div>
          </div>
          <div className="breadth-bar" role="img" aria-label={`${x.advances} advances, ${x.unchanged} unchanged, ${x.declines} declines`}>
            <b style={{ width: `${(x.advances / total) * 100}%`, background: UP }} />
            <b style={{ width: `${(x.unchanged / total) * 100}%`, background: 'var(--neutral-bg)' }} />
            <b style={{ width: `${(x.declines / total) * 100}%`, background: DOWN }} />
          </div>
          <p className="tiny muted">{x.unchanged.toLocaleString('en-IN')} unchanged · {x.up_4pct} stocks up 4%+ · {x.down_4pct} down 4%+</p>
        </div>
        <div>
          <h4>Advances minus declines</h4>
          {hist.length > 1 ? (
            <ResponsiveContainer width="100%" height={150}>
              <BarChart data={hist} margin={{ top: 4, right: 8, left: -14, bottom: 0 }}>
                <CartesianGrid stroke="var(--grid)" vertical={false} />
                <XAxis dataKey="day" tick={axisTick} tickLine={false} axisLine={false} minTickGap={16} />
                <YAxis tick={axisTick} tickLine={false} axisLine={false} />
                <ReferenceLine y={0} stroke="var(--text-muted)" />
                <Tooltip formatter={(v, n, p) => [`${v > 0 ? '+' : ''}${v} (▲ ${p.payload.adv} / ▼ ${p.payload.dec})`, 'Net breadth']} cursor={{ fill: 'var(--grid)' }} />
                <Bar dataKey="net" radius={3} isAnimationActive={false}>
                  {hist.map((h) => <Cell key={h.day} fill={h.net >= 0 ? UP : DOWN} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : <p className="tiny muted">Needs at least two sessions.</p>}
        </div>
        <div>
          <h4>By index</h4>
          {idx.length ? (
            <div className="table-wrap"><table className="tbl mk-tbl">
              <tbody>
                {idx.map((r) => {
                  const t = r.advances + r.declines
                  return (
                    <tr key={r.name}>
                      <td className="nowrap">{r.name}</td>
                      <td className="ad-mini"><span className="ls-bar"><b style={{ width: `${(r.advances / t) * 100}%`, background: UP }} /><b style={{ width: `${(r.declines / t) * 100}%`, background: DOWN }} /></span></td>
                      <td className="num tiny"><span className="up">{r.advances}</span> / <span className="down">{r.declines}</span></td>
                    </tr>
                  )
                })}
              </tbody>
            </table></div>
          ) : <p className="tiny muted">{weekly ? 'Shown in the daily briefing.' : 'Needs NSE’s live index snapshot.'}</p>}
        </div>
      </div>
    </section>
  )
}

function WeeklyFlows({ fw }) {
  if (!fw) return null
  const days = (fw.fii_dii_days || []).map((h) => ({ date: h.date, fii: h.fii, dii: h.dii }))
  return (
    <section className="panel" data-tour="mk-flows">
      <div className="panel-head"><h3>Who bought &amp; sold this week</h3><span className="muted tiny">NSE</span></div>
      <div className="grid2">
        <CashFlows fd={fw.fii_net != null ? { fii: { net: fw.fii_net }, dii: { net: fw.dii_net } } : null} history={days} />
        <div>
          <h4>F&amp;O positions: change over the week</h4>
          <ParticipantTable part={fw.participants} changeLabel="Week change" />
        </div>
      </div>
    </section>
  )
}

function Story({ it }) {
  return (
    <li className="story">
      <SentDot s={it.sentiment} />
      <div>
        <a href={it.link} target="_blank" rel="noreferrer">{it.title}</a>
        <div className="tiny muted">
          {it.source}{it.publisher ? ` (${it.publisher})` : ''}{it.published ? ` · ${ago(it.published)}` : ''}
          {it.also_in?.length > 0 && ` · also in ${it.also_in.join(', ')}`}
        </div>
      </div>
    </li>
  )
}

function NewsColumn({ title, r }) {
  const [more, setMore] = useState(false)
  if (!r || !r.count) return <div><h4>{title}</h4><p className="tiny muted">No stories in the last 30 hours.</p></div>
  return (
    <div>
      <div className="panel-head"><h4>{title}</h4><span className="tiny muted">{r.count} stories · mood <SentTag label={r.label} /></span></div>
      {r.themes.map((t) => (
        <div className="theme" key={t.label}>
          <div className="row theme-head">
            <b>{t.label}</b>
            <span className="tiny muted">{t.size} stories</span>
            <SentTag s={t.sentiment} />
          </div>
          <ul className="stories">{t.items.slice(0, 3).map((it) => <Story key={it.link + it.title} it={it} />)}</ul>
        </div>
      ))}
      {r.other?.length > 0 && (
        <>
          <button className="link tiny" onClick={() => setMore(!more)}>{more ? 'Hide' : `Show ${r.other.length} other stories`}</button>
          {more && <ul className="stories">{r.other.map((it) => <Story key={it.link + it.title} it={it} />)}</ul>}
        </>
      )}
    </div>
  )
}

function StocksInNews({ stocks, onOpen }) {
  const [sel, setSel] = useState(null)
  if (!stocks?.length) return null
  const s = stocks.find((x) => x.symbol === sel)
  return (
    <div className="stocks-news" data-tour="mk-stocks">
      <h4>Stocks in the news <span className="tiny muted">· ★ = on your watchlist · click for headlines</span></h4>
      <div className="chips">
        {stocks.map((x) => (
          <button key={x.symbol} className={`chip on ${sel === x.symbol ? 'sel' : ''}`} onClick={() => setSel(sel === x.symbol ? null : x.symbol)}>
            {x.watchlist && '★ '}{x.symbol} <SentDot s={x.sentiment} /> <span className="muted">{x.count}</span>
          </button>
        ))}
      </div>
      {s && (
        <div className="chip-detail">
          <ul className="stories">{s.headlines.map((h) => <li key={h.title} className="story"><span /><div><a href={h.link} target="_blank" rel="noreferrer">{h.title}</a><div className="tiny muted">{h.source}</div></div></li>)}</ul>
          {s.watchlist && onOpen && <button onClick={() => onOpen(s.symbol)}>Open {s.symbol} analysis</button>}
        </div>
      )}
    </div>
  )
}

function Events({ ev, title = 'Stock events', upcomingTitle = 'Next 7 days' }) {
  const Row = ({ e, showDate }) => (
    <tr className={e.watchlist ? 'wl-row' : ''}>
      {showDate && <td className="nowrap">{shortDay(e.date)}</td>}
      <td className="nowrap"><b>{e.watchlist && '★ '}{e.symbol}</b></td>
      <td><span className={`badge sm ${e.type === 'Ex-date' ? 'neutral' : 'info'}`}>{e.type}</span></td>
      <td>{e.purpose}{e.detail && <div className="tiny muted ev-detail">{e.detail}</div>}</td>
    </tr>
  )
  return (
    <section className="panel" data-tour="mk-events">
      <div className="panel-head"><h3>{title}</h3><span className="muted tiny">NSE event calendar &amp; corporate actions</span></div>
      <div className="grid2">
        <div>
          <h4>Today</h4>
          {ev.today?.length ? (
            <div className="table-wrap"><table className="tbl"><tbody>{ev.today.map((e, i) => <Row key={i} e={e} />)}</tbody></table></div>
          ) : <p className="tiny muted">No board meetings or ex-dates today.</p>}
        </div>
        <div>
          <h4>{upcomingTitle}</h4>
          {ev.upcoming?.length ? (
            <div className="table-wrap ev-scroll"><table className="tbl"><tbody>{ev.upcoming.map((e, i) => <Row key={i} e={e} showDate />)}</tbody></table></div>
          ) : <p className="tiny muted">Nothing scheduled.</p>}
        </div>
      </div>
    </section>
  )
}

function Sources({ list }) {
  if (!list?.length) return null
  const bad = list.filter((s) => !s.ok)
  return (
    <details className="sources">
      <summary className="tiny">{list.length - bad.length}/{list.length} sources OK{bad.length ? ` · ${bad.length} failed` : ''}</summary>
      <ul className="tiny">
        {list.map((s) => <li key={s.name} className={s.ok ? '' : 'down'}>{s.ok ? '✓' : '✕'} {s.name} — {s.detail}</li>)}
      </ul>
    </details>
  )
}

function Daily({ b, onOpen }) {
  return (
    <>
      <MoodTiles b={b} />
      <section className="panel narrative" data-tour="mk-summary">
        <h3>Summary</h3>
        {b.narrative.map((p, i) => <p key={i}>{p}</p>)}
      </section>
      <GlobalMarkets rows={b.global} />
      <IndiaMarkets india={b.india} />
      <AllIndices rows={b.india.all_indices} source={b.india.all_indices_source} />
      {b.flows && <Flows fl={b.flows} />}
      {b.flows && <AdvanceDecline ad={b.flows.advance_decline} />}
      <section className="panel" data-tour="mk-news">
        <div className="panel-head"><h3>News summary</h3><span className="muted tiny">CNBC-TV18 · CNBC · Yahoo Finance — grouped and scored offline</span></div>
        <div className="grid2">
          <NewsColumn title="India" r={b.news.regions.india} />
          <NewsColumn title="World" r={b.news.regions.world} />
        </div>
        <StocksInNews stocks={b.news.stocks_in_news} onOpen={onOpen} />
      </section>
      <Events ev={b.events} />
    </>
  )
}

// ------------------------------------------------------------ weekly

function Weekly({ w, onOpen }) {
  const sectors = w.india.filter((x) => x.group === 'Sector' && x.change_pct != null)
    .map((x) => ({ name: x.name.replace('Nifty ', ''), v: x.change_pct })).sort((a, b) => b.v - a.v)
  const mood = w.mood_by_day.map((d) => ({ day: shortDay(d.date), news: Math.round(d.news * 100) }))
  const right = w.premarket_calls.filter((c) => c.correct).length
  return (
    <>
      <section className="panel narrative">
        <h3>Week in review · {shortDay(w.week_start)} – {shortDay(w.week_end)}</h3>
        {w.narrative.map((p, i) => <p key={i}>{p}</p>)}
        <p className="tiny muted">Built from {w.daily_briefings} morning briefings and {w.news_count} news stories.</p>
      </section>
      <section className="panel">
        <div className="grid2">
          <div>
            <h4>Indian indices this week</h4>
            <table className="tbl mk-tbl">
              <tbody>
                {w.india.filter((x) => x.group === 'Broad').map((x) => (
                  <tr key={x.symbol}><td>{x.name}</td><td className="num">{fmt(x.close)}</td><td className="num"><Change v={x.change_pct} /></td><td className="spark-cell"><Spark data={x.daily} w={64} /></td></tr>
                ))}
              </tbody>
            </table>
            <h4>Sectors this week</h4>
            {sectors.length ? <DivergingBars data={sectors} /> : <p className="tiny muted">No sector data.</p>}
          </div>
          <div>
            <h4>World markets this week</h4>
            <table className="tbl mk-tbl">
              <tbody>
                {w.global.map((x) => (
                  <tr key={x.symbol}><td>{x.name}</td><td className="num"><Change v={x.change_pct} /></td><td className="spark-cell"><Spark data={x.daily} w={64} /></td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>
      <AllIndices rows={w.all_indices} weekly />
      {w.flows && <WeeklyFlows fw={w.flows} />}
      {w.flows?.advance_decline?.history?.length > 0 && (
        <AdvanceDecline ad={{ ...w.flows.advance_decline, latest: w.flows.advance_decline.history.slice(-1)[0], by_index: [] }} weekly />
      )}
      <section className="panel">
        <div className="grid2">
          <div>
            <h4>News mood by day <span className="tiny muted">(−100 … +100)</span></h4>
            {mood.length > 1 ? (
              <ResponsiveContainer width="100%" height={160}>
                <LineChart data={mood} margin={{ top: 8, right: 12, left: -18, bottom: 0 }}>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="day" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} tickLine={false} axisLine={false} />
                  <YAxis domain={[-100, 100]} ticks={[-50, 0, 50]} tick={{ fontSize: 11, fill: 'var(--text-muted)' }} tickLine={false} axisLine={false} />
                  <ReferenceLine y={0} stroke="var(--text-muted)" />
                  <Tooltip />
                  <Line dataKey="news" name="News mood" stroke={SERIES.sma20} strokeWidth={2} dot={{ r: 4 }} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : <p className="tiny muted">Needs at least two stored morning briefings this week.</p>}
          </div>
          <div>
            <h4>Pre-market calls vs actual open</h4>
            {w.premarket_calls.length ? (
              <>
                <table className="tbl">
                  <thead><tr><th>Day</th><th className="num">P(opens higher)</th><th>Actual open</th><th /></tr></thead>
                  <tbody>
                    {w.premarket_calls.map((c) => (
                      <tr key={c.date}>
                        <td>{shortDay(c.date)}</td><td className="num">{probPct(c.prob_up)}%</td>
                        <td className={c.opened_up ? 'up' : 'down'}>{c.opened_up ? '▲ higher' : '▼ lower'}</td>
                        <td>{c.correct ? '✓' : '✗'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="tiny muted">{right} of {w.premarket_calls.length} correct this week.</p>
              </>
            ) : <p className="tiny muted">No stored morning calls for this week yet.</p>}
          </div>
        </div>
      </section>
      <section className="panel">
        <div className="panel-head"><h3>Themes of the week</h3></div>
        <div className="grid2">
          {['india', 'world'].map((r) => (
            <div key={r}>
              <h4>{r === 'india' ? 'India' : 'World'}</h4>
              {w.themes[r].length ? w.themes[r].map((t) => (
                <div className="theme" key={t.label}>
                  <div className="row theme-head"><b>{t.label}</b><span className="tiny muted">{t.size} stories</span><SentTag s={t.sentiment} /></div>
                  <ul className="stories">{t.items.slice(0, 3).map((it) => <Story key={it.link + it.title} it={it} />)}</ul>
                </div>
              )) : <p className="tiny muted">No recurring themes.</p>}
            </div>
          ))}
        </div>
        <StocksInNews stocks={w.stocks_in_news} onOpen={onOpen} />
      </section>
      <Events ev={{ today: [], upcoming: w.next_week_events }} title="Week ahead" upcomingTitle="Board meetings & ex-dates" />
    </>
  )
}

// ------------------------------------------------------------ page

export default function MarketPage({ onOpen, onBriefing }) {
  const [data, setData] = useState(null)
  const [view, setView] = useState('daily')
  const [list, setList] = useState({ daily: [], weekly: [] })
  const [picked, setPicked] = useState({ daily: null, weekly: null })
  const [status, setStatus] = useState(null)
  const [err, setErr] = useState('')
  const timer = useRef(null)

  const load = useCallback(async () => {
    try {
      const [d, l] = await Promise.all([getBriefingLatest(), getBriefingList()])
      setData(d); setList(l); setStatus(d.status)
      setPicked({ daily: null, weekly: null })
    } catch (e) { setErr(e.message) }
  }, [])
  useEffect(() => { load(); return () => clearTimeout(timer.current) }, [load])

  // while a briefing is being built, poll its progress and reload when it finishes
  useEffect(() => {
    if (!status?.running) return
    timer.current = setTimeout(async () => {
      try {
        const s = await getBriefingStatus()
        if (s.status.running) setStatus(s.status)
        else load()
      } catch { /* keep polling */ }
    }, 1500)
    return () => clearTimeout(timer.current)
  }, [status, load])

  const refresh = async (kind) => {
    setErr('')
    try { await refreshBriefing(kind); setStatus({ running: true, kind, step: 'starting' }) } catch (e) { setErr(e.message) }
  }
  const pick = async (kind, key) => {
    try {
      const b = await getBriefing(kind, key)
      setPicked((p) => ({ ...p, [kind]: b }))
    } catch (e) { setErr(e.message) }
  }

  useEffect(() => { onBriefing?.(!!data?.daily) }, [data, onBriefing])

  const daily = picked.daily || data?.daily
  const weekly = picked.weekly || data?.weekly
  const cur = view === 'daily' ? daily : weekly
  const sched = data?.schedule

  return (
    <div className="stack market">
      <section className="panel mk-head" data-tour="mk-head">
        <div>
          <h2>{view === 'daily' ? 'Morning briefing' : 'Weekly recap'}</h2>
          <span className="muted tiny">
            {view === 'daily' && daily && <>{dayName(daily.date)} · built {timeOf(daily.generated_at)} IST</>}
            {view === 'weekly' && weekly && <>{shortDay(weekly.week_start)} – {shortDay(weekly.week_end)} · built {weekly.generated_at.slice(0, 10)} {timeOf(weekly.generated_at)}</>}
            {sched?.enabled ? <> · auto: weekdays {sched.daily_time}, weekly Sat {sched.weekly_time} IST</> : <> · automatic schedule off</>}
          </span>
        </div>
        <div className="row mk-controls">
          <nav className="seg" data-tour="mk-toggle">
            <button className={view === 'daily' ? 'on' : ''} onClick={() => setView('daily')}>Daily</button>
            <button className={view === 'weekly' ? 'on' : ''} onClick={() => setView('weekly')}>Weekly</button>
          </nav>
          {list[view]?.length > 1 && (
            <select value={(view === 'daily' ? daily?.date : weekly?.week_start) || ''} onChange={(e) => pick(view, e.target.value)} title="Earlier briefings">
              {list[view].map((k) => <option key={k} value={k}>{shortDay(k)}</option>)}
            </select>
          )}
          <button className="primary" disabled={status?.running} onClick={() => refresh(view)}>
            {status?.running ? 'Building…' : 'Refresh now'}
          </button>
        </div>
      </section>
      {err && <div className="error">{err}</div>}
      {status?.running && (
        <div className="panel sync-box">
          <div className="tiny">Building the {status.kind} briefing: {status.step}</div>
          <div className="progress indeterminate"><b /></div>
        </div>
      )}
      {!status?.running && status?.error && <div className="error">Last build failed: {status.error}</div>}

      {!cur ? (
        <section className="panel empty">
          <h3>No {view} briefing yet</h3>
          <p className="muted">
            {view === 'daily'
              ? 'A briefing is built automatically every weekday at 08:15 IST. Build one now to see it — it takes a minute or two while it downloads quotes, news and NSE events.'
              : 'The weekly recap is built every Saturday morning. You can build it now; it uses the morning briefings stored for that week.'}
          </p>
          <button className="primary" disabled={status?.running} onClick={() => refresh(view)}>Build {view} briefing now</button>
        </section>
      ) : view === 'daily' ? <Daily b={cur} onOpen={onOpen} /> : <Weekly w={cur} onOpen={onOpen} />}

      {cur && <Sources list={cur.sources} />}
      <p className="disclaimer">
        Headlines and links belong to their publishers (CNBC-TV18, CNBC, Yahoo Finance). Summaries, sentiment and the outlook are produced
        offline by this app and can be wrong. Educational use only — not investment advice.
      </p>
    </div>
  )
}
