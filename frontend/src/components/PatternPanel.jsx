import { useState } from 'react'
import { UP, DOWN, pct } from '../format'

const pctOrDash = (v) => (v == null ? '—' : `${(v * 100).toFixed(0)}%`)

function WinBar({ rate }) {
  if (rate == null) return <span className="muted">—</span>
  return (
    <span>
      <span className="winbar"><b style={{ width: `${rate * 100}%`, background: rate >= 0.5 ? UP : DOWN }} /></span>
      {(rate * 100).toFixed(0)}%
    </span>
  )
}

export default function PatternPanel({ patterns }) {
  const [showAll, setShowAll] = useState(false)
  if (!patterns) return null
  const { today, prediction, model, stats, occurrences, horizon_sessions: H } = patterns
  const todayNames = new Set(today.map((t) => t.name))
  const rows = showAll ? stats : stats.filter((s) => s.bias !== 0).slice(0, 10)
  const recent = [...occurrences].reverse().slice(0, 8)

  return (
    <section className="panel">
      <div className="panel-head">
        <h3>Candlestick patterns</h3>
        <span className="muted tiny">22 patterns · success judged {H} sessions later</span>
      </div>

      {prediction && prediction.prob_up != null ? (
        <div className="pred">
          <div>
            <div className="muted tiny">Pattern says</div>
            <b className={prediction.direction === 'Up' ? 'up' : 'down'}>
              {prediction.direction === 'Up' ? '▲ Bullish' : '▼ Bearish'}
            </b>
          </div>
          <div>
            <div className="muted tiny">Success chance</div>
            <span className="pred-prob">{(prediction.success_probability * 100).toFixed(0)}%</span>
          </div>
          <div>
            <div className="muted tiny">Reliability</div>
            <span className={`badge ${prediction.reliability === 'High' ? 'bull' : prediction.reliability === 'Low' ? 'bear' : 'neutral'}`}>
              {prediction.reliability}
            </span>
          </div>
          <div className="pred-text">
            <div>{prediction.text}</div>
            <div className="tiny muted">
              This stock's history: {pctOrDash(prediction.stock_history_probability)}
              {prediction.model_probability != null && <> · pattern model: {pctOrDash(prediction.model_probability)}</>}
              {prediction.expected_move_pct != null && <> · avg move after: {pct(prediction.expected_move_pct, 2)}</>}
            </div>
          </div>
        </div>
      ) : (
        <p className="muted">
          {prediction?.text || (today.length
            ? 'Only neutral (indecision) patterns on the latest candle — no directional signal.'
            : 'No candlestick pattern on the latest candle.')}
        </p>
      )}

      {today.length > 0 && (
        <div className="pat-today">
          {today.map((t) => (
            <div className="pat-card" key={t.name}>
              <div className="row">
                <b>{t.name}</b>
                <span className={`badge sm ${t.bias > 0 ? 'bull' : t.bias < 0 ? 'bear' : 'neutral'}`}>
                  {t.bias > 0 ? 'Bullish' : t.bias < 0 ? 'Bearish' : 'Neutral'} · {t.candles}-candle
                </span>
              </div>
              <div className="tiny muted">{t.description}</div>
              <div className="tiny">
                Seen {t.occurrences_this_stock}× on this stock
                {t.hist_win_rate != null && <> · worked {pctOrDash(t.hist_win_rate)} · avg {pct(t.hist_avg_move_pct, 2)}</>}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="grid2">
        <div>
          <div className="panel-head">
            <h4>How patterns performed on this stock</h4>
            <button className="link tiny" onClick={() => setShowAll(!showAll)}>{showAll ? 'Directional only' : 'Show all'}</button>
          </div>
          <div className="table-wrap">
            <table className="tbl">
              <thead>
                <tr><th>Pattern</th><th className="num">Seen</th><th>Worked ({H}d)</th><th className="num">Avg {H}d</th><th className="num">Avg 10d</th></tr>
              </thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.pattern} className={todayNames.has(s.pattern) ? 'sel' : ''}>
                    <td>
                      <span className={s.bias > 0 ? 'up' : s.bias < 0 ? 'down' : 'muted'}>{s.bias > 0 ? '▲' : s.bias < 0 ? '▼' : '●'}</span>{' '}
                      {s.pattern}
                    </td>
                    <td className="num">{s.occurrences}</td>
                    <td>{s.bias !== 0 ? <WinBar rate={s[`win_rate_${H}`]} /> : <span className="tiny muted">up {pctOrDash(s[`up_rate_${H}`])}</span>}</td>
                    <td className="num">{pct(s[`avg_move_${H}`], 2)}</td>
                    <td className="num">{pct(s.avg_move_10, 2)}</td>
                  </tr>
                ))}
                {!rows.length && <tr><td colSpan={5} className="muted">No patterns detected yet.</td></tr>}
              </tbody>
            </table>
          </div>
          <p className="tiny muted">"Worked" = price moved in the pattern's direction after {H} sessions. Small samples are unreliable.</p>
        </div>
        <div>
          <h4>Recent signals</h4>
          <table className="tbl">
            <thead><tr><th>Date</th><th>Pattern</th><th className="num">Move after {H}d</th></tr></thead>
            <tbody>
              {recent.map((o) => (
                <tr key={o.date}>
                  <td>{o.date}</td>
                  <td><span className={o.bias > 0 ? 'up' : 'down'}>{o.bias > 0 ? '▲' : '▼'}</span> {o.patterns.join(', ')}</td>
                  <td className="num">
                    {o.move_after_pct == null ? <span className="muted">pending</span> : (
                      <span className={(o.move_after_pct > 0) === (o.bias > 0) ? 'up' : 'down'}>
                        {pct(o.move_after_pct, 2)} {(o.move_after_pct > 0) === (o.bias > 0) ? '✓' : '✗'}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <h4>Pattern model</h4>
          {model.available ? (
            <p className="tiny">
              Trained on {model.events} pattern events from {model.stocks_in_pool.length} stock{model.stocks_in_pool.length > 1 ? 's' : ''} ({model.stocks_in_pool.join(', ')}).
              Walk-forward accuracy {pctOrDash(model.cv_accuracy)} vs baseline {pctOrDash(model.baseline_accuracy)}
              {' '}— {model.has_edge ? 'has an edge (60% weight).' : 'no reliable edge yet (30% weight; this stock\'s own stats carry the rest).'}
              {' '}Uploading more stocks and longer history makes it stronger.
            </p>
          ) : <p className="tiny muted">{model.reason}</p>}
        </div>
      </div>
    </section>
  )
}
