import { useState } from 'react'
import { fmt, pct, verdictClass, TF_LABELS } from '../format'

function ScoreBar({ score }) {
  const pos = ((score + 100) / 200) * 100
  return (
    <div className="scorebar" title={`Score ${score}`}>
      <div className="scorebar-track" />
      <div className="scorebar-mid" />
      <div className={`scorebar-dot ${score >= 25 ? 'bull' : score <= -25 ? 'bear' : 'neutral'}`} style={{ left: `${pos}%` }} />
    </div>
  )
}

export default function TimeframeCard({ tfKey, tf }) {
  const [open, setOpen] = useState(false)
  const label = TF_LABELS[tfKey]
  const c = tf.combined
  const ml = tf.ml || {}
  const p = tf.plan
  return (
    <div className="tf-card">
      <div className="tf-head">
        <div>
          <h3>{label.title}</h3>
          <span className="muted">{label.sub}</span>
        </div>
        <span className={`badge ${verdictClass(c.verdict)}`}>{c.verdict}</span>
      </div>

      <ScoreBar score={c.score} />
      <div className="tf-scores">
        <div><span className="muted">Combined</span><b>{c.score > 0 ? '+' : ''}{c.score}</b></div>
        <div><span className="muted">Technical</span><b>{tf.score > 0 ? '+' : ''}{tf.score}</b></div>
        <div>
          <span className="muted">ML P(up)</span>
          <b>{ml.available ? `${(ml.prob_up * 100).toFixed(0)}%` : '—'}</b>
        </div>
      </div>
      {ml.available ? (
        <p className="tiny muted">
          Model ({ml.horizon_label}): walk-forward accuracy {pct(ml.cv_accuracy * 100, 1).replace('+', '')} vs baseline{' '}
          {pct(ml.baseline_accuracy * 100, 1).replace('+', '')} — {ml.has_edge ? 'has an edge, weighted 40%' : 'no reliable edge, weighted 15%'}.
          Trained on {ml.train_rows} rows.
        </p>
      ) : (
        <p className="tiny muted">ML: {ml.reason}</p>
      )}

      <div className="plan" data-tour="plan">
        <div className="plan-row"><span>Bias</span><b className={p.bias === 'long' ? 'up' : p.bias === 'short' ? 'down' : ''}>{p.bias.toUpperCase()}</b></div>
        <div className="plan-row"><span>Entry</span><b>₹{fmt(p.entry)}</b></div>
        <div className="plan-row"><span>Stop-loss</span><b className="down">₹{fmt(p.stop_loss)}</b></div>
        <div className="plan-row"><span>Targets</span><b className="up">{p.targets.map((t) => `₹${fmt(t)}`).join(' · ')}</b></div>
        <div className="plan-row"><span>Risk : Reward</span><b>{p.risk_reward ? `1 : ${p.risk_reward}` : '—'}</b></div>
        <p className="tiny">{p.note}</p>
        {tf.notes?.map((n) => <p key={n} className="tiny muted">{n}</p>)}
        {tf.annualized_volatility_pct != null && <p className="tiny muted">Annualised volatility: {tf.annualized_volatility_pct}%</p>}
      </div>

      <button className="link" data-tour="signals" onClick={() => setOpen(!open)}>
        {open ? 'Hide' : 'Show'} {tf.signals.length} signals
      </button>
      {open && (
        <ul className="signals">
          {tf.signals.map((s, i) => (
            <li key={i}>
              <span className={`dot ${s.bias > 0 ? 'bull' : s.bias < 0 ? 'bear' : 'neutral'}`} aria-label={s.bias > 0 ? 'bullish' : s.bias < 0 ? 'bearish' : 'neutral'}>
                {s.bias > 0 ? '▲' : s.bias < 0 ? '▼' : '●'}
              </span>
              <div>
                <b>{s.indicator}</b>{s.value != null && <span className="muted"> · {fmt(s.value)}</span>}
                <div className="tiny muted">{s.note}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
