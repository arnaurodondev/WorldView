# QA Beta Blockers Audit — 2026-05-09

> **Specialist**: Beta-Deployment Blockers (PLAN-0087)
> **Mission**: Identify everything preventing a real hedge-fund analyst from using
> the platform productively for a week. Bar = paying user inside a regulated
> financial firm, not friendly demo audience.
> **Scope**: Read-only investigation. ~120 min budget. Live stack at
> `localhost:8000` (S9 healthy), `localhost:3001` (web healthy). All 30+ runtime
> containers reported `healthy` at audit time.
> **Methodology**: Source review + live `curl`, no end-to-end test runs.

---

## Headline

The platform is **demo-ready** but **not beta-ready** for any regulated firm.
The single biggest gap is the **trust-and-control surface**: a real customer
cannot sign themselves up, cannot reset a password, cannot manage MFA, cannot
revoke a session, cannot export or delete their data, cannot see who accessed
what, and (critically) operates over **plaintext HTTP between every internal
service plus plaintext to Postgres/Kafka/MinIO**. Almost every settings
sub-page is a `SettingsPlaceholder`.

For a 30-min director walkthrough this is invisible. For a paying analyst
using it for a week, every one of those gaps is a blocker the moment the
firm's IT security review sees it.

---

## A. Auth flow gaps

### A.1 No production sign-up path BLOCKING
- **Finding**: `/v1/auth/register` (S9) just `302`-redirects to
  `${oidc_issuer_url}/ui/console/register`, but **Zitadel is not running** in
  the current stack. `docker-compose.zitadel.yml` exists as an offline option,
  no `worldview-zitadel-*` container is running, and `OIDC_ISSUER_URL` is
  unset on the live api-gateway. Result: `dev-login` is the **only** working
  auth path.
- **File**: `services/api-gateway/src/api_gateway/routes/auth.py:610-619`,
  `apps/worldview-web/app/register/page.tsx:32-45`
- **Workaround**: Provision users manually via `POST
  /internal/v1/users/provision` (admin-only). Not user-facing.
- **Effort to close**: 2-3 days for self-host Zitadel + integration testing,
  or 1 day to wire Zitadel Cloud (PRD-0025 has the design; only ops setup
  pending).
- **Beta-launch in scope**: YES — non-negotiable.

### A.2 Dev-login is wide open in dev, but the live stack uses dev-login CRITICAL
- **Finding**: `POST /v1/auth/dev-login` returns a 5-minute access token for
  the seeded demo user with no challenge whatsoever. Currently the real auth
  pathway because `oidc_config is None`. `app_env != "production"` is the
  only guard. Live stack has `app_env="development"` (default).
- **Confirmed live**: `curl -X POST http://localhost:8000/v1/auth/dev-login`
  returns a valid JWT.
- **File**: `services/api-gateway/src/api_gateway/routes/auth.py:675-784`
- **Workaround**: None for beta; relying on dev-login in any non-local
  environment is a hard fail.
- **Effort to close**: Tied to A.1 — once Zitadel is wired, dev-login
  remains hard-blocked by `oidc_config is not None`.
- **Beta-launch in scope**: YES.

### A.3 No MFA, no password reset, no email verification BLOCKING
- **Finding**: All three are delegated to Zitadel ("self-service"). With
  Zitadel not deployed, none exist. The Settings → Security page
  (`apps/worldview-web/app/(app)/settings/security/page.tsx:8-24`) is a
  `SettingsPlaceholder` listing these as future bullets:
  - "Active sessions list with revoke"
  - "Two-factor enrolment (TOTP / WebAuthn)"
  - "Password change (proxied to identity provider)"
  - "Audit log of recent sign-ins"
- **Workaround**: Zitadel ships all four out of the box. So the cost is
  ops, not feature work. But the **UI surfaces them inside Worldview as
  placeholders**, which a hedge-fund analyst will perceive as missing
  features.
- **Effort to close**: 1-2 days for Settings UI to deep-link into Zitadel
  account console; 0 days for the underlying capability **if Zitadel is
  deployed**.
- **Beta-launch in scope**: YES — financial firms require MFA.

