# Windows VPS Deployment Guide

To deploy your Pure Quant Mumo Syntax & Capital system and begin monetizing via live execution and Telegram subscriptions, follow these steps to migrate the system to a 24/7 Windows Virtual Private Server (VPS).

> [!IMPORTANT]  
> **Prerequisites:**
> - A Windows VPS (e.g., AWS EC2 Windows, Contabo, Vultr)
> - MetaTrader 5 installed on the VPS
> - A Telegram Bot Token from BotFather

## Step 1: Prepare the VPS Environment
1. Log into your Windows VPS via Remote Desktop (RDP).
2. Download and install **Python 3.10+** (Ensure you check the box that says "Add Python to PATH" during installation).
3. Open your Broker's MetaTrader 5 Terminal, log into your live or demo account, and ensure "Auto Trading" is enabled in the top toolbar.
4. In MT5, go to `Tools -> Options -> Expert Advisors` and check "Allow automated trading" and "Allow WebRequest for listed URL".
5. Keep MT5 and the Python backend in the same Windows user session. For initial testing, do not run the backend as a Windows service.

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
   - `MT5_PATH`: The exact terminal path, usually `C:\Program Files\MetaTrader 5\terminal64.exe`
   - `TELEGRAM_BOT_TOKEN`: Your token from BotFather
   - `TELEGRAM_CHAT_ID`: Your admin Telegram ID
   - `JWT_SECRET`: A long random string, at least 32 bytes
   - `ADMIN_PASS`: A strong password for the dashboard
3. Change the Live Trading Flags in `.env`:
   - Start with `MT5_PAPER_MODE=true` while validating MT5 connectivity and dashboard behavior.
   - Only set `MT5_PAPER_MODE=false` and `LIVE_TRADING_APPROVED=true` after MT5 connectivity is verified and you intentionally approve live execution.
4. Optional MT5 connection tuning:
   - `MT5_CONNECT_TIMEOUT_MS=15000`
   - `MT5_CONNECT_MAX_RETRIES=1`
   - `MT5_CONNECT_RETRY_DELAY_SECONDS=5`
   - `MT5_CONNECT_FAILURE_BACKOFF_SECONDS=60`
   - `MT5_STATUS_CACHE_SECONDS=30`

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

## MT5 IPC Timeout Troubleshooting

If the logs show:

```text
(-10005, 'IPC timeout')
```

Python cannot communicate with the local `terminal64.exe`. This is a Windows/MT5 IPC problem, not usually an AWS or broker-network problem.

Use this checklist:

1. Confirm MT5 is open on the VPS desktop and logged into the correct broker account.
2. Confirm the MT5 bottom-right connection status is live, not disconnected.
3. Make sure Python and MT5 run under the same Windows user and privilege level.
   - If the log says `Python Process Administrator Status: True`, open MT5 as Administrator too.
   - Or run both MT5 and Python as a normal user.
4. Do not run `admin_server.py` as a Windows service while testing MT5 IPC. Services often run in Session 0 and cannot communicate with the MT5 app opened in your RDP desktop session.
5. Kill stale MT5 processes and restart cleanly:

```powershell
taskkill /F /IM terminal64.exe
Start-Process "C:\Program Files\MetaTrader 5\terminal64.exe" -Verb RunAs
```

6. After MT5 is open and logged in, start the backend from a PowerShell window with the same privilege level:

```powershell
cd C:\Users\Administrator\Desktop\mumo-syntax-capital\mumo-syntax-capital
.\.venv\Scripts\activate
$env:MT5_PATH="C:\Program Files\MetaTrader 5\terminal64.exe"
$env:MT5_CONNECT_TIMEOUT_MS="15000"
$env:MT5_CONNECT_MAX_RETRIES="1"
python admin_server.py
```

If MT5 still times out, restart the Windows VPS and repeat the clean-start sequence before attempting live execution.

## Dashboard Notes

- `/api/mt5/status` is cached briefly to avoid hammering MT5 during dashboard polling.
- Failed MT5 connection attempts enter a short cooldown before another full retry sequence.
- In paper mode, open positions are read from the local SQLite paper ledger and should not initialize MT5.
- `401 Unauthorized` after a backend restart usually means the browser token no longer matches the server signing key. Log into the dashboard again.
