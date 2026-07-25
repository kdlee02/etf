"""SQLite 캐시 스키마 + 연결. 읽기 헬퍼는 tools.py가 씀."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "etf_cache.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS etfs(
    ticker TEXT PRIMARY KEY, name TEXT, category TEXT, country TEXT,
    ret_3mo REAL, ret_1y REAL, updated_at TEXT);
CREATE TABLE IF NOT EXISTS holdings(
    ticker TEXT, symbol TEXT, name TEXT, weight REAL,
    PRIMARY KEY(ticker, symbol));
CREATE TABLE IF NOT EXISTS sector_weights(
    ticker TEXT, sector TEXT, weight REAL,
    PRIMARY KEY(ticker, sector));
CREATE TABLE IF NOT EXISTS sector_industries(
    sector_key TEXT, industry_key TEXT, industry_name TEXT, weight REAL,
    PRIMARY KEY(sector_key, industry_key));
CREATE TABLE IF NOT EXISTS industry_companies(
    industry_key TEXT, symbol TEXT, name TEXT, weight REAL,
    PRIMARY KEY(industry_key, symbol));
CREATE TABLE IF NOT EXISTS sector_etfs_ext(
    sector_key TEXT, ticker TEXT, name TEXT,
    PRIMARY KEY(sector_key, ticker));
"""


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: Streamlit reruns on different threads; this conn is read cache
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
