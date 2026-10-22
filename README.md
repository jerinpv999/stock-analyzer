# NSE Stock Analyzer

The app opens on a **Morning briefing** of world and Indian markets, ready before 08:30 IST. For any stock you upload or track, it adds:

- **Technical analysis for three timeframes** — Day trading (next session), Short term (1–4 week swing), Long term (positional) — each with a verdict, a score from −100 to +100, the individual signals behind it, and a trade plan (entry, stop-loss, targets, risk:reward).
- **An ML model trained on that stock's own history** — a gradient-boosted classifier per horizon (1 / 5 / 20 sessions) predicting the probability the price will be higher. It is validated walk-forward, and its accuracy is shown next to a "always guess the majority" baseline, so you can see whether it actually has an edge.
- **Candlestick pattern model** — detects 22 one-, two- and three-candle patterns (Hammer, Engulfing, Harami, Morning/Evening Star, Three White Soldiers, Tweezers, Doji family…) on every bar, shows how each pattern actually performed on this stock, and predicts the chance today's pattern works out over the next 3 sessions. The prediction blends the stock's own pattern history with a model trained on pattern events pooled from every stock you've uploaded. Patterns are marked on the chart.
- **Charts** — candlesticks with SMA/EMA/VWAP/Bollinger/Supertrend overlays, support/resistance lines and volume; RSI, MACD, Stochastic and ADX panels; a model-probability chart.
- **Morning briefing (main page)** — built automatically every weekday at 08:15 IST, before the 09:15 open, with a weekly recap every Saturday. It covers:
  - world indices, commodities, currencies and yields (Yahoo Finance);
  - Indian benchmarks, sectors, market breadth, top movers and an **all-NSE-index summary**;
  - India and world news summaries (CNBC-TV18, CNBC, Yahoo Finance);
  - today's and this week's stock events (results, dividends, splits, bonus from NSE);
  - a pre-market model's chance that the Nifty opens and closes higher.

  All summarising and modelling runs offline on your machine; the internet is used only to download data.
- **Memory in ChromaDB** — every analysis summary is embedded and stored. The next analysis of the same stock shows what changed since last time, checks whether earlier Bullish/Bearish calls came true, surfaces similar setups in other stocks, and supports semantic search over all past analyses.

> **For educational purposes only.** Not investment advice or a recommendation, and not from a SEBI-registered investment adviser or research analyst. Automated analysis can be wrong. 9 out of 10 individual traders in equity F&O incurred net losses (SEBI study, January 2023). The app shows this notice every time it's opened, and keeps it in the header and footer.

> 📘 Full user guide: [`docs/NSE-Stock-Analyzer-User-Guide.pdf`](docs/NSE-Stock-Analyzer-User-Guide.pdf). The app also has a built-in guided tour: it opens on first visit, and the **Tour** button replays it.

## Quick start with Docker (recommended)

```bash
mkdir -p ~/nse-analyzer-data          # your data lives here, outside the project
docker compose up -d --build
```

Open http://localhost:8080 (API docs: http://localhost:8000/docs).

- **Settings:** copy `.env.example` to `.env` to change the data folder, port, sync time or your user id (`HOST_UID`/`HOST_GID`, so data files stay owned by you).
- **Your data is stored on your computer, not inside Docker.** `~/nse-analyzer-data` is mounted into the backend as `/data`. It survives `docker compose down`, rebuilds and app updates, and the header shows its real location. To use another disk or folder, set it in `.env` before starting:
  ```bash
  NSE_DATA_HOST_DIR=/mnt/storage/nse-analyzer-data   # Linux/macOS
  NSE_DATA_HOST_DIR=D:/nse-analyzer-data             # Windows (Docker Desktop)
  ```
  To move existing data, stop the app (`docker compose down`), copy the old folder to the new place, set `NSE_DATA_HOST_DIR`, then run `docker compose up -d`.
- **Logs:** `docker compose logs -f backend`.
- **"Backend not reachable" on the page:** run `docker compose logs backend`. The backend container fixes the data folder's ownership on start (Docker creates a missing `~/nse-analyzer-data` as root), then runs as `HOST_UID`/`HOST_GID` (default 1000 — check yours with `id -u`; set it in `.env` if different). The page keeps retrying every 5 seconds, so it connects as soon as the backend is up.
- **Updating:** replace the code, then run `docker compose up -d --build`. Your data is untouched.
- **Auto-restart:** the containers restart automatically, so the 18:45 IST daily sync keeps running.

## Morning briefing (main page)

The **Market** tab is the first thing you see. It has two views.

**Daily briefing** (weekdays, built at 08:15 IST):

