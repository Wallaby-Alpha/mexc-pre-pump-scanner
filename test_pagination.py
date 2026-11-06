import requests
import time
from datetime import datetime, timezone

def test_pagination():
    symbol = "BTCUSDT"
    interval = "4h"
    # Let's say we want 90 days of 4h candles
    # 90 days * 24h = 2160h / 4h = 540 candles.
    # 180 days = 1080 candles.
    # In MEXC, limit can be up to 1000.
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (180 * 24 * 3600 * 1000) # 180 days ago
    
    url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval={interval}&startTime={start_ms}&limit=1000"
    r = requests.get(url, timeout=10)
    candles = r.json()
    print(f"Candles fetched for {symbol} 4h from startTime: {len(candles)}")
    if candles:
        first_dt = datetime.fromtimestamp(candles[0][0]/1000, tz=timezone.utc)
        last_dt = datetime.fromtimestamp(candles[-1][0]/1000, tz=timezone.utc)
        print(f"First candle: {first_dt.strftime('%Y-%m-%d %H:%M')}")
        print(f"Last candle: {last_dt.strftime('%Y-%m-%d %H:%M')}")
        
        # Next batch if > 1000
        last_close_time = candles[-1][6] # closeTime
        url2 = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval={interval}&startTime={last_close_time + 1}&limit=1000"
        r2 = requests.get(url2, timeout=10)
        candles2 = r2.json()
        print(f"Second batch candles: {len(candles2)}")
        if candles2:
            print(f"Second batch first: {datetime.fromtimestamp(candles2[0][0]/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')}")
            print(f"Second batch last: {datetime.fromtimestamp(candles2[-1][0]/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')}")

if __name__ == "__main__":
    test_pagination()
