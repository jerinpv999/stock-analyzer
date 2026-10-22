"""What the briefing tracks. Yahoo Finance symbols for indices, commodities, FX and rates."""

GLOBAL = [
    # (yahoo symbol, display name, group, kind) — kind "index" | "commodity" | "fx" | "yield"
    ("^GSPC", "S&P 500", "Americas", "index"),
    ("^IXIC", "Nasdaq Composite", "Americas", "index"),
    ("^DJI", "Dow Jones", "Americas", "index"),
    ("^RUT", "Russell 2000", "Americas", "index"),
    ("^VIX", "CBOE VIX", "Americas", "index"),
    ("^FTSE", "FTSE 100", "Europe", "index"),
    ("^GDAXI", "DAX", "Europe", "index"),
    ("^FCHI", "CAC 40", "Europe", "index"),
    ("^STOXX50E", "Euro Stoxx 50", "Europe", "index"),
    ("^N225", "Nikkei 225", "Asia-Pacific", "index"),
    ("^HSI", "Hang Seng", "Asia-Pacific", "index"),
    ("000001.SS", "Shanghai Composite", "Asia-Pacific", "index"),
    ("^KS11", "KOSPI", "Asia-Pacific", "index"),
    ("^TWII", "Taiwan Weighted", "Asia-Pacific", "index"),
    ("^AXJO", "ASX 200", "Asia-Pacific", "index"),
    ("^STI", "Straits Times", "Asia-Pacific", "index"),
    ("BZ=F", "Brent crude", "Commodities & FX", "commodity"),
    ("CL=F", "WTI crude", "Commodities & FX", "commodity"),
    ("GC=F", "Gold", "Commodities & FX", "commodity"),
    ("SI=F", "Silver", "Commodities & FX", "commodity"),
    ("INR=X", "USD / INR", "Commodities & FX", "fx"),
    ("DX-Y.NYB", "US Dollar Index", "Commodities & FX", "fx"),
    ("^TNX", "US 10-year yield", "Commodities & FX", "yield"),
]

INDIA = [
    # (yahoo symbol, display name, NSE allIndices name, group)
    ("^NSEI", "Nifty 50", "NIFTY 50", "Broad"),
    ("^BSESN", "Sensex", None, "Broad"),
    ("^NSEBANK", "Nifty Bank", "NIFTY BANK", "Broad"),
    ("^NSEMDCP50", "Nifty Midcap 50", "NIFTY MIDCAP 50", "Broad"),
    ("^CNXSC", "Nifty Smallcap 100", "NIFTY SMALLCAP 100", "Broad"),
    ("^INDIAVIX", "India VIX", "INDIA VIX", "Broad"),
    ("^CNXIT", "Nifty IT", "NIFTY IT", "Sector"),
    ("^CNXAUTO", "Nifty Auto", "NIFTY AUTO", "Sector"),
    ("^CNXFMCG", "Nifty FMCG", "NIFTY FMCG", "Sector"),
    ("^CNXPHARMA", "Nifty Pharma", "NIFTY PHARMA", "Sector"),
    ("^CNXMETAL", "Nifty Metal", "NIFTY METAL", "Sector"),
    ("^CNXREALTY", "Nifty Realty", "NIFTY REALTY", "Sector"),
    ("^CNXENERGY", "Nifty Energy", "NIFTY ENERGY", "Sector"),
    ("^CNXPSUBANK", "Nifty PSU Bank", "NIFTY PSU BANK", "Sector"),
    ("NIFTY_FIN_SERVICE.NS", "Nifty Financial Services", "NIFTY FINANCIAL SERVICES", "Sector"),
    ("^CNXMEDIA", "Nifty Media", "NIFTY MEDIA", "Sector"),
]

# Features for the pre-market model: everything here has fully closed before 08:15 IST.
MODEL_INPUTS = ["^GSPC", "^IXIC", "^DJI", "^VIX", "^FTSE", "^GDAXI", "^N225", "^HSI",
                "BZ=F", "GC=F", "INR=X", "DX-Y.NYB", "^TNX"]
NIFTY = "^NSEI"

