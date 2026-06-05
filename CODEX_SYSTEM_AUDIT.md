# CODEX SYSTEM AUDIT: Pure Quant Research Terminal

Date: 2026-06-05
Current version: `5.4.3-native`  
Scope: FastAPI backend, Stitch/vanilla dashboard, SQLite persistence, Native MT5 execution engine, execution gate, data fidelity, and governance.

## 2026-05-29 Quant Database Update

Baseline: `database/backtest_results.db`, Run ID `58`, date range `2026-05-01` to `2026-05-29`.

Run `58` closed-trade summary:

- Total closed trades: `8,901`
- Win rate: `58.68%`
- Net result: `+856.59R`
- Profit factor: `1.23`
- Computed max drawdown: `463.56R`

Strategy-level result for Run `58`:

| Strategy | Trades | Win Rate | Net R | Avg R | PF | Status |
| :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| CRT H1 | 8,115 | 61.77% | +1,029.52 | +0.127 | 1.33 | Research-active |
| Advanced Patterns | 19 | 73.68% | +15.90 | +0.837 | 4.18 | Promising but under-sampled |

**[Addendum: 2026-06-04] System Overhaul (Version 5.3.0) & 30-Day Dashboarding**
Following a forensic investigation into earlier false-positive trade densities and the subsequent "zero trade" blocking bugs, the ExecutionGate was refactored with strict `run_id` isolation. Run 1 (30-day window: `2026-05-05` to `2026-06-04`) stands as the mathematically clean institutional baseline.

**Run 1 Final Strategy Breakdown:**
| Strategy | Trades | Win Rate | Net R | Status |
| :--- | ---: | ---: | ---: | :--- |
| CRT H1 | 1,651 | 70.9% | +670.9R | Core baseline |
| Advanced Patterns | 8 | 62.5% | +4.4R | Active research extension |

Engineering actions applied from this audit:

- Active signal generation and default backtests are limited to CRT and Advanced Patterns.
- Backtests now use a timestamp-aware open-position check in `ExecutionGate`, so simulated trades remain blocking until their `closed_at` time has passed.
- Documentation now distinguishes backtest evidence from paper/live execution evidence.

Execution evidence boundary:

- Active `database/signals.db` contains paper-only orders/fills.
- There is no active ledger evidence of live broker fills, live slippage, or live profitability.
- Any live-readiness language must remain conditional until broker-side fills and reconciliation records exist.

## Executive Summary

This is the active project audit for `/home/evans/Projects/smc-scalp-signals`.

The current codebase is advanced and it already includes encrypted Native MT5 credential persistence, role-aware admin users, a Native-backed `TradeExecutor`, an `ExecutionGate`, persistent trade reservations, strategy toggles, and execution state fields on `signals`.

The remaining institutional-readiness work is now narrower:

- Ensure persisted config changes are validated, versioned, and actually consumed by live strategy/risk code.
- Ensure high-frequency bursts are idempotent across restarts/workers without overblocking distinct valid signals.
- Preserve an immutable execution-event trail rather than relying only on mutable signal rows.
- Continue moving live execution tracking away from yfinance toward broker tick/position reconciliation.
- Eventually migrate execution-critical state from SQLite to Postgres for 24/5 multi-worker operation.

## Remediation Applied

Implemented in this pass:

