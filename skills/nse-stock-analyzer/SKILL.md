---
name: nse-stock-analyzer
description: Operate the local NSE Stock Analyzer app through its REST API: read the morning market briefing and weekly recap (world + Indian indices, all NSE indices, news summaries, stock events, pre-market outlook), add Indian stocks or indices to the watchlist, sync daily NSE bhavcopy data, run technical/ML/candlestick analysis, read results and search past analyses. Use when the user asks how the market looks today or this week, asks to analyse an NSE stock or index, check their watchlist, run or troubleshoot a sync, or compare past calls.
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

### "How does the market look today?" → the morning briefing
```bash
curl -s localhost:8000/api/briefing/latest      # {"daily": {...}, "weekly": {...}, "status": {...}, "schedule": {...}}
```
- **Check freshness first.** If `daily.date` isn't today (IST) and it's a weekday after 08:15, or the user wants it rebuilt, run `POST /api/briefing/refresh` with `{"kind": "daily"}`. Then poll `GET /api/briefing/status` until `status.running` is false; it takes about 1–2 minutes. Use `{"kind": "weekly"}` for the weekly recap.
- **Key fields:**
  - `narrative[]`: ready-made plain-English paragraphs; quote these.
  - `mood.global_cues` and `mood.news`.
  - `outlook.targets.gap_up` / `close_up`: `{prob_up, cv_accuracy, baseline_accuracy, has_edge, drivers[]}`.
  - `global[]`: world indices, commodities and FX.
  - `india.indices[]`, `india.breadth`, `india.gainers`, `india.losers`.
  - `india.all_indices[]`: every NSE index with `group`, `change_pct`, `pe` and the 52-week range.
  - `news.regions.{india,world}.themes[]` and `key_stories[]`; `news.stocks_in_news[]` (with a `watchlist` flag).
  - `events.today[]` / `events.upcoming[]`: board meetings and ex-dates; `watchlist` flags the user's stocks.
  - `sources[]`: which feeds loaded.
  - `flows.fii_dii`: `{date, fii:{buy,sell,net}, dii:{...}}` in ₹ crore (provisional; null if NSE blocked it); `flows.fii_dii_history[]`.
  - `flows.participants.rows[]`: one row each for `CLIENT` (retail), `PRO`, `FII` and `DII`, with:
    - `index_fut.{long,short,net,long_pct}`;
    - `index_calls.net`, `index_puts.net`, `stock_fut.net`;
    - `change.index_fut_net` (vs the previous session);
    - `flows.participants.trend[]` gives the 10-session history.
  - `flows.advance_decline.latest`: `{advances, declines, unchanged, ratio, up_4pct, down_4pct}`; also `history[]` (10 sessions) and `by_index[]`.
- **Weekly fields:** `global[]`, `india[]` and `all_indices[]` with weekly `change_pct`; `themes`; `premarket_calls[]` (how the outlook did); `next_week_events[]`; `flows` (`fii_net`, `dii_net`, `fii_dii_days[]`, `participants` with week change, `advance_decline.history[]`).
- **When reporting:**
  - Start or end with "for educational purposes only — not investment advice". The app is not SEBI-registered.
  - Describe participant positions as a snapshot of the last session, not a forecast.
  - Lead with the narrative.
  - Name the user's watchlist stocks that have events or news today.
  - Say plainly if `outlook...has_edge` is false (the model did not beat a naive guess in testing), and never present `prob_up` as certain.
  - If a source in `sources[]` has `ok: false`, mention what's missing, e.g. "NSE blocked the events request".

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
| Briefing `sources` show NSE ✕ | NSE often blocks automated requests; all-index data falls back to the official daily file, but events may be missing. Retry with refresh later. |
| `daily` is null in `/api/briefing/latest` | No briefing built yet: `POST /api/briefing/refresh` `{"kind":"daily"}`. |
| `embedding_backend: hashing` in health | ONNX model couldn't download. Search still works, with lower quality. |

## 6. Configuration

All data lives in `~/nse-analyzer-data`, or wherever `NSE_DATA_DIR` points. The morning briefing builds Mon–Fri at `BRIEFING_TIME` (default 08:15 IST) and the weekly recap on Saturday at `WEEKLY_TIME` (09:00); `AUTO_BRIEFING=false` turns that off. The daily auto-sync runs Mon–Fri at `AUTO_SYNC_TIME` (default 18:45 IST) while the server runs. For one-off syncs without the server, run `python scripts/daily_sync.py [--add SYMBOLS]` in `backend/`.
