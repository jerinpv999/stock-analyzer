import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

log = logging.getLogger("nse.config")

BASE_DIR = Path(__file__).resolve().parent.parent

# All your data (price history, watchlist, models, ChromaDB, bhavcopy cache) lives OUTSIDE
# the project folder, so replacing the code with a new zip never touches it.
#   Default: ~/nse-analyzer-data   (Linux/macOS: /home/<you>/nse-analyzer-data,
#                                   Windows: C:\Users\<you>\nse-analyzer-data)
#   Override: set NSE_DATA_DIR=/any/folder
DEFAULT_DATA_DIR = Path.home() / "nse-analyzer-data"
DATA_DIR = Path(os.getenv("NSE_DATA_DIR") or DEFAULT_DATA_DIR).expanduser().resolve()
LEGACY_DATA_DIR = BASE_DIR / "data"  # where older versions stored data


def _has_files(p: Path) -> bool:
    return p.is_dir() and any(p.iterdir())


def _migrate_legacy_data() -> None:
    """One-time copy of backend/data (older versions) into the new external folder."""
    if DATA_DIR == LEGACY_DATA_DIR.resolve() or not _has_files(LEGACY_DATA_DIR) or _has_files(DATA_DIR):
        return
    shutil.copytree(LEGACY_DATA_DIR, DATA_DIR, dirs_exist_ok=True)
    (LEGACY_DATA_DIR / "MOVED_TO.txt").write_text(
        f"On {datetime.now():%Y-%m-%d %H:%M} this data was copied to:\n{DATA_DIR}\n\n"
        "The app now uses that folder. Once you've checked everything is there, "
        "you can delete this old backend/data folder.\n"
    )
    log.warning("Copied existing data from %s to %s", LEGACY_DATA_DIR, DATA_DIR)


_migrate_legacy_data()
DATA_DIR.mkdir(parents=True, exist_ok=True)
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
