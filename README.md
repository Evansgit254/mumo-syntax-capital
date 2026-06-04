# 🏛️ Pure Quant Institutional Terminal (v5.3.3 - Direct Execution)

> Deterministic alpha research, paper execution, and controlled deployment tooling.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Status: Research/Paper](https://img.shields.io/badge/Status-Research%2FPaper-cyan.svg)]()
[![Core: Deterministic](https://img.shields.io/badge/Logic-Pure%20Math-white.svg)]()

---

## 📖 Overview

The **Pure Quant Research Terminal** is a deterministic trading-signal research system with paper-execution infrastructure and a MetaAPI execution bridge. Current database evidence supports research and paper validation; live broker performance is not yet proven by the active ledger.

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

Latest audited benchmark: `database/backtest_results.db`, Run ID `69` (30-day window), date range `2026-05-06` to `2026-06-05`.

| Metric | CRT Strategy (H1) | Advanced Patterns |
| :--- | :--- | :--- |
| **Closed Trades** | 1,693 | 31 |
| **Win Rate** | 67.9% | 51.6% |
| **Net Profit** | +564.0R | +6.1R |
| **Status** | Core baseline | Active research extension |

Run `69` is the current retained operational baseline. Active signal generation remains strictly limited to the CRT and Advanced Pattern engines.

---

## 🧪 Deployment & Auditing

### 1. Initialize Terminal
```bash
# Clone the institutional core
git clone https://github.com/Evansgit254/smc-scalp-signals.git
cd smc-scalp-signals

# Deploy Environment
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
python run_backtest_cli.py --days 30
```

### 5. Visual Dashboard
Generate an interactive HTML dashboard from the SQLite backtest results:
```bash
python generate_dashboard.py
```
View the resulting `backtest_dashboard.html` for equity curves and symbol-level analysis.

---

## ⚡ Direct MT5 Mode (v5.3.3)
For XM, HFM, and other MT5 brokers, the system now supports **Direct Execution** bypassing the MetaAPI bridge.

### Setup (Windows)
1. **Requirements**: `pip install MetaTrader5`
2. **Broker**: Open your MT5 terminal (XM/HFM) and login locally.
3. **Configuration**:
   - `MT5_USE_DIRECT=true`
   - `MT5_PAPER_MODE=false` (Set to `true` for paper testing)
   - `MT5_SYMBOL_SUFFIX=` (Set if your broker uses cent suffixes like `.m`)

This mode offers **sub-millisecond execution** and removes all cloud subscription fees.

---

## 📂 System Architecture

```bash
├── app/                # Terminal entry points & Dashboard API
├── core/               # Mathematical Alpha Kernels & Risk Brain
│   ├── alpha_factors.py
│   └── alpha_combiner.py
├── strategies/         # Institutional Model Implementations
│   ├── crt_strategy.py
│   └── advanced_pattern_strategy.py
├── research/           # Quantitative Backtesting & Labs
├── tests/              # Unit/integration tests; not a 100% proof suite
└── dashboard/          # Institutional Grid UI (HTML/CSS)
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

**System Version: 5.3.2 (Precision Shield Update 68)**
