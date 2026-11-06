"""
Core Analysis & Signal Detection Engine for MEXC Pre-Pump Scanner.
"""

import time
import sqlite3
import logging
import requests
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone

from config import MEXC_BASE_URL, EXCLUDED_KEYWORDS, ScannerConfig, DB_PATH
from pre_pump_analyzer import calculate_technical_features
from collector import MexcCollector

logger = logging.getLogger("mexc_scanner")

class ScannerEngine:
    def __init__(self, config: Optional[ScannerConfig] = None):
        self.config = config or ScannerConfig()
        self.collector = MexcCollector(delay=self.config.request_delay)
        self._init_alert_db()

    def _init_alert_db(self):
        conn = sqlite3.connect(DB_PATH)
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fired_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    candle_timestamp INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss_price REAL NOT NULL,
                    target_1 REAL NOT NULL,
                    target_2 REAL NOT NULL,
                    fired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, alert_type, candle_timestamp)
                );
            """)
        conn.close()

    def is_alert_already_fired(self, symbol: str, alert_type: str, candle_timestamp: int) -> bool:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM fired_alerts WHERE symbol = ? AND alert_type = ? AND candle_timestamp = ?",
            (symbol, alert_type, candle_timestamp)
        )
        row = cursor.fetchone()
        conn.close()
        return bool(row)

    def log_fired_alert(self, data: Dict[str, Any]):
        conn = sqlite3.connect(DB_PATH)
        try:
            with conn:
                conn.execute("""
                    INSERT OR IGNORE INTO fired_alerts (symbol, alert_type, candle_timestamp, entry_price, stop_loss_price, target_1, target_2)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                """, (
                    data["symbol"],
                    data["alert_type"],
                    int(data["candle_timestamp"]),
                    float(data["entry_price"]),
                    float(data["stop_loss_price"]),
                    float(data["target_1_price"]),
                    float(data["target_2_price"])
                ))
        except Exception as e:
            logger.warning(f"Error logging alert: {e}")
        finally:
            conn.close()

    def check_btc_regime(self) -> Tuple[bool, str]:
        """Checks if Bitcoin 4h candle is trading above its 20 EMA."""
        try:
            df_btc = self.collector.fetch_klines_chunk(symbol="BTCUSDT", interval="4h", limit=50)
            if df_btc.empty:
                return True, "UNKNOWN (API error, neutral default)"
            df_btc['ema20'] = df_btc['close'].ewm(span=20, adjust=False).mean()
            last_closed = df_btc.iloc[-2]
            current = df_btc.iloc[-1]
            
            is_bullish = bool(current['close'] >= current['ema20'] or last_closed['close'] >= last_closed['ema20'])
            status_desc = "🟢 BULLISH (BTC > 20 EMA)" if is_bullish else "🔴 BEARISH REGIME (BTC < 20 EMA - Exercise Caution)"
            return is_bullish, status_desc
        except Exception as e:
            logger.warning(f"Failed to check BTC regime: {e}")
            return True, "UNKNOWN (Error)"

    def get_target_universe(self) -> List[str]:
        """Retrieves and filters the top active USDT altcoins."""
        raw_symbols = self.collector.fetch_spot_symbols()
        tickers = self.collector.fetch_24h_tickers()
        
        eligible = []
        for s in raw_symbols:
            sym = s["symbol"]
            if sym in ("BTCUSDT", "ETHUSDT"):
                continue
            t = tickers.get(sym, {})
            vol_usd = t.get("quoteVolume", 0.0)
            if vol_usd >= self.config.min_24h_turnover_usd:
                eligible.append((sym, vol_usd))
                
        eligible.sort(key=lambda x: x[1], reverse=True)
        top_symbols = [x[0] for x in eligible[:self.config.max_coins_to_scan]]
        return top_symbols

    def scan_market(self) -> List[Dict[str, Any]]:
        """
        Executes a complete scan of the universe for both:
        1. Stage 2 Confirmed 4h Breakouts (last closed 4h candle)
        2. Stage 1 Pre-Alerts (currently forming 4h candle with early volume expansion)
        """
        btc_ok, btc_status = self.check_btc_regime()
        symbols = self.get_target_universe()
        logger.info(f"Scanning {len(symbols)} active altcoins. BTC Regime: {btc_status}")
        
        new_alerts = []
        
        for idx, sym in enumerate(symbols, 1):
            try:
                df_raw = self.collector.fetch_klines_chunk(symbol=sym, interval="4h", limit=70)
                if len(df_raw) < 50:
                    continue
                    
                df = calculate_technical_features(df_raw)
                last_closed = df.iloc[-2]     # Most recently closed 4h candle
                current_candle = df.iloc[-1]  # In-progress 4h candle
                
                # ----------------------------------------------------
                # CHECK 1: STAGE 2 CONFIRMED 4H BREAKOUT (Last Closed Bar)
                # ----------------------------------------------------
                ts_closed = int(last_closed['timestamp'])
                if not self.is_alert_already_fired(sym, "CONFIRMED_4H", ts_closed):
                    prior_7d_high = df['high'].iloc[-44 : -2].max()
                    cond_base = (
                        last_closed['range_7d_pct'] <= self.config.max_7d_range_pct and 
                        last_closed['bb_squeeze_rank'] >= self.config.min_squeeze_rank
                    )
                    cond_vol = (last_closed['quote_volume'] >= self.config.min_volume_surge * last_closed['vol_ma20'])
                    cond_break = (last_closed['close'] > last_closed['open'] and last_closed['close'] >= prior_7d_high * 0.98)
                    
                    if cond_base and cond_vol and cond_break:
                        entry_price = float(last_closed['close'])
                        candle_low = float(last_closed['low'])
                        
                        # Dynamic Capped Stop Loss: max(candle_low - 0.5%, entry * 0.925)
                        raw_sl = candle_low * (1.0 - (self.config.sl_buffer_pct / 100.0))
                        capped_sl = entry_price * (1.0 - (self.config.max_stop_loss_pct / 100.0))
                        sl_price = max(raw_sl, capped_sl)
                        sl_pct = ((entry_price - sl_price) / entry_price) * 100.0
                        
                        target_1 = entry_price * (1.0 + (self.config.target_scale1_pct / 100.0))
                        target_2 = entry_price * (1.0 + (self.config.target_scale2_pct / 100.0))
                        
                        alert_dict = {
                            "symbol": sym,
                            "alert_type": "CONFIRMED_4H",
                            "candle_timestamp": ts_closed,
                            "candle_time_str": str(last_closed['datetime']),
                            "entry_price": entry_price,
                            "volume_surge": float(last_closed['quote_volume'] / (last_closed['vol_ma20'] + 1e-6)),
                            "squeeze_rank": float(last_closed['bb_squeeze_rank']),
                            "range_7d_pct": float(last_closed['range_7d_pct']),
                            "stop_loss_price": round(sl_price, 6),
                            "stop_loss_pct": round(sl_pct, 2),
                            "target_1_price": round(target_1, 6),
                            "target_2_price": round(target_2, 6),
                            "btc_status": btc_status
                        }
                        self.log_fired_alert(alert_dict)
                        new_alerts.append(alert_dict)
                        continue

                # ----------------------------------------------------
                # CHECK 2: STAGE 1 PRE-ALERT (Current In-Progress Bar)
                # ----------------------------------------------------
                ts_curr = int(current_candle['timestamp'])
                if not self.is_alert_already_fired(sym, "PRE_ALERT", ts_curr):
                    prior_7d_high_curr = df['high'].iloc[-43 : -1].max()
                    cond_base_curr = (
                        current_candle['range_7d_pct'] <= self.config.max_7d_range_pct and 
                        current_candle['bb_squeeze_rank'] >= self.config.min_squeeze_rank
                    )
                    cond_vol_curr = (current_candle['quote_volume'] >= self.config.pre_alert_min_volume * current_candle['vol_ma20'])
                    cond_break_curr = (current_candle['close'] > current_candle['open'] and current_candle['close'] >= prior_7d_high_curr * 0.98)
                    
                    if cond_base_curr and cond_vol_curr and cond_break_curr:
                        curr_price = float(current_candle['close'])
                        candle_low = float(current_candle['low'])
                        raw_sl = candle_low * (1.0 - (self.config.sl_buffer_pct / 100.0))
                        capped_sl = curr_price * (1.0 - (self.config.max_stop_loss_pct / 100.0))
                        sl_price = max(raw_sl, capped_sl)
                        sl_pct = ((curr_price - sl_price) / curr_price) * 100.0
                        
                        target_1 = curr_price * (1.0 + (self.config.target_scale1_pct / 100.0))
                        target_2 = curr_price * (1.0 + (self.config.target_scale2_pct / 100.0))
                        
                        alert_dict = {
                            "symbol": sym,
                            "alert_type": "PRE_ALERT",
                            "candle_timestamp": ts_curr,
                            "candle_time_str": str(current_candle['datetime']),
                            "entry_price": curr_price,
                            "volume_surge": float(current_candle['quote_volume'] / (current_candle['vol_ma20'] + 1e-6)),
                            "squeeze_rank": float(current_candle['bb_squeeze_rank']),
                            "range_7d_pct": float(current_candle['range_7d_pct']),
                            "stop_loss_price": round(sl_price, 6),
                            "stop_loss_pct": round(sl_pct, 2),
                            "target_1_price": round(target_1, 6),
                            "target_2_price": round(target_2, 6),
                            "btc_status": btc_status
                        }
                        self.log_fired_alert(alert_dict)
                        new_alerts.append(alert_dict)

            except Exception as e:
                logger.debug(f"Error evaluating {sym}: {e}")
                continue

        return new_alerts
