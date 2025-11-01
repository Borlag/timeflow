import os
from pathlib import Path

APP_NAME = "TimeFlow"
SECRET_KEY = os.environ.get("TIMEFLOW_SECRET_KEY", "change-me-in-prod")
# Path to a shared SQLite database file. Set TIMEFLOW_DB to a UNC path or synced folder.
DB_PATH = os.environ.get("TIMEFLOW_DB", str(Path(__file__).parent / "timeflow.db"))
SHIFT_HOURS = float(os.environ.get("TIMEFLOW_SHIFT_HOURS", "8.0"))
ALLOW_BACKFILL_DAYS = int(os.environ.get("TIMEFLOW_ALLOW_BACKFILL_DAYS", "1"))  # by default only previous day
ORG_NAME = os.environ.get("TIMEFLOW_ORG_NAME", "Your Organization")
ENABLE_SIGNUP = os.environ.get("TIMEFLOW_ENABLE_SIGNUP", "false").lower() == "true"
