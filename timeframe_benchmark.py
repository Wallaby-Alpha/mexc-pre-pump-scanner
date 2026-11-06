"""
Comprehensive Timeframe Benchmark:
Compares 1h Single, 1h Two-Consecutive, 4h Single, and Multi-Timeframe Confluence.
Evaluated across identical 75-coin universe over 72-hour forward holding windows.
"""

import numpy as np
import pandas as pd
from datetime import datetime
from database import get_connection, get_symbol_klines

def add_indicators_1h(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d['ema20'] = d['close'].ewm(span=20, adjust=False).mean()
    d['ema50'] = d['close'].ewm(span=50, adjust=False).mean()
    
    # BB (20, 2)
    rm = d['close'].rolling(20).mean()
    rstd = d['close'].rolling(20).std()
    d['bb_width'] = ((rm + 2*rstd) - (rm - 2*rstd)) / (rm + 1e-12)
    # Squeeze rank over 180 bars (7.5 days of 1h)
    d['bb_squeeze_rank'] = 100.0 - (d['bb_width'].rolling(180, min_periods=30).apply(
        lambda x: (x[-1] <= x).mean() * 100.0, raw=True
    ))
    
    # 7-day range (7 * 24 = 168 bars)
    roll_max_7d = d['high'].rolling(168).max()
    roll_min_7d = d['low'].rolling(168).min()
    d['range_7d_pct'] = ((roll_max_7d - roll_min_7d) / (roll_min_7d + 1e-12)) * 100.0
    
    d['vol_ma20'] = d['quote_volume'].rolling(20).mean()
    return d

def add_indicators_4h(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d['ema20'] = d['close'].ewm(span=20, adjust=False).mean()
    d['ema50'] = d['close'].ewm(span=50, adjust=False).mean()
    
    rm = d['close'].rolling(20).mean()
    rstd = d['close'].rolling(20).std()
    d['bb_width'] = ((rm + 2*rstd) - (rm - 2*rstd)) / (rm + 1e-12)
    d['bb_squeeze_rank'] = 100.0 - (d['bb_width'].rolling(180, min_periods=30).apply(
        lambda x: (x[-1] <= x).mean() * 100.0, raw=True
    ))
    
    # 7-day range (42 bars of 4h)
    roll_max_7d = d['high'].rolling(42).max()
    roll_min_7d = d['low'].rolling(42).min()
    d['range_7d_pct'] = ((roll_max_7d - roll_min_7d) / (roll_min_7d + 1e-12)) * 100.0
    
    d['vol_ma20'] = d['quote_volume'].rolling(20).mean()
    return d

def run_benchmark():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT DISTINCT symbol FROM klines_1h;")
    symbols = [r[0] for r in c.fetchall()]
    conn.close()
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Benchmarking timeframe variations across {len(symbols)} coins...")
    
    results = {
        "1. Single 1h Ignition (Fast Entry)": [],
        "2. Two Consecutive 1h Candles (Confirmed 1h)": [],
        "3. Single 4h Ignition (Hypothesis 5 Baseline)": [],
        "4. Two Consecutive 4h Candles (Confirmed 4h)": [],
        "5. Multi-TF (4h Base Squeeze + 1h Ignition Trigger)": []
    }
    
    unconditional_1h = []
    
    for sym in symbols:
        df1h_raw = get_symbol_klines(sym, table="klines_1h")
        df4h_raw = get_symbol_klines(sym, table="klines_4h")
        
        if len(df1h_raw) < 250 or len(df4h_raw) < 100:
            continue
            
        df1h = add_indicators_1h(df1h_raw)
        df4h = add_indicators_4h(df4h_raw)
        
        # Build timestamp map for fast multi-timeframe lookup
        df4h_indexed = df4h.set_index('timestamp')
        
        n1 = len(df1h)
        # Test 1h series
        for i in range(180, n1 - 72):
            r = df1h.iloc[i]
            r_prev = df1h.iloc[i-1]
            base_close = r['close']
            if base_close <= 0:
                continue
                
            # Forward 72-hour window (72 bars on 1h)
            fwd = df1h.iloc[i+1 : i+73]
            mfe = ((fwd['high'].max() - base_close) / base_close) * 100.0
            mae = ((fwd['low'].min() - base_close) / base_close) * 100.0
            
            outcome = {
                "symbol": sym,
                "time": r['datetime'],
                "mfe": mfe,
                "mae": mae,
                "is_pump_30": 1 if mfe >= 30.0 else 0,
                "is_pump_50": 1 if mfe >= 50.0 else 0
            }
            
            if i % 20 == 0:
                unconditional_1h.append(outcome)
                
            # Model 1: Single 1h Ignition
            prior_7d_high_1h = df1h['high'].iloc[i-168 : i].max()
            cond_base_1h = (r['range_7d_pct'] <= 35.0 or r['bb_squeeze_rank'] >= 60)
            cond_vol_1h = (r['quote_volume'] >= 2.5 * r['vol_ma20'])
            cond_break_1h = (r['close'] > r['open'] and r['close'] >= prior_7d_high_1h * 0.98)
            
            if cond_base_1h and cond_vol_1h and cond_break_1h:
                results["1. Single 1h Ignition (Fast Entry)"].append(outcome)
                
            # Model 2: Two Consecutive 1h Candles (Ignition + Confirmation)
            prev_7d_high = df1h['high'].iloc[i-169 : i-1].max()
            prev_ignited = (
                r_prev['quote_volume'] >= 2.0 * r_prev['vol_ma20'] and
                r_prev['close'] > r_prev['open'] and
                r_prev['close'] >= prev_7d_high * 0.98
            )
            curr_confirmed = (
                r['close'] > r_prev['close'] and 
                r['close'] > r['open'] and 
                r['quote_volume'] >= 1.5 * r['vol_ma20']
            )
            if cond_base_1h and prev_ignited and curr_confirmed:
                results["2. Two Consecutive 1h Candles (Confirmed 1h)"].append(outcome)
                
            # Model 5: Multi-TF (4h Base Squeeze + 1h Ignition)
            # Find the most recent closed 4h candle before this 1h candle
            ts_4h = (r['timestamp'] // (4 * 3600 * 1000)) * (4 * 3600 * 1000)
            if ts_4h in df4h_indexed.index:
                row_4h = df4h_indexed.loc[ts_4h]
                cond_4h_squeeze = (row_4h['bb_squeeze_rank'] >= 65 and row_4h['range_7d_pct'] <= 35.0)
                if cond_4h_squeeze and cond_vol_1h and cond_break_1h:
                    results["5. Multi-TF (4h Base Squeeze + 1h Ignition Trigger)"].append(outcome)
                    
        # Test 4h series
        n4 = len(df4h)
        for i in range(50, n4 - 18):
            r = df4h.iloc[i]
            r_prev = df4h.iloc[i-1]
            base_close = r['close']
            if base_close <= 0:
                continue
                
            fwd = df4h.iloc[i+1 : i+19]
            mfe = ((fwd['high'].max() - base_close) / base_close) * 100.0
            mae = ((fwd['low'].min() - base_close) / base_close) * 100.0
            
            outcome_4h = {
                "symbol": sym,
                "time": r['datetime'],
                "mfe": mfe,
                "mae": mae,
                "is_pump_30": 1 if mfe >= 30.0 else 0,
                "is_pump_50": 1 if mfe >= 50.0 else 0
            }
            
            prior_7d_high_4h = df4h['high'].iloc[i-42 : i].max()
            cond_base_4h = (r['range_7d_pct'] <= 35.0 or r['bb_squeeze_rank'] >= 60)
            cond_vol_4h = (r['quote_volume'] >= 2.5 * r['vol_ma20'])
            cond_break_4h = (r['close'] > r['open'] and r['close'] >= prior_7d_high_4h * 0.98)
            
            # Model 3: Single 4h Ignition
            if cond_base_4h and cond_vol_4h and cond_break_4h:
                results["3. Single 4h Ignition (Hypothesis 5 Baseline)"].append(outcome_4h)
                
            # Model 4: Two Consecutive 4h Candles
            prev_4h_high = df4h['high'].iloc[i-43 : i-1].max()
            prev_4h_ignited = (
                r_prev['quote_volume'] >= 2.0 * r_prev['vol_ma20'] and
                r_prev['close'] > r_prev['open'] and
                r_prev['close'] >= prev_4h_high * 0.98
            )
            curr_4h_confirmed = (
                r['close'] > r_prev['close'] and 
                r['close'] > r['open'] and 
                r['quote_volume'] >= 1.5 * r['vol_ma20']
            )
            if cond_base_4h and prev_4h_ignited and curr_4h_confirmed:
                results["4. Two Consecutive 4h Candles (Confirmed 4h)"].append(outcome_4h)

    print("\n" + "="*95)
    print("TIMEFRAME & MULTI-CANDLE COMBINATION COMPARISON")
    print("="*95)
    
    df_base = pd.DataFrame(unconditional_1h)
    base_p30 = df_base['is_pump_30'].mean() * 100.0
    base_p50 = df_base['is_pump_50'].mean() * 100.0
    
    print(f"Market Unconditional Baseline (Random Bars):  Pump >= 30%: {base_p30:.2f}% | Pump >= 50%: {base_p50:.2f}%\n")
    
    summary = []
    for model_name, triggers in results.items():
        if not triggers:
            continue
        df_t = pd.DataFrame(triggers)
        n_trig = len(df_t)
        p30 = df_t['is_pump_30'].mean() * 100.0
        p50 = df_t['is_pump_50'].mean() * 100.0
        edge30 = p30 / (base_p30 + 1e-6)
        med_mfe = df_t['mfe'].median()
        med_mae = df_t['mae'].median()
        rr = med_mfe / (abs(med_mae) + 1e-6)
        
        print(f"{model_name}:")
        print(f"  - Triggers Count:             {n_trig:,}")
        print(f"  - Probability of >= +30% Run: {p30:.2f}%  ({edge30:.2f}x Market Edge)")
        print(f"  - Probability of >= +50% Run: {p50:.2f}%")
        print(f"  - Median 72h Upside (MFE):    +{med_mfe:.1f}%")
        print(f"  - Median 72h Drawdown (MAE):  {med_mae:.1f}%")
        print(f"  - Reward / Risk Ratio:        {rr:.2f}x\n")
        
        summary.append({
            "model": model_name,
            "triggers": n_trig,
            "pump30_pct": round(p30, 2),
            "pump50_pct": round(p50, 2),
            "edge": round(edge30, 2),
            "median_mfe": round(med_mfe, 1),
            "median_mae": round(med_mae, 1),
            "reward_to_risk": round(rr, 2)
        })
        
    print("="*95)
    from config import DATA_DIR
    pd.DataFrame(summary).to_csv(DATA_DIR / "timeframe_comparison.csv", index=False)

if __name__ == "__main__":
    run_benchmark()