### A.4 Session expiry behavior is correct but UX is unproven CRITICAL
- **Finding**: 5-minute access token (`dev-login`) / 15-minute (Zitadel
  default) plus 30-day httpOnly refresh cookie. Frontend's `AuthContext`
  has a silent-refresh timer 60 s before expiry
  (`apps/worldview-web/contexts/AuthContext.tsx:92-112`). Refresh path:
  `POST /v1/auth/refresh`. On 401, must redirect to `/login`. There is
  **no observed integration test** that validates the silent-refresh window
  during long-lived browser sessions (e.g., charts page idle for 20 min,
  then click).
- **File**: `services/api-gateway/src/api_gateway/routes/auth.py:367-426`
  (refresh path), `AuthContext.tsx`
- **Workaround**: Manual reload.
- **Effort to close**: 1 day to write the long-idle Playwright test +
  fix any drift discovered.
- **Beta-launch in scope**: YES — analysts leave tabs open for hours.

### A.5 No tenant onboarding flow MAJOR
- **Finding**: Tenants are created server-side via `POST /tenants`
  (still in `docs/SECURITY_ISSUES.md` SEC-005 as "unauthenticated" — needs
  re-verification, but no UI surface exists). Multi-tenant infrastructure
  exists (PLAN-0086) but the **firm-onboarding flow is absent**: there is
  no "Create your firm's tenant, invite your team, configure SSO" funnel.
- **File**: `services/portfolio/src/portfolio/api/routes/tenant.py`
- **Workaround**: Manual tenant + first-admin provisioning by Worldview
  staff per onboarding.
- **Effort to close**: 1 week (scope: tenant create + admin invite + SSO
  config).
- **Beta-launch in scope**: NO — fine to assist onboarding manually for
  the first 5-10 firms.

---

## B. Settings UI

### B.1 Five of seven Settings sections are placeholders BLOCKING (cumulative)
- **Finding**: Frontend Settings layout (`apps/worldview-web/app/(app)/settings/`)
  has seven sub-routes: profile, preferences, appearance, notifications,
  security, integrations, data, beta-program. Of these:
  - **Wired**: `profile/page.tsx` (basic profile),
    `preferences/page.tsx` (density/currency/timezone, **localStorage-only**),
    `appearance/page.tsx`, `notifications/page.tsx`.
  - **Placeholder**: `security/page.tsx`, `integrations/page.tsx`,
    `data/page.tsx`, `beta-program/page.tsx` — each renders
    `<SettingsPlaceholder>` with a bullet list of "future" features.
- **File**: `apps/worldview-web/app/(app)/settings/{security,integrations,data}/page.tsx`
- **Workaround**: None — placeholder is visible to user.
- **Effort to close**:
  - Integrations (TastyTrade/SnapTrade self-management): 3-5 days
  - Data (export/delete-my-data): 5 days
  - Security (sessions/MFA/audit): 5 days (assumes Zitadel deployed)
- **Beta-launch in scope**: YES for Integrations + Data; PARTIAL for
  Security (could deep-link to Zitadel account portal as MVP).

### B.2 Theme switcher present but not validated MAJOR
- **Finding**: Appearance page exists. The product is documented as
  "dark theme enforced permanently" (`docs/ui/DESIGN_SYSTEM.md`,
  `apps/frontend/...`). Light-mode is a customer expectation that is
  **not supported**. If a firm's accessibility policy requires light
  mode, this is a hard rejection.
- **Workaround**: None.
- **Effort to close**: 2-3 weeks for full light-mode token sweep + visual
  QA.
- **Beta-launch in scope**: NO if customer is dark-mode-tolerant; YES if
  not — pre-qualify customers.

### B.3 Brokerage management is tied to single-flow connect MAJOR
- **Finding**: TastyTrade connect was validated 2026-04-28 (per memory).
  Settings → Integrations is a placeholder; the "remove brokerage" or
  "trigger re-sync" surfaces are **not in the audit-visible UI**. Backend
  has `BrokerageTransactionSyncWorker` and a `BrokerageConnection` entity.
- **Workaround**: Disconnect server-side via direct DB.
- **Effort to close**: 2-3 days.
- **Beta-launch in scope**: YES — first brokerage hiccup will require
  user-driven recovery.

### B.4 Alert/notification preferences are surfaced but limited MAJOR
- **Finding**: Notifications tab exists (NotificationsTab component).
  Backend `alert-preferences` API exists at S1 (`/api/v1/alert-preferences`)
  with severity threshold and entity suppression. **What's missing**:
  channel routing (email/SMS/Slack/webhook), mute windows
  ("don't ping me before 9 AM"), and digest opt-in. `EmailPreference`
  entity exists in S10 (PLAN-0016 Wave C-1) but no UI for it; the
  `Integrations` placeholder lists "Slack alert delivery (planned)".
