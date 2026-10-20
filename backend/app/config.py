import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("NSE_DATA_DIR", BASE_DIR / "data"))
HISTORY_DIR = DATA_DIR / "history"      # merged price history per symbol (training data grows each upload)
MODEL_DIR = DATA_DIR / "models"         # trained models per symbol + horizon
CHROMA_DIR = DATA_DIR / "chroma_db"     # ChromaDB persistent store for analysis summaries

for d in (HISTORY_DIR, MODEL_DIR, CHROMA_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Forces an embedding backend: "sentence_transformers", "onnx" or "hashing". Empty = auto.
EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "").strip().lower()

# Max bars sent to the UI for charting
CHART_BARS = int(os.getenv("CHART_BARS", "750"))

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")

# ---- bhavcopy auto-sync
BHAV_DIR = DATA_DIR / "bhavcopy"        # cached raw NSE bhavcopy files (shared by all symbols)
RESULTS_DIR = DATA_DIR / "results"      # latest full analysis per symbol (shown in the UI)
WATCHLIST_FILE = DATA_DIR / "watchlist.json"
for d in (BHAV_DIR, RESULTS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Daily scheduler: runs Mon–Fri at this IST time (NSE publishes bhavcopy around 6 pm IST)
AUTO_SYNC = os.getenv("AUTO_SYNC", "true").lower() in ("1", "true", "yes")
AUTO_SYNC_TIME = os.getenv("AUTO_SYNC_TIME", "18:45")
# On startup, catch up on any trading days missed while the computer was off
AUTO_SYNC_ON_START = os.getenv("AUTO_SYNC_ON_START", "true").lower() in ("1", "true", "yes")
