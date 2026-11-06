"""
Stop-Loss Optimization:
1. Static Stop-Loss Sweep: -3%, -4%, -5%, -6%, -7%, -8%, -10%, -12%.
2. Structural Stop-Loss: Placed just below the Low of the 4h Impulse Candle (-0.5% buffer).
Evaluated on the exact 6-month dataset (May - Nov 2026, 150 altcoins + BTC filter).
"""

import pandas as pd
import numpy as np
from database import get_connection, get_symbol_klines
from pre_pump_analyzer import calculate_technical_features
from config import DATA_DIR

def run_stop_loss_study():
    print("Loading 6-month historical dataset and BTC filter...")
    
    df_btc = get_symbol_klines("BTCUSDT", table="klines_4h")
    df_btc['btc_ema20'] = df_btc['close'].ewm(span=20, adjust=False).mean()
    btc_map = {int(r['timestamp']): bool(r['close'] >= r['btc_ema20']) for _, r in df_btc.iterrows()}
    
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT DISTINCT symbol FROM klines_4h WHERE symbol != 'BTCUSDT' ORDER BY symbol ASC;")
    symbols = [r[0] for r in c.fetchall()]
    conn.close()
    
    # Pre-extract all setup signals
    signals = []
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
            
            # BTC Filter
            if not btc_map.get(ts, True):
                i += 1
                continue
                
            cond_base = (row['range_7d_pct'] <= 35.0 and row['bb_squeeze_rank'] >= 80)
            cond_vol = (row['quote_volume'] >= 2.5 * row['vol_ma20'])
            prior_7d_high = df['high'].iloc[max(0, i-42) : i].max()
            cond_break = (row['close'] > row['open'] and row['close'] >= prior_7d_high * 0.98)
            
            if cond_base and cond_vol and cond_break:
                entry_price = row['close']
                ignition_low = row['low']
                # Risk to low of impulse candle with 0.5% buffer
                impulse_risk_pct = ((entry_price - (ignition_low * 0.995)) / entry_price) * 100.0
                
                # Extract forward bars (up to 84 bars = 14 days)
                fwd_bars = df.iloc[i+1 : min(n, i+85)].copy()
                
                signals.append({
                    "symbol": sym,
                    "datetime": row['datetime'],
                    "entry_price": entry_price,
                    "impulse_risk_pct": impulse_risk_pct,
                    "ignition_low": ignition_low,
                    "fwd_bars": fwd_bars
                })
                i += 10 # skip window
            else:
                i += 1
                
    print(f"Total verified signals to test: {len(signals)}\n")
    
    def simulate_with_sl(sl_mode="static", static_sl_pct=6.0, target_scale1=18.0, target_scale2=45.0):
        trades = []
        for s in signals:
            entry_price = s['entry_price']
            fwd = s['fwd_bars']
            if fwd.empty:
                continue
                
            if sl_mode == "static":
                initial_sl_pct = static_sl_pct
            else:
                # Impulse candle low (plus buffer)
                initial_sl_pct = s['impulse_risk_pct']
                
            p1_closed = False
            p2_closed = False
            p3_closed = False
            p1_pnl = 0.0
            p2_pnl = 0.0
            p3_pnl = 0.0
            
            current_sl_pct = -abs(initial_sl_pct)
            scale1_hit = False
            scale2_hit = False
            bars_held = 0
            
            for _, bar in fwd.iterrows():
                bars_held += 1
                bar_high = bar['high']
                bar_low = bar['low']
                bar_close = bar['close']
                bar_ema20 = bar['ema20']
                
                gain_high = ((bar_high - entry_price) / entry_price) * 100.0
                loss_low = ((bar_low - entry_price) / entry_price) * 100.0
                
                # 1. Stop loss hit
                if loss_low <= current_sl_pct:
                    exit_pnl = current_sl_pct
                    if not p1_closed: p1_pnl = exit_pnl; p1_closed = True
                    if not p2_closed: p2_pnl = exit_pnl; p2_closed = True
                    if not p3_closed: p3_pnl = exit_pnl; p3_closed = True
                    break
                    
                # 2. Scale 1 (+18%)
                if not p1_closed and gain_high >= target_scale1:
                    p1_pnl = target_scale1
                    p1_closed = True
                    scale1_hit = True
                    current_sl_pct = 0.0 # Breakeven
                    
                # 3. Scale 2 (+45%)
                if not p2_closed and gain_high >= target_scale2:
                    p2_pnl = target_scale2
                    p2_closed = True
                    scale2_hit = True
                    
                # 4. Trailing stop on piece 3 (closes below 20 EMA)
                if scale1_hit and not p3_closed and bar_close < bar_ema20:
                    p3_pnl = ((bar_close - entry_price) / entry_price) * 100.0
                    p3_closed = True
                    if p2_closed:
                        break
                        
            if not p1_closed: p1_pnl = ((bar_close - entry_price) / entry_price) * 100.0
            if not p2_closed: p2_pnl = ((bar_close - entry_price) / entry_price) * 100.0
            if not p3_closed: p3_pnl = ((bar_close - entry_price) / entry_price) * 100.0
            
            blended = (0.40 * p1_pnl) + (0.30 * p2_pnl) + (0.30 * p3_pnl)
            trades.append({
                "blended_pnl": blended,
                "initial_sl": initial_sl_pct,
                "scale1_hit": scale1_hit,
                "scale2_hit": scale2_hit,
                "bars_held": bars_held
            })
            
        df_tr = pd.DataFrame(trades)
        wins = df_tr[df_tr['blended_pnl'] > 0]
        losses = df_tr[df_tr['blended_pnl'] <= 0]
        
        gross_profit = wins['blended_pnl'].sum()
        gross_loss = abs(losses['blended_pnl'].sum())
        pf = gross_profit / (gross_loss + 1e-6)
        win_rate = (len(wins) / len(df_tr)) * 100.0
        avg_win = wins['blended_pnl'].mean() if len(wins) > 0 else 0
        avg_loss = abs(losses['blended_pnl'].mean()) if len(losses) > 0 else 0
        exp = df_tr['blended_pnl'].mean()
        
        # Drawdown simulation (10% allocation)
        cap = 10000.0
        eq = [cap]
        for p in df_tr['blended_pnl']:
            cap += (cap * 0.10) * (p / 100.0)
            eq.append(cap)
        eq_s = pd.Series(eq)
        max_dd = ((eq_s - eq_s.cummax()) / eq_s.cummax()).min() * 100.0
        comp_growth = ((cap - 10000.0) / 10000.0) * 100.0
        
        return {
            "win_rate": round(win_rate, 1),
            "scale1_rate": round(df_tr['scale1_hit'].mean() * 100.0, 1),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "payoff": round(avg_win / (avg_loss + 1e-6), 2),
            "expectancy": round(exp, 2),
            "pf": round(pf, 2),
            "comp_return": round(comp_growth, 1),
            "max_dd": round(max_dd, 1),
            "avg_sl": round(df_tr['initial_sl'].mean(), 2)
        }

    # 1. Sweep Static SL values
    static_levels = [3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 12.0]
    results_static = []
    for sl in static_levels:
        res = simulate_with_sl(sl_mode="static", static_sl_pct=sl)
        res["stop_type"] = f"Static -{sl:.0f}%"
        results_static.append(res)
        
    # 2. Impulse Candle Low
    res_impulse = simulate_with_sl(sl_mode="impulse")
    res_impulse["stop_type"] = "Impulse Candle Low"
    
    print("="*95)
    print("STOP-LOSS PERFORMANCE COMPARISON (6-MONTH BACKTEST)")
    print("="*95)
    print(f"{'Stop-Loss Model':<22} | {'WinRate':<7} | {'Scale 1':<7} | {'Avg Win':<8} | {'Avg Loss':<8} | {'Payoff':<6} | {'Expectancy':<10} | {'PF':<5} | {'Max DD':<6} | {'Return':<7}")
    print("-" * 95)
    
    for r in results_static:
        print(f"{r['stop_type']:<22} | {r['win_rate']:>5.1f}% | {r['scale1_rate']:>5.1f}% | +{r['avg_win']:>5.2f}% | -{r['avg_loss']:>5.2f}% | {r['payoff']:>5.2f}x | +{r['expectancy']:>6.2f}%/tr | {r['pf']:>4.2f} | {r['max_dd']:>5.1f}% | +{r['comp_return']:>5.1f}%")
        
    print("-" * 95)
    r = res_impulse
    lbl = f"{r['stop_type']} (Avg -{r['avg_sl']}%)"
    print(f"{lbl:<22} | {r['win_rate']:>5.1f}% | {r['scale1_rate']:>5.1f}% | +{r['avg_win']:>5.2f}% | -{r['avg_loss']:>5.2f}% | {r['payoff']:>5.2f}x | +{r['expectancy']:>6.2f}%/tr | {r['pf']:>4.2f} | {r['max_dd']:>5.1f}% | +{r['comp_return']:>5.1f}%")
    print("="*95)

if __name__ == "__main__":
    run_stop_loss_study()