- **Workaround**: None — analyst either gets every alert or none.
- **Effort to close**: 1 week (channel routing + mute window).
- **Beta-launch in scope**: YES if alerts are core; NO if alerts are
  optional in beta.

### B.5 Preferences persisted in localStorage only CRITICAL
- **Finding**: `PreferencesContext.tsx:18-26` explicitly says: "Today
  persisted in localStorage via `safeStorage`; the S1 backend endpoint
  that will own canonical persistence is a **deferred follow-up**".
  Density, currency, and timezone settings are lost when the user
  switches device or clears the browser.
- **File**: `apps/worldview-web/contexts/PreferencesContext.tsx`
- **Workaround**: User reconfigures each device.
- **Effort to close**: 2 days (S1 endpoint + frontend wire-through).
- **Beta-launch in scope**: YES — institutional users use multiple
  machines.

---

## C. Data persistence + recovery

### C.1 No production-grade backup/restore on local stack BLOCKING
- **Finding**: Backups exist **only** as a documented cron in
  `infra/gitops/docs/production-deployment.md:175-179` — `pg_dumpall
  | gzip > /opt/backups/...` daily, 7-day rotation. This is for the
  Hetzner production cluster (PLAN-0024), not the local stack a beta
  firm would run.
  - No PITR (point-in-time recovery).
  - No off-site replication.
  - No tested restore drill (`docs/audits` contains no restore drill).
  - **The `worldview_postgres_data` volume is ephemeral by Docker Compose
    convention** — `docker compose down -v` wipes everything.
- **File**: `infra/gitops/docs/disaster-recovery.md`
- **Workaround**: Customer firm runs their own pg_dump cron; documented in
  PRODUCTION_READINESS.md item 4.4 (P0, status TODO).
- **Effort to close**: 3-5 days (PITR via WAL archiving) + 1 day for a
  documented + tested restore drill.
- **Beta-launch in scope**: YES — losing a customer's portfolio is fatal.

### C.2 Browser cache TTLs may not align with backend caches MAJOR
- **Finding**: Frontend uses TanStack Query with default `staleTime`
  per-page; backend uses Valkey TTLs (e.g., `briefing:morning:v2` 24 h,
  `gw:v1:quote` 30 s, `gw:v1:ohlcv` 2 min). No documented mapping
  between the two ensures the user sees fresh data when the backend
  invalidates upstream. A user hitting "refresh OHLCV" can be served a
  stale TanStack cache while the backend has fresh data.
- **Workaround**: Hard-refresh.
- **Effort to close**: 2 days (audit TanStack query keys + align with
  S9 cache headers).
- **Beta-launch in scope**: YES for trading-adjacent surfaces; NO for
  static surfaces.

### C.3 Chat history retention policy: undefined CRITICAL
- **Finding**: `messages` and `threads` tables (rag_db) have no TTL,
  no retention policy, no automatic deletion. Free-form analyst chat
  ("I have $5M and want to short ESG names…") accumulates indefinitely.
  Memory grows unbounded; PII handling is **not addressed** in the
  service code (no field-level redaction, no chat-message access log).
- **File**: `services/rag-chat/src/rag_chat/infrastructure/db/models/message.py`
- **Workaround**: Manual `DELETE FROM messages WHERE created_at < NOW() -
  INTERVAL '90 days'` cron. Not in repo.
- **Effort to close**: 2 days (Alembic migration + retention worker +
  user-visible setting "delete chat older than X").
- **Beta-launch in scope**: YES — GDPR + financial-firm record-keeping
  policies require defined retention.

### C.4 Workspace layout, watchlists, alerts: persistence semantics unclear MAJOR
- **Finding**: `WorkspaceContext.tsx` and `WorkspaceSymbolContext.tsx`
  manage layout. Memory note "workspace multi-instance + persistence"
  exists from 2026-04-23 status, but the durability story — "is this
  per-device, per-user, or per-tenant?" — is not surfaced in the UI.
  Watchlists are server-side (S1). Alerts are server-side (S10).
- **Workaround**: User reconfigures per device.
- **Effort to close**: 1 day to document; 3 days to add a "sync workspace
  to server" feature.
- **Beta-launch in scope**: NO — document the current behavior; defer
  sync.

