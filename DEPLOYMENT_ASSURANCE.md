# Deployment Assurance: V33.0 Core Refactor

This document details exactly what is inside the refactored system being deployed.

## 1. The Safety Layers (Gates)

We are deploying a **Triple-Gate** system. A signal must pass all three to reach your Telegram/MT5:

| Layer | Gate | Purpose |
| :--- | :--- | :--- |
| **Trend Guard** | EMA 200 | Blocks "Counter-Trend" buys below the EMA or sells above it. Ensures we trade with the intermediate-term momentum. |
| **Institutional Boost**| ICT Confluence | CRT setups must show a "Sweep Extreme" (taking liquidity) or high displacement. Without this "Institutional" signature, the quality score remains low. |
| **Quality Gate** | 7.0 Threshold | The system blocks any signal with a Quality Score below 7.0. Because we added the "Institutional Boost," only the cleanest CRT setups will pass this gate. |

## 2. Why this is "Safer" than the old VM System

- **Old VM System**: Used a simpler Swing strategy that often ignored the broader H1 trend and lacked a rigorous quality scoring mechanism. It was prone to "price bounce flooding."
- **Refactored System**:
    - **Deduplication**: Uses an MD5 hash of (Symbol + Direction + Timeframe) to ensure you don't get 5 alerts for the same trade.
    - **Regime Awareness**: Detects if the market is "Trending" or "Ranging" and adjusts weights dynamically.
    - **Fixed Execution Bias**: Path-aware backtesting ensures results are HONEST.

## 3. New Performance Metrics (R-Multiples)

We are moving away from "Pips" because they are misleading across different symbols.
- **Reporting**: All backtests and live results will show performance in **R**.
- **The edge**: A win rate of 50% with a 2.0R average win is a highly profitable system.

## 4. The "Fresh Start" Protocol

- **Empty Database**: Starting with a clean `signals.db`.
- **Portable Code**: Path-independent logic works everywhere.
- **Auto-Deployment**: `fresh_deploy.sh` handles the migration exactly as verified locally.

---

### Assurance Checklist
- [x] EMA 200 Filter: **ACTIVE**
- [x] Quality Score (7.0): **ACTIVE**
- [x] MT5 Auto-Trade: **PAPER MODE** (Safe Start)
- [x] Deduplication: **ACTIVE** (45 min window)
- [x] Path Independence: **VERIFIED**
