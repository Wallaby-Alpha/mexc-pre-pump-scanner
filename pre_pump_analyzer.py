"""
Pre-Pump Feature Analyzer (Step C: Inductive / Reverse Pattern Discovery).

Analyzes the pre-ignition window (T-24h to T-7d) of all historical major pumps
to discover empirical statistical signatures across volume, volatility compression,
moving average positioning, and consolidation structure.
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Any
from datetime import datetime
from database import get_all_symbols, get_symbol_klines, get_connection
from config import DATA_DIR

def calculate_technical_features(df: pd.DataFrame) -> pd.DataFrame:
    """Calculates rolling quantitative indicators on 4h klines."""
    d = df.copy()
    
    # Moving Averages
    d['ema20'] = d['close'].ewm(span=20, adjust=False).mean()
    d['ema50'] = d['close'].ewm(span=50, adjust=False).mean()
    
    # Bollinger Bands (20, 2)
    rolling_mean = d['close'].rolling(window=20).mean()
    rolling_std = d['close'].rolling(window=20).std()
    d['bb_upper'] = rolling_mean + (2 * rolling_std)
    d['bb_lower'] = rolling_mean - (2 * rolling_std)
    d['bb_width'] = (d['bb_upper'] - d['bb_lower']) / (rolling_mean + 1e-12)
    
    # 60-day (360 bars of 4h) BB Width Percentile (Squeeze Rank)
    d['bb_width_percentile'] = d['bb_width'].rolling(window=180, min_periods=30).apply(
        lambda x: (x[-1] <= x).mean() * 100.0, raw=True
    )
    # The above gives percentile where 0 is tightest squeeze and 100 is widest
    d['bb_squeeze_rank'] = 100.0 - d['bb_width_percentile'] # 0 = wide, 100 = tightest
    
    # Average True Range (ATR 14)
    tr1 = d['high'] - d['low']
    tr2 = (d['high'] - d['close'].shift(1)).abs()
    tr3 = (d['low'] - d['close'].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    d['atr14'] = tr.rolling(window=14).mean()
    d['atr_pct'] = (d['atr14'] / (d['close'] + 1e-12)) * 100.0
    
    # Volume Baselines
    d['vol_ma20'] = d['quote_volume'].rolling(window=20).mean()
    d['vol_ma180'] = d['quote_volume'].rolling(window=180, min_periods=30).mean() # ~30-day baseline
    
    # Rolling 7-day (42 bars) price range %
    roll_max_7d = d['high'].rolling(window=42).max()
    roll_min_7d = d['low'].rolling(window=42).min()
    d['range_7d_pct'] = ((roll_max_7d - roll_min_7d) / (roll_min_7d + 1e-12)) * 100.0
    
    # Rolling 30-day price trend %
    d['trend_30d_pct'] = ((d['close'] - d['close'].shift(180)) / (d['close'].shift(180) + 1e-12)) * 100.0

    return d

def analyze_all_pumps():
    symbols = get_all_symbols()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Step C: Extracting pre-pump features across {len(symbols)} coins...")
    
    pump_features = []
    
    for sym in symbols:
        df_raw = get_symbol_klines(sym)
        if len(df_raw) < 180: # Need sufficient warm-up for 30-day indicators
            continue
            
        df = calculate_technical_features(df_raw)
        
        closes = df['close'].values
        highs = df['high'].values
        timestamps = df['datetime'].values
        n = len(df)
        
        # Scan forward for pumps
        i = 60 # Ensure warm-up history
        while i < n - 12:
            base_price = closes[i]
            forward_highs = highs[i+1 : i+13]
            max_forward_high = forward_highs.max()
            gain_pct = ((max_forward_high - base_price) / base_price) * 100.0
            
            if gain_pct >= 40.0:
                peak_idx = i + 1 + forward_highs.argmax()
                
                # Pre-pump feature extraction at T_0 (bar i) and immediate preceding bars
                prior_bar = df.iloc[i-1]
                t0_bar = df.iloc[i]
                
                # Pre-pump volume ratios
                vol_24h_prior = df['quote_volume'].iloc[max(0, i-6):i].sum()
                vol_baseline_24h = (df['vol_ma180'].iloc[i] * 6) if df['vol_ma180'].iloc[i] > 0 else 1.0
                vol_ratio_24h = vol_24h_prior / (vol_baseline_24h + 1e-6)
                
                # Single bar pre-ignition volume spike (T-1)
                t_minus_1_vol_surge = prior_bar['quote_volume'] / (prior_bar['vol_ma20'] + 1e-6)
                
                # Volatility compression metrics at T_0
                bb_squeeze = t0_bar['bb_squeeze_rank']
                atr_pct = t0_bar['atr_pct']
                range_7d = t0_bar['range_7d_pct']
                
                # Moving Average relationships at T_0
                dist_ema20_pct = ((t0_bar['close'] - t0_bar['ema20']) / t0_bar['ema20']) * 100.0
                dist_ema50_pct = ((t0_bar['close'] - t0_bar['ema50']) / t0_bar['ema50']) * 100.0
                ema_alignment = 1 if t0_bar['ema20'] > t0_bar['ema50'] else 0
                
                # Check if reclaimed EMA50 recently (closed above EMA50 at T0 after being below)
                ema50_reclaim = 1 if (t0_bar['close'] >= t0_bar['ema50'] and df['close'].iloc[i-3:i].min() < df['ema50'].iloc[i-3:i].min()) else 0
                
                # Prior 30-day macro trend
                trend_30d = t0_bar['trend_30d_pct']
                
                pump_features.append({
                    "symbol": sym,
                    "ignition_time": str(timestamps[i]),
                    "gain_pct": round(gain_pct, 1),
                    "bars_to_peak": int(peak_idx - i),
                    "hours_to_peak": int((peak_idx - i) * 4),
                    # Volume Precursors
                    "pre_vol_ratio_24h": round(vol_ratio_24h, 2),
                    "t_minus_1_vol_surge": round(t_minus_1_vol_surge, 2),
                    "pre_24h_quote_usd": round(vol_24h_prior, 0),
                    # Volatility Compression
                    "bb_squeeze_rank": round(bb_squeeze, 1),
                    "atr_pct": round(atr_pct, 2),
                    "range_7d_pct": round(range_7d, 1),
                    # Moving Averages
                    "dist_ema20_pct": round(dist_ema20_pct, 2),
                    "dist_ema50_pct": round(dist_ema50_pct, 2),
                    "bullish_ema_cross": ema_alignment,
                    "ema50_reclaim": ema50_reclaim,
                    "trend_30d_pct": round(trend_30d, 1)
                })
                
                i = peak_idx + 6 # Jump past pump
            else:
                i += 1
                
    feat_df = pd.DataFrame(pump_features)
    out_csv = DATA_DIR / "pre_pump_features.csv"
    feat_df.to_csv(out_csv, index=False)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Saved feature matrix to {out_csv} ({len(feat_df)} pumps analyzed)")
    
    # Statistical Profile
    print("\n" + "="*70)
    print("EMPIRICAL PRE-PUMP FOOTPRINT (STEP C FINDINGS)")
    print("="*70)
    
    print("\n1. VOLATILITY COMPRESSION AT IGNITION:")
    print(f"  - 7-Day Price Range (Median): {feat_df['range_7d_pct'].median():.1f}% (IQR: {feat_df['range_7d_pct'].quantile(0.25):.1f}% - {feat_df['range_7d_pct'].quantile(0.75):.1f}%)")
    print(f"  - BB Squeeze Rank (Median):   {feat_df['bb_squeeze_rank'].median():.1f}/100 (Tight squeeze >= 70 in {(feat_df['bb_squeeze_rank'] >= 70).mean()*100:.1f}% of cases)")
    print(f"  - ATR % (Median):            {feat_df['atr_pct'].median():.2f}% of price")
    
    print("\n2. VOLUME ANOMALIES PRIOR TO IGNITION:")
    print(f"  - 24h Pre-Ignition Vol vs 30d Baseline (Median): {feat_df['pre_vol_ratio_24h'].median():.2f}x")
    print(f"  - Volume >= 1.5x baseline in pre-24h:             {(feat_df['pre_vol_ratio_24h'] >= 1.5).mean()*100:.1f}% of pumps")
    print(f"  - Volume >= 2.0x baseline in pre-24h:             {(feat_df['pre_vol_ratio_24h'] >= 2.0).mean()*100:.1f}% of pumps")
    print(f"  - T-1 Immediate Precursor Bar Volume Surge:      {feat_df['t_minus_1_vol_surge'].median():.2f}x over MA20")
    
    print("\n3. MOVING AVERAGE & TREND POSITION:")
    print(f"  - Price vs 20 EMA at Ignition (Median):          {feat_df['dist_ema20_pct'].median():+.2f}%")
    print(f"  - Price vs 50 EMA at Ignition (Median):          {feat_df['dist_ema50_pct'].median():+.2f}%")
    print(f"  - EMA20 > EMA50 (Bullish Alignment):             {(feat_df['bullish_ema_cross'] == 1).mean()*100:.1f}% of pumps")
    print(f"  - Fresh EMA50 Reclaim Setup:                     {(feat_df['ema50_reclaim'] == 1).mean()*100:.1f}% of pumps")
    print(f"  - 30-Day Pre-Base Trend (Median):                {feat_df['trend_30d_pct'].median():+.1f}%")
    
    print("="*70)
    return feat_df

if __name__ == "__main__":
    analyze_all_pumps()
