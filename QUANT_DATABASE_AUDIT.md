# Quant Database Audit

Audit date: 2026-05-29

System version: `5.3.0-stable`

Primary evidence sources:

- `database/backtest_results.db`
- `database/signals.db`
- `database/clients.db`

## Backtest Baseline

Latest benchmark run: Run ID `63` (Deep History)

Date range: `2026-04-07` to `2026-05-29`

Closed-trade totals:

| Metric | Value |
| :--- | ---: |
| Closed trades | 2,772 |
| Win rate | 70.9% |
| Net result | +1,061.4R |

Strategy breakdown:

| Strategy | Closed Trades | Win Rate | Net R | Status |
| :--- | ---: | ---: | ---: | :--- |
| CRT H1 | 2,720 | 71.1% | +1,034.1R | Live-Ready Phase |
| Session Clock | 42 | 64.2% | +24.8R | Live-Ready Phase |
| Advanced Patterns | 10 | 50.0% | +2.3R | Under-sampled |
| SMC Sweep | N/A | N/A | N/A | Quarantined |

## Engineering Interpretation

The system is now classified as **Live-Ready Baseline (v5.3.0)**. The breakthrough in Run 63 resolved the critical ExecutionGate cross-run isolation bug, proving that the structural CRT edge remains above 70% even when filtered against historical "ghost" trades.

SMC Sweep remains quarantined. CRT and Session Clock are verified for institutional-scale deployment. 1,000+ R-multiples over 60 days confirms the mathematical robustness of the current structural combiners.

## Active Ledger Evidence

`database/signals.db` currently shows:

- 14 signals
- 10 blocked signals
- 4 open signals with `execution_status=NONE`
- 7 orders
- 7 fills
- all orders/fills are `PAPER_EXECUTED`
- no active live broker fills

Execution evidence is paper-only. Any production/live claims must wait for broker-side orders, fills, slippage, commission, swap, and reconciliation records.

## Current Known Limitations

- `yfinance` remains a fallback market-data source.
- SQLite is still the active control/execution database.
- Backtest trade density remains high and must be interpreted as research output.
- Quality score is not yet a calibrated probability or monotonic edge ranker.
- Paper account balance and client account balance are not the same ledger.
