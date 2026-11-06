"""
Step D: Specificity & False Positive Matrix Analyzer.

Compares candidate pre-pump setups against normal non-pumping bars across all 97,000+ candles.
Computes:
1. Signal Frequency (how often the setup triggers in normal market conditions)
2. Win Rate / Pump Probability: P(Pump >= 30% | Signal)
3. Median Forward Gain (MFE) vs Median Max Drawdown (MAE) over 48h to 7 days
4. False Discovery Rate
"""

import numpy as np
import pandas as pd
from datetime import datetime
from database import get_all_symbols, get_symbol_klines
from pre_pump_analyzer import calculate_technical_features
from config import DATA_DIR

def evaluate_hypotheses_and_specificity():
    symbols = get_all_symbols()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Step D: Running Specificity & Forward Evaluation across market...")
    
    # We will test 4 distinct rule-based candidate setups:
    # Setup 1: Volatility Squeeze at MA (BB Squeeze Rank >= 70, Price within 2.5% of 20 EMA, EMA20 > EMA50)
    # Setup 2: Stealth Accumulation (Pre-24h Volume >= 1.75x baseline, 7-day Range <= 25%, Price > EMA50)
    # Setup 3: Tight Base Breakout Readiness (BB Squeeze Rank >= 75, ATR% <= 6.0%, Price > EMA20)
    # Setup 4: Pure Relative Compression (BB Squeeze Rank >= 80, 7-day Range <= 20%)
    
    setups = {
        "Setup 1 (Coiled Trend: BB Squeeze >= 70 + EMA20 > EMA50 + Near EMA20)": [],
        "Setup 2 (Stealth Accumulation: Vol >= 1.75x + Range <= 25% + > EMA50)": [],
        "Setup 3 (Low ATR Compression: BB Squeeze >= 75 + ATR% <= 6% + > EMA20)": [],
        "Setup 4 (Extreme Tight Base: BB Squeeze >= 80 + 7d Range <= 20%)": []
    }
    
    # Also collect unconditional baseline (all random active bars)
    unconditional_outcomes = []
    
    for sym in symbols:
        df_raw = get_symbol_klines(sym)
        if len(df_raw) < 180:
            continue
            
        df = calculate_technical_features(df_raw)
        n = len(df)
        
        # Test signals on bar i, evaluate forward outcomes over next 18 bars (72 hours / 3 days)
        for i in range(100, n - 18):
            row = df.iloc[i]
            base_close = row['close']
            if base_close <= 0:
                continue
                
            # Forward 72-hour window outcomes
            forward_bars = df.iloc[i+1 : i+19]
            max_high = forward_bars['high'].max()
            min_low = forward_bars['low'].min()
            
            mfe_pct = ((max_high - base_close) / base_close) * 100.0 # Max Favorable Excursion
            mae_pct = ((min_low - base_close) / base_close) * 100.0  # Max Adverse Excursion (Drawdown)
            is_pump_30 = 1 if mfe_pct >= 30.0 else 0
            is_pump_50 = 1 if mfe_pct >= 50.0 else 0
            
            outcome = {
                "symbol": sym,
                "time": row['datetime'],
                "mfe_pct": mfe_pct,
                "mae_pct": mae_pct,
                "is_pump_30": is_pump_30,
                "is_pump_50": is_pump_50
            }
            
            # Subsample 5% of unconditional bars for fast baseline
            if i % 10 == 0:
                unconditional_outcomes.append(outcome)
                
            # Check Setup 1
            dist_ema20 = abs(row['close'] - row['ema20']) / row['ema20'] * 100.0
            if (row['bb_squeeze_rank'] >= 70 and row['ema20'] > row['ema50'] and dist_ema20 <= 2.5):
                setups["Setup 1 (Coiled Trend: BB Squeeze >= 70 + EMA20 > EMA50 + Near EMA20)"].append(outcome)
                
            # Check Setup 2
            vol_24h_prior = df['quote_volume'].iloc[max(0, i-6):i].sum()
            vol_baseline_24h = (row['vol_ma180'] * 6) if row['vol_ma180'] > 0 else 1.0
            vol_ratio = vol_24h_prior / (vol_baseline_24h + 1e-6)
            if (vol_ratio >= 1.75 and row['range_7d_pct'] <= 25.0 and row['close'] > row['ema50']):
                setups["Setup 2 (Stealth Accumulation: Vol >= 1.75x + Range <= 25% + > EMA50)"].append(outcome)
                
            # Check Setup 3
            if (row['bb_squeeze_rank'] >= 75 and row['atr_pct'] <= 6.0 and row['close'] > row['ema20']):
                setups["Setup 3 (Low ATR Compression: BB Squeeze >= 75 + ATR% <= 6% + > EMA20)"].append(outcome)
                
            # Check Setup 4
            if (row['bb_squeeze_rank'] >= 80 and row['range_7d_pct'] <= 20.0):
                setups["Setup 4 (Extreme Tight Base: BB Squeeze >= 80 + 7d Range <= 20%)"].append(outcome)

    print("\n" + "="*85)
    print("SPECIFICITY & FALSE POSITIVE BENCHMARK (STEP D RESULTS)")
    print("="*85)
    
    # 0. Unconditional Baseline
    df_base = pd.DataFrame(unconditional_outcomes)
    base_pump30_rate = df_base['is_pump_30'].mean() * 100.0
    base_pump50_rate = df_base['is_pump_50'].mean() * 100.0
    base_mfe = df_base['mfe_pct'].median()
    base_mae = df_base['mae_pct'].median()
    
    print(f"MARKET UNCONDITIONAL BASELINE (Random Bar Selection across 150 Altcoins):")
    print(f"  - Total Sample Bars:      {len(df_base):,}")
    print(f"  - Base Prob of >= +30% in 72h:  {base_pump30_rate:.2f}%")
    print(f"  - Base Prob of >= +50% in 72h:  {base_pump50_rate:.2f}%")
    print(f"  - Median 72h MFE (Upside):      +{base_mfe:.1f}%")
    print(f"  - Median 72h MAE (Drawdown):    {base_mae:.1f}%")
    print("-" * 85)
    
    summary_rows = []
    
    for name, triggers in setups.items():
        if not triggers:
            continue
        df_trig = pd.DataFrame(triggers)
        n_triggers = len(df_trig)
        pump30_rate = df_trig['is_pump_30'].mean() * 100.0
        pump50_rate = df_trig['is_pump_50'].mean() * 100.0
        med_mfe = df_trig['mfe_pct'].median()
        med_mae = df_trig['mae_pct'].median()
        edge_multiplier_30 = pump30_rate / (base_pump30_rate + 1e-6)
        
        # Risk/Reward Ratio: Median Upside / |Median Drawdown|
        rr_ratio = med_mfe / (abs(med_mae) + 1e-6)
        
        print(f"\n{name}:")
        print(f"  - Total Signals Triggered:      {n_triggers:,}")
        print(f"  - Probability of >= +30% Pump:  {pump30_rate:.2f}%  ({edge_multiplier_30:.2f}x Market Baseline Edge)")
        print(f"  - Probability of >= +50% Pump:  {pump50_rate:.2f}%")
        print(f"  - Median 72h Upside (MFE):      +{med_mfe:.1f}%")
        print(f"  - Median 72h Drawdown (MAE):    {med_mae:.1f}%")
        print(f"  - Upside / Drawdown Ratio:      {rr_ratio:.2f}x")
        
        summary_rows.append({
            "setup_name": name,
            "triggers": n_triggers,
            "pump30_pct": round(pump30_rate, 2),
            "pump50_pct": round(pump50_rate, 2),
            "edge_vs_baseline": round(edge_multiplier_30, 2),
            "median_mfe": round(med_mfe, 1),
            "median_mae": round(med_mae, 1),
            "reward_to_risk": round(rr_ratio, 2)
        })
        
    print("="*85)
    
    # Save summary
    res_df = pd.DataFrame(summary_rows)
    res_df.to_csv(DATA_DIR / "specificity_comparison.csv", index=False)
    print(f"Saved specificity comparison to {DATA_DIR / 'specificity_comparison.csv'}")

if __name__ == "__main__":
    evaluate_hypotheses_and_specificity()
