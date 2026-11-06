"""
Production Daemon for MEXC Pre-Pump Scanner.
Designed to run 24/7 on a DigitalOcean droplet, home server, or local machine.
"""

import os
import sys
import time
import signal
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone

from config import ScannerConfig, LOG_DIR
from scanner_engine import ScannerEngine
from notifier import Notifier

# Ensure UTF-8 output across all operating systems
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Configure Logging
log_file = LOG_DIR / "scanner.log"
file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
stream_handler = logging.StreamHandler(sys.stdout)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    handlers=[file_handler, stream_handler]
)
logger = logging.getLogger("mexc_scanner")

class ScannerDaemon:
    def __init__(self, check_interval_seconds: int = 900): # Check every 15 minutes
        self.config = ScannerConfig()
        self.engine = ScannerEngine(self.config)
        self.notifier = Notifier(
            telegram_token=self.config.telegram_bot_token,
            telegram_chat_id=self.config.telegram_chat_id,
            discord_webhook=self.config.discord_webhook_url
        )
        self.check_interval = check_interval_seconds
        self.running = True

        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)

    def _handle_exit(self, signum, frame):
        logger.info("Received termination signal. Shutting down gracefully...")
        self.running = False

    def run_single_scan(self):
        """Executes a single market-wide scan pass."""
        utc_now = datetime.now(timezone.utc)
        logger.info(f"Initiating scan pass at {utc_now.strftime('%Y-%m-%d %H:%M:%S UTC')}...")
        start_t = time.time()
        
        alerts = self.engine.scan_market()
        elapsed = time.time() - start_t
        
        if alerts:
            logger.info(f"Detected {len(alerts)} new alert(s) in {elapsed:.1f}s!")
            for alert in alerts:
                self.notifier.send_alert(alert)
        else:
            logger.info(f"Scan pass complete in {elapsed:.1f}s. No new breakout triggers.")

    def start(self):
        print("\n" + "="*70)
        print("🚀 MEXC PRE-PUMP SCANNER DAEMON STARTED")
        print("="*70)
        print(f"Target Universe:    Top {self.config.max_coins_to_scan} Active Altcoins (>= ${self.config.min_24h_turnover_usd:,.0f} 24h Vol)")
        print(f"Setup Criteria:     BB Squeeze Rank >= {self.config.min_squeeze_rank} | 7d Range <= {self.config.max_7d_range_pct}% | Vol >= {self.config.min_volume_surge}x")
        print(f"Alert Webhooks:     Discord: {'Configured' if self.config.discord_webhook_url else 'None (Terminal only)'} | Telegram: {'Configured' if self.config.telegram_bot_token else 'None'}")
        print(f"Scan Cadence:       Every {self.check_interval // 60} minutes")
        print("="*70 + "\n")

        # Immediate first scan
        self.run_single_scan()

        while self.running:
            try:
                # Sleep in small increments to respond quickly to Ctrl+C or SIGTERM
                for _ in range(self.check_interval):
                    if not self.running:
                        break
                    time.sleep(1)
                
                if self.running:
                    self.run_single_scan()
                    
            except Exception as e:
                logger.error(f"Unexpected error in daemon loop: {e}", exc_info=True)
                time.sleep(15)

        logger.info("Daemon has stopped.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="MEXC Pre-Pump Scanner 24/7 Daemon")
    parser.add_argument("--interval", type=int, default=900, help="Scan interval in seconds (default: 900s = 15m)")
    parser.add_argument("--once", action="store_true", help="Run a single scan pass and exit immediately")
    args = parser.parse_args()

    daemon = ScannerDaemon(check_interval_seconds=args.interval)
    if args.once:
        daemon.run_single_scan()
    else:
        daemon.start()
