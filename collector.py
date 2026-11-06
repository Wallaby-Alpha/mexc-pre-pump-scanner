"""
MEXC REST API Collector for Historical Klines.
"""

import time
import requests
import pandas as pd
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from config import MEXC_BASE_URL, EXCLUDED_KEYWORDS, DatasetConfig
from database import init_db, save_symbols, save_klines, get_db_summary

class MexcCollector:
    def __init__(self, delay: float = 0.08):
        self.base_url = MEXC_BASE_URL
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MexcPrePumpStudy/1.0"
        })

    def fetch_spot_symbols(self) -> List[Dict[str, Any]]:
        """Fetch all active Spot USDT trading pairs from MEXC exchangeInfo."""
        url = f"{self.base_url}/api/v3/exchangeInfo"
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        symbols_info = []
        for s in data.get("symbols", []):
            symbol = s.get("symbol", "")
            status = str(s.get("status", ""))
            quote = s.get("quoteAsset", "")
            base = s.get("baseAsset", "")

            # Filter for active USDT spot pairs
            if quote != "USDT" or status not in ("1", "ENABLED"):
                continue

            # Exclude leveraged tokens, stablecoins, fiat, or irregular symbols
            if any(kw in base for kw in EXCLUDED_KEYWORDS) or not base.isalnum():
                continue

            symbols_info.append({
                "symbol": symbol,
                "base_asset": base,
                "quote_asset": quote
            })

        return symbols_info

    def fetch_24h_tickers(self) -> Dict[str, Dict[str, Any]]:
        """Fetch 24h ticker statistics for volume and price changes."""
        url = f"{self.base_url}/api/v3/ticker/24hr"
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        tickers = {}
        for item in data:
            sym = item.get("symbol")
            if sym:
                try:
                    tickers[sym] = {
                        "priceChangePercent": float(item.get("priceChangePercent", 0.0)),
                        "lastPrice": float(item.get("lastPrice", 0.0)),
                        "quoteVolume": float(item.get("quoteVolume", 0.0)),
                        "volume": float(item.get("volume", 0.0)),
                    }
                except (ValueError, TypeError):
                    continue
        return tickers

    def fetch_klines_chunk(
        self,
        symbol: str,
        interval: str = "4h",
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        limit: int = 500,
        retries: int = 3
    ) -> pd.DataFrame:
        api_interval = "60m" if interval == "1h" else interval
        url = f"{self.base_url}/api/v3/klines"
        params: Dict[str, Any] = {
            "symbol": symbol,
            "interval": api_interval,
            "limit": min(limit, 500)
        }
        if start_time_ms:
            params["startTime"] = int(start_time_ms)
        if end_time_ms:
            params["endTime"] = int(end_time_ms)

        for attempt in range(retries):
            try:
                if self.delay > 0:
                    time.sleep(self.delay)

                r = self.session.get(url, params=params, timeout=12)
                if r.status_code == 429:
                    time.sleep(2.0 * (attempt + 1))
                    continue

                data = r.json()
                if not isinstance(data, list) or not data:
                    return pd.DataFrame()

                # [open_time, open, high, low, close, volume, close_time, quote_volume]
                df = pd.DataFrame(data, columns=[
                    "open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume"
                ])
                df["timestamp"] = df["open_time"].astype(int)
                df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
                    df[col] = df[col].astype(float)

                return df[["timestamp", "datetime", "open", "high", "low", "close", "volume", "quote_volume"]]

            except Exception as e:
                if attempt == retries - 1:
                    return pd.DataFrame()
                time.sleep(1.0)

        return pd.DataFrame()

    def fetch_history(self, symbol: str, interval: str = "4h", days: int = 120) -> pd.DataFrame:
        """Paginates backwards to retrieve full historical dataset."""
        now_ms = int(time.time() * 1000)
        target_start_ms = now_ms - (days * 24 * 3600 * 1000)
        
        if interval in ("1h", "60m"):
            interval_ms = 3600 * 1000
        elif interval == "4h":
            interval_ms = 4 * 3600 * 1000
        elif interval == "1d":
            interval_ms = 86400 * 1000
        else:
            interval_ms = 3600 * 1000
        chunk_span_ms = 500 * interval_ms
        
        all_dfs = []
        current_end_ms = now_ms

        while current_end_ms > target_start_ms:
            chunk_start_ms = max(target_start_ms, current_end_ms - chunk_span_ms)
            df_chunk = self.fetch_klines_chunk(
                symbol=symbol,
                interval=interval,
                start_time_ms=chunk_start_ms,
                end_time_ms=current_end_ms,
                limit=500
            )
            if df_chunk.empty:
                break

            all_dfs.append(df_chunk)
            earliest_ms = int(df_chunk["timestamp"].min())
            
            if earliest_ms <= target_start_ms or earliest_ms >= current_end_ms:
                break

            current_end_ms = earliest_ms - 1
            if len(df_chunk) < 500:
                break

        if not all_dfs:
            return pd.DataFrame()

        combined = pd.concat(all_dfs, ignore_index=True)
        combined.drop_duplicates(subset=["timestamp"], inplace=True)
        combined.sort_values(by="timestamp", inplace=True)
        combined.reset_index(drop=True, inplace=True)
        return combined

