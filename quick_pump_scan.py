"""
Quick scan of historical pump events across the downloaded 97,863 candles.
"""
import pandas as pd
from database import get_connection, get_all_symbols, get_symbol_klines

def scan_historical_pumps():
    symbols = get_all_symbols()
    print(f"Scanning {len(symbols)} altcoins for major historical pumps...")
    
    # Define pump criteria on 4h candles:
    # A pump is defined as: within 12 candles (48 hours), max price reaches >= +40% from base
    pumps_40 = []
    pumps_60 = []
    pumps_100 = []
    
    for sym in symbols:
        df = get_symbol_klines(sym)
        if len(df) < 50:
            continue
            
        # Scan rolling 12 bars (48h) forward return from close
        closes = df['close'].values
        highs = df['high'].values
        timestamps = df['datetime'].values
        
        n = len(df)
        i = 20 # Leave room for pre-pump lookback
        while i < n - 12:
            base_price = closes[i]
            # Max high over the next 12 candles (48 hours)
            forward_highs = highs[i+1 : i+13]
            max_forward_high = forward_highs.max()
            gain_pct = ((max_forward_high - base_price) / base_price) * 100.0
            
            if gain_pct >= 40.0:
                peak_idx = i + 1 + forward_highs.argmax()
                pumps_40.append({
                    "symbol": sym,
                    "ignition_time": str(timestamps[i]),
                    "peak_time": str(timestamps[peak_idx]),
                    "gain_pct": gain_pct,
                    "bars_to_peak": int(peak_idx - i)
                })
                if gain_pct >= 60.0:
                    pumps_60.append(pumps_40[-1])
                if gain_pct >= 100.0:
                    pumps_100.append(pumps_40[-1])
                    
                # Skip forward past peak to avoid double-counting the same pump wave
                i = peak_idx + 6
            else:
                i += 1
                
    print(f"\n--- PUMP DETECTION RESULTS (July 2026 - Nov 2026) ---")
    print(f"Total >= +40% Pumps in 48h: {len(pumps_40)}")
    print(f"Total >= +60% Pumps in 48h: {len(pumps_60)}")
    print(f"Total >= +100% Pumps in 48h: {len(pumps_100)}")
    
    # Sort by gain descending
    pumps_40.sort(key=lambda x: x["gain_pct"], reverse=True)
    print("\nTop 10 Biggest Pumps Detected:")
    for p in pumps_40[:10]:
        print(f"  {p['symbol']:12s} | +{p['gain_pct']:6.1f}% | Ignition: {p['ignition_time'][:16]} | Peak: {p['peak_time'][:16]} ({p['bars_to_peak']*4}h)")

if __name__ == "__main__":
    scan_historical_pumps()
