"""Run the bhavcopy sync once, without the web server (for cron / Windows Task Scheduler).

Usage (from the backend folder):
    python scripts/daily_sync.py                      # sync every watchlist symbol
    python scripts/daily_sync.py --add RELIANCE TCS   # add symbols, then sync (backfills 1 year)
    python scripts/daily_sync.py --add NIFTY50 --kind index

Linux/macOS cron, weekdays at 6:45 pm IST:
    45 18 * * 1-5  cd /path/to/backend && .venv/bin/python scripts/daily_sync.py
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AUTO_SYNC", "false")  # the scheduler thread isn't needed for a one-shot run

from app import sync as S  # noqa: E402
from app.main import ANALYSE  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--add", nargs="*", default=[], help="symbols to add to the watchlist first")
p.add_argument("--kind", choices=["equity", "index"], help="force the kind for --add symbols")
p.add_argument("--backfill-days", type=int, default=365)
p.add_argument("--only", nargs="*", help="sync only these symbols")
args = p.parse_args()

for s in args.add:
    print("watching", S.add_symbol(s, args.kind))

S.JOB.start(ANALYSE, symbols=args.only, backfill_days=args.backfill_days, trigger="cli", wait=True)
st = S.JOB.status()
print("\n".join(st["log"]))
sys.exit(1 if st["error"] else 0)