NEWS_FEEDS = [
    # (key, display source, region, url)
    ("cnbctv18_market", "CNBC-TV18 Markets", "india", "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml"),
    ("cnbctv18_economy", "CNBC-TV18 Economy", "india", "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/economy.xml"),
    ("cnbctv18_world", "CNBC-TV18 World", "world", "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/world.xml"),
    ("cnbc_top", "CNBC Top News", "world", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("cnbc_world", "CNBC World", "world", "https://www.cnbc.com/id/100727362/device/rss/rss.html"),
    ("cnbc_asia", "CNBC Asia", "world", "https://www.cnbc.com/id/19832390/device/rss/rss.html"),
    ("cnbc_economy", "CNBC Economy", "world", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("yahoo_news", "Yahoo Finance", "world", "https://finance.yahoo.com/news/rssindex"),
    ("yahoo_headlines", "Yahoo Finance", "world",
     "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC,%5EIXIC,%5EN225,%5EHSI,%5ENSEI&region=US&lang=en-US"),
]

# Fallback company-name aliases for linking headlines to NSE symbols (used alongside NSE's
# full equity list when that can be downloaded). Lower-case alias -> symbol.
CORE_ALIASES = {
    "reliance industries": "RELIANCE", "reliance": "RELIANCE", "ril": "RELIANCE",
    "tcs": "TCS", "tata consultancy": "TCS", "infosys": "INFY", "wipro": "WIPRO", "hcltech": "HCLTECH",
    "hcl tech": "HCLTECH", "hcl technologies": "HCLTECH", "tech mahindra": "TECHM", "ltimindtree": "LTIM",
    "hdfc bank": "HDFCBANK", "icici bank": "ICICIBANK", "axis bank": "AXISBANK", "kotak mahindra bank": "KOTAKBANK",
    "kotak bank": "KOTAKBANK", "state bank of india": "SBIN", "sbi": "SBIN", "indusind bank": "INDUSINDBK",
    "bank of baroda": "BANKBARODA", "punjab national bank": "PNB", "federal bank": "FEDERALBNK", "yes bank": "YESBANK",
    "bajaj finance": "BAJFINANCE", "bajaj finserv": "BAJAJFINSV", "bajaj auto": "BAJAJ-AUTO",
    "hdfc life": "HDFCLIFE", "sbi life": "SBILIFE", "lic": "LICI", "jio financial": "JIOFIN",
    "larsen & toubro": "LT", "larsen and toubro": "LT", "l&t": "LT",
    "itc": "ITC", "hindustan unilever": "HINDUNILVR", "hul": "HINDUNILVR", "nestle india": "NESTLEIND",
    "britannia": "BRITANNIA", "tata consumer": "TATACONSUM", "asian paints": "ASIANPAINT", "titan": "TITAN",
    "maruti suzuki": "MARUTI", "maruti": "MARUTI", "tata motors": "TATAMOTORS", "mahindra & mahindra": "M&M",
    "mahindra and mahindra": "M&M", "m&m": "M&M", "hero motocorp": "HEROMOTOCO", "eicher motors": "EICHERMOT",
    "tvs motor": "TVSMOTOR", "ashok leyland": "ASHOKLEY",
    "sun pharma": "SUNPHARMA", "sun pharmaceutical": "SUNPHARMA", "dr reddy's": "DRREDDY", "dr reddys": "DRREDDY",
    "cipla": "CIPLA", "divi's": "DIVISLAB", "divis lab": "DIVISLAB", "apollo hospitals": "APOLLOHOSP", "lupin": "LUPIN",
    "tata steel": "TATASTEEL", "jsw steel": "JSWSTEEL", "hindalco": "HINDALCO", "vedanta": "VEDL", "coal india": "COALINDIA",
    "ongc": "ONGC", "ntpc": "NTPC", "power grid": "POWERGRID", "bpcl": "BPCL", "ioc": "IOC", "indian oil": "IOC",
    "gail": "GAIL", "tata power": "TATAPOWER", "adani enterprises": "ADANIENT", "adani ports": "ADANIPORTS",
    "adani green": "ADANIGREEN", "adani power": "ADANIPOWER", "ultratech": "ULTRACEMCO", "grasim": "GRASIM",
    "shree cement": "SHREECEM", "bharti airtel": "BHARTIARTL", "airtel": "BHARTIARTL", "vodafone idea": "IDEA",
    "zomato": "ETERNAL", "eternal": "ETERNAL", "swiggy": "SWIGGY", "paytm": "PAYTM", "nykaa": "NYKAA",
    "dmart": "DMART", "avenue supermarts": "DMART", "trent": "TRENT", "hal": "HAL", "hindustan aeronautics": "HAL",
    "bel": "BEL", "bharat electronics": "BEL", "irctc": "IRCTC", "dlf": "DLF", "godrej properties": "GODREJPROP",
    "pidilite": "PIDILITIND", "havells": "HAVELLS", "siemens": "SIEMENS", "abb india": "ABB", "indigo": "INDIGO",
    "interglobe aviation": "INDIGO", "bse": "BSE", "mcx": "MCX", "polycab": "POLYCAB", "dixon": "DIXON",
}
