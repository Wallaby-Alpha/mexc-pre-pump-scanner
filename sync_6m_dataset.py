"""
Sync 180 days (6 months) of 4h Kline data for BTC and Top 150 Altcoins.
"""

import time
import pandas as pd
from datetime import datetime
from collector import MexcCollector
from database import init_db, save_klines, get_connection

def sync_6m_dataset():
    init_db()
    collector = MexcCollector(delay=0.06)
    
    # 1. First fetch BTCUSDT for benchmark and market filter
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Syncing 180 days of 4h data for BTCUSDT...")
    df_btc = collector.fetch_history(symbol="BTCUSDT", interval="4h", days=180)
    if not df_btc.empty:
        save_klines("BTCUSDT", df_btc, table="klines_4h")
        print(f"  Synced BTCUSDT: {len(df_btc)} 4h candles ({df_btc['datetime'].min()} to {df_btc['datetime'].max()})")
        
    # 2. Get the list of top 150 altcoins from symbols table
    conn = get_connection()
    df_syms = pd.read_sql_query(
        "SELECT symbol, quote_volume_24h FROM symbols WHERE symbol NOT IN ('BTCUSDT', 'ETHUSDT') ORDER BY quote_volume_24h DESC LIMIT 150",
        conn
    )
    conn.close()
    
    symbols = df_syms['symbol'].tolist()
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Syncing 180 days of 4h klines for top {len(symbols)} altcoins...")
    
    start_time = time.time()
    total_candles = 0
    
    for idx, sym in enumerate(symbols, 1):
        df = collector.fetch_history(symbol=sym, interval="4h", days=180)
        if not df.empty:
            save_klines(sym, df, table="klines_4h")
            total_candles += len(df)
            
        if idx % 25 == 0 or idx == len(symbols):
            elapsed = time.time() - start_time
            print(f"  [{idx:3d}/{len(symbols)}] Synced {sym:12s} ({len(df):4d} candles) | {idx/elapsed:.1f} coins/sec")
            
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(DISTINCT symbol), COUNT(*), MIN(datetime_utc), MAX(datetime_utc) FROM klines_4h;")
    res = c.fetchone()
    conn.close()
    
    print("\n" + "="*65)
    print("6-MONTH 4H DATASET SYNC COMPLETE")
    print(f"Total Symbols in 4h Table: {res[0]}")
    print(f"Total 4h Candles:          {res[1]:,}")
    print(f"Date Range:                {res[2]} --> {res[3]}")
    print("="*65)

if __name__ == "__main__":
    sync_6m_dataset()
