#!/usr/bin/env bash
# ==============================================================================
# MEXC Pre-Pump Scanner: DigitalOcean Droplet Automated Setup Script
# Ubuntu 22.04 / 24.04 LTS
# ==============================================================================

set -e

APP_DIR="/opt/mexc-pre-pump-scanner"
SERVICE_NAME="mexc-scanner"

echo "=========================================================="
echo " Starting MEXC Pre-Pump Scanner Droplet Setup..."
echo "=========================================================="

# 1. Update system packages
echo "[1/5] Updating APT package repositories..."
sudo apt update -y
sudo apt install -y python3 python3-pip python3-venv git curl ufw

# 2. Setup destination directory if running outside /opt
if [ "$PWD" != "$APP_DIR" ]; then
    echo "[2/5] Creating application directory at $APP_DIR..."
    sudo mkdir -p "$APP_DIR"
    sudo cp -r ./* "$APP_DIR/"
    cd "$APP_DIR"
fi

# 3. Create Python virtual environment
echo "[3/5] Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 4. Ensure directories exist
mkdir -p data logs

# Check for .env file
if [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "NOTE: Edit /opt/mexc-pre-pump-scanner/.env to add your Discord/Telegram webhooks."
fi

# 5. Install and enable systemd service
echo "[4/5] Configuring systemd background service..."
sudo cp mexc-scanner.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME
sudo systemctl restart $SERVICE_NAME

echo "=========================================================="
echo " SETUP COMPLETE!"
echo "=========================================================="
echo " The scanner is now running 24/7 in the background."
echo ""
echo " Useful Management Commands:"
echo "   • Check status:      sudo systemctl status $SERVICE_NAME"
echo "   • View live logs:    tail -f $APP_DIR/logs/scanner.log"
echo "   • Restart scanner:   sudo systemctl restart $SERVICE_NAME"
echo "   • Stop scanner:      sudo systemctl stop $SERVICE_NAME"
echo "   • Edit webhooks:     nano $APP_DIR/.env && sudo systemctl restart $SERVICE_NAME"
echo "=========================================================="