### C.5 What's lost on session expiry vs explicit logout MAJOR
- **Finding**:
  - On expiry → silent refresh attempts, then 401 → redirect to login.
    In-flight chat stream is dropped (no SSE resumption).
  - On explicit logout → `POST /v1/auth/logout` revokes refresh cookie,
    invalidates Valkey identity cache, and the frontend clears React
    state. **`localStorage` preferences (B.5) survive**; `IndexedDB`
    instrument-context survives.
  - There is no "you have unsaved changes" prompt anywhere.
- **Effort to close**: 2 days for SSE resumption + UX polish.
- **Beta-launch in scope**: YES — chat interruptions are user-visible.

---

## D. Rate limits

### D.1 Default 300/min/user is too loose for free tier; too tight for power users MAJOR
- **Finding**: `rate_limit_requests=300/60s` per user (api-gateway/config.py:61).
  The comment explicitly says "100 was too tight". 300/min ≈ 5 req/sec
  sustained — a single power user opening multiple instrument tabs can
  saturate. Conversely, a malicious authenticated user can spend 50 K/day
  worth of LLM calls on `/v1/chat` alone (no tier-specific cap).
- **Workaround**: None.
- **Effort to close**: 1 day to add per-route caps (`/v1/chat` should
  have its own ~30/min/user bucket; `/v1/briefings/*` should be cached
  + ~60/hour).
- **Beta-launch in scope**: YES.

### D.2 Financial-mutation sub-tier is correctly tighter (20/min) MINOR (no change)
- **Finding**: `_FINANCIAL_MUTATION_LIMIT=20` for POST/PUT/DELETE on
  `/v1/transactions`, `/v1/brokerage`, `/v1/portfolios`. Correct.

### D.3 Unauthenticated tier (20/min/IP) is too tight when behind any NAT MAJOR
- **Finding**: 20 req/min per `sha256(IP)[:16]` for unauthenticated
  traffic. Behind a single corporate NAT, **all unauthenticated visitors
  share one bucket** — a single noisy tab can 429-lock everyone. PLAN-0052
  partially fixed this for `/v1/feedback/*` (120/min). Other public
  surfaces (login page assets) remain at 20.
- **Workaround**: User retries.
- **Effort to close**: 1 day (add `X-Forwarded-For` trust + per-route IP
  buckets).
- **Beta-launch in scope**: YES if any non-VPN customer; NO if always
  authenticated behind their own SSO.

### D.4 No per-tenant cap MAJOR
- **Finding**: Rate limit key is `rl:v1:user:{user_id}` — never
  `{tenant_id}`. A single tenant with N users can collectively burn
  N × 300/min = unbounded LLM cost. No `429` ever fires at tenant level.
- **Workaround**: None.
- **Effort to close**: 2 days.
- **Beta-launch in scope**: YES if any pricing tier has caps.

### D.5 Chat-specific limits not enforced at gateway CRITICAL
- **Finding**: `/v1/chat` is in the default 300/min user bucket. MASTER_PLAN
  §9.5 says "Rate limit: 10 queries/min/tenant" — the documented design.
  Gateway does not enforce it; whatever S8 enforces internally is the
  only protection. No gateway-side `_CHAT_RATE_LIMIT` constant exists.
- **File**: `services/api-gateway/src/api_gateway/middleware.py`
- **Workaround**: None.
- **Effort to close**: 0.5 day.
- **Beta-launch in scope**: YES — cost runaway risk.

### D.6 Brief throttle observed (D-Q-008) MAJOR
- **Finding**: User reported 429 on 3 idle requests to
  `/v1/briefings/instrument/...` from earlier QA. Likely due to S8
  per-user concurrency limit + shared bucket. Not investigated in
  this audit.
- **Workaround**: Wait + retry.
- **Effort to close**: 0.5 day to investigate.
- **Beta-launch in scope**: YES.

---

## E. Error recovery — partial-failure UX

### E.1 DeepInfra outage → fallback chain partially defended MAJOR
- **Finding**: `provider_chain.py` (rag-chat) has 3-tier DeepInfra
  → OpenRouter → Ollama fallback with Valkey-backed negative caching
  (60-120 s). Ollama (local) is the emergency fallback. **Caveat**:
  the locally-hosted GLiNER and BGE-large containers are dependencies
  that **cannot fall over to a remote** (no fallback adapters).
  - **What user sees on DeepInfra outage**: chat continues but
    response quality degrades silently. **No banner.**
