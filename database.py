"""
SQLite storage for MEXC market data and historical klines.
"""

import sqlite3
import pandas as pd
from typing import List, Dict, Any, Optional
from config import DB_PATH

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn

def init_db():
    conn = get_connection()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS symbols (
                symbol TEXT PRIMARY KEY,
                base_asset TEXT NOT NULL,
                quote_asset TEXT NOT NULL,
                quote_volume_24h REAL DEFAULT 0,
                price_change_24h REAL DEFAULT 0,
                last_price REAL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS klines_4h (
                symbol TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                datetime_utc TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                quote_volume REAL NOT NULL,
                PRIMARY KEY (symbol, timestamp)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS klines_1h (
                symbol TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                datetime_utc TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                quote_volume REAL NOT NULL,
                PRIMARY KEY (symbol, timestamp)
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_k4h_sym_ts ON klines_4h(symbol, timestamp);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_k4h_ts ON klines_4h(timestamp);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_k1h_sym_ts ON klines_1h(symbol, timestamp);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_k1h_ts ON klines_1h(timestamp);")
    conn.close()

def save_symbols(symbols_data: List[Dict[str, Any]]):
    if not symbols_data:
        return
    conn = get_connection()
    with conn:
        conn.executemany("""
            INSERT INTO symbols (symbol, base_asset, quote_asset, quote_volume_24h, price_change_24h, last_price)
            VALUES (:symbol, :base_asset, :quote_asset, :quote_volume_24h, :price_change_24h, :last_price)
            ON CONFLICT(symbol) DO UPDATE SET
                quote_volume_24h = excluded.quote_volume_24h,
                price_change_24h = excluded.price_change_24h,
                last_price = excluded.last_price,
                updated_at = CURRENT_TIMESTAMP;
        """, symbols_data)
    conn.close()

def save_klines(symbol: str, df: pd.DataFrame, table: str = "klines_4h"):
    if df.empty:
        return
    conn = get_connection()
    records = []
    for _, row in df.iterrows():
        records.append((
            symbol,
            int(row["timestamp"]),
            str(row["datetime"]),
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
            float(row["volume"]),
            float(row["quote_volume"])
        ))
    with conn:
        conn.executemany(f"""
            INSERT OR IGNORE INTO {table} (symbol, timestamp, datetime_utc, open, high, low, close, volume, quote_volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, records)
    conn.close()

def get_symbol_klines(symbol: str, table: str = "klines_4h") -> pd.DataFrame:
    conn = get_connection()
    query = f"SELECT timestamp, datetime_utc as datetime, open, high, low, close, volume, quote_volume FROM {table} WHERE symbol = ? ORDER BY timestamp ASC"
    df = pd.read_sql_query(query, conn, params=(symbol,))
    conn.close()
    if not df.empty:
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    return df

def get_all_symbols(table: str = "klines_4h") -> List[str]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT DISTINCT symbol FROM {table} ORDER BY symbol ASC;")
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_db_summary():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM symbols;")
    sym_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT symbol), COUNT(*), MIN(datetime_utc), MAX(datetime_utc) FROM klines_4h;")
    kline_stats = cursor.fetchone()
    conn.close()
    return {
        "symbols_tracked": sym_count,
        "kline_symbols": kline_stats[0] if kline_stats else 0,
        "total_candles": kline_stats[1] if kline_stats else 0,
        "earliest_candle": kline_stats[2] if kline_stats else None,
        "latest_candle": kline_stats[3] if kline_stats else None
    }
