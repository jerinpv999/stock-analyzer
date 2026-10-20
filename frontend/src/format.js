export const fmt = (v, d = 2) =>
  v === null || v === undefined || Number.isNaN(v)
    ? '—'
    : Number(v).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d })

export const pct = (v, d = 1) => (v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${Number(v).toFixed(d)}%`)

export const verdictClass = (v = '') =>
  v.includes('Bullish') ? 'bull' : v.includes('Bearish') ? 'bear' : 'neutral'

export const TF_LABELS = {
  day_trading: { title: 'Day Trading', sub: 'Next session · intraday' },
  short_term: { title: 'Short Term', sub: '1–4 weeks · swing' },
  long_term: { title: 'Long Term', sub: 'Months · positional' },
}

// Categorical palette (fixed order, validated for colour-vision deficiency)
export const SERIES = {
  sma20: '#2a78d6',
  sma50: '#eb6834',
  sma200: '#6250d6',
  ema9: '#1baf7a',
  ema21: '#e87ba4',
  vwap: '#eda100',
}
export const UP = '#1baf7a'
export const DOWN = '#e34948'
