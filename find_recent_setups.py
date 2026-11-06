"""
Find recent occurrences of the 4h Base Compression + Ignition setup,
and scan live MEXC market for coins triggering right now (including 3/4 1h candle pre-alerts).
"""

import time
import requests
import pandas as pd
from datetime import datetime, timezone
from database import get_connection, get_all_symbols, get_symbol_klines
from pre_pump_analyzer import calculate_technical_features
from collector import MexcCollector

def find_recent_historical_triggers(days_back: int = 14):
    """Scan local historical database for triggers in the last 14 days."""
    symbols = get_all_symbols("klines_4h")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Scanning historical database for triggers in the past {days_back} days...")
    
    triggers = []
    
    for sym in symbols:
        df_raw = get_symbol_klines(sym, table="klines_4h")
        if len(df_raw) < 100:
            continue
            
        df = calculate_technical_features(df_raw)
        n = len(df)
        
        # Look back over recent bars
        recent_bars = min(n - 50, days_back * 6) # 6 4h bars per day
        
        for i in range(n - recent_bars, n):
            row = df.iloc[i]
            
            # Base Compression Condition
            cond_base = (row['range_7d_pct'] <= 35.0 or row['bb_squeeze_rank'] >= 60)
            # Volume Expansion (>= 2.5x 20-bar MA)
            cond_vol = (row['quote_volume'] >= 2.5 * row['vol_ma20'])
            # Price Breakout
            prior_7d_high = df['high'].iloc[max(0, i-42) : i].max()
            cond_break = (row['close'] > row['open'] and row['close'] >= prior_7d_high * 0.98)
            
            if cond_base and cond_vol and cond_break:
                # Measure forward outcome if history exists
                forward = df.iloc[i+1 : min(n, i+19)]
                if not forward.empty:
                    max_high = forward['high'].max()
                    gain_pct = ((max_high - row['close']) / row['close']) * 100.0
                    peak_bar_offset = forward['high'].argmax() + 1
                    peak_time = str(forward.iloc[forward['high'].argmax()]['datetime'])
                else:
                    max_high = row['close']
                    gain_pct = 0.0
                    peak_time = "In Progress"
                    
                triggers.append({
                    "symbol": sym,
                    "trigger_time": str(row['datetime']),
                    "trigger_price": row['close'],
                    "quote_vol_surge": round(row['quote_volume'] / (row['vol_ma20'] + 1e-6), 2),
                    "bb_squeeze": round(row['bb_squeeze_rank'], 1),
                    "7d_range": round(row['range_7d_pct'], 1),
                    "forward_gain_pct": round(gain_pct, 1),
                    "peak_time": peak_time
                })
                
    df_trig = pd.DataFrame(triggers)
    if not df_trig.empty:
        # Sort by trigger_time descending
        df_trig.sort_values(by="trigger_time", ascending=False, inplace=True)
    return df_trig

