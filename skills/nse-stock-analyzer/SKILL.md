---
name: nse-stock-analyzer
description: Operate the local NSE Stock Analyzer app through its REST API: add Indian stocks or indices to the watchlist, sync daily NSE bhavcopy data, run technical/ML/candlestick analysis, read results and search past analyses. Use when the user asks to analyse an NSE stock or index, check their watchlist, run or troubleshoot a sync, or compare past calls.
---

# NSE Stock Analyzer

A self-hosted app that analyses NSE stocks and indices across three timeframes (day trading, short term, long term). It combines rule-based technical indicators, a per-stock ML model and a candlestick-pattern model, and remembers every analysis in ChromaDB. You drive it over HTTP; the user sees the same results in the web UI.

## 1. Find the API

Try these in order and use the first that answers `/api/health`:

| Setup | Base URL |
|---|---|
| Docker Compose | `http://localhost:8080` (nginx proxy) or `http://localhost:8000` |
| Local run (`uvicorn`) | `http://localhost:8000` |

```bash
curl -s http://localhost:8000/api/health
# {"status":"ok","embedding_backend":"onnx_minilm","stored_analyses":42,"data_dir":"/home/you/nse-analyzer-data"}
```

**If nothing answers**, the server isn't running. Tell the user how to start it rather than guessing:
- Docker: `docker compose up -d` from the project root.
- Local: `cd backend && source .venv/bin/activate && uvicorn app.main:app --port 8000`.

Do not start long-running servers yourself unless the user asks.

## 2. Core workflows

### Analyse a stock that is (or should be) on the watchlist
1. `GET /api/watchlist`. If the symbol is listed and has `rows >= 30`, go to step 3.
2. If it isn't listed, add it. This starts a background sync that backfills history from NSE bhavcopy:
   ```bash
   curl -s -X POST localhost:8000/api/watchlist -H 'Content-Type: application/json' \
     -d '{"symbols": ["RELIANCE"], "backfill_days": 365}'
   ```
   Poll `GET /api/sync/status` every few seconds until `running` is false. A first 1-year backfill takes a few minutes. Report progress from `progress.done/total`, and read `log` for problems.
3. Run a fresh analysis on stored data (no download):
   ```bash
   curl -s -X POST localhost:8000/api/analyze-stored/RELIANCE
   ```
   To show the last saved analysis instead, use `GET /api/results/RELIANCE`.

### Bring everything up to date
`POST /api/sync` with `{}` for all symbols, or `{"symbols": ["TCS"]}` for some. Then poll `/api/sync/status`. A sync analyses every symbol that received new sessions; per-symbol outcomes are in `results`.

### Analyse a CSV the user provides
```bash
curl -s -F file=@Quote-Equity-RELIANCE-EQ-....csv -F merge=true localhost:8000/api/analyze
```
- `merge=true` appends to stored history. A 1-row daily file is fine once history exists.
- `ephemeral=true` analyses without saving anything (good for one-off looks).
- Multi-stock bhavcopy files need `-F symbol=RELIANCE`.

### Look back
- `GET /api/history/{SYMBOL}`: all stored analyses, newest first. Includes `*_verdict`, `*_score` and `*_prob_up` fields.
- `GET /api/search?q=oversold+bounce+near+support&symbol=` runs semantic search across all stored summaries.
- `GET /api/symbols` lists symbols in memory with counts.

## 3. Symbols

- **Stocks:** use the NSE ticker exactly: `RELIANCE`, `M&M`, `BAJAJ-AUTO`, `FEDERALBNK`. URL-encode `&` in paths (`M%26M`).
- **Indices:** use the name with or without spaces (`NIFTY 50` becomes `NIFTY50`, `NIFTY BANK` becomes `NIFTYBANK`). The kind is auto-detected; force it with `"kind": "index"` or `"equity"`.
- **Bad symbol:** if a sync log says `not found in bhavcopy`, the ticker is wrong. Ask the user or suggest the likely NSE ticker.

## 4. Reading an analysis (key fields)

```
meta.symbol, meta.last_date, meta.close, meta.change_pct, meta.rows_total, meta.source
summary                                   # one-paragraph text; good to quote to the user
timeframes.{day_trading|short_term|long_term}
  .combined.verdict / .combined.score     # final call, -100..+100 (Strong Bullish ≥60, Bullish ≥25, …)
  .score                                  # rule-based technical score alone
  .signals[]  {indicator, value, bias(+1/0/-1), note}
  .plan       {bias, entry, stop_loss, targets[], risk_reward, note}
  .ml         {available, prob_up, cv_accuracy, baseline_accuracy, has_edge, train_rows}
patterns.today[], patterns.prediction {direction, success_probability, reliability, text}
patterns.model {available, cv_accuracy, baseline_accuracy, has_edge, events, stocks_in_pool}
levels  {pivots{P,R1..R3,S1..S3,TC,BC}, supports[], resistances[], high_52w, low_52w}
memory  {previous{verdict_changes, price_change_pct}, track_record.by_timeframe{hit_rate, evaluated}}
```

**How to report results:**
- **Lead with the verdicts:** give each timeframe's `combined.verdict` and score, then the 2–3 strongest `signals` behind each.
- **Give the trade plan as levels:** entry, stop-loss and targets in ₹, plus risk:reward.
- **Always state model reliability:** if `ml.has_edge` is false, say the ML model did not beat its baseline for that horizon and the verdict rests mainly on technical rules. Do the same for `patterns.model.has_edge`.
- **Patterns:** quote `patterns.prediction.text`. Low reliability means the pattern shouldn't be traded on its own.
- **Track record:** if `memory.track_record` has evaluated calls, mention the hit rate. This is the most honest evidence of usefulness.
- **Disclaimer:** close with a short note that this is educational technical analysis, not investment advice.

**Never:**
- present `prob_up` as a certainty;
- invent price levels not in the response;
- recommend position sizes.

## 5. Troubleshooting

| Symptom | Likely cause → action |
|---|---|
| `400 Only N bars available` | Needs ≥30 sessions. Sync with a backfill, or upload more history. |
| `404 No stored data for X` | Not synced yet. Add it to the watchlist first. |
| `409 A sync is already running` | Wait; poll `/api/sync/status`. |
| Sync log `No bhavcopy for N weekday(s)` | Holidays, or today's file isn't out yet (NSE publishes ~6 pm IST). Normal. |
| Sync log `Ignored … different date` | NSE served a stale file; it is retried automatically next sync. |
| Sync log `Download failed … HTTP 403` | NSE blocked the request. Retry later; check internet access from the server. |
| `embedding_backend: hashing` in health | ONNX model couldn't download. Search still works, with lower quality. |

## 6. Configuration

All data lives in `~/nse-analyzer-data`, or wherever `NSE_DATA_DIR` points. The daily auto-sync runs Mon–Fri at `AUTO_SYNC_TIME` (default 18:45 IST) while the server runs. For one-off syncs without the server, run `python scripts/daily_sync.py [--add SYMBOLS]` in `backend/`.
