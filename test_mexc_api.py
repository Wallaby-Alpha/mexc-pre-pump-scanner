import requests
import json
import time

def test_api():
    print("Testing MEXC API /api/v3/defaultSymbols and /api/v3/ticker/24hr...")
    url = "https://api.mexc.com/api/v3/ticker/24hr"
    resp = requests.get(url, timeout=10)
    data = resp.json()
    print(f"Total tickers returned: {len(data)}")
    
    usdt_pairs = [d for d in data if d.get('symbol', '').endswith('USDT')]
    print(f"Total USDT pairs: {len(usdt_pairs)}")
    
    # Sort by quoteVolume descending
    usdt_pairs.sort(key=lambda x: float(x.get('quoteVolume', 0)), reverse=True)
    print("\nTop 10 USDT pairs by 24h volume:")
    for p in usdt_pairs[:10]:
        print(f"  {p['symbol']}: ${float(p['quoteVolume']):,.0f} (Price: {p['lastPrice']})")
        
    sample_symbol = "BTCUSDT"
    kline_url = f"https://api.mexc.com/api/v3/klines?symbol={sample_symbol}&interval=4h&limit=5"
    k_resp = requests.get(kline_url, timeout=10)
    klines = k_resp.json()
    print(f"\nSample 4h kline for {sample_symbol}:")
    print(klines[0])
    # [openTime, open, high, low, close, volume, closeTime, quoteVolume]

if __name__ == "__main__":
    test_api()
