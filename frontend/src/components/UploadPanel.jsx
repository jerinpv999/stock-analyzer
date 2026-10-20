import { useRef, useState } from 'react'

export default function UploadPanel({ onAnalyze, onSample, loading }) {
  const [file, setFile] = useState(null)
  const [symbol, setSymbol] = useState('')
  const [merge, setMerge] = useState(true)
  const [drag, setDrag] = useState(false)
  const input = useRef(null)

  const pick = (f) => {
    if (!f) return
    setFile(f)
    const m = f.name.match(/Quote-Equity-([A-Z0-9&-]+?)-(EQ|BE|BZ)/i)
    if (m && !symbol) setSymbol(m[1].toUpperCase())
  }

  return (
    <section className="panel upload" data-tour="upload">
      <div
        className={`dropzone ${drag ? 'drag' : ''} ${file ? 'has-file' : ''}`}
        onClick={() => input.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]) }}
      >
        <input ref={input} type="file" accept=".csv,text/csv" hidden onChange={(e) => pick(e.target.files[0])} />
        {file ? (
          <>
            <strong>{file.name}</strong>
            <span>{(file.size / 1024).toFixed(1)} KB · click to change</span>
          </>
        ) : (
          <>
            <strong>Drop NSE CSV here or click to browse</strong>
            <span>nseindia.com → Get Quote → Historical Data → Download (.csv). Daily or intraday OHLCV.</span>
          </>
        )}
      </div>
      <div className="upload-controls">
        <label>
          Symbol
          <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} placeholder="Auto-detect e.g. RELIANCE" />
        </label>
        <label className="check">
          <input type="checkbox" checked={merge} onChange={(e) => setMerge(e.target.checked)} />
          Merge with stored history (grows training data)
        </label>
        <button className="ghost" data-tour="sample" disabled={loading} onClick={onSample} title="Analyse a bundled demo file (not saved to your history)">
          Try sample data
        </button>
        <button className="primary" disabled={!file || loading} onClick={() => onAnalyze(file, symbol, merge)}>
          {loading ? 'Analysing…' : 'Analyse'}
        </button>
      </div>
    </section>
  )
}
