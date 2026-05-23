# Pure Quant Institutional Terminal (v28.0) — Technical Implementation Documentation

This document provides a comprehensive technical overview of the **Pure Quant Institutional Terminal**, an institutional-grade algorithmic engine designed for structural liquidity tracking and deterministic execution.

---

## 1. Architectural Philosophy
The terminal is built on **Structural Alpha Factors**. It rejects "black-box" machine learning in favor of pure institutional price action mechanics (ICT/SMC) and statistical mean reversion.

### Core Principles:
- **Structural Integrity**: Signals are derived from market transitions, not lagging indicators.
- **Liquidity Awareness**: Logic accounts for high-impact liquidity pools and "trap" zones.
- **Friction-Aware**: Modeling accounts for real-world spread, slippage, and swap.
- **Regime-Adaptive**: Logic shifts dynamically between Trend, Range, and Choppy market states.

---

## 2. Mathematical Kernels (Structural Alpha)

### A. Candle Range Theory (CRT) Modules
Authentic implementation of ICT Killzone mechanics.
- **Daily Bias Sync**: Dynamic D1 directional tracking.
- **Killzone Filtration**: Automated execution restriction to high-volatility sessions (London/NY).
- **MSS Logic**: Discovery of Market Structure Shifts on M5/M15 timeframes.

### B. Displacement Alpha (FVG)
- **Logic**: Algorithmic discovery of algorithmic price imbalances.
- **Feature**: Detects large-candle gaps that represent institutional "footprints."
- **Execution**: Optimizes entries at the 50% (Consequent Encroachment) or 0.25% levels of the displacement.

### C. Velocity Engine
- **Logic**: Normalized Linear Regression Slope.
- **Purpose**: Measures the unitless speed of price movement relative to its recent volatility to confirm trend validity.

---

## 3. Alpha Combiner & Decision Core

The `AlphaCombiner` aggregates structural factors into a final conviction score.

| Regime | Structural Weight | Momentum Weight | Volatility Multiplier |
| :--- | :--- | :--- | :--- |
| **EXPANSION** | 0.80 | 0.15 | 1.2x |
| **CONSOLIDATION** | 0.40 | 0.10 | 0.8x |
| **REVERSAL** | 0.60 | 0.30 | 1.0x |

---

## 4. Institutional Model Stack

### A. CRT Alpha (Candle Range Theory)
1.  **Reference Range**: Tracks the *previous* session/hour candle's extremes.
2.  **Sweep Forensic**: Detects "Liquidity Hunts" outside the range.
3.  **Displacement Entry**: Waits for MSS + FVG formation back inside the range.
4.  **Targeting**: Surgical TP hits at Equilibrium, Opposite Extreme, and Extended Deviation.

### B. SMC Liquidity Sweep
- **Asian Session Mapping**: Identifies the 00:00 - 07:00 UTC range.
- **Trap Identification**: Marks highs/lows as liquidity targets.
- **Reversal Kernel**: Statistical modeling of the "Fake-Out" before the real move.

---

## 5. Advanced Risk Management

The `RiskManager` is the system's "Safety Brain."

### Key Features:
- **Asymmetric Sizing**: Dynamically adjusts lot size based on proximity to high-impact news.
- **SATP (Spread-Adjusted Terminal Profit)**: Blocks trades if friction consumes >35% of the expected R-Multiple.
- **Layered Execution**: Automated position scaling (Aggressive -> Optimal -> Safety).

---

## 6. Global Integrity Filters
- **Macro Matrix**: Correlation scoring with the USD Index (DXY) to prevent over-exposure.
- **News Wash Zone**: Automated 30-minute blackout window around Red-Folder events.
- **Execution Guard**: Ensures 100% alignment between Signal Engine and MT5 Bridge state.

---

## 7. Backtesting & Verification
The system uses a **Forensic Backtest Suite** that:
1.  Simulates M5 tick-level price action for H1 models.
2.  Models realistic institutional friction (Institutional Raw Spreads).
3.  Calculates Profit Factor, Sharpe Ratio, and Maximum Drawdown.

---

## 8. Technology Stack
- **Language**: Python 3.12 (High-performance NumPy/Pandas integration).
- **Execution**: Async Signal Service + Institutional Dashboard.
- **Broker Bridge**: Python MetaTrader 5 API Gateway.
- **Interface**: High-Density Institutional Dashboard (Tailwind/JS).

---

## 9. Conviction Matrix
| Model | Win Rate Target | Expectancy |
| :--- | :--- | :--- |
| **CRT (H1)** | 30-35% | 0.75R+ |
| **SMC Sweep (M5)** | 40-45% | 0.45R+ |

---

## 10. Optimization Vectors
*When utilizing the AI Optimization Layer:*
1.  **Liquidity Map Decay**: Are Asian session traps losing edge in the current regime?
2.  **FVG Sensitivity**: Fine-tuning displacement thresholds for low-volatility periods.
3.  **Macro Weighting**: Improving the DXY correlation filter for multi-pair baskets.
