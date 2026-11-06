"""
6-Month Complete Backtest of the Pre-Pump Asymmetric Scaling Strategy.
Period: May 10, 2026 - November 6, 2026 (143,707 candles, 150 altcoins + BTC).

Rules:
1. Entry: 4h close when Squeeze Rank >= 80, 7d Range <= 35%, Volume >= 2.5x MA20, Close > Open, Close >= 0.98 * 7d High.
2. Market Filter: BTC 4h Close > BTC 4h 20 EMA.
3. Stop Loss: -6.0% below entry (or low of ignition candle if tighter).
4. Scale 1: Sell 40% at +18% gain -> Stop on remaining 60% moved to Breakeven (0.0%).
5. Scale 2: Sell 30% at +45% gain.
6. Scale 3: Trailing 30% runner until 4h candle closes below 20 EMA (max 14 days).
"""

import pandas as pd
import numpy as np
from datetime import datetime
from database import get_connection, get_symbol_klines
from pre_pump_analyzer import calculate_technical_features
from config import DATA_DIR

def run_6m_backtest():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Preparing 6-Month Backtest Engine...")
    
    # 1. Load and compute indicators for BTCUSDT
    df_btc = get_symbol_klines("BTCUSDT", table="klines_4h")
    df_btc['btc_ema20'] = df_btc['close'].ewm(span=20, adjust=False).mean()
    btc_map = {}
    for _, row in df_btc.iterrows():
        # BTC filter is Bullish if BTC Close >= BTC EMA20
        btc_map[int(row['timestamp'])] = bool(row['close'] >= row['btc_ema20'])
        
    print(f"BTC filter mapped across {len(btc_map)} 4h periods.")
    
    # 2. Get list of altcoins
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT DISTINCT symbol FROM klines_4h WHERE symbol != 'BTCUSDT' ORDER BY symbol ASC;")
    symbols = [r[0] for r in c.fetchall()]
    conn.close()
    
    print(f"Scanning {len(symbols)} altcoins over 180 days...")
    
    def simulate_trades(use_btc_filter=True, target_scale1=18.0, target_scale2=45.0, sl_cap=6.0):
        trades = []
        
        for sym in symbols:
            df_raw = get_symbol_klines(sym, table="klines_4h")
            if len(df_raw) < 180:
                continue
                
            df = calculate_technical_features(df_raw)
            n = len(df)
            
            i = 60
            while i < n - 20:
                row = df.iloc[i]
                ts = int(row['timestamp'])
                
                # Check BTC filter
                if use_btc_filter:
                    btc_ok = btc_map.get(ts, True)
                    if not btc_ok:
                        i += 1
                        continue
                        
                # Setup Conditions
                cond_base = (row['range_7d_pct'] <= 35.0 and row['bb_squeeze_rank'] >= 80)
                cond_vol = (row['quote_volume'] >= 2.5 * row['vol_ma20'])
                prior_7d_high = df['high'].iloc[max(0, i-42) : i].max()
                cond_break = (row['close'] > row['open'] and row['close'] >= prior_7d_high * 0.98)
                
                if cond_base and cond_vol and cond_break:
                    entry_price = row['close']
                    ignition_low = row['low']
                    
                    # Risk calculation
                    risk_pct = ((entry_price - ignition_low) / entry_price) * 100.0
                    stop_loss_pct = min(risk_pct, sl_cap) # Capped at -6%
                    
                    # Trade execution tracking
                    # Tranches: Piece 1 (40%), Piece 2 (30%), Piece 3 (30%)
                    p1_closed = False
                    p2_closed = False
                    p3_closed = False
                    
                    p1_pnl = 0.0
                    p2_pnl = 0.0
                    p3_pnl = 0.0
                    
                    current_stop_pct = -stop_loss_pct
                    scale1_hit = False
                    scale2_hit = False
                    
                    max_gain_reached = 0.0
                    max_dd_reached = 0.0
                    bars_held = 0
                    
                    # Forward simulation bar by bar (up to 84 bars = 14 days)
                    for j in range(i + 1, min(n, i + 85)):
                        bars_held += 1
                        bar = df.iloc[j]
                        bar_high = bar['high']
                        bar_low = bar['low']
                        bar_close = bar['close']
                        bar_ema20 = bar['ema20']
                        
                        gain_high = ((bar_high - entry_price) / entry_price) * 100.0
                        loss_low = ((bar_low - entry_price) / entry_price) * 100.0
                        
                        max_gain_reached = max(max_gain_reached, gain_high)
                        max_dd_reached = min(max_dd_reached, loss_low)
                        
                        # 1. Check Stop Loss
                        if loss_low <= current_stop_pct:
                            # Position stopped out
                            exit_pnl = current_stop_pct
                            if not p1_closed: p1_pnl = exit_pnl; p1_closed = True
                            if not p2_closed: p2_pnl = exit_pnl; p2_closed = True
                            if not p3_closed: p3_pnl = exit_pnl; p3_closed = True
                            break
                            
                        # 2. Check Scale 1 (+18%)
                        if not p1_closed and gain_high >= target_scale1:
                            p1_pnl = target_scale1
                            p1_closed = True
                            scale1_hit = True
                            current_stop_pct = 0.0 # Breakeven!
                            
                        # 3. Check Scale 2 (+45%)
                        if not p2_closed and gain_high >= target_scale2:
                            p2_pnl = target_scale2
                            p2_closed = True
                            scale2_hit = True
                            
                        # 4. Check Scale 3 Trailing Stop (closes below 20 EMA, only active after scale 1)
                        if scale1_hit and not p3_closed and bar_close < bar_ema20:
                            p3_pnl = ((bar_close - entry_price) / entry_price) * 100.0
                            p3_closed = True
                            if p2_closed:
                                break # All pieces closed
                                
                    # If end of window reached and pieces still open, close at market close
                    if not p1_closed: p1_pnl = ((bar_close - entry_price) / entry_price) * 100.0
                    if not p2_closed: p2_pnl = ((bar_close - entry_price) / entry_price) * 100.0
                    if not p3_closed: p3_pnl = ((bar_close - entry_price) / entry_price) * 100.0
                    
                    # Total blended trade PnL
                    total_pnl = (0.40 * p1_pnl) + (0.30 * p2_pnl) + (0.30 * p3_pnl)
                    
                    trades.append({
                        "symbol": sym,
                        "entry_time": str(row['datetime']),
                        "entry_price": entry_price,
                        "blended_pnl_pct": round(total_pnl, 2),
                        "max_gain_pct": round(max_gain_reached, 2),
                        "max_dd_pct": round(max_dd_reached, 2),
                        "scale1_hit": scale1_hit,
                        "scale2_hit": scale2_hit,
                        "p1_pnl": round(p1_pnl, 1),
                        "p2_pnl": round(p2_pnl, 1),
                        "p3_pnl": round(p3_pnl, 1),
                        "bars_held": bars_held,
                        "days_held": round(bars_held * 4 / 24, 1)
                    })
                    
                    # Jump past this trade to avoid immediate re-entry on same wave
                    i = j + 4
                else:
                    i += 1
                    
        return pd.DataFrame(trades)

    # Run variations
    print("\nRunning Simulation 1: Full Rules WITH Bitcoin Market Filter...")
    df_with_btc = simulate_trades(use_btc_filter=True)
    
    print("Running Simulation 2: Full Rules WITHOUT Bitcoin Market Filter...")
    df_no_btc = simulate_trades(use_btc_filter=False)
    
    def print_performance_report(df_res, title):
        total = len(df_res)
        wins = df_res[df_res['blended_pnl_pct'] > 0]
        losses = df_res[df_res['blended_pnl_pct'] <= 0]
        
        win_rate = (len(wins) / total) * 100 if total > 0 else 0
        scale1_rate = (df_res['scale1_hit'].mean()) * 100 if total > 0 else 0
        scale2_rate = (df_res['scale2_hit'].mean()) * 100 if total > 0 else 0
        mega_runners = (df_res['max_gain_pct'] >= 100.0).sum()
        
        avg_win = wins['blended_pnl_pct'].mean() if len(wins) > 0 else 0
        avg_loss = abs(losses['blended_pnl_pct'].mean()) if len(losses) > 0 else 0
        
        gross_profit = wins['blended_pnl_pct'].sum()
        gross_loss = abs(losses['blended_pnl_pct'].sum())
        pf = gross_profit / (gross_loss + 1e-6)
        
        # Cumulative compounded return simulation with 10% position sizing (max 10 slots)
        capital = 10000.0
        equity_curve = [capital]
        for p in df_res['blended_pnl_pct']:
            trade_alloc = capital * 0.10 # 10% per trade
            profit = trade_alloc * (p / 100.0)
            capital += profit
            equity_curve.append(capital)
            
        total_growth_pct = ((capital - 10000.0) / 10000.0) * 100.0
        
        # Max portfolio drawdown
        eq_series = pd.Series(equity_curve)
        rolling_max = eq_series.cummax()
        drawdowns = (eq_series - rolling_max) / rolling_max * 100.0
        max_drawdown = drawdowns.min()
        
        print("\n" + "="*80)
        print(f"6-MONTH BACKTEST RESULTS: {title}")
        print("="*80)
        print(f"Total Trade Setups:               {total}")
        print(f"Win Rate (Positive Net Trade):    {win_rate:.1f}%")
        print(f"Scale 1 (+18%) Hit Rate:          {scale1_rate:.1f}% (Moved to Breakeven)")
        print(f"Scale 2 (+45%) Hit Rate:          {scale2_rate:.1f}%")
        print(f"100%+ Mega-Runners Caught:        {mega_runners} trades")
        print(f"Average Win / Average Loss:       +{avg_win:.2f}%  /  -{avg_loss:.2f}% (Payoff Ratio: {avg_win/(avg_loss+1e-6):.2f}x)")
        print(f"Expectancy per Trade:             +{df_res['blended_pnl_pct'].mean():.2f}%")
        print(f"PROFIT FACTOR:                    {pf:.2f}")
        print(f"Compounded Account Growth:        +{total_growth_pct:.1f}% (Starting $10,000 -> ${capital:,.2f})")
        print(f"Max Portfolio Drawdown:           {max_drawdown:.1f}%")
        print(f"Average Trade Duration:           {df_res['days_held'].mean():.1f} days")
        print("="*80)
        
    print_performance_report(df_with_btc, "WITH BITCOIN REGIME FILTER (RECOMMENDED)")
    print_performance_report(df_no_btc, "WITHOUT BITCOIN REGIME FILTER (RAW ALTS)")
    
    # Save trades
    df_with_btc.to_csv(DATA_DIR / "backtest_6m_trades.csv", index=False)
    print(f"\nSaved trade log to {DATA_DIR / 'backtest_6m_trades.csv'}")
    
    # Top 5 Best Trades
    print("\nTop 5 Most Profitable Trades:")
    for _, t in df_with_btc.sort_values(by="blended_pnl_pct", ascending=False).head(5).iterrows():
        print(f"  {t['symbol']:12s} | Entry: {t['entry_time'][:16]} | Max Run: +{t['max_gain_pct']}% | Blended Net PnL: +{t['blended_pnl_pct']}% (Held {t['days_held']}d)")

if __name__ == "__main__":
    run_6m_backtest()