- Added `core/db_utils.py` with consistent SQLite WAL, `busy_timeout`, row factory setup, and audit-event helpers.
- Updated admin DB access to use the shared connection helper.
- Added `version` support for `system_config`.
- Added typed config validation for risk, status, strategy toggles, data provider, and MT5 execution settings.
- Blocked arbitrary unknown config writes through `/api/config`.
- Added structured `audit_events` alongside the existing `config_audit`.
- Added audit events for config updates, data-provider changes, Native MT5 credential updates, and regime-driven threshold updates.
- Updated regime detection to version and audit `min_quality_score`.
- Fixed dynamic config propagation for `risk_per_trade`, `min_quality_score`, `min_quality_score_intraday`, `max_concurrent_trades`, `mt5_auto_trade`, and `mt5_paper_mode`.
- Updated risk sizing and major strategies to read dynamic config values at decision time instead of relying on stale imported constants.
- Added persistent `signal_gate` idempotency for exact signal delivery suppression across process restarts/workers.
- Added `idempotency_key` to logged signals and a unique index for deduplication.
- Hardened `ExecutionGate._get_thresholds()` so a missing optional `weight_overrides` table does not prevent reading `system_config`.
- Added `execution_events` logging in `TradeExecutor` so execution transitions are append-only, not only reflected in mutable `signals` fields.
- Stripe webhook handling now requires `STRIPE_WEBHOOK_SECRET` unless `ALLOW_UNSIGNED_STRIPE_WEBHOOK=true` is explicitly enabled for development.
- Live-trading config keys (`mt5_auto_trade`, `mt5_paper_mode`) now require `risk_manager` access to change through the admin API.
- Signal delivery reservation now fails closed when the dedupe database is unavailable.
- Test metadata now distinguishes `integration`, `live`, and `authentic` coverage for clearer local versus external selection.

## Critical Vulnerabilities And Status

### 1. Config State Drift

**Status:** Partially remediated.

Risk:

- Runtime config was DB-persistent, but several strategy/risk modules imported constants at module import time.
- General config API accepted arbitrary keys and values.
- Regime detector could change `min_quality_score`, but not all live consumers reliably read the updated value.

Remediation:

- Config updates are now validated by key and type.
- Config rows are versioned and audited.
- Risk sizing and key strategies now read from the centralized `config_manager` at decision time, with `config/config.py` retained as a compatibility snapshot.
- Signal service refreshes the centralized config manager during `_load_dynamic_config()` and maps DB keys into runtime fields through that layer.

Remaining:

- Replace module-level config mutation with a dedicated typed `ConfigService`.
- Add integration tests proving DB config changes affect signal decisions in the same cycle.

### 2. SQLite Concurrency

**Status:** Improved, not fully institutional.

Risk:

- SQLite WAL helps, but multi-worker writes can still collide.
- Runtime schema mutation still exists in service startup/logging paths.
- Execution, config, signals, reservations, and audit events all share file-backed SQLite.

Remediation:

- Shared connection helper applies WAL and `busy_timeout`.
- Config writes use explicit transactional updates where governance matters.
- Exact signal delivery dedup is now DB-backed.

Remaining:

- Move schema mutation into migrations only.
- Migrate control-plane and execution-plane state to Postgres before true multi-worker institutional deployment.

### 3. Execution Gate And Burst Handling

**Status:** Improved.

Existing strengths:

- `ExecutionGate.validate_and_reserve()` atomically reserves symbol inventory.
- Existing position checks block pyramiding.
- Daily loss and minimum quality thresholds are supported.

Risk:

- Previous in-memory signal dedup did not survive restart.
- Symbol-level reservations may intentionally block multiple signals on the same symbol, which is safe for risk but can reject separate valid liquidity events.

Remediation:

- Added `signal_gate` for exact signal idempotency.
- Exact duplicates are blocked using symbol, direction, timeframe, strategy, trade type, timestamp/data timestamp, entry, SL, and TP.
- Symbol-level risk reservation remains separate from exact delivery deduplication.

Remaining:

- Correlated exposure groups are now enforced for major currencies, metals, oil, and crypto.
- Configurable strategy and session exposure budgets now supplement no-pyramiding.
- Add per-symbol burst budgets if the system later needs multiple valid liquidity events on the same symbol.

### 4. Native MT5 Execution Reliability

**Status:** Remediated (V5.4.3).

Existing strengths:

- `TradeExecutor` uses `DirectMT5Engine` for native terminal execution.
- Paper mode is default.
- Live/paper execution status is persisted on `signals`.
- Partial fill is detected when returned volume is below requested lot size.

Risk:

- MetaAPI cloud dependencies have been completely purged.
- Execution state is tracked via `execution_events`.

Remediation:

- Added `execution_events` append-only table for every persisted execution transition.
- Existing state fields continue to support dashboard reads.

Remaining:

- Prove `orders`, `fills`, reconciliation runs, and broker reconciliation events against real broker traffic.
- Persist request payload, raw broker response, latency, commission, swap, and residual volume.
- Add retry policy with idempotent client order identifiers.