def scan_live_mexc_for_setups(top_n: int = 100):
    """Query live MEXC API for the latest closed 4h candle and current in-progress candle."""
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Scanning LIVE MEXC spot market across top {top_n} altcoins...")
    collector = MexcCollector(delay=0.06)
    
    # Get active pairs sorted by 24h volume
    tickers = collector.fetch_24h_tickers()
    symbols_info = collector.fetch_spot_symbols()
    
    eligible = []
    for s in symbols_info:
        sym = s['symbol']
        if sym in ('BTCUSDT', 'ETHUSDT'):
            continue
        t = tickers.get(sym, {})
        vol = t.get('quoteVolume', 0.0)
        if vol >= 100_000:
            eligible.append((sym, vol, t.get('lastPrice', 0.0)))
            
    eligible.sort(key=lambda x: x[1], reverse=True)
    target_symbols = [x[0] for x in eligible[:top_n]]
    
    live_triggers = []
    pre_alert_candidates = [] # 3-hour pre-alerts
    
    now_ms = int(time.time() * 1000)
    
    for sym in target_symbols:
        # Fetch latest 60 4h candles
        df_4h = collector.fetch_klines_chunk(symbol=sym, interval="4h", limit=60)
        if len(df_4h) < 45:
            continue
            
        df = calculate_technical_features(df_4h)
        last_closed = df.iloc[-2] # Last completed 4h candle
        current_candle = df.iloc[-1] # Currently forming 4h candle
        
        # Check if last closed 4h bar triggered
        prior_7d_high = df['high'].iloc[-44 : -2].max()
        cond_base = (last_closed['range_7d_pct'] <= 35.0 or last_closed['bb_squeeze_rank'] >= 60)
        cond_vol = (last_closed['quote_volume'] >= 2.5 * last_closed['vol_ma20'])
        cond_break = (last_closed['close'] > last_closed['open'] and last_closed['close'] >= prior_7d_high * 0.98)
        
        if cond_base and cond_vol and cond_break:
            live_triggers.append({
                "symbol": sym,
                "status": "4H_CLOSED_TRIGGER",
                "candle_time": str(last_closed['datetime']),
                "price": last_closed['close'],
                "vol_surge": round(last_closed['quote_volume'] / (last_closed['vol_ma20'] + 1e-6), 2),
                "bb_squeeze": round(last_closed['bb_squeeze_rank'], 1),
                "7d_range": round(last_closed['range_7d_pct'], 1)
            })
            
        # Check current forming candle for 3-hour pre-alert:
        # If current 4h candle is in its 3rd or 4th hour and already has volume >= 2.0x of normal full bar
        prior_7d_high_curr = df['high'].iloc[-43 : -1].max()
        cond_base_curr = (current_candle['range_7d_pct'] <= 35.0 or current_candle['bb_squeeze_rank'] >= 60)
        cond_vol_curr = (current_candle['quote_volume'] >= 2.0 * current_candle['vol_ma20'])
        cond_break_curr = (current_candle['close'] > current_candle['open'] and current_candle['close'] >= prior_7d_high_curr * 0.98)
        
        if cond_base_curr and cond_vol_curr and cond_break_curr:
            pre_alert_candidates.append({
                "symbol": sym,
                "status": "PRE_ALERT_IN_PROGRESS",
                "candle_open_time": str(current_candle['datetime']),
                "current_price": current_candle['close'],
                "in_progress_vol_surge": round(current_candle['quote_volume'] / (current_candle['vol_ma20'] + 1e-6), 2),
                "bb_squeeze": round(current_candle['bb_squeeze_rank'], 1),
                "7d_range": round(current_candle['range_7d_pct'], 1)
            })
            
    return live_triggers, pre_alert_candidates

if __name__ == "__main__":
    # 1. Historical recent occurrences
    recent_df = find_recent_historical_triggers(days_back=12)
    print("\n" + "="*85)
    print("RECENT HISTORICAL OCCURRENCES IN OUR DATASET (LATE OCT - NOV 2026)")
    print("="*85)
    if not recent_df.empty:
        for _, r in recent_df.head(25).iterrows():
            gain_str = f"+{r['forward_gain_pct']}%" if r['forward_gain_pct'] > 0 else "0.0%"
            print(f"  {r['symbol']:12s} | Trigger: {r['trigger_time'][:16]} | Price: {r['trigger_price']:<10.4f} | Vol Surge: {r['quote_vol_surge']:4.1f}x | Squeeze: {r['bb_squeeze']:4.1f} | 72h Gain: {gain_str:<7s}")
    else:
        print("  No triggers in the specified window.")
        
    # 2. Live market scan
    live_trig, pre_alerts = scan_live_mexc_for_setups(top_n=100)
    print("\n" + "="*85)
    print("LIVE MEXC MARKET SCAN (RIGHT NOW)")
    print("="*85)
    print(f"Confirmed 4h Closed Triggers (Last 4h-8h): {len(live_trig)}")
    for t in live_trig:
        print(f"  [CONFIRMED 4H] {t['symbol']:12s} | Closed: {t['candle_time'][:16]} | Price: {t['price']} | Vol: {t['vol_surge']}x | Squeeze: {t['bb_squeeze']}")
        
    print(f"\n3-Hour Pre-Alert Candidates (Current Candle In-Progress): {len(pre_alerts)}")
    for p in pre_alerts:
        print(f"  [PRE-ALERT]    {p['symbol']:12s} | Started: {p['candle_open_time'][:16]} | Price: {p['current_price']} | Vol: {p['in_progress_vol_surge']}x | Squeeze: {p['bb_squeeze']}")
    print("="*85)
