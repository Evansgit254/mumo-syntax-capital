# 🏛️ Pure Quant Institutional Terminal (v5.4.1 - Deep History Stress Test)

> Deterministic alpha research, paper execution, and controlled deployment tooling.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Status: Research/Paper](https://img.shields.io/badge/Status-Research%2FPaper-cyan.svg)]()
[![Core: Deterministic](https://img.shields.io/badge/Logic-Pure%20Math-white.svg)]()

---

## 📖 Overview

The **Pure Quant Research Terminal** is a deterministic trading-signal research system with paper-execution infrastructure and a Native MT5 execution engine. Current database evidence supports research and paper validation; live broker performance is not yet proven by the active ledger.

The system is optimized for **H1/H4 Macro Trends** and **M5/M15 Institutional Execution Windows**, focusing on surgical entries within high-probability liquidity zones.

---

## 🚀 Active Alpha Modules

### 1. CRT (Candle Range Theory)
Authentic implementation of institutional range mechanics.
*   **Daily Bias**: D1 order flow synchronization.
*   **Killzone Logic**: Precise execution windows (London/NY).
*   **Range Forensics**: H1/H4 reference range tracking with M5 Market Structure Shifts (MSS).

### 2. Advanced Pattern
Maintained pattern-extension engine for strict price-action setups.
*   **Day-of-Week Context**: Pattern scoring respects recurring weekday behavior.
*   **Pin-Bar Stop Hunts**: Reversal detection around stop-run candle structures.
*   **Locked Scope**: CRT and Advanced Pattern are the only active signal engines.

### 3. Shared Structural Alpha Kernel
*   **Velocity Alpha**: Normalized momentum measurement for volatility-adjusted trend strength.
*   **Regime-Adaptive Filters**: Dynamic logic shifts between trending and mean-reverting states.
*   **Volatility Shield**: Precision ATR-relative gating (V5.3.2) to prevent low-volatility chop.

---

## Performance Matrix (Database-Derived)

Latest audited benchmark: `database/backtest_results.db`, Run ID `72` (30-day window), date range `2026-05-12` to `2026-06-11`.

| Metric | CRT Strategy (H1) | Advanced Patterns |
| :--- | :--- | :--- |
| **Closed Trades** | 2,318 | 9 |
| **Win Rate** | 55.0% | 55.6% |
| **Net Profit** | +584.1R | +5.4R |
| **Status** | Core baseline | Active research extension |

Run `72` is the current retained operational baseline. Active signal generation remains strictly limited to the CRT and Advanced Pattern engines.


---

## 🧪 Deployment & Auditing

### 1. Initialize Terminal
```bash
# Clone the institutional core
git clone https://github.com/Evansgit254/mumo-syntax-capital.git
cd mumo-syntax-capital

# Deploy Environment
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Run Forensic Generator
Generate high-conviction signals with full reasoning forensics:
```bash
python app/generate_signals.py
```

### 3. Integrated Management (v5.3.2+)
Manage backups, updates, and rollbacks using the native maintenance script:
```bash
./manage.sh status     # Check versioning and DB health
./manage.sh backup     # Snapshot the signals database
./manage.sh update     # Pull code and run migrations
./manage.sh rollback   # Revert to previous stable release
```

### 4. Backtesting (Realistic Friction)
Run the backtest engine with spread and slippage modeling (1.0 pip handicap):
```bash
# Recent window (default: last 30 days via yfinance)
python run_backtest_cli.py --days 30

# Custom date range
python run_backtest_cli.py --start 2025-01-01 --end 2025-06-30

# Selective symbols (skip slow crypto/crude downloads)
python run_backtest_cli.py --start 2022-01-02 --end 2025-12-31 \
  --symbols "EURUSD=X,GBPUSD=X,NZDUSD=X,USDJPY=X,AUDUSD=X,GBPJPY=X,GC=F"
```

### 5. Visual Dashboard
Generate an interactive HTML dashboard from the SQLite backtest results:
```bash
python generate_dashboard.py
```
View the resulting `backtest_dashboard.html` for equity curves and symbol-level analysis.

---

## 📊 Deep History Stress Testing (v5.4.1)

The system supports multi-year backtesting (2022–2025) using locally stored 1-minute bar data from [HistData.com](https://www.histdata.com/). This enables rigorous stress testing across different market regimes.

### Downloading Historical Data

Use the automated downloader to fetch M1 data for all supported forex pairs and gold:

```bash
# Automated download (fetches 28 ZIP files from HistData.com)
python scripts/download_histdata.py --download

# Extract and convert to Dukascopy-compatible CSVs
python scripts/download_histdata.py --extract
```

**Supported Symbols**: EURUSD, GBPUSD, NZDUSD, USDJPY, AUDUSD, GBPJPY, XAUUSD (Gold)
**Years Available**: 2022, 2023, 2024, 2025
**Total Data**: ~10 million M1 bars (~477 MB)

### Data Pipeline

The data pipeline resamples raw M1 bars into the required timeframes automatically:

```
HistData.com (M1 ZIPs) → scripts/download_histdata.py → data/dukascopy/<SYMBOL>/*.csv
                                                              ↓
                                                     DukascopyLoader.load()
                                                              ↓
                                                    M1 → M5 / M15 / H1 resample
                                                              ↓
                                                     BacktestEngine simulation
```

- **M5, M15, H1**: Resampled from local M1 data via `DukascopyLoader`
- **D1**: Fetched from yfinance (supports years of daily data natively)
- **BTC-USD**: Fetched from Binance via CCXT (requires `pip install ccxt`)

### Data Format

HistData files use semicolon-delimited ASCII format which is automatically parsed:
```
20220103 170100;1.13000;1.13050;1.12980;1.13020;0
```

---

## ⚡ Native MT5 Terminal (v5.4.3)
The system now operates exclusively via **Direct Native Execution**, completely bypassing cloud bridges like MetaAPI.

### Recommended Brokers & Setup

Depending on your capital size and trading style, two brokers are highly recommended for integration:

#### 1. HFM (HotForex) — *Recommended for low-capital/Cent accounts ($50 - $200)*
Cent accounts allow safe sizing with micro-lots since a $200 account is treated as 20,000 cents.
* **Suffix Configuration**: You **must** set `MT5_SYMBOL_SUFFIX=c` in your configuration (to parse pairs like `EURUSDc`).

#### 2. IC Markets — *Recommended for standard raw-spread accounts*
IC Markets raw-spread account offers near-zero spreads, matching the tight slippage/spread constraints modeling in the backtest system.
* **Suffix Configuration**: Leave `MT5_SYMBOL_SUFFIX=` empty.

### Setup (Windows)
1. **Requirements**: `pip install MetaTrader5`
2. **Broker**: Open your MT5 terminal (XM/HFM/IC Markets) and login locally.
3. **Configuration**:
   - `MT5_LOGIN`
   - `MT5_PASSWORD`
   - `MT5_SERVER`
   - `MT5_PATH` (for example `C:\Program Files\MetaTrader 5\terminal64.exe`)
   - `MT5_PAPER_MODE=false` (Set to `true` for paper testing)
   - `MT5_SYMBOL_SUFFIX=` (Set if your broker uses suffixes like `c` or `m`)

This mode offers **institutional-grade execution speed** and eliminates all cloud subscription fees and rate-limiting issues.

### Windows MT5 IPC Requirements

The native MT5 engine requires Python and `terminal64.exe` to run in the same Windows desktop context. On Windows VPS platforms such as AWS EC2:

- Open MT5 manually in the same RDP session before starting the backend.
- Match privilege levels. If Python is running as Administrator, MT5 must also run as Administrator.
- Avoid running the backend as a Windows service until MT5 connectivity has been verified interactively.
- `(-10005, 'IPC timeout')` means Python cannot communicate with the local MT5 process. It is usually a Windows IPC/session issue, not a broker login or AWS networking issue.
- In paper mode, the dashboard reads paper positions from SQLite and does not need MT5 initialization.

Useful test startup on Windows:

```powershell
cd C:\Users\Administrator\Desktop\mumo-syntax-capital\mumo-syntax-capital
.\.venv\Scripts\activate
$env:MT5_PATH="C:\Program Files\MetaTrader 5\terminal64.exe"
$env:MT5_CONNECT_TIMEOUT_MS="15000"
$env:MT5_CONNECT_MAX_RETRIES="1"
python admin_server.py
```

---

## 📂 System Architecture

```
├── app/                  # Terminal entry points & Dashboard API
├── core/                 # Mathematical Alpha Kernels & Risk Brain
│   ├── alpha_factors.py
│   ├── alpha_combiner.py
│   └── backtest_engine.py  # Multi-year simulation engine
├── strategies/           # Institutional Model Implementations
│   ├── crt_strategy.py
│   └── advanced_pattern_strategy.py
├── data/                 # Data layer
│   ├── fetcher.py          # yfinance real-time fetcher
│   ├── deep_fetcher.py     # Routes deep history (Dukascopy/CCXT)
│   └── dukascopy_loader.py # M1 CSV parser & resampler
├── scripts/              # Operational utilities
│   └── download_histdata.py  # Automated M1 data downloader
├── research/             # Quantitative Backtesting & Labs
├── tests/                # Unit/integration tests; not a 100% proof suite
└── dashboard/            # Institutional Grid UI (HTML/CSS)
```

---

## ⚠️ Risk & Transparency

Trading financial markets involves significant risk. Current performance metrics are based on local backtest database records. The active execution ledger contains paper orders/fills only; it does not prove live broker fill quality or live profitability.

## 🔐 Operational Safety

- Stripe webhook processing requires `STRIPE_WEBHOOK_SECRET` by default.
- Unsigned webhook payloads are only accepted when `ALLOW_UNSIGNED_STRIPE_WEBHOOK=true` is set for local development.
- Runtime configuration is centralized through `config/manager.py`, with `config/config.py` exposing compatibility snapshots for modules that still import constants.
- Admin config updates refresh the runtime config manager immediately, so service reads stay aligned with the database state within the same process.
- Live-trading toggles such as `mt5_auto_trade` and `mt5_paper_mode` require `risk_manager` access.
- Signal delivery reservation fails closed if the dedupe database is unavailable, so a storage fault will block delivery instead of duplicating it.
- Test markers now separate `integration`, `live`, and `authentic` coverage so local runs can skip external dependencies cleanly.

**System Version: 5.4.1 (Deep History Stress Test Update)**
