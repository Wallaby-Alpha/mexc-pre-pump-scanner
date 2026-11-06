"""
Alert Dispatcher for MEXC Pre-Pump Scanner.
Supports rich terminal formatting, Discord Webhook, and Telegram Bot.
"""

import os
import json
import logging
import requests
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger("mexc_scanner")

class Notifier:
    def __init__(self, telegram_token: str = "", telegram_chat_id: str = "", discord_webhook: str = ""):
        self.telegram_token = telegram_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id = telegram_chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self.discord_webhook = discord_webhook or os.getenv("DISCORD_WEBHOOK_URL", "")

    def send_alert(self, alert_data: Dict[str, Any]):
        """Format and dispatch alert to console and external webhooks."""
        is_pre_alert = (alert_data.get("alert_type") == "PRE_ALERT")
        sym = alert_data.get("symbol", "UNKNOWN")
        price = alert_data.get("entry_price", 0.0)
        vol_surge = alert_data.get("volume_surge", 0.0)
        squeeze = alert_data.get("squeeze_rank", 0.0)
        range_7d = alert_data.get("range_7d_pct", 0.0)
        sl_price = alert_data.get("stop_loss_price", 0.0)
        sl_pct = alert_data.get("stop_loss_pct", 0.0)
        t1 = alert_data.get("target_1_price", 0.0)
        t2 = alert_data.get("target_2_price", 0.0)
        btc_status = alert_data.get("btc_status", "NEUTRAL")
        
        # 1. Format Console / Log Message
        header_tag = "🟡 [PRE-ALERT - ON-DECK]" if is_pre_alert else "🟢 [CONFIRMED 4H ENTRY]"
        lines = [
            "=" * 65,
            f"{header_tag} {sym} @ ${price:<10.6f}",
            "=" * 65,
            f"  • Vol Surge:       {vol_surge:.1f}x 20-bar baseline",
            f"  • Squeeze Rank:    {squeeze:.1f}/100 (Coiled Multi-Day Base)",
            f"  • 7-Day Range:     {range_7d:.1f}%",
            f"  • BTC Regime:      {btc_status}",
            "-" * 65,
            f"  • Entry Price:     ${price:<10.6f}",
            f"  • Stop-Loss:       ${sl_price:<10.6f} (-{sl_pct:.2f}%)",
            f"  • Target 1 (+18%): ${t1:<10.6f} (Sell 40% & Move SL to Breakeven)",
            f"  • Target 2 (+45%): ${t2:<10.6f} (Sell 30%)",
            f"  • Runner (30%):    Trail with 4h 20-EMA",
            "=" * 65
        ]
        console_msg = "\n".join(lines)
        print(console_msg)
        logger.info(f"Fired {header_tag} for {sym} at ${price}")

        # 2. Dispatch to Discord if configured
        if self.discord_webhook:
            self._send_discord(alert_data, is_pre_alert)

        # 3. Dispatch to Telegram if configured
        if self.telegram_token and self.telegram_chat_id:
            self._send_telegram(alert_data, is_pre_alert)

    def _send_discord(self, data: Dict[str, Any], is_pre_alert: bool):
        try:
            color = 16763904 if is_pre_alert else 3066993 # Yellow vs Green
            title = f"🟡 PRE-ALERT: {data['symbol']} (Hour 3 Build-Up)" if is_pre_alert else f"🟢 CONFIRMED ENTRY: {data['symbol']} (4H Breakout)"
            
            embed = {
                "title": title,
                "color": color,
                "timestamp": datetime.utcnow().isoformat(),
                "fields": [
                    {"name": "Price", "value": f"`${data['entry_price']}`", "inline": True},
                    {"name": "Volume Surge", "value": f"`{data['volume_surge']:.1f}x`", "inline": True},
                    {"name": "Squeeze Rank", "value": f"`{data['squeeze_rank']:.1f}/100`", "inline": True},
                    {"name": "Suggested Stop-Loss", "value": f"`${data['stop_loss_price']}` (-{data['stop_loss_pct']:.2f}%)", "inline": True},
                    {"name": "Target 1 (+18%)", "value": f"`${data['target_1_price']}` (Take 40% -> BE)", "inline": True},
                    {"name": "Target 2 (+45%)", "value": f"`${data['target_2_price']}` (Take 30%)", "inline": True},
                    {"name": "Trailing Runner", "value": "Trail remaining 30% with 4h 20-EMA", "inline": False},
                    {"name": "BTC Market Filter", "value": f"`{data['btc_status']}`", "inline": False}
                ],
                "footer": {"text": "MEXC Pre-Pump Scanner • 4h Institutional Setup"}
            }
            requests.post(self.discord_webhook, json={"embeds": [embed]}, timeout=8)
        except Exception as e:
            logger.warning(f"Failed to send Discord alert: {e}")

    def _send_telegram(self, data: Dict[str, Any], is_pre_alert: bool):
        try:
            title = f"🟡 *PRE-ALERT (ON-DECK)*: `{data['symbol']}`" if is_pre_alert else f"🟢 *CONFIRMED 4H BREAKOUT*: `{data['symbol']}`"
            text = (
                f"{title}\n\n"
                f"💵 *Entry Price*: `${data['entry_price']}`\n"
                f"📊 *Volume Surge*: `{data['volume_surge']:.1f}x`\n"
                f"🗜️ *Squeeze Rank*: `{data['squeeze_rank']:.1f}/100`\n"
                f"🌐 *BTC Market*: `{data['btc_status']}`\n\n"
                f"🛑 *Stop-Loss*: `${data['stop_loss_price']}` (-{data['stop_loss_pct']:.2f}%)\n"
                f"🎯 *Target 1 (+18%)*: `${data['target_1_price']}` (Sell 40% -> Move Stop to Breakeven)\n"
                f"🎯 *Target 2 (+45%)*: `${data['target_2_price']}` (Sell 30%)\n"
                f"🚀 *Runner (30%)*: Trail with 4h 20-EMA"
            )
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            requests.post(url, json={"chat_id": self.telegram_chat_id, "text": text, "parse_mode": "Markdown"}, timeout=8)
        except Exception as e:
            logger.warning(f"Failed to send Telegram alert: {e}")
