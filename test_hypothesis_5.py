"""
Test Hypothesis 5: Compression Base + Fresh Ignition Breakout Bar.
Does waiting for the first 4h ignition expansion bar turn the edge from 1.0x to 3x-5x?
"""
import pandas as pd
from database import get_all_symbols, get_symbol_klines
from pre_pump_analyzer import calculate_technical_features

def test_ignition_breakout():
    symbols = get_all_symbols()
    print("Testing Hypothesis 5: Compression Base + Fresh Ignition Breakout Bar...")
    
    triggers = []
    
    for sym in symbols:
        df_raw = get_symbol_klines(sym)
        if len(df_raw) < 180:
            continue
            
        df = calculate_technical_features(df_raw)
        n = len(df)
        
        for i in range(100, n - 18):
            row = df.iloc[i]
            prior_bars = df.iloc[i-6 : i] # Prior 24h
            
            # Condition 1: Prior base was in compression (prior 7-day range <= 35% or BB squeeze rank >= 60)
            base_compressed = (row['range_7d_pct'] <= 35.0 or row['bb_squeeze_rank'] >= 60)
            
            # Condition 2: Fresh Volume Expansion on current bar (Volume >= 2.5x the 20-bar MA)
            vol_expansion = (row['quote_volume'] >= 2.5 * row['vol_ma20'])
            
            # Condition 3: Bullish expansion bar (close > open, and close > 20 EMA, close breaks above 7d prior high)
            prior_7d_high = df['high'].iloc[i-42 : i].max()
            price_breakout = (row['close'] > row['open'] and row['close'] >= prior_7d_high * 0.98)
            
            if base_compressed and vol_expansion and price_breakout:
                base_close = row['close']
                forward_bars = df.iloc[i+1 : i+19]
                max_high = forward_bars['high'].max()
                min_low = forward_bars['low'].min()
                
                mfe_pct = ((max_high - base_close) / base_close) * 100.0
                mae_pct = ((min_low - base_close) / base_close) * 100.0
                
                triggers.append({
                    "symbol": sym,
                    "time": row['datetime'],
                    "mfe_pct": mfe_pct,
                    "mae_pct": mae_pct,
                    "is_pump_30": 1 if mfe_pct >= 30.0 else 0,
                    "is_pump_50": 1 if mfe_pct >= 50.0 else 0
                })
                
    df_res = pd.DataFrame(triggers)
    print(f"\n--- HYPOTHESIS 5 RESULTS: COMPRESSION BASE + IGNITION BREAKOUT ---")
    print(f"Total Signals Triggered:        {len(df_res):,}")
    print(f"Probability of >= +30% Run:     {df_res['is_pump_30'].mean()*100:.2f}% (vs 5.95% baseline -> {df_res['is_pump_30'].mean()*100 / 5.95:.2f}x EDGE)")
    print(f"Probability of >= +50% Run:     {df_res['is_pump_50'].mean()*100:.2f}% (vs 2.84% baseline -> {df_res['is_pump_50'].mean()*100 / 2.84:.2f}x EDGE)")
    print(f"Median 72h Upside (MFE):        +{df_res['mfe_pct'].median():.1f}%")
    print(f"Median 72h Drawdown (MAE):      {df_res['mae_pct'].median():.1f}%")
    print(f"Upside / Drawdown Ratio:        {df_res['mfe_pct'].median() / abs(df_res['mae_pct'].median()):.2f}x")

if __name__ == "__main__":
    test_ignition_breakout()