def run_collection(max_symbols: int = 150, days: int = 120):
    init_db()
    collector = MexcCollector(delay=DatasetConfig.rate_limit_delay)
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Step 1: Querying MEXC exchangeInfo & 24h tickers...")
    raw_symbols = collector.fetch_spot_symbols()
    tickers = collector.fetch_24h_tickers()
    
    eligible = []
    for s in raw_symbols:
        sym = s["symbol"]
        t = tickers.get(sym, {})
        vol_usd = t.get("quoteVolume", 0.0)
        if vol_usd >= DatasetConfig.min_24h_turnover_usd:
            s["quote_volume_24h"] = vol_usd
            s["price_change_24h"] = t.get("priceChangePercent", 0.0)
            s["last_price"] = t.get("lastPrice", 0.0)
            eligible.append(s)
            
    # Sort by 24h turnover descending
    eligible.sort(key=lambda x: x["quote_volume_24h"], reverse=True)
    
    # Exclude BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, DOGEUSDT from altcoin pump universe
    # as we want true altcoins / microcaps / runners where pre-pump accumulation happens
    major_benchmarks = {"BTCUSDT", "ETHUSDT"}
    target_symbols = [s for s in eligible if s["symbol"] not in major_benchmarks][:max_symbols]
    
    save_symbols(eligible)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Discovered {len(eligible)} active USDT pairs. Selected top {len(target_symbols)} altcoins (turnover: ${target_symbols[-1]['quote_volume_24h']:,.0f} - ${target_symbols[0]['quote_volume_24h']:,.0f}).")
    
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Step 2: Downloading {days} days of 4h klines for {len(target_symbols)} altcoins...")
    
    success_count = 0
    total_candles = 0
    start_time = time.time()
    
    for idx, s in enumerate(target_symbols, 1):
        sym = s["symbol"]
        df = collector.fetch_history(symbol=sym, interval="4h", days=days)
        if not df.empty:
            save_klines(sym, df)
            success_count += 1
            total_candles += len(df)
            
        if idx % 25 == 0 or idx == len(target_symbols):
            elapsed = time.time() - start_time
            rate = idx / elapsed if elapsed > 0 else 0
            print(f"  [{idx:3d}/{len(target_symbols)}] Synced {sym:12s} ({len(df):4d} candles) | {rate:.1f} coins/sec")

    summary = get_db_summary()
    print("\n" + "="*60)
    print("DATASET COLLECTION COMPLETE")
    print("="*60)
    print(f"Total Altcoins Synced: {summary['kline_symbols']}")
    print(f"Total 4h Candles:      {summary['total_candles']:,}")
    print(f"Date Range:            {summary['earliest_candle']}  -->  {summary['latest_candle']}")
    print("="*60)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Collect MEXC 4h Kline Dataset")
    parser.add_argument("--symbols", type=int, default=150, help="Number of altcoin pairs to fetch")
    parser.add_argument("--days", type=int, default=120, help="Days of history (default: 120)")
    args = parser.parse_args()
    run_collection(max_symbols=args.symbols, days=args.days)
