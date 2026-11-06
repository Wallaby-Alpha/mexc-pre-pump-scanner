"""
Download 1h historical klines for top altcoins to benchmark 1h vs 4h combinations.
"""

import time
import pandas as pd
from datetime import datetime
from config import DatasetConfig
from collector import MexcCollector
from database import init_db, save_klines, get_all_symbols, get_connection

def sync_1h_dataset(symbol_limit: int = 75, days: int = 75):
    init_db()
    collector = MexcCollector(delay=0.06)
    
    # Get top symbols by 24h volume from symbols table
    conn = get_connection()
    df_syms = pd.read_sql_query(
        "SELECT symbol, quote_volume_24h FROM symbols WHERE symbol NOT IN ('BTCUSDT', 'ETHUSDT') ORDER BY quote_volume_24h DESC LIMIT ?",
        conn,
        params=(symbol_limit,)
    )
    conn.close()
    
    symbols = df_syms['symbol'].tolist()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Downloading {days} days of 1h klines for top {len(symbols)} altcoins...")
    
    start_time = time.time()
    total_candles = 0
    
    for idx, sym in enumerate(symbols, 1):
        df = collector.fetch_history(symbol=sym, interval="60m", days=days)
        if not df.empty:
            save_klines(sym, df, table="klines_1h")
            total_candles += len(df)
            
        if idx % 15 == 0 or idx == len(symbols):
            elapsed = time.time() - start_time
            print(f"  [{idx:2d}/{len(symbols)}] Synced 1h for {sym:12s} ({len(df):4d} candles) | {idx/elapsed:.1f} coins/sec")
            
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(DISTINCT symbol), COUNT(*) FROM klines_1h;")
    res = c.fetchone()
    conn.close()
    
    print("\n" + "="*60)
    print("1H DATASET SYNC COMPLETE")
    print(f"Total Symbols in 1h Table: {res[0]}")
    print(f"Total 1h Candles:          {res[1]:,}")
    print("="*60)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=75)
    parser.add_argument("--days", type=int, default=75)
    args = parser.parse_args()
    sync_1h_dataset(symbol_limit=args.limit, days=args.days)
