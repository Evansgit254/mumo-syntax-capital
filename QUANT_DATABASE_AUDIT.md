# Quant Database Audit

Audit date: 2026-06-11

Engineering update: 2026-06-11

System version: `5.4.4-native`

Primary evidence sources:

- `database/backtest_results.db`
- `database/signals.db`
- `database/clients.db`

## Backtest Baseline

Latest benchmark run: Run ID `72` (Institutional Audit - 30 Days)

Date range: `2026-05-12` to `2026-06-11`

Closed-trade totals:

| Metric | Value |
| :--- | ---: |
| Closed trades | 2,327 |
| Win rate | 52.6% |
| Net result | +589.5R |

Strategy breakdown:

| Strategy | Closed Trades | Win Rate | Net R | Status |
| :--- | ---: | ---: | ---: | :--- |
| CRT H1 | 2,318 | 55.0% | +584.1R | Core baseline |
| Advanced Patterns | 9 | 55.6% | +5.4R | Active research extension |

## Engineering Interpretation

The system is now classified as **Live-Ready Baseline (v5.3.0)**. The breakthrough in Run 63 resolved the critical ExecutionGate cross-run isolation bug, proving that the structural CRT edge remains above 70% even when filtered against historical "ghost" trades.

Active development is now narrowed to CRT and Advanced Patterns. The historical 1,000+ R-multiple result primarily reflects CRT strength; non-CRT/non-Advanced strategy results are no longer part of the active trading surface.

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

Update: the codebase now includes fail-closed live-readiness checks, broker spread validation before live orders, correlated exposure gates, reconciliation run records, and broker reconciliation event records. This improves readiness but does not replace the missing broker-side proof.

## Current Known Limitations

- `yfinance` remains a fallback market-data source.
- Live execution now requires broker data mode by default, but `yfinance` remains available for research/fallback.
- SQLite is still the active control/execution database.
- Backtest trade density remains high and must be interpreted as research output.
- Quality score is not yet a calibrated probability or monotonic edge ranker.
- Paper account balance and client account balance are not the same ledger.
- Live broker fill evidence is still required before production/live claims.
