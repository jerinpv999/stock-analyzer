import { fmt, pct, TF_LABELS } from '../format'

export default function MemoryPanel({ memory, backend }) {
  const prev = memory.previous
  const track = memory.track_record?.by_timeframe
  return (
    <section className="panel" data-tour="memory">
      <div className="panel-head">
        <h3>Memory · previous analyses</h3>
        <span className="muted tiny">ChromaDB · {memory.total_past_analyses} past analyses · embeddings: {backend}</span>
      </div>
      {!prev ? (
        <p className="muted">First analysis for this symbol — saved to memory. The next upload will be compared against it and its calls checked against actual prices.</p>
      ) : (
        <div className="grid2">
          <div>
            <h4>Since last analysis</h4>
            <p>
              Last analysed on <b>{prev.previous_created_at?.replace('T', ' ')}</b> (data to {prev.previous_last_date?.slice(0, 10)}) at ₹{fmt(prev.previous_close)}.
              {' '}Price change since: <b className={prev.price_change_pct >= 0 ? 'up' : 'down'}>{pct(prev.price_change_pct, 2)}</b>
            </p>
            <ul className="plain">{prev.verdict_changes.map((c) => <li key={c}>{c}</li>)}</ul>
            <details><summary className="tiny">Previous summary</summary><p className="tiny muted">{prev.previous_summary}</p></details>
          </div>
          <div>
            <h4>Track record of past calls</h4>
            <table className="tbl">
              <thead><tr><th>Timeframe</th><th className="num">Checked</th><th className="num">Hit rate</th></tr></thead>
              <tbody>
                {track && Object.entries(track).map(([k, v]) => (
                  <tr key={k}>
                    <td>{TF_LABELS[k].title}</td>
                    <td className="num">{v.evaluated}</td>
                    <td className="num">{v.hit_rate == null ? '—' : `${(v.hit_rate * 100).toFixed(0)}%`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="tiny muted">Bullish/Bearish calls are checked once enough new sessions arrive (1 / 5 / 20). Neutral calls are skipped.</p>
          </div>
        </div>
      )}
      {memory.similar_other_symbols?.length > 0 && (
        <>
          <h4>Similar setups in other stocks</h4>
          <ul className="similar">
            {memory.similar_other_symbols.map((s) => (
              <li key={s.id}>
                <b>{s.symbol}</b> <span className="muted tiny">· {s.last_date?.slice(0, 10)} · similarity {(s.similarity * 100).toFixed(0)}%</span>
                <div className="tiny muted">{s.summary.slice(0, 220)}…</div>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
