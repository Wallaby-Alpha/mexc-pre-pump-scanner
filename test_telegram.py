"""
Test Telegram Bot Integration.
Sends a test pre-pump alert to verify your bot token and chat ID.
"""

import os
import sys
import requests
from dotenv import load_dotenv
from config import BASE_DIR

# Load .env file
load_dotenv(BASE_DIR / ".env")

token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

if not token or not chat_id:
    print("\n❌ ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing!")
    print("Please edit your .env file and add:")
    print("  TELEGRAM_BOT_TOKEN=your_token_here")
    print("  TELEGRAM_CHAT_ID=your_chat_id_here\n")
    sys.exit(1)

print(f"Testing Telegram Bot with Token: {token[:8]}... and Chat ID: {chat_id}...")

url = f"https://api.telegram.org/bot{token}/sendMessage"
sample_message = (
    "🔔 *MEXC PRE-PUMP SCANNER CONNECTED!*\n\n"
    "✅ Your Telegram Bot is successfully configured and active.\n"
    "📡 You will receive:\n"
    "  • 🟡 *Stage 1 Pre-Alerts* (Hour 3 heads-up)\n"
    "  • 🟢 *Stage 2 Confirmed 4h Breakouts* with suggested Entry, Stop-Loss, and Targets.\n\n"
    "🚀 *Scanner running 24/7 on DigitalOcean.*"
)

try:
    resp = requests.post(url, json={"chat_id": chat_id, "text": sample_message, "parse_mode": "Markdown"}, timeout=10)
    data = resp.json()
    if data.get("ok"):
        print("✅ SUCCESS! Test alert received on Telegram!")
    else:
        print(f"❌ Telegram API returned an error: {data.get('description')}")
        print("Tip: Make sure you opened a chat with your bot and clicked 'START' before running this test.")
except Exception as e:
    print(f"❌ Network/Request error: {e}")
