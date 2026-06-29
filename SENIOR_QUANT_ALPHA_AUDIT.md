# Senior Quant Alpha And System Audit

Audit date: 2026-06-30

Scope: active alpha generation, strategy scoring, backtest/research methodology, execution gating, risk sizing, data-provider assumptions, and operational safeguards.

Code-change status: documentation only. This audit did not modify alpha logic, strategy code, risk code, execution code, or configuration.

## Executive Verdict

The active alpha path is coherent and the focused alpha/gate/risk test suite passes. The system has meaningful engineering controls around signal delivery, idempotency, and execution gating.

The main quant risk is not a visible implementation break. The main risk is research validity: several live production constants and gates appear to be derived from recent forensic/backtest observations, then embedded directly into the strategy and risk logic. Without strict walk-forward separation, those rules can inflate apparent edge and hide overfit.

Current classification:

- Engineering state: functional active research system.
- Quant research state: promising but not yet research-grade validated.
- Live deployment state: conditional; broker-side fill, slippage, spread, commission, swap, and reconciliation evidence is still required before strong live-performance claims.

## Verification Performed

Focused tests run:

```bash
python3 -m pytest tests/test_alpha_factors.py tests/test_alpha_combiner.py tests/test_alpha_combiner_logic.py tests/test_crt_strategy.py tests/test_v23_advanced_patterns.py tests/test_integrity.py tests/test_risk_unit.py tests/test_risk_manager_fixed.py
```

Result:

```text
60 passed in 2.47s
```

An attempted full-suite pytest run collected 319 selected tests, but did not produce a completed result before the session ended. It is not counted as verified.

An attempted `npm test` command failed because the repository has no `package.json`; this is a Python project. It did not affect code.

## Positive Findings

### 1. Main Signal Service Gates Before Broadcast And Execution

The main service validates and reserves a signal before broadcast or MT5 execution. This is a strong operational control because blocked signals are logged but not broadcast or executed.

Evidence:

- `signal_service.py` validates with `ExecutionGate.validate_and_reserve()`.
- Gate status and reason are persisted.
- Broadcast happens only after a passed gate.
- MT5 execution is attempted only after the signal passes the same gate path.

### 2. Focused Alpha/Gate/Risk Tests Pass

The tests covering alpha factors, alpha combiner behavior, CRT strategy behavior, advanced pattern behavior, execution-gate integrity, and risk sizing passed.

This does not prove alpha validity, but it does show that the expected local behavior is currently stable.

### 3. Backtest Exit Simulation Uses Future Bars Only

The main `BacktestEngine` constructs point-in-time data bundles for signal generation and uses future entry-timeframe bars only for exit simulation. That is directionally correct and avoids the most obvious form of look-ahead in trade outcome calculation.

### 4. Incomplete Live Evidence Is Documented Elsewhere

Existing docs already separate paper/backtest evidence from live broker evidence. That distinction should be preserved.

## Ranked Findings

### High: Forensic Tuning Is Embedded Directly In Live Alpha Logic

Files:

- `strategies/crt_strategy.py`
- `core/filters/risk_manager.py`

Examples:

- CRT blocks specific "toxic" hours from prior forensic observations.
- CRT applies a hard `base_boost = 4.5` to help clear the quality gate.
- Risk sizing increases exposure during selected "power hours" based on prior run observations.

Risk:

These may be valid production controls, but they are not neutral alpha definitions. They encode past observed performance directly into current live behavior. If the same data was used to discover, tune, and evaluate these rules, reported edge may be materially overstated.

Quant recommendation:

Promote each such rule into an explicit research parameter with:

- discovery window,
- validation window,
- out-of-sample test window,
- sample size,
- expected effect size,
- confidence interval,
- decay monitoring rule.

Do not treat these constants as proven until they survive walk-forward testing.

### High: Advanced Pattern Strategy Uses Very Small-Sample Hard-Coded Edges

File:

- `strategies/advanced_pattern_strategy.py`

Examples:

- DOW/hour/symbol rules are hard-coded from recent research comments.
- One visible rule references `4/4 WR`, which is not enough sample size for deployable statistical confidence.

Risk:

Small-sample day-of-week/hour effects are highly prone to false discovery, especially when many symbols, hours, directions, and filters were searched.

Quant recommendation:

Treat Advanced Patterns as an exploratory sleeve until it has:

- multi-year validation,
- cross-provider validation,
- symbol-by-symbol sample-size thresholds,
- multiple-testing adjustment or a false-discovery control,
- explicit deactivation criteria when live/paper performance decays.

### High: Dynamic Forensic Multipliers Can Leak Outcomes Into Scoring

File:

- `core/alpha_combiner.py`

Observation:

`get_forensic_multiplier()` reads historical `signals` performance and changes the score multiplier when win-rate thresholds are met.

Risk:

This is acceptable as an adaptive live-control mechanism only if historical data is strictly point-in-time. In a backtest, using all prior stored signals without enforcing a training cutoff can leak future outcomes into simulated decisions.

