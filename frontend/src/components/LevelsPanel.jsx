import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, ReferenceLine, Cell, LabelList } from 'recharts'
import { fmt, TF_LABELS, UP, DOWN } from '../format'

export default function LevelsPanel({ levels, close, timeframes }) {
  const pv = levels.pivots
  const pivRows = ['R3', 'R2', 'R1', 'TC', 'P', 'BC', 'S1', 'S2', 'S3']
  const probs = Object.entries(timeframes)
    .filter(([, t]) => t.ml?.available)
    .map(([k, t]) => ({ name: TF_LABELS[k].title, prob: +(t.ml.prob_up * 100).toFixed(1) }))

  return (
    <section className="panel grid3" data-tour="levels">
      <div>
        <h3>Pivots & CPR <span className="muted tiny">(next session)</span></h3>
        <table className="tbl">
          <tbody>
            {pivRows.map((k) => (
              <tr key={k} className={k.startsWith('R') ? 'r' : k.startsWith('S') ? 's' : 'p'}>
                <td>{k === 'TC' ? 'CPR top' : k === 'BC' ? 'CPR bottom' : k === 'P' ? 'Pivot' : k}</td>
                <td className="num">₹{fmt(pv[k])}</td>
                <td className="num muted">{((pv[k] / close - 1) * 100).toFixed(2)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="tiny muted">CPR width {levels.cpr_width_pct}% of price.</p>
      </div>
      <div>
        <h3>Support & resistance</h3>
        <table className="tbl">
          <tbody>
            {[...levels.resistances].reverse().map((l, i) => (
              <tr key={'r' + i} className="r"><td>Resistance</td><td className="num">₹{fmt(l.price)}</td><td className="num muted">{l.touches}× tested</td></tr>
            ))}
            <tr className="cur"><td><b>Last close</b></td><td className="num"><b>₹{fmt(close)}</b></td><td /></tr>
            {levels.supports.map((l, i) => (
              <tr key={'s' + i} className="s"><td>Support</td><td className="num">₹{fmt(l.price)}</td><td className="num muted">{l.touches}× tested</td></tr>
            ))}
          </tbody>
        </table>
        <p className="tiny muted">52W high ₹{fmt(levels.high_52w)} · 52W low ₹{fmt(levels.low_52w)}</p>
        {levels.patterns.length > 0 && (
          <div className="patterns">
            {levels.patterns.map((p) => (
              <span key={p.name} className={`badge ${p.bias > 0 ? 'bull' : p.bias < 0 ? 'bear' : 'neutral'}`} title={p.note}>{p.name}</span>
            ))}
          </div>
        )}
      </div>
      <div>
        <h3>Model probability of rise</h3>
        {probs.length ? (
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={probs} layout="vertical" margin={{ top: 4, right: 36, left: 8, bottom: 0 }}>
              <XAxis type="number" domain={[0, 100]} ticks={[0, 50, 100]} tick={{ fontSize: 11, fill: 'var(--text-muted)' }} tickLine={false} axisLine={false} />
              <YAxis type="category" dataKey="name" width={84} tick={{ fontSize: 12, fill: 'var(--text-secondary)' }} tickLine={false} axisLine={false} />
              <ReferenceLine x={50} stroke="var(--text-muted)" strokeDasharray="4 4" />
              <Tooltip formatter={(v) => `${v}%`} cursor={{ fill: 'var(--grid)' }} />
              <Bar dataKey="prob" name="P(up)" radius={[0, 4, 4, 0]} barSize={18} isAnimationActive={false}>
                {probs.map((p) => <Cell key={p.name} fill={p.prob >= 50 ? UP : DOWN} />)}
                <LabelList dataKey="prob" position="right" formatter={(v) => `${v}%`} style={{ fontSize: 12, fill: 'var(--text-primary)' }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : <p className="muted">Not enough history to train the model.</p>}
        <p className="tiny muted">Gradient-boosted classifier trained on this stock's own history; validated walk-forward.</p>
      </div>
    </section>
  )
}