### 5. Paper Mode Versus Live Broker Reality

**Status:** Open.

Risk:

- Paper mode assumes the scored entry and requested lot are executable.
- Live fills may have slippage, partial fill, widened spread, or rejection.
- Tracker still has yfinance-derived assumptions in parts of the system.

Required:

- Broker-side pre-trade bid/ask validation before live order submission.
- Broker tick/position reconciliation for SL/TP and open risk.
- Slippage and partial-fill analytics by symbol/session/provider.

Update: live execution now performs a pre-trade broker spread check and refuses live orders when explicit approval, credentials, or broker data mode are missing. Broker reconciliation is scheduled and records auditable reconciliation runs/events, but still needs real broker evidence.

### 6. Data Fidelity And Regime Drift

**Status:** Open.

Risk:

- Regime and macro bias are based on yfinance REST candles.
- Execution happens on broker symbols through local Native MT5 terminal.
- yfinance can be delayed, adjusted, incomplete, or structurally different from broker candles.

Required:

- Stamp every signal with source, candle close time, and data latency.
- Score only closed candles.
- Use broker quote validation immediately before execution.
- Add drift monitoring between yfinance close and broker bid/ask at decision time.

### 7. Credential Security

**Status:** Improved.

Existing strengths:

- `core/secure_config.py` protects `mt5_login`, `mt5_password`, and `mt5_server`.
- API config responses redact secret values.
- Native MT5 config endpoint refuses storage if encryption is unavailable.

Remaining:

- Prefer a dedicated `CONFIG_ENCRYPTION_KEY` over falling back to `JWT_SECRET`.
- Ensure database backups never expose encrypted credentials through casual dashboard download workflows.
- Add credential rotation metadata.

### 9. Webhook And Live-Trade Governance

**Status:** Improved.

Risk:

- Unsigned payment webhooks can activate subscriptions if the secret is missing.
- Live-trading toggles should not be writable by broad operator access.
- Delivery gating should never fail open when the dedupe table cannot be written.

Remediation:

- Stripe webhook processing now rejects unsigned requests unless an explicit development bypass is enabled.
- Live-trading toggles are restricted to `risk_manager` access.
- Signal delivery reservation now fails closed on storage faults.

Remaining:

- Keep the unsigned webhook bypass limited to non-production use.
- Add explicit approval/audit metadata for live-trade toggle changes if the system is expanded to more operators.

### 8. Permission Model

**Status:** Improved, but incomplete.

Existing strengths:

- Users carry a role.
- `require_role()` protects config and Native MT5 credential endpoints.

Remaining:

- Add explicit `viewer`, `operator`, `risk_manager`, `executor`, and `admin` policy documentation.
- Add maker-checker approval for live execution enablement.
- Audit login success/failure and permission denials.

## 10. Operational Scalability

Scaling from 1 to 50 symbols still stresses:

- yfinance request volume.
- thread executor saturation.
- SQLite write locks.
- signal cycle latency.
- Telegram rate limits.

Recommended next steps:

- Bounded concurrent market-data fetches.
- Separate signal worker from FastAPI process.
- Move durable state to Postgres.
- Add Prometheus-style metrics for fetch latency, signal count, gate blocks, execution latency, slippage, and DB write failures.

## Next Engineering Priorities

1. Run a controlled live-broker proof cycle and archive orders, fills, reconciliation runs, slippage, commission, swap, and rejection evidence.
2. Add retry policy with idempotent client order identifiers and latency capture.
3. Move schema changes out of runtime code into migrations.
4. Add maker-checker workflow before `MT5_AUTO_TRADE=true` can be enabled for non-paper trading.
5. Add Postgres migration plan for `system_config`, `signals`, `trade_reservations`, `execution_events`, `orders`, `fills`, `reconciliation_runs`, `broker_reconciliation_events`, and `audit_events`.

## Readiness Verdict

The terminal is materially safer after this pass, especially around config governance, exact signal idempotency, live-readiness blocking, exposure controls, and execution auditability. It is still not fully institutional 24/5-ready until real broker evidence, maker-checker approval, retry/idempotency policy, and Postgres-backed state are implemented.
