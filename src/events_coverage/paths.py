from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

NEWS_DB = PROJECT_ROOT / "news_data" / "ask_media_unified_messages_20260604.db"
FOM_EVENTS_CLEAN = PROJECT_ROOT / "fom_events" / "processed_events" / "events_table.csv"

DATA_INTERIM = PROJECT_ROOT / "data" / "interim"
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"
DATA_WAREHOUSE = PROJECT_ROOT / "data" / "warehouse"
WAREHOUSE_DB = DATA_WAREHOUSE / "events.duckdb"
DBT_PROJECT = PROJECT_ROOT / "dbt"
OUTPUTS = PROJECT_ROOT / "outputs"
REPORTS = PROJECT_ROOT / "reports"
