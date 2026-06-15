# Windows VPS Deployment Guide

To deploy your Pure Quant SMC Scalp Signals system and begin monetizing via live execution and Telegram subscriptions, follow these steps to migrate the system to a 24/7 Windows Virtual Private Server (VPS).

> [!IMPORTANT]  
> **Prerequisites:**
> - A Windows VPS (e.g., AWS EC2 Windows, Contabo, Vultr)
> - MetaTrader 5 installed on the VPS
> - A Telegram Bot Token from BotFather

## Step 1: Prepare the VPS Environment
1. Log into your Windows VPS via Remote Desktop (RDP).
2. Download and install **Python 3.10+** (Ensure you check the box that says "Add Python to PATH" during installation).
3. Open your Broker's MetaTrader 5 Terminal, log into your live account, and ensure "Auto Trading" is enabled in the top toolbar. 
4. In MT5, go to `Tools -> Options -> Expert Advisors` and check "Allow automated trading" and "Allow WebRequest for listed URL".

## Step 2: Transfer the Codebase
1. Zip this entire project folder on your Mac.
2. Transfer the zip file to your VPS (you can usually copy-paste directly through RDP, or use Google Drive/Dropbox).
3. Unzip the folder onto the VPS Desktop.

## Step 3: Configure the Environment
1. Inside the unzipped folder, rename `.env.example` to `.env`.
2. Open `.env` in a text editor (like Notepad) and fill in the critical production values:
   - `MT5_LOGIN`: Your MT5 account number
   - `MT5_PASSWORD`: Your MT5 password
   - `MT5_SERVER`: The exact server name of your broker (e.g., `MetaQuotes-Demo`)
   - `TELEGRAM_BOT_TOKEN`: Your token from BotFather
   - `TELEGRAM_CHAT_ID`: Your admin Telegram ID
   - `JWT_SECRET`: A long random string
   - `ADMIN_PASS`: A strong password for the dashboard
3. Change the Live Trading Flags in `.env`:
   - `MT5_PAPER_MODE=false`
   - `LIVE_TRADING_APPROVED=true`

## Step 4: Launch the System
1. Double-click the `start_vps.bat` file.
2. A command prompt window will open. The script will automatically:
   - Create a Python virtual environment.
   - Install all required dependencies (including `MetaTrader5` for Windows).
   - Start the Admin API Server on port 5000.
   - Start the `signal_tracker.py` engine to listen for SMC setups.
3. The system is now live! Open `http://localhost:5000` in the VPS browser to view your dashboard, add Telegram clients, and monitor live trades.

> [!WARNING]  
> Do not close the command prompt window, or the trading engine will stop. Keep the VPS running 24/7.