| Section | What it shows | Source |
|---|---|---|
| Mood tiles | Global cues (overnight US + Asia), news mood for India and the world, and the pre-market model's chance the Nifty opens/closes higher, with "Why?" drivers | computed locally |
| Summary | A plain-English paragraph of all of the below | computed locally |
| World markets | S&P 500, Nasdaq, Dow, Russell, VIX, FTSE, DAX, CAC, Euro Stoxx, Nikkei, Hang Seng, Shanghai, KOSPI, Taiwan, ASX, STI, Brent, WTI, gold, silver, USD/INR, dollar index, US 10-year, each with a 1-month trend | Yahoo Finance |
| Indian markets | Nifty 50, Sensex, Nifty Bank, Midcap, Smallcap, India VIX, sector moves, market breadth (advances vs declines across all NSE stocks), top gainers and losers among liquid stocks | NSE, Yahoo Finance, NSE bhavcopy |
| All NSE indices | Every NSE index (broad, sectoral, thematic, strategy, fixed income) with change, P/E, 52-week range, advances/declines and 1-year change; filter, search and sort | NSE (falls back to NSE's official daily index file) |
| Who's buying & selling | FII/FPI and DII buying, selling and net in the cash market (₹ crore, NSE provisional) with a 10-session chart; F&O positions of **Retail (Client), Pro traders, FII and DII**: % of index-futures positions that are long, net index futures, day change, net index calls and puts, net stock futures, plus a 10-session trend | NSE FII/DII data; NSE participant-wise open interest file |
| Advance / decline | Advances, declines, unchanged and the A/D ratio across all NSE equity stocks; stocks up or down 4%+; net breadth over the last 10 sessions; advances vs declines inside each index | NSE bhavcopy; NSE index snapshot |
| News summary | Stories from the last 30 hours, de-duplicated across sources, grouped into themes, scored for sentiment, with "stocks in the news" (★ = on your watchlist) | CNBC-TV18, CNBC, Yahoo Finance RSS |
| Stock events | Today's and the next 7 days' board meetings (results, dividends, fund raising) and ex-dates (dividend, bonus, split); watchlist stocks starred | NSE event calendar and corporate actions |

**Weekly recap** (Saturday 09:00 IST):
- the week's change for world and Indian indices, sectors and every NSE index;
- news mood by day and recurring themes of the week;
- how the pre-market calls did against the actual open;
- FII/DII net for the week and the change in each participant's F&O positions;
- advance/decline for each session;
- the week ahead's results and corporate actions.

Other ways to get a briefing:
- **Refresh now** rebuilds the briefing on demand.
- The date picker opens earlier briefings.
- If the computer was off at 08:15, the briefing is built when the backend next starts.

**How the offline models work** (no cloud AI, no API keys):

- **Sentiment:** a finance-tuned word list with phrase and negation rules ("misses estimates", "not higher"). For a stronger model, `SENTIMENT_BACKEND=finbert` (with `pip install transformers torch`) switches to FinBERT. It downloads once, then runs locally.
- **De-duplication and themes:** TF-IDF similarity merges the same story from several sources. Hierarchical clustering then groups stories into themes, labelled by subject (companies, places, policy) rather than by movement words like "rises".
- **Key stories:** chosen with TextRank, an extractive summary that picks the most central headlines.
- **Company linking:** headlines are matched to NSE symbols using NSE's equity list plus curated aliases (e.g. "Zomato" → ETERNAL).
- **Pre-market outlook:** a logistic regression trained on about 5 years of history. It learns P(Nifty opens higher) and P(Nifty closes higher) from the previous session's moves in US, European and Asian indices, crude, gold, the dollar, USD/INR and US yields. It is validated walk-forward against a naive baseline. The page always shows the tested accuracy and whether the model has an edge, and probabilities are capped at 1–99%.

Briefings are saved in `~/nse-analyzer-data/briefings/` (daily and weekly JSON), and raw downloads are cached for 10 days in `market_cache/`. A source that fails (NSE often blocks automated requests) never breaks the briefing: the "sources" line at the bottom of the page shows what loaded and what didn't.

## Using it with Claude

`skills/nse-stock-analyzer/SKILL.md` teaches Claude how to operate the app through its API. It covers adding symbols, syncing, analysing and reading results honestly, including whether the models have an edge. Add the folder as a skill (or put it in your project's skills directory for Claude Code), then ask things like *"Add HDFCBANK to my watchlist and give me the short-term view."*

## Project layout

```
nse-analyzer/
├── docker-compose.yml       Docker setup (backend + nginx-served frontend)
├── docs/                    PDF user guide
├── skills/                  Claude skill for operating the app
├── backend/                 FastAPI + pandas + scikit-learn + ChromaDB
│   ├── app/
│   │   ├── main.py          API endpoints
│   │   ├── data_loader.py   NSE CSV parsing (handles NSE's quirky headers/number formats)
│   │   ├── indicators.py    SMA/EMA/RSI/MACD/BB/ATR/Stoch/ADX/OBV/Supertrend/VWAP, pivots, CPR, S/R, candle patterns
│   │   ├── analysis.py      Rule-based timeframe analysis + trade plans
│   │   ├── model.py         ML training, walk-forward validation, prediction
│   │   ├── memory.py        ChromaDB storage, recall, track-record evaluation
│   │   └── config.py
│   ├── scripts/make_sample.py   Generates a synthetic NSE-format CSV for testing
│   └── scripts/
└── frontend/                React (Vite) + lightweight-charts + Recharts
```

## Where your data lives

Everything the app builds up is stored **outside the project folder**, in `~/nse-analyzer-data`:
- price history
- watchlist
- trained models
- ChromaDB memory
- bhavcopy cache

On Linux that's `/home/<you>/nse-analyzer-data`; on Windows, `C:\Users\<you>\nse-analyzer-data`.

This means you can delete or replace the project folder with a new zip at any time without losing anything. The exact path is shown in the app's header and at `/api/health`.

- **Different location:** set `NSE_DATA_DIR`, e.g. `NSE_DATA_DIR=/mnt/backup/nse-data uvicorn app.main:app --port 8000`.
- **Upgrading from an older version** that kept data in `backend/data`: the first start copies it to the new folder automatically and leaves a `MOVED_TO.txt` note. Delete the old folder once you've checked.
- **Backup:** copy the `nse-analyzer-data` folder.

## Setup

**Requirements:** Python 3.10+ and Node.js 18+.

### 1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The first start downloads ChromaDB's small MiniLM embedding model (~80 MB). If that download is blocked, the app automatically falls back to a local hashing embedder, so it still works offline. For the best embeddings, `pip install sentence-transformers`.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The dev server proxies `/api` to the backend on port 8000.

## Getting the CSV from NSE

1. Go to nseindia.com, search for the stock and open its quote page.
2. Open **Historical Data**, choose a range (1 year or more is recommended — the 200-day average and the ML model need history) and click **Download (.csv)**.
3. Drop the file into the app. The symbol is detected from the file name (e.g. `Quote-Equity-RELIANCE-EQ-...csv`) or you can type it.

Also accepted: NSE bhavcopy / security-wise archive files, and generic OHLCV CSVs (daily or intraday, e.g. 5-minute bars with a `datetime` column).

### Automatic daily data from NSE bhavcopy (recommended)

Open the **Watchlist** tab and add symbols, e.g. `RELIANCE, TCS, M&M, NIFTY 50`.

- **New symbols are backfilled** (6 months / 1 year / 2 years) from NSE's daily bhavcopy files.
- **Symbols you already uploaded by CSV** simply continue from their last date.
- **Every weekday at 18:45 IST** the backend downloads that day's bhavcopy, appends the new session to every watchlist symbol, retrains the models and stores a new analysis in ChromaDB. Click **Open** to view it.
- **If the computer was off**, the next start catches up on the missed days automatically.
- **Caching:** downloaded files are cached in `nse-analyzer-data/bhavcopy/`, so the first 1-year backfill takes a few minutes (~250 files, fetched politely) and adding more symbols later is instant.

Sources used (public NSE archives):

| Data | File |
|---|---|
| Stocks (current UDiFF format) | `nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip` |
| Stocks (fallback) | `nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv` |
| Indices (NIFTY 50, NIFTY BANK…) | `nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv` |

**Symbol format:** use the NSE ticker (`RELIANCE`, `M&M`, `BAJAJ-AUTO`). For indices use the name as NSE writes it, with or without spaces (`NIFTY 50`, `NIFTY BANK`).

**Holidays:** these are detected automatically (no file that day).

**The server must be running for the schedule.** If you'd rather not keep it running, use the one-shot script with cron or Windows Task Scheduler:

```bash
python scripts/daily_sync.py                      # sync the watchlist once
python scripts/daily_sync.py --add RELIANCE TCS   # add symbols, then sync
```

**Analysing data you've already fetched:**
- **Open** shows the last saved analysis for a symbol.
- **Analyse** re-runs the full analysis (indicators, ML, patterns, memory) on the stored data without downloading anything.
- **Analyse all** does that for every watchlist symbol.
- The API equivalent is `POST /api/analyze-stored/{symbol}`.

Settings: `AUTO_SYNC=false` turns the schedule off. `AUTO_SYNC_TIME=19:15` changes the time. `AUTO_SYNC_ON_START=false` skips the catch-up at startup.

### Daily workflow with manual CSV uploads

1. Upload 1 year (or more) of history once.
2. After that, upload just the new day's file each evening (a one-row CSV is fine — same NSE download, date range = today). It is merged into the stored history, every model is retrained on the full history, and the previous day's calls are scored against what actually happened.
3. Missed a few days? Upload a file covering the gap; duplicates are ignored.

Also works with **index files** (NIFTY 50, NIFTY BANK… from the NSE indices historical page) and with the **full-market bhavcopy**: if a file contains many stocks, type the symbol and only that stock is used.

**Tip:** keep "Merge with stored history" ticked. Each upload is merged into `nse-analyzer-data/history/<SYMBOL>_daily.csv`, so the training set grows and you can upload just the latest few weeks next time.

## How the pieces fit

| Step | What happens |
|---|---|
| Parse | Column names, comma-formatted numbers, `20-Oct-2026` dates and newest-first ordering are normalised; only the `EQ` series is kept. |
| Indicators | Computed with pandas (no TA-Lib needed). |
| Rules | Each timeframe has its own indicator set; each signal votes +1 / 0 / −1 and the score is the average × 100. |
| ML | Around 30 features (returns, RSI, MACD, band position, ATR, ADX, distance from averages, volume ratio, gap, …). `HistGradientBoostingClassifier`, `TimeSeriesSplit` with a gap equal to the horizon to prevent look-ahead. Saved to `data/models/`. |
| Patterns | 22 patterns detected with trend context; per-stock win rates (smoothed toward 50% when samples are few); a pooled gradient-boosted model of pattern success using RSI, trend, volume and range position, expressed relative to the pattern's direction. Saved to `data/models/candlestick_pattern_model.joblib`. |
| Blend | Combined score = rules × 0.6 + ML × 0.4 when the model beats the baseline by more than 2 points; otherwise ML gets only 15% weight. |
| Memory | The summary text is embedded and stored in ChromaDB with metadata (symbol, date, close, verdicts, probabilities). Before storing, past analyses for the symbol are recalled and scored against the prices that arrived since. |

## API

| Method | Path | Description |
|---|---|---|
| POST | `/api/analyze` | multipart: `file` (CSV), optional `symbol`, `merge` (true/false, default true) |
| GET | `/api/history/{symbol}` | Stored analyses for a symbol, newest first |
| GET | `/api/symbols` | Symbols in memory with counts |
| GET | `/api/search?q=...&symbol=` | Semantic search over stored summaries |
| DELETE | `/api/history/{symbol}` | Remove a symbol's stored analyses |
| GET/POST | `/api/watchlist` | List (with latest verdicts) / add symbols `{"symbols": ["RELIANCE, TCS"], "backfill_days": 365}` |
| DELETE | `/api/watchlist/{symbol}` | Stop tracking a symbol |
| POST | `/api/sync` | Run the bhavcopy sync now (optionally `{"symbols": [...]}`) |
| GET | `/api/sync/status` | Progress + log of the current/last sync |
| POST | `/api/analyze-stored/{symbol}` | Re-run analysis on stored data (no download) |
| GET | `/api/results/{symbol}` | Latest saved full analysis |
| GET | `/api/briefing/latest` | Latest daily briefing + weekly recap, build status and schedule |
| GET | `/api/briefing/list` | Dates of stored daily briefings and weekly recaps |
| GET | `/api/briefing/daily/{YYYY-MM-DD}` · `/api/briefing/weekly/{monday}` | A specific stored briefing |
| POST | `/api/briefing/refresh` | Build now: `{"kind": "daily"}` or `{"kind": "weekly"}` |
| GET | `/api/briefing/status` | Progress of the current/last build |
| GET | `/api/health` | Status, embedding backend, stored count |

Interactive docs: http://localhost:8000/docs

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `NSE_DATA_DIR` | `~/nse-analyzer-data` | Where history, models and ChromaDB live |
| `EMBEDDING_BACKEND` | auto | Force `sentence_transformers`, `onnx` or `hashing` |
| `CHART_BARS` | 750 | Bars sent to the UI |
| `AUTO_BRIEFING` | true | Build the morning briefing and weekly recap automatically |
| `BRIEFING_TIME` | 08:15 | Daily briefing time (IST, Mon–Fri) — keep it before 08:30 |
| `WEEKLY_TIME` | 09:00 | Weekly recap time (IST, Saturday) |
| `SENTIMENT_BACKEND` | lexicon | `finbert` for the optional local FinBERT model |
| `CORS_ORIGINS` | localhost:5173 | Allowed UI origins |
| `VITE_API_URL` (frontend) | empty | Backend URL when not using the dev proxy |

## Try it without real data

```bash
cd backend
python scripts/make_sample.py DEMO 800
```

This writes `Quote-Equity-DEMO-EQ-sample.csv` in NSE's exact format. Upload it in the UI.

## A note on expectations

Daily stock direction is close to a coin flip; a model with 52–56% walk-forward accuracy is doing well, and many stocks will show no edge at all. The app shows that honestly rather than hiding it. Use the analysis as one input alongside your own research and risk management.
