const BASE = import.meta.env.VITE_API_URL || ''

async function handle(res) {
  if (!res.ok) {
    let msg = `Request failed (${res.status})`
    try {
      const j = await res.json()
      msg = j.detail || msg
    } catch { /* not json */ }
    throw new Error(msg)
  }
  return res.json()
}

export function analyzeCsv(file, symbol, merge, ephemeral = false) {
  const fd = new FormData()
  fd.append('file', file)
  if (symbol) fd.append('symbol', symbol)
  fd.append('merge', merge ? 'true' : 'false')
  if (ephemeral) fd.append('ephemeral', 'true')
  return fetch(`${BASE}/api/analyze`, { method: 'POST', body: fd }).then(handle)
}

export const getHistory = (symbol) => fetch(`${BASE}/api/history/${encodeURIComponent(symbol)}`).then(handle)
export const getSymbols = () => fetch(`${BASE}/api/symbols`).then(handle)
export const getHealth = () => fetch(`${BASE}/api/health`).then(handle)
export const searchMemory = (q, symbol) =>
  fetch(`${BASE}/api/search?q=${encodeURIComponent(q)}${symbol ? `&symbol=${encodeURIComponent(symbol)}` : ''}`).then(handle)
export const deleteHistory = (symbol) =>
  fetch(`${BASE}/api/history/${encodeURIComponent(symbol)}`, { method: 'DELETE' }).then(handle)

const json = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
export const getWatchlist = () => fetch(`${BASE}/api/watchlist`).then(handle)
export const addWatchlist = (symbols, kind, backfillDays) =>
  fetch(`${BASE}/api/watchlist`, json('POST', { symbols: [symbols], kind: kind || undefined, backfill_days: backfillDays })).then(handle)
export const removeWatchlist = (symbol) =>
  fetch(`${BASE}/api/watchlist/${encodeURIComponent(symbol)}`, { method: 'DELETE' }).then(handle)
export const syncNow = (symbols) => fetch(`${BASE}/api/sync`, json('POST', symbols ? { symbols } : {})).then(handle)
export const getSyncStatus = () => fetch(`${BASE}/api/sync/status`).then(handle)
export const getResult = (symbol) => fetch(`${BASE}/api/results/${encodeURIComponent(symbol)}`).then(handle)
export const analyzeStored = (symbol) =>
  fetch(`${BASE}/api/analyze-stored/${encodeURIComponent(symbol)}`, { method: 'POST' }).then(handle)

// ---- morning market briefing
export const getBriefingLatest = () => fetch(`${BASE}/api/briefing/latest`).then(handle)
export const getBriefingList = () => fetch(`${BASE}/api/briefing/list`).then(handle)
export const getBriefing = (kind, key) => fetch(`${BASE}/api/briefing/${kind}/${key}`).then(handle)
export const getBriefingStatus = () => fetch(`${BASE}/api/briefing/status`).then(handle)
export const refreshBriefing = (kind) => fetch(`${BASE}/api/briefing/refresh`, json('POST', { kind })).then(handle)
