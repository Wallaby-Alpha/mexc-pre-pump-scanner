"""
Configuration and Environment Settings for MEXC Pre-Pump Scanner.
"""

import os
from pathlib import Path
from dataclasses import dataclass

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "mexc_scanner.db"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

MEXC_BASE_URL = "https://api.mexc.com"

# Exclude stablecoins, leveraged ETF tokens, fiat currencies, synthetic dollars
EXCLUDED_KEYWORDS = [
    "3L", "3S", "4L", "4S", "5L", "5S",
    "BEAR", "BULL", "DOWN", "UP",
    "USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDD", "USDE", "USD1", "USDF", "USDS",
    "EUR", "TRY", "GBP", "AUD", "BRL", "RUB", "UAH"
]

@dataclass
class ScannerConfig:
    # Universe Filters
    min_24h_turnover_usd: float = 100_000.0   # Only scan coins with >= $100k daily volume
    max_coins_to_scan: int = 150             # Top 150 altcoins
    
    # Quantitative Signal Rules
    min_squeeze_rank: float = 75.0           # Extreme Bollinger Band compression percentile
    max_7d_range_pct: float = 35.0           # Maximum 7-day consolidation range %
    min_volume_surge: float = 2.5            # 4h volume >= 2.5x 20-period moving average
    
    # 3-Hour Pre-Alert Rules
    pre_alert_min_volume: float = 1.8        # 3h volume already >= 1.8x full 4h MA
    
    # Stop-Loss & Target Rules
    max_stop_loss_pct: float = 7.5           # Capped maximum stop loss %
    sl_buffer_pct: float = 0.5               # 0.5% below impulse candle low
    target_scale1_pct: float = 18.0          # Target 1: Sell 40%, move SL to Breakeven
    target_scale2_pct: float = 45.0          # Target 2: Sell 30%
    
    # Alert Dispatching
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    discord_webhook_url: str = os.getenv("DISCORD_WEBHOOK_URL", "")
    
    # Network Rate Limiting
    rate_limit_delay: float = 0.05
    request_delay: float = 0.05              # ~20 req/s polite REST polling

DatasetConfig = ScannerConfig