Quant recommendation:

For research mode:

- disable DB-derived multipliers, or
- require an explicit `as_of_timestamp` so only signals closed before that timestamp contribute.

For live mode:

- log the exact multiplier source, sample count, win rate, and cutoff timestamp into `score_details`.

### Medium: Backtest Execution Realism Is Incomplete

File:

- `core/backtest_engine.py`

Observation:

The exit model applies static spread/slippage and binary TP1/SL resolution.

Risk:

Static friction understates live variance. It does not model:

- variable spread by symbol/session/news,
- bid/ask OHLC,
- partial fills,
- order rejection,
- latency,
- stop slippage,
- commission,
- swap/rollover,
- spread widening at news or daily rollover.

Quant recommendation:

Add a broker-realism layer with symbol/session spread distributions and explicit bid/ask simulation. Keep the simple engine for fast research, but do not use it as final live-readiness evidence.

### Medium: Regime Detector Uses First Symbol As Global Proxy

File:

- `core/market_regime.py`

Observation:

When passed a symbol-to-dataframe map, the regime detector selects the first symbol as the global proxy.

Risk:

The first symbol can misrepresent broad-market conditions, especially across FX majors, JPY crosses, metals, oil, and crypto. This can shift quality thresholds and symbol weights system-wide.

Quant recommendation:

Aggregate across symbols using robust statistics:

- median ADX,
- median ATR ratio,
- dispersion by asset cluster,
- per-cluster regime labels for FX, JPY, metals, oil, and crypto.

### Medium: Legacy MT5 JSON Handler Can Bypass The Main Gate

File:

- `execution/mt5_handler.py`

Observation:

The main service is gated, but the legacy JSON bridge handler can execute the latest unexecuted JSON signal directly.

Risk:

If this handler is run separately, it bypasses the stronger `ExecutionGate.validate_and_reserve()` path.

Recommendation:

Retire the legacy handler or make it call the same execution gate and reservation path before any order is sent.

### Medium: Data Provider Consistency Risk

File:

- `data/fetcher.py`

Observation:

The system can fall back to yfinance with adjusted candles.

Risk:

For MT5/CFD execution, yfinance candles may differ from broker-native tradable bid/ask data. Backtests may look better or worse than broker execution reality depending on symbol, session, spread, and provider gaps.

Recommendation:

For production validation, use broker-native MT5 data or an auditable institutional-quality source. Keep yfinance as a fallback only, and label any yfinance-based result as research evidence rather than execution evidence.

### Medium: Risk Scaling Is Outcome-Adaptive But Needs Governance

File:

- `core/filters/risk_manager.py`

Observation:

Risk can scale up after recent wins, scale down after losses, and optionally use Kelly sizing.

Risk:

Outcome-adaptive sizing can improve capital efficiency, but it can also amplify streak artifacts and produce unstable realized risk if the edge estimate is noisy.

Recommendation:

Require:

- capped fractional Kelly only,
- minimum sample thresholds,
- per-strategy and per-symbol Kelly estimates,
- drawdown-state overrides,
- paper/live separation so paper streaks do not scale live risk unless explicitly approved.

## Research Validity Gaps

The system needs a stricter research protocol before alpha claims should be treated as durable.

Required protocol:

1. Define immutable alpha candidates.
2. Split data into train, validation, and untouched test windows.
3. Tune parameters only on train.
4. Select rules only on validation.
5. Report final performance only on untouched test.
6. Repeat with rolling walk-forward windows.
7. Track degradation from research to paper to live.

Minimum metrics to report:

- trade count,
- win rate,
- expectancy,
- profit factor,
- max drawdown,
- average win/loss,
- median R,
- skew,
- longest loss streak,
- turnover,
- exposure time,
- symbol/session contribution,
- confidence intervals,
- parameter sensitivity.

## Recommended Remediation Plan

### Phase 1: Freeze And Measure

- Freeze current alpha logic as a named baseline.
- Record exact config, symbol list, data source, and database state for each backtest.
- Disable adaptive DB-derived multipliers in pure research tests.
- Produce a clean 3-window walk-forward report.

### Phase 2: Separate Research From Production Adaptation

- Add `research_mode=True` path that disables live adaptive state.
- Add `as_of_timestamp` to any DB-derived scoring function.
- Persist each dynamic multiplier's sample count and cutoff.

### Phase 3: Improve Execution Realism

- Add variable spread/slippage distributions.
- Simulate bid/ask execution.
- Add commission and swap assumptions.
- Compare research fills against MT5 paper/live fills.

### Phase 4: Govern Risk Scaling

- Require sample-size thresholds before risk scaling activates.
- Separate paper/live streaks.
- Cap risk expansion independently from base risk.
- Add audit logs for every risk multiplier applied.

## Bottom Line

The codebase is not obviously broken. The active alpha path is test-covered and operationally gated. The next serious improvement is not another alpha tweak; it is a clean research harness that proves which parts of the current edge survive out-of-sample testing after removing future leakage and recent-window curve fitting.

