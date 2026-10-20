"""Generate a synthetic CSV in the exact NSE 'Historical Data' download format for testing.

Usage: python scripts/make_sample.py RELIANCE 800 [end-date YYYY-MM-DD]
"""
import sys

import numpy as np
import pandas as pd

sym = sys.argv[1] if len(sys.argv) > 1 else "SAMPLE"
n = int(sys.argv[2]) if len(sys.argv) > 2 else 800
end = sys.argv[3] if len(sys.argv) > 3 else "2026-10-19"

rng = np.random.default_rng(sum(map(ord, sym)))  # deterministic per symbol
dates = pd.bdate_range(end=end, periods=n)
regime = np.sin(np.linspace(0, 6 * np.pi, n)) * 0.0012
rets = regime + rng.normal(0.0004, 0.016, n)
close = 1500 * np.exp(np.cumsum(rets))
open_ = close * (1 + rng.normal(0, 0.006, n))
high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.008, n)))
low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.008, n)))
vol = (rng.lognormal(14, 0.4, n)).astype(int)
fmt = lambda a: [f"{x:,.2f}" for x in a]  # noqa: E731

df = pd.DataFrame({
    "Date ": [d.strftime("%d-%b-%Y") for d in dates],
    "series ": "EQ",
    "OPEN ": fmt(open_), "HIGH ": fmt(high), "LOW ": fmt(low),
    "PREV. CLOSE ": fmt(np.r_[close[0], close[:-1]]),
    "ltp ": fmt(close), "close ": fmt(close), "vwap ": fmt((high + low + close) / 3),
    "52W H ": fmt(pd.Series(high).rolling(252, min_periods=1).max()),
    "52W L ": fmt(pd.Series(low).rolling(252, min_periods=1).min()),
    "VOLUME ": [f"{v:,}" for v in vol], "VALUE ": fmt(vol * close), "No of trades ": [f"{v // 50:,}" for v in vol],
}).iloc[::-1]  # NSE downloads are newest-first
out = f"Quote-Equity-{sym}-EQ-sample.csv"
df.to_csv(out, index=False)
print("wrote", out)