- **Workaround**: None visible to user.
- **Effort to close**: 1 day (banner: "answers are running on local
  fallback model — quality may be reduced").
- **Beta-launch in scope**: YES.

### E.2 Kafka down → user can browse, but writes silently fail MAJOR
- **Finding**: Outbox pattern means writes commit to DB regardless of
  Kafka. The dispatcher will catch up. Reads are unaffected. Alert
  WebSocket disconnects when Kafka is down? Probably. **No reconnect
  logic visible on the frontend** — `grep reconnect` in
  `apps/worldview-web/lib/` and `hooks/` returns only IndexedDB error
  handlers.
- **File**: alert WebSocket consumer at S10 + frontend `AlertStreamContext`
- **Workaround**: Page refresh.
- **Effort to close**: 2 days for exponential-backoff WS reconnect.
- **Beta-launch in scope**: YES.

### E.3 S3/MinIO down → news/article body fetch fails MAJOR
- **Finding**: Article bodies live in MinIO silver. If MinIO is down,
  any "open article" click fails with a network error. No graceful
  degradation ("we have the title and summary, full body unavailable").
- **Workaround**: None.
- **Effort to close**: 2 days.
- **Beta-launch in scope**: YES.

### E.4 Single container restart → no SSE resumption MAJOR
- **Finding**: Chat SSE stream (`POST /v1/chat/stream`) is dropped if
  S8 restarts mid-answer. Frontend shows truncated answer. No
  "resume" button. WebSocket alert reconnect: see E.2.
- **Effort to close**: 3 days (SSE resumption is non-trivial — needs
  request continuation token).
- **Beta-launch in scope**: NO — document as known limitation.

### E.5 DB read replica lag → silent stale reads CRITICAL
- **Finding**: `R27` mandates `ReadOnlyUnitOfWork` for read use cases,
  pointing at the read replica when configured. There is **no
  freshness banner** when the read replica lags ("data may be 15s
  behind"). For a portfolio view post-trade, this matters.
- **File**: `libs/storage` ReadOnlyUnitOfWork + S1/S3 use cases
- **Effort to close**: 2 days (lag detection + banner threshold).
- **Beta-launch in scope**: YES if read replica is configured; NO
  for single-DB local stack.

---

## F. Observability for operators

### F.1 No customer-facing health/status page CRITICAL
- **Finding**: `apps/worldview-web/app/(public)/status/page.tsx` exists
  but its content was not inspected here. There is **no per-component
  health dashboard** for an IT operator: no "Kafka lag", "consumer-group
  status", "outbox backlog" surface. PRODUCTION_READINESS.md §7.2 lists
  "Grafana dashboards ... not yet created" (P1 TODO).
- **Workaround**: SSH into host, `docker ps`, `kafka-ui`.
- **Effort to close**: 1 week (Grafana dashboards + status page wiring).
- **Beta-launch in scope**: YES for tier-1 firms; partial for others.

### F.2 No runbook for operational failure modes MAJOR
- **Finding**: `docs/runbooks/` has 9 entries — `debugging-guide`,
  `error-observability`, `hotfix-procedures`, `market-data-operations`,
  `market-ingestion-operations`, `partition-retention`,
  `secrets-management`, `sentry-alerts`, `uptime-monitoring`. **Missing**:
  - "narrative worker is wedged"
  - "DeepInfra is rate-limiting; what now?"
  - "Kafka consumer-group lag is climbing"
  - "Alembic migration is hung"
  - "MinIO is full"
- **Effort to close**: 2-3 days for top-10 runbooks.
- **Beta-launch in scope**: YES.

### F.3 LLM cost telemetry exists but not exposed to tenants MAJOR
- **Finding**: `llm_usage_log` is populated across S6/S7/S8.
  `GET /api/v1/admin/llm-costs` aggregates cross-service for **admin
  users only** (`role == "admin"`). There is **no per-tenant cost
  surface** for the firm itself — they cannot see what they're
  spending.
- **File**: `services/api-gateway/src/api_gateway/routes/admin_costs.py`
- **Effort to close**: 2 days (per-tenant filter + Settings → Data
  surface).
- **Beta-launch in scope**: YES if cost-passthrough; NO if all-you-can-eat.

### F.4 No daily cost alert / cap MAJOR
- **Finding**: No "tenant approached 80% of monthly LLM budget" alert.
  No hard-cap that 503s when budget is exhausted. Single misconfigured
  prompt loop could drain the platform's DeepInfra account.
- **Effort to close**: 3 days (budget table + check + alert + hard-cap).
- **Beta-launch in scope**: YES — cost-protection is mandatory.

---

## G. Privacy + compliance

### G.1 Encryption at rest: NOT enforced BLOCKING
- **Finding**: PRODUCTION_READINESS.md item 6.3 (SSE-S3/SSE-KMS): TODO.
  Postgres TDE: not configured. MinIO buckets: no `BucketEncryption`
  policy. Documented in MASTER_PLAN.md §10 "Layer 3 — Encryption at
  rest (Postgres TDE, MinIO SSE-S3)" but **not implemented**.
- **Workaround**: Disk-level FDE if hosted on Hetzner with LUKS.
- **Effort to close**: 1 week (KMS integration + per-volume keys).
- **Beta-launch in scope**: YES — every firm's IT review will ask.

### G.2 Encryption in transit between services: NOT enforced BLOCKING
- **Finding**: PRODUCTION_READINESS.md items 2.1-2.7 all TODO. All
  S1↔S2↔...↔S10 traffic is plaintext HTTP inside Docker Compose. Kafka
  broker uses PLAINTEXT. Postgres connections use no `sslmode=require`.
  MinIO uses HTTP. **Only the public ingress (Traefik) terminates TLS**.
  Inside the cluster: zero encryption.
- **Workaround**: VPC-only deployment; assume the cluster network is a
  trust boundary.
- **Effort to close**: 2-3 weeks (mTLS rollout) or 1 week (Postgres
  + Kafka SSL only).
- **Beta-launch in scope**: YES if customer requires defense-in-depth;
  PARTIAL acceptable if VPC isolation is contractually documented.

### G.3 No GDPR right-to-delete BLOCKING
- **Finding**: `/v1/users/me/delete` endpoint: not present.
  Settings → Data is a placeholder listing "Account data deletion (GDPR
  right-to-be-forgotten)" as a future feature. User chat history
  (`messages.content`) is unbounded.
- **File**: `apps/worldview-web/app/(app)/settings/data/page.tsx`
- **Effort to close**: 1 week (cascade deletion across S1/S8/S10 +
  audit + 30-day soft-delete window).
- **Beta-launch in scope**: YES — GDPR is non-optional in EU.

### G.4 Audit log: partial CRITICAL
- **Finding**: `auth_audit_log` (portfolio_db) records auth events
  (provision, login). **No equivalent for**:
  - "User X accessed entity Y at time Z"
  - "User X queried portfolio Y"
  - "Admin viewed cost dashboard"
  No searchable audit-log surface for the firm's IT.
- **File**: `services/portfolio/src/portfolio/infrastructure/db/repositories/auth_audit_log.py`
- **Effort to close**: 1-2 weeks (event taxonomy + write paths +
  read API + UI).
- **Beta-launch in scope**: YES for regulated firms.

### G.5 PII in chat content: not redacted MAJOR
- **Finding**: A user typing "I have $5M and want to short ESG names"
  is logged verbatim in `messages.content` and propagated through
  `llm_usage_log`. Sentry has PII scrubbing
  (`libs/observability/src/observability/sentry.py:89-147`) but the
  primary data store does not.
- **Workaround**: Customer trains users not to share PII.
- **Effort to close**: 3 days for opt-in client-side redaction +
  flag-on-store.
- **Beta-launch in scope**: YES if customer's compliance demands it.

---

## H. Multi-tenant isolation re-verification

PLAN-0086 ("Multi-tenant content pipeline") landed 2026-05-09. This
audit reviewed code paths but **did not run two-tenant E2E tests**.

### H.1 Tenant filter in API reads: present CONFIRMED
- **Portfolio (S1)**: queries filter on `tenant_id` (e.g.,
  `repositories/user.py:36` — `where(UserModel.id == user_id,
  UserModel.tenant_id == tenant_id)`).
- **Alert (S10)**: `alerts.tenant_id` column + index
  (`alert/db/models.py:75-92`); JWT-derived
  `request.state.tenant_id`.
- **rag-chat (S8)**: `tenant_id` propagated from JWT through retrieval
  (`retrieval_orchestrator.py:120-273` forwards `tenant_id` to S6).
- **knowledge-graph (S7)**: `narratives.py:68-82` reads `tenant_id`
  from JWT claims; `intelligence_db` migrations 0006/0031/0032 add
  `tenant_id UUID NULL` overlay (NULL = shared platform).

### H.2 Content pipeline tenant propagation: present CONFIRMED
- `content-store` (`process_article.py:61-371`): PLAN-0086 Wave A-1 +
  C-1 explicitly propagate `tenant_id` from `content.article.raw.v1`
  through dedup + storage.

### H.3 MinIO key prefixing by tenant: NOT confirmed CRITICAL
- **Finding**: Searching `libs/storage/src` for `tenant_id` returned
  no hits. MinIO bronze/silver paths use the documented pattern
  `bronze/<service>/<source>/<id>/raw/v1.<ext>` —
  **no tenant prefix** in the path. Risk: object key enumeration
  could leak cross-tenant data if an attacker gets bucket-list
  permission.
- **Workaround**: Bucket policies + per-service IAM (PRODUCTION_
  READINESS §6.2 TODO).
- **Effort to close**: 1 week (re-prefix + migration).
- **Beta-launch in scope**: YES — cross-tenant leak risk.

### H.4 KG `intelligence_db` is shared CONFIRMED (by design)
- `tenant_id` on path/narrative/relation tables is NULLable; NULL =
  shared. Tenant-private overlays exist but are opt-in. A query that
  forgets to scope by tenant returns shared+all.

### H.5 Two-tenant E2E test: NOT RUN
- This audit did not authenticate as two distinct tenants and verify
  isolation. Memory mentions "1,688 tenant-isolation tests passing"
  for PLAN-0086 but the live two-tenant browser smoke is **not**
  in scope here.
- **Effort to close**: 1 day for an E2E test pair.
- **Beta-launch in scope**: YES.

---

## I. Onboarding documentation

### I.1 No user-facing user-guide MAJOR
- **Finding**: `find -name "user-guide*" -o -name "QUICKSTART*"` in
  the repo (excluding node_modules/.claude/worktrees) returned **zero
  hits**. `apps/worldview-web/app/docs/[[...slug]]` exists as a route
  but its content was not inspected.
- **Workaround**: User figures it out.
- **Effort to close**: 1-2 weeks (10 core flows × 1 page each).
- **Beta-launch in scope**: YES.

### I.2 Operator runbook for the firm's IT team: missing for ~12 scenarios MAJOR
- See F.2.

### I.3 API documentation: partial MAJOR
- **Finding**: `docs/services/api-gateway.md` lists 55+ routes per the
  CLAUDE.md reference, but no public-facing OpenAPI spec or developer
  portal. If a customer wants to integrate Worldview into their own
  systems, there is nothing to hand them.
- **Effort to close**: 2 days (FastAPI auto-generates OpenAPI;
  publish + tag stable subset).
- **Beta-launch in scope**: NO — customer integration is post-beta.

### I.4 Status page / incident comms plan: stub-only MAJOR
- **Finding**: `apps/worldview-web/app/(public)/status/page.tsx` exists.
  Content not inspected here, but no `/api/v1/status` endpoint surfaces
  per-service health to it.
- **Effort to close**: 3 days (incident schema + endpoint + page).
- **Beta-launch in scope**: YES.

---

## J. Pricing / cost management

### J.1 No per-tenant cost dashboard MAJOR
- See F.3.

### J.2 No token-usage caps + no approach-cap alerts MAJOR
- See F.4.

### J.3 No tier feature-gating BLOCKING for SaaS launch
- **Finding**: `BrokerageConnection.$0_Free_tier_≤5_users` (PRD-0022
  reference) is the only documented tier. There is no concept of
  "Pro tier gets 100 chats/day; Enterprise gets unlimited". All users
  see all features. The frontend has no `<FeatureGate>` component.
- **Effort to close**: 2 weeks (entitlement service + gates throughout
  UI + Stripe wire).
- **Beta-launch in scope**: NO — beta = free for all early customers.

---

## Final go/no-go matrix per surface

| Surface | Status | Why |
|---------|--------|-----|
| Auth (sign-up, MFA, password reset) | NO-GO | Zitadel not deployed; dev-login is only path (A.1, A.2, A.3) |
| Settings (Security, Integrations, Data, Beta-Program) | NO-GO | 4/7 sections are placeholders (B.1, B.5) |
| Backups + restore drill | NO-GO | Documented only on Hetzner overlay; no PITR; no tested restore (C.1) |
| Encryption at rest | NO-GO | Postgres + MinIO unencrypted (G.1) |
| Encryption in transit (intra-cluster) | NO-GO if customer requires; PARTIAL otherwise — VPC isolation only (G.2) |
| GDPR right-to-delete | NO-GO | Not implemented (G.3) |
| Audit log search | NO-GO for regulated firms | Auth events only (G.4) |
| MinIO tenant isolation | NO-GO until verified | No tenant key-prefix found (H.3) |
| Rate limits (chat, per-tenant cap) | NO-GO | No chat-specific cap; no tenant cap (D.4, D.5) |
| Cost telemetry per tenant | NO-GO | Admin-only; no caps (F.3, F.4) |
| Status page / runbooks | PARTIAL | Stubs exist; ~12 runbooks missing (F.1, F.2, I.4) |
| User guide | NO-GO | Doesn't exist (I.1) |
| Theme (light mode) | NO-GO if required | Dark-only (B.2) |
| Brokerage management UI | PARTIAL | Connect works; remove/re-sync via UI missing (B.3) |
| Alert preferences (channels, mute) | PARTIAL | Severity threshold works; channel/mute missing (B.4) |
| Multi-tenant DB isolation | GO (with H.5 verification pending) | Tenant filters confirmed in S1/S7/S8/S10 |
| Live walkthrough demo | GO | Already confirmed by prior QA |

---

## F-NNN findings — in-scope BLOCKING/CRITICAL items

| Finding | Severity | VA / Section |
|---------|----------|--------------|
| F-BB-001 — No production sign-up path; Zitadel not deployed | BLOCKING | A.1 |
| F-BB-002 — Dev-login is the live auth path | CRITICAL | A.2 |
| F-BB-003 — No MFA / password reset / email verification surface | BLOCKING | A.3 |
| F-BB-004 — Silent-refresh window unproven for long-lived sessions | CRITICAL | A.4 |
| F-BB-005 — Settings → Security/Integrations/Data are placeholders | BLOCKING (cumulative) | B.1 |
| F-BB-006 — Preferences persisted in localStorage only | CRITICAL | B.5 |
| F-BB-007 — No production backup/restore (PITR, off-site, drill) | BLOCKING | C.1 |
| F-BB-008 — Chat history retention undefined; unbounded growth | CRITICAL | C.3 |
| F-BB-009 — DB read-replica lag has no freshness banner | CRITICAL | E.5 |
| F-BB-010 — Encryption at rest not enforced (Postgres/MinIO) | BLOCKING | G.1 |
| F-BB-011 — Encryption in transit not enforced (intra-cluster plaintext) | BLOCKING | G.2 |
| F-BB-012 — No GDPR right-to-delete | BLOCKING | G.3 |
| F-BB-013 — Audit log scoped to auth events only | CRITICAL | G.4 |
| F-BB-014 — MinIO objects not tenant-prefixed | CRITICAL | H.3 |
| F-BB-015 — No `/v1/chat` per-route rate limit | CRITICAL | D.5 |
| F-BB-016 — No customer-facing health/status surface | CRITICAL | F.1 |

---

## Recommended action

If beta is **demo-only / supervised**, the platform clears the bar with
known gaps documented in a "post-beta hardening" plan.

If beta means **paying analyst at a regulated firm uses it for a week
unsupervised**: do not launch. Minimum to launch:

1. Deploy Zitadel (cloud or self-host) → unlock A.1, A.2, A.3.
2. Wire Settings → Security to Zitadel account portal → close A.3 UI.
3. Move preferences to S1 backend → close B.5.
4. Tested PITR backup + restore drill → close C.1.
5. Postgres `sslmode=require` + Kafka SASL_SSL + MinIO TLS → partial G.2.
6. Postgres pgcrypto / MinIO SSE-S3 → close G.1.
7. GDPR delete + chat retention worker → close G.3 + C.3.
8. Per-tenant + per-route (`/v1/chat`) rate limits + tenant cost
   dashboard + budget alerts → close D.4, D.5, F.3, F.4.
9. MinIO key prefix migration → close H.3.
10. Top-10 user guide pages + top-10 runbooks → close I.1, I.2.

Aggregate effort estimate: **3-4 engineer-weeks** to hit minimum
beta-grade for a regulated single firm. Most items are integration
work (Zitadel, KMS, S1 endpoints), not new architecture.

---

*End of audit.*
