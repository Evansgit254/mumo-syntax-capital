# Authenticity Gap Assessment

System version: `5.4.3-native`

Assessment date: 2026-05-29

Engineering update: 2026-06-05

Baseline evidence:

- Backtest baseline: `database/backtest_results.db`, Run ID `69` (30-day Gold Standard)
- Verification baseline: `database/backtest_results.db`, Run ID `68` (Precision Shield)
- Active execution ledger: `database/signals.db`
- Current status: research-active prototypes with paper-execution baseline

## Current Rating

| Area | Rating |
| :--- | ---: |
| Code existence/authenticity | 8/10 |
| Research/backtest evidence | 6.5/10 |
| Live execution proof | 1/10 |
| Institutional readiness | 4/10 |
| Documentation honesty after updates | 8/10 |

## Primary Gaps

### 1. Live Execution Proof

The system has a Direct MT5 execution engine and order/fill tables, but the active ledger only shows `PAPER_EXECUTED` fills. There is no broker-side proof of real fills, slippage, commissions, swap, rejections, partial fills, or reconciliation.

### 2. Backtest Validity

Run `63` (Max deep history window) finalized the historical baseline logic. It definitively resolved the ExecutionGate cross-run temporal pollution bug. The previous high-density false-positive clusters (e.g. Run 58) were confirmed as database isolation violations and have been excised. Active development is now narrowed to CRT and Advanced Pattern only.

### 3. Strategy Quality

CRT has the strongest current evidence (>71% WR in Run 63). Advanced Patterns is promising but structurally under-sampled without strict PA mappings. All other strategy engines have been removed from active generation and dashboard strategy surfaces.

### 4. Data Fidelity

The system can fall back to `yfinance`. That is acceptable for research, but not enough for execution-grade signals. Broker candles, bid/ask, spread, and close-time alignment must become the source of truth for live deployment.

### 5. Risk And Portfolio Controls

Current controls now include configurable correlated exposure, strategy exposure, and session exposure gates in `ExecutionGate`. Remaining work is live calibration of those limits against broker-side open risk and realized drawdown.

### 6. Execution Governance

Live execution now fails closed unless `live_trading_approved=true`, Native MT5 Terminal credentials exist, and broker data mode is active when `require_broker_data_for_live=true`. A full maker-checker workflow is still not implemented; approval is currently a governed config key, not a two-person release process.

### 7. Ledger Quality

Paper fills currently include `filled_price=0.0` in the active DB. That makes the paper ledger insufficient for realistic execution analytics.

### 8. Test Coverage Quality

There are many tests, but some are shallow and the full suite previously showed hanging behavior. Key gaps remain around live config propagation, burst execution gating, broker reconciliation, and backtest no-lookahead guarantees.

### 9. Database Architecture

SQLite is acceptable for local research and a single-process bot. It is not ideal for 24/5 multi-worker execution state, order/fill ledgers, config governance, and audit trails. Postgres remains the likely production-grade target.

### 10. Monitoring And Reconciliation

Monitoring infrastructure exists. Broker reconciliation now records reconciliation runs and broker reconciliation events, and unmatched broker deals can populate the order/fill ledger. Remaining work is proving this against real broker traffic and extending drift metrics for stale reservations, execution latency, data latency, and slippage.

## Honest Classification

The system is an authentic engineering prototype and quant research terminal with paper-execution support plus live-execution guardrails. It is not yet an authenticated live trading product until real broker fills and reconciliation runs are captured.

## Documentation Rule

Until the above gaps are resolved, system documentation should avoid phrases such as:

- live-proven
- institutional-grade performance
- verified real-world execution
- production alpha

Acceptable phrasing:

- research-active
- paper-execution baseline
- backtest-derived evidence
- live execution not yet verified
