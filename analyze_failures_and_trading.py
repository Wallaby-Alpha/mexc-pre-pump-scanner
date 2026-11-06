"""
Anatomy of Failed Setups & Trade Execution Optimization.
Analyzes:
1. Specific coins that triggered the setup but failed to pump.
2. Distinct characteristics of failures vs winners (wick ratios, volume magnitude, drawdown).
3. Trade management models: Stop-loss placement, take-profit scaling, and profit factor.
"""

import pandas as pd
import numpy as np
from database import get_all_symbols, get_symbol_klines
from pre_pump_analyzer import calculate_technical_features
from config import DATA_DIR

def analyze_failures_and_execution():
    symbols = get_all_symbols("klines_4h")
    print("Analyzing all historical setup triggers, separating winners vs failures...")
    
    triggers = []
    
    for sym in symbols:
        df_raw = get_symbol_klines(sym, table="klines_4h")
        if len(df_raw) < 100:
            continue
            
        df = calculate_technical_features(df_raw)
        n = len(df)
        
        for i in range(50, n - 18):
            row = df.iloc[i]
            
            # Setup conditions
            cond_base = (row['range_7d_pct'] <= 35.0 or row['bb_squeeze_rank'] >= 60)
            cond_vol = (row['quote_volume'] >= 2.5 * row['vol_ma20'])
            prior_7d_high = df['high'].iloc[max(0, i-42) : i].max()
            cond_break = (row['close'] > row['open'] and row['close'] >= prior_7d_high * 0.98)
            
            if cond_base and cond_vol and cond_break:
                entry_price = row['close']
                ignition_low = row['low']
                ignition_high = row['high']
                candle_range = ignition_high - ignition_low
                body = row['close'] - row['open']
                upper_wick = ignition_high - row['close']
                upper_wick_ratio = upper_wick / (candle_range + 1e-12)
                
                # Forward 72 hours (18 bars)
                forward = df.iloc[i+1 : i+19]
                max_high = forward['high'].max()
                min_low = forward['low'].min()
                mfe_pct = ((max_high - entry_price) / entry_price) * 100.0
                mae_pct = ((min_low - entry_price) / entry_price) * 100.0
                close_72h_pct = ((forward.iloc[-1]['close'] - entry_price) / entry_price) * 100.0
                
                is_win_30 = 1 if mfe_pct >= 30.0 else 0
                is_failure = 1 if mfe_pct < 10.0 else 0
                
                triggers.append({
                    "symbol": sym,
                    "date": str(row['datetime']),
                    "entry_price": entry_price,
                    "ignition_low": ignition_low,
                    "ignition_risk_pct": ((entry_price - ignition_low) / entry_price) * 100.0,
                    "mfe_pct": round(mfe_pct, 1),
                    "mae_pct": round(mae_pct, 1),
                    "close_72h_pct": round(close_72h_pct, 1),
                    "vol_surge": round(row['quote_volume'] / (row['vol_ma20'] + 1e-6), 2),
                    "bb_squeeze": round(row['bb_squeeze_rank'], 1),
                    "7d_range": round(row['range_7d_pct'], 1),
                    "upper_wick_ratio": round(upper_wick_ratio, 2),
                    "is_win_30": is_win_30,
                    "is_failure": is_failure
                })
                
    df_all = pd.DataFrame(triggers)
    
    print("\n" + "="*85)
    print("1. SUMMARY OF TRIGGERS: WINNERS VS FAILURES")
    print("="*85)
    total_triggers = len(df_all)
    winners = df_all[df_all['is_win_30'] == 1]
    failures = df_all[df_all['is_failure'] == 1]
    modest = df_all[(df_all['mfe_pct'] >= 10.0) & (df_all['mfe_pct'] < 30.0)]
    
    print(f"Total Triggers:                  {total_triggers}")
    print(f"Big Pumps (>= +30% to +900%):    {len(winners)} ({len(winners)/total_triggers*100:.1f}%)")
    print(f"Modest Moves (+10% to +30%):     {len(modest)} ({len(modest)/total_triggers*100:.1f}%)")
    print(f"Failures / Duds (< +10% gain):   {len(failures)} ({len(failures)/total_triggers*100:.1f}%)")
    
    print("\n" + "-"*85)
    print("RECENT NOTABLE FAILED SETUPS (What Happened When They Didn't Pump)")
    print("-" * 85)
    # Filter failures from late October / November
    recent_failures = failures.sort_values(by="date", ascending=False).head(12)
    for _, r in recent_failures.iterrows():
        print(f"  {r['symbol']:12s} | Trigger: {r['date'][:16]} | Price: {r['entry_price']:<9.4f} | Max Upside: +{r['mfe_pct']:4.1f}% | Max Drawdown: {r['mae_pct']:4.1f}% | Upper Wick: {r['upper_wick_ratio']*100:.0f}%")
        
    print("\n" + "="*85)
    print("2. ANATOMY: WHAT DISTINGUISHES WINNERS FROM FAILURES?")
    print("="*85)
    print(f"  Metric                         Big Winners (>=30%)     Failures (<10%)")
    print(f"  ------------------------------------------------------------------------")
    print(f"  Median 72h Drawdown:           {winners['mae_pct'].median():.1f}%                 {failures['mae_pct'].median():.1f}%")
    print(f"  Median Vol Surge:              {winners['vol_surge'].median():.1f}x                 {failures['vol_surge'].median():.1f}x")
    print(f"  Upper Wick Ratio:              {winners['upper_wick_ratio'].median()*100:.1f}%                 {failures['upper_wick_ratio'].median()*100:.1f}%")
    print(f"  Candle Squeeze Rank:           {winners['bb_squeeze'].median():.1f}                  {failures['bb_squeeze'].median():.1f}")
    print(f"  Pre-Ignition 7d Range:         {winners['7d_range'].median():.1f}%                 {failures['7d_range'].median():.1f}%")
    
    print("\n" + "="*85)
    print("3. TRADE EXECUTION OPTIMIZATION (HOW TO TRADE THIS FOR MAXIMUM EXPECTANCY)")
    print("="*85)
    
    # Simulate 3 execution rules across all triggers:
    # Rule A: Fixed Stop Loss at Low of Ignition Candle, Target 2.5R
    # Rule B: Fixed -6% Stop Loss, Target +25% Take Profit (1:4 R:R)
    # Rule C: Dynamic Asymmetric Management:
    #         Stop Loss: -6% (or candle low, whichever is tighter).
    #         Scale Out: Take 50% profit at +15%, move stop to breakeven, let 50% ride with 4h 20EMA trailing stop.
    
    def simulate_strategy_b(sl_pct=6.0, tp_pct=25.0):
        pnl = []
        for _, r in df_all.iterrows():
            # If hit SL first:
            if r['mae_pct'] <= -sl_pct:
                pnl.append(-sl_pct)
            elif r['mfe_pct'] >= tp_pct:
                pnl.append(tp_pct)
            else:
                pnl.append(r['close_72h_pct'])
        s = pd.Series(pnl)
        win_rate = (s > 0).mean() * 100
        gross_profit = s[s > 0].sum()
        gross_loss = abs(s[s < 0].sum())
        profit_factor = gross_profit / (gross_loss + 1e-6)
        return win_rate, s.mean(), profit_factor
        
    def simulate_strategy_ignition_low(r_target=2.5):
        pnl = []
        for _, r in df_all.iterrows():
            risk = min(max(r['ignition_risk_pct'], 3.0), 10.0) # Cap risk between 3% and 10%
            target = risk * r_target
            if r['mae_pct'] <= -risk:
                pnl.append(-risk)
            elif r['mfe_pct'] >= target:
                pnl.append(target)
            else:
                pnl.append(r['close_72h_pct'])
        s = pd.Series(pnl)
        win_rate = (s > 0).mean() * 100
        profit_factor = s[s > 0].sum() / (abs(s[s < 0].sum()) + 1e-6)
        return win_rate, s.mean(), profit_factor

    wr_b, exp_b, pf_b = simulate_strategy_b(sl_pct=6.0, tp_pct=25.0)
    wr_c, exp_c, pf_c = simulate_strategy_ignition_low(r_target=2.5)
    
    print(f"Strategy Model A: Fixed -6% Stop-Loss / +25% Target (1:4 Risk/Reward)")
    print(f"  - Win Rate:               {wr_b:.1f}%")
    print(f"  - Expectancy per Trade:   +{exp_b:.2f}%")
    print(f"  - Profit Factor:          {pf_b:.2f}")
    
    print(f"\nStrategy Model B: Ignition Candle Low Stop-Loss / 2.5R Asymmetric Target")
    print(f"  - Win Rate:               {wr_c:.1f}%")
    print(f"  - Expectancy per Trade:   +{exp_c:.2f}%")
    print(f"  - Profit Factor:          {pf_c:.2f}")
    print("="*85)

if __name__ == "__main__":
    analyze_failures_and_execution()
