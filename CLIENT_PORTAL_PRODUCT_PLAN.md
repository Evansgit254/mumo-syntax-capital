# Client Portal Product Plan

## Objective

Build a separate client-facing portal that exposes the value of the Mumo Syntax Capital signal system without exposing the internal operator terminal, execution controls, credentials, logs, or system governance tools.

The current admin dashboard should remain an internal institutional terminal. Clients should receive a simpler, faster, mobile-friendly experience focused on signals, subscription status, performance visibility, and trust.

## Product Direction

### Internal Admin Terminal

Keep the existing dashboard for internal operations:

- Signal monitoring and forensic review
- MT5 status, exposure, and execution oversight
- Client management
- Risk and system configuration
- Backtests, logs, health checks, and maintenance actions

The admin terminal can remain dense and technical because its audience is operators, risk managers, and system owners.

### Client Portal

Create a separate client experience with a narrower surface:

- Latest entitled signals
- Signal details: entry, stop loss, take profits, timeframe, confidence, and status
- Plain-language reasoning
- Signal lifecycle: active, expired, TP hit, SL hit, closed
- Client subscription status
- Signal delivery preferences
- Personal performance summary
- Support or account contact path

Clients should not see internal machinery. The portal should make the system feel powerful through clarity, reliability, and speed.

## Role Model

Use strict role-based access boundaries:

- `admin`: full access to internal terminal and all backend actions
- `risk_manager`: risk, execution, live-trading, and sensitive client controls
- `operator`: limited client operations and support workflows
- `client`: only their own subscription, signal history, and permitted analytics

The client role must never be able to access global configuration, MT5 credentials, other clients, raw logs, execution controls, system management actions, or unscoped signal data.

## Phase 1: Stabilize Admin UX

Purpose: improve internal operations before introducing a client product.

Scope:

- Split dashboard polling by view instead of running one broad `syncAll()` loop.
- Slow down expensive checks such as MT5 terminal status.
- Stop background config refreshes while settings forms are being edited.
- Add visible stale/error states instead of silent console-only failures.
- Add last-updated timestamps to major panels.
- Preserve the current internal dashboard identity while making it more predictable.

Acceptance criteria:

- Editing config fields is never overwritten by background refresh.
- MT5 status does not block or slow normal dashboard operation.
- API failures show visible panel-level states.
- The dashboard remembers the last active view during a session.

## Phase 2: Add Client-Scoped Backend APIs

Purpose: create safe data boundaries before building the client UI.

Proposed endpoints:

- `GET /api/client/me`
- `GET /api/client/subscription`
- `GET /api/client/signals`
- `GET /api/client/signals/{signal_id}`
- `GET /api/client/performance`
- `POST /api/client/preferences`

Security requirements:

- Every client endpoint must require authentication.
- Every query must be scoped to the authenticated client identity.
- No endpoint should accept a client id from the request path unless the caller is an admin/operator endpoint.
- Signal access must respect subscription status, tier, and client entitlement.
- Responses must not include raw internal fields such as forensic debug payloads unless intentionally simplified.

Acceptance criteria:

- A client cannot read another client's data.
- A client cannot call admin endpoints.
- Expired or inactive clients receive a controlled subscription state instead of data leakage.
- Unit tests cover cross-client access attempts.

## Phase 3: Build Client Portal Frontend

Purpose: provide a polished experience for paying clients.

Recommended structure:

- Add a separate frontend under `client_dashboard/` or a separate `/client` route.
- Keep it visually related to Mumo Syntax Capital, but simpler than the admin terminal.
- Prioritize mobile and tablet layouts.

Core screens:

- Dashboard overview
- Latest signals
- Signal detail
- Performance history
- Subscription/account
- Preferences

Client dashboard overview should show:

- Active subscription state
- Latest active signal
- Recent signal outcomes
- Win/loss or TP/SL summary
- Telegram delivery status
- Clear account status message

Signal detail should show:

- Symbol
- Direction
- Entry
- Stop loss
- Take-profit levels
- Timeframe
- Created time
- Expiry or status
- Plain-language reasoning
- Risk reminder

Acceptance criteria:

- First screen is useful immediately after login.
- Works cleanly on mobile.
- No admin terminology or system internals are exposed.
- Empty states are clear for new clients.
- Expired clients see renewal/subscription guidance, not a broken dashboard.

## Phase 4: Productize Subscriptions And Onboarding

Purpose: make the portal operationally usable for real clients.

Scope:

- Add client onboarding flow.
- Connect Stripe payment/subscription state clearly to portal access.
- Add subscription renewal or upgrade path.
- Add Telegram connection instructions/status.
- Add support contact or escalation path.
- Add basic account preferences.

Acceptance criteria:

- A new paid client can log in and understand what to do next.
- Subscription status is obvious.
- Payment failures or expiry states are handled cleanly.
- Support/admin can diagnose a client account without exposing system internals.

## Phase 5: Trust, Reporting, And Retention

Purpose: help clients understand value over time.

Scope:

- Personal signal history
- Outcome tracking
- Weekly/monthly performance summaries
- Asset-level summaries
- Signal quality summaries
- Exportable client-facing reports

Reporting principles:

- Do not overpromise live profitability.
- Clearly distinguish backtest, paper execution, and live broker outcomes.
- Show timestamps and signal lifecycle transparently.
- Keep performance explanations simple and defensible.

Acceptance criteria:

- Clients can see what signals they received and what happened afterward.
- Reports are understandable without trading-system knowledge.
- Performance metrics do not mix incompatible data sources without labels.

## UX Principles

- Client UX should be calm, fast, and clear.
- Admin UX can remain dense and technical.
- Avoid exposing controls that clients cannot use.
- Avoid raw system labels where plain language is better.
- Prefer stable panels over constantly repainting content.
- Show stale states and last sync times.
- Make mobile a first-class target.

## Technical Guardrails

- Do not reuse admin endpoints for client views.
- Do not filter client data only in the frontend.
- Do not expose global signals without entitlement checks.
- Do not expose MT5 credentials or execution controls.
- Do not let background polling overwrite user input.
- Do not rely on external CDN assets for critical client portal rendering if deployment reliability matters.

## Suggested Delivery Order

1. Stabilize admin dashboard refresh behavior.
2. Define client role and authentication mapping.
3. Build client-scoped API endpoints with tests.
4. Build the client portal shell and overview screen.
5. Add latest signals and signal detail.
6. Add subscription/account screen.
7. Add personal performance summaries.
8. Pilot with one internal/test client.
9. Roll out to selected real clients.
10. Improve based on observed support issues and client behavior.

## Success Metrics

- Clients can access their latest signal in under 10 seconds after login.
- Client portal works well on mobile.
- No client can access another client's data.
- Support requests about "where is my signal" decrease.
- Dashboard API errors are visible and diagnosable.
- Admin terminal and client portal have clearly separated responsibilities.

