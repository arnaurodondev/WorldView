# PLAN-0065 — W9: Visible Regression Cleanup + Observability

> **Source PRD**: `docs/specs/0034-mvp-launch-readiness-program.md` (PRD-0034) §3 FR-T2-3 + FR-T3-1, §6 Workstream W9.
> **Workstream**: W9 only — explicitly excludes W1/W2/W3/W4/W5/W6/W7/W8/W10.
> **Tier**: 2 (regression cleanup) + 3 (observability).
> **Estimate**: 1.5 dev-days (PRD §15) — confirmed achievable; the four BP-302/F-VISUAL-002/F-E8/F-D4 code fixes are **already merged** in commit `f27e266b` (verified 2026-05-03 against current `main`/`feat/content-ingestion-wave-a1`). The remaining work is operational (redeploy + verify) and net-new (Sentry / UptimeRobot / status page).
> **Author**: `/plan` skill, 2026-05-03; revised 2026-05-03 per audit `docs/audits/2026-05-03-revise-plan-0065-w9.md` (3 BLOCKING + 6 IMPORTANT + 3 NICE-TO-HAVE applied; 2 NICE-TO-HAVE deferred to §15 Follow-ups).
> **Status**: in-progress (Wave A complete 2026-05-04; Wave B complete 2026-05-04; Wave C complete 2026-05-04).
> **Revision 2 changes** (2026-05-04): Wire `init_sentry()` into **all 10 backend services** (S1–S10), not just S9/S6/S8; add Sentry issue-alert email notification to `arnaurodondev@gmail.com`; add Grafana error-observability dashboard; expand worldview-gitops env var coverage to all 10 service `.env` files and `values.yaml`; zero deferrals. See T-C-05 (new), T-E-03 (new), T-E-04 (new).

---

## 1. Plan Summary

| Metric | Value |
|--------|-------|
| Total waves | 5 (A pre-flight, B operational, C backend Sentry, D frontend Sentry, E uptime + status page) |
| Total tasks | 23 (rev-1: +T-B-04 EU offset reset, +T-C-05 S6+S8 Sentry; rev-2: +T-C-05 remaining 7 services, +T-C-06 worldview-gitops all 10, +T-E-03 Grafana dashboard, +T-E-04 Sentry alert email) |
| Critical path | A → B → C (D is independent and can run in parallel with B/C) |
| Parallelisable | Wave D (frontend Sentry) is independent of Waves B/C; Wave A serialises everything else |
| Affected services | **All 10 backend services** (S1 portfolio, S2 market-ingestion, S3 market-data, S4 content-ingestion, S5 content-store, S6 nlp-pipeline, S7 knowledge-graph, S8 rag-chat, S9 api-gateway, S10 alert) — all get `init_sentry()` wired at startup; S6 also operational redeploy; S7 also EU offset reset. worldview-web (frontend), infra/observability, infra/grafana/dashboards |
| Affected libs | `libs/observability` (new `sentry.py` module), `apps/worldview-web/instrumentation*.ts` |
| New env vars | 10 (`SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `SENTRY_TRACES_SAMPLE_RATE`, `SENTRY_RELEASE`, `SENTRY_ENABLED`, `SENTRY_FINGERPRINT_RATE_LIMIT`, `NEXT_PUBLIC_SENTRY_DSN`, `UPTIMEROBOT_MONITOR_ID`, `STATUS_PAGE_URL`, `UPTIMEROBOT_READONLY_API_KEY` — server-only proxy key). Added to all 10 service `.env` files in `worldview-gitops/env/dev/` (default `SENTRY_ENABLED=false`) and their `values.yaml`. |
| New external services | Sentry SaaS (free tier), UptimeRobot (free tier; monitor-scoped read-only API key), in-tree Next.js status page proxy (per audit I-004 — Atlassian Statuspage free tier was discontinued) |
| New tables / topics / Avro | none |
| Architecture risk | LOW — additive instrumentation; no event/schema changes |

### Critical Path

```
Wave A (Pre-flight verification)
    ↓
Wave B (Operational — redeploy + offset reset + smoke verify)   Wave D (Frontend Sentry)  ◄ parallel-safe with B/C
    ↓
Wave C (Backend Sentry via libs/observability + S9 wiring)
    ↓
Wave E (UptimeRobot + status page + final verification)
```

Wave D can execute in parallel with Wave B and Wave C because it touches a disjoint file set (`apps/worldview-web/`) and the only S9 contract it depends on (`/healthz`) already exists. Strict gate: Wave E may not start until A+B+C+D have all completed.

> **Cross-plan coordination — Sentry scope expansion (decision-locked 2026-05-03)**: Per the audit revision pass, W9 pilots Sentry in **three** backends, not just S9: `api-gateway` (S9), `nlp-pipeline` (S6), and `rag-chat` (S8). Rationale: PLAN-0063 (W5) Wave W5-5 emits 4 new Prometheus metrics from S6 + S8 and PLAN-0064 (W6) explicitly references Sentry on `FatalSearchError` in S6. Both downstream plans assume W9 has already wired Sentry in their service. Wiring all three at once costs ~30 min/service (~1 h additional) and prevents duplicate init churn when W5 / W6 land. The remaining 7 services stay deferred to a post-launch hardening sprint as before.

### Cross-Workstream Coordination (do NOT duplicate)

| Other workstream | Boundary | Rule |
|------------------|----------|------|
| **W4 (Structured AI Brief, PLAN-0062-W4)** | Brief endpoint shape, citation contract | W9 does **not** touch S8 RAG or S9 brief routes. By the time W4 ships, W9 has already wired Sentry in S8 (rag-chat) and S9 — W4 inherits coverage with zero extra code. |
| **W5 (Hybrid Retrieval, PLAN-0063)** | 4 new Prometheus metrics from S6/S8 (Wave W5-5) | **Metric ownership stays with W5** (it adds them in `services/nlp-pipeline/...` and `services/rag-chat/...`); W9 only ships the Sentry SDK in S6 + S8 so W5's Wave W5-5 can call `sentry_sdk.capture_message` for the citation-accuracy weekly cron exceptions. The Grafana dashboard wiring (mentioned in PLAN-0063 W5-5 acceptance) is owned by the W5 author and references the existing retrieval-board PR template under `infra/grafana/dashboards/`. |
| **W6 (Full-Text Search, PLAN-0064)** | new `/v1/search` route in S6 + `FatalSearchError` exception class | PLAN-0064 Wave 3 explicitly references "+log + Sentry" on `FatalSearchError`. W9 must wire `init_sentry` in S6 **before** W6 ships — covered by Wave C T-C-05 below. W6's new route then auto-inherits Sentry capture via the lib's `register_error_handlers` extension (T-C-02). |
| **PLAN-0054 (Observability — Loki/Tempo/Prometheus)** | Already shipped: structlog → Loki, OTel → Tempo, Prometheus alerts | W9 **adds Sentry as a fourth pillar**, not a replacement. Sentry handles "user-visible exception capture with stack frames + breadcrumbs"; Loki keeps service logs; Tempo keeps traces. No duplication: Sentry's `attach_stacktrace=True` is for unhandled exceptions only. |
| **PLAN-0024 Wave A (Production Deployment)** | Helm values, env-var injection | W9 adds env vars to **all 10** `infra/gitops/values/<service>.yaml` and all 10 `worldview-gitops/env/dev/<service>.env` files — coordinate with PLAN-0024 owner if they are mid-edit. |

---

## 2. Phase 0.5 — PRD Pre-Flight Gate

| Check | Result | Notes |
|-------|--------|-------|
| No unresolved BLOCKING open questions for W9 | **PASS** | PRD-0034 §14 BLOCKING items (OQ-1..OQ-4) are all about **lane/pricing/cull scope**, not W9. W9-relevant DEFERRED items are `OQ-12` (production domain) — affects only the *value* of `STATUS_PAGE_URL`, not the implementation. |
| No unverified external API fields | **PASS** | Sentry SDK fields (DSN, environment, traces_sample_rate, release) are stable and documented. UptimeRobot has no schema change — it polls `GET /healthz` only (route corrected from draft's `/v1/health` per audit B-002 — verified at `services/api-gateway/src/api_gateway/routes/health.py:12`). |
| No active cross-plan conflicts | **PASS** | TRACKING.md scan: PLAN-0060 (KG/retrieval activation), PLAN-0055 (backfill), PLAN-0059 (frontend remediation), PLAN-0062 (Avro enforcement) all touch disjoint file sets. The only overlap is `apps/worldview-web/app/providers.tsx` (PLAN-0059 C-3 wraps `useApiClient`); Wave D adds an `<ErrorBoundary>` *outside* providers — no conflict. |
| PRD recency check | **PASS** | PRD-0034 created 2026-05-02; today is 2026-05-03. <14 days; no `/revise-prd` needed. |
| Architecture compliance | **PASS** | Sentry init is infrastructure-layer (libs/observability); domain layers untouched. R10 (structlog only) preserved — Sentry runs **alongside** structlog, capturing exceptions in addition to logging them. |

**Gate result**: PASS. Proceed.

---

## 3. Codebase State Verification

Read the actual source files (not docs) and recorded the current state of every artifact this plan touches.

| PRD Reference | Type | Service / File | Actual Current State (verified 2026-05-03) | PRD Expected State | Delta |
|---|---|---|---|---|---|
| BP-302 (article-consumer hang) | Code fix | `services/nlp-pipeline/src/nlp_pipeline/application/blocks/embeddings.py:115-140` | `progress_made` flag present (lines 115, 124, 130, 140) | fix applied | **NONE — already in commit `f27e266b`** |
| F-VISUAL-002 (`--muted-foreground` :root vs .dark) | CSS fix | `apps/worldview-web/app/globals.css:74,177` | both `:root` and `.dark` blocks set `--muted-foreground: 240 4% 55%` (matched) | matched | **NONE — already in commit `99b8bcf7` (PLAN-0059 W0)** |
| F-E8 (`/undefined` race) | Frontend guard | `apps/worldview-web/lib/api/_client.ts:60-75` | regex guard `if (/\/undefined(\/|\?|$)/.test(path)) return "undefined"` present | guard present | **NONE — already in commit `f27e266b`** |
| F-D4 (EU date parsing) | **Backend** fix (NOT frontend — corrected 2026-05-03 audit) | `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/economic_events_dataset_consumer.py:_parse_event_date` (lines 84-109) | `_parse_event_date` normalises EU `YYYY-MM-DD HH:MM:SS` (e.g. `"2026-04-30 12:15:00"`) to ISO `T` form via `date_str.replace(" ", "T", 1)` before strptime. Verified at line 102. The frontend never had a bug — `apps/worldview-web/components/ui/StaleBadge.tsx` and other surfaces have always been EU-locale-aware via `toLocaleString("en-GB", …)`. | fix applied to KG consumer | **CODE — already in commit `f27e266b`**; **OPERATIONAL follow-up: reset `kg-economic-events-dataset-group` consumer offsets (live cluster logged 81 EU events ingested=0 pre-fix). Wave B T-B-04 owns this.** |
| Article-consumer offset / lag | **Operational** state (not code) | Live cluster `nlp-pipeline-article-consumer` group | **Unknown until Wave A runs**: BP-302 fix shipped 2026-05-01 but the consumer may still have a stuck offset on a poison-pill message that was committed before the fix landed | offset healthy, no stuck partition | **OPERATIONAL — Wave B T-B-02** |
| Economic-events offset / lag | **Operational** state (not code) | Live cluster `kg-economic-events-dataset-group` | **81 EU events known dropped on 2026-04-30 12:25:55** per commit `f27e266b` message ("Operator follow-up: reset `kg-economic-events-dataset-group` consumer offsets to backfill the dropped events"). Without offset reset, those events stay missing in `temporal_events`. | offset rewound to before drop window; events re-ingested | **OPERATIONAL — Wave B T-B-04 (NEW)** |
| Sentry SDK (Python backends) | New | `libs/observability/` | does not exist; `error_capture.py` only logs to structlog | new `libs/observability/sentry.py` module + DSN config | **NEW — Wave C** |
| Sentry SDK (frontend) | New | `apps/worldview-web/package.json` | no `@sentry/nextjs` dependency | `@sentry/nextjs` installed + `instrumentation.ts` + `sentry.client.config.ts` + `sentry.server.config.ts` | **NEW — Wave D** |
| UptimeRobot monitor | New | none | no monitor configured | UptimeRobot polls `https://<prod-domain>/healthz` every 5min (NOT `/v1/health` — that route does not exist on api-gateway; verified at `services/api-gateway/src/api_gateway/routes/health.py:12`) | **NEW — Wave E (manual + doc)** |
| Public status page | New | none | no page | public status page rendered in-tree at `apps/worldview-web/app/(public)/status/page.tsx` + a server-only Route Handler at `apps/worldview-web/app/(public)/status/api/uptime/route.ts` that holds the UptimeRobot read-only API key in `UPTIMEROBOT_READONLY_API_KEY` env var (never `NEXT_PUBLIC_*`) | **NEW — Wave E** |
| `/healthz` and `/readyz` routes | API | `services/api-gateway/src/api_gateway/routes/health.py:12,18` (verified to exist) | `/healthz` returns `{"status": "ok"}`; `/readyz` returns `{"status": "ok", "valkey": "ok"}` (200) or `{"status": "degraded", ...}` (503). Mounted with **no prefix** per `app.py:216` (verified). The literal string `/v1/health` is **not** a valid route on api-gateway. | unchanged | **NONE** |
| `register_error_handlers` (libs/observability) | Lib | `libs/observability/src/observability/error_capture.py:35` | exists, hooks `Exception` into structlog | extend to also send to Sentry | **EXTEND — Wave C** |
| `apps/worldview-web/app/providers.tsx` | Frontend root | exists with `<NuqsAdapter>` + `<ApiClientProvider>` (PLAN-0059 C-3/C-6) | Wave D adds `<SentryErrorBoundary>` outermost | wrap | **EXTEND — Wave D** |
| `apps/worldview-web/next.config.ts` | Frontend config | exists (185 LOC); top-level `throw` for `ws://` in production server (`isProductionServer` block lines 24–34); existing `rewrites()`, `headers()`, `images.remotePatterns`, `env`, `experimental.reactCompiler`, `output: "standalone"` | wrap with `withSentryConfig(...)` **only when** `SENTRY_AUTH_TOKEN` is set; existing `throw` must run BEFORE the Sentry wrap (top-of-file → bottom-export ordering preserves this naturally) | **EXTEND — Wave D T-D-01** |

**Bottom-line baseline finding**: 4 of the 4 PRD-referenced code fixes are already merged. **W9 reduces to (a) operational verification + (b) net-new observability instrumentation.** No blockers, no schema changes, no migrations.

---

## 4. Wave Plan

### Wave A — Pre-flight Verification (Read-only, No Code Changes) ✅

**Goal**: Empirically verify which W9 items are truly already shipped vs. which are still pending in the live cluster (because "code merged" ≠ "deployed and consumed").

**Status**: **DONE** — 2026-05-04 · no code changes · audit file committed · ruff + mypy N/A (no code)

**Depends on**: none.
**Estimated effort**: 30–45 min.
**Architecture layer**: ops/diagnostics (no code).

#### Tasks

##### T-A-01: Verify BP-302 fix is deployed in nlp-pipeline image

**Type**: config (verification only — no code change)
**depends_on**: none
**blocks**: T-B-01, T-B-02
**Target files**: none (read-only)
**PRD reference**: §3 FR-T2-3 ("apply BP-302 article-consumer hang fix")

**What to verify**:
1. The running `nlp-pipeline` container image contains the `progress_made` guard. Run inside the container: `python -c "import inspect; from nlp_pipeline.application.blocks import embeddings; print('progress_made' in inspect.getsource(embeddings.chunk_section))"` — must print `True`.
2. The Kafka consumer-group offset for `nlp-pipeline-article-consumer` is **not** parked at the same partition+offset for >2 hours (proxy for "currently hung"). Capture the offsets via `docker compose exec kafka kafka-consumer-groups --bootstrap-server localhost:9092 --describe --group nlp-pipeline-article-consumer`.

**Logic & Behavior**:
- This is a verification gate. If (1) is False → image needs rebuild. If (2) shows lag with frozen offset → Wave B's offset reset is required. Otherwise Wave B's offset reset can be **skipped** (record decision in commit message).

**Tests to write**: none (this is an operational probe, not a unit-testable change).

**Acceptance criteria**:
- [ ] Image source-introspection confirms `progress_made` present.
- [ ] Captured `kafka-consumer-groups` output recorded in plan tracking comment / commit message.
- [ ] Decision documented: "skip offset reset" or "execute offset reset in T-B-02".

---

##### T-A-02: Verify F-VISUAL-002 / F-E8 / F-D4 are deployed in current frontend bundle

**Type**: config (verification only)
**depends_on**: none
**blocks**: T-B-03
**Target files**: none (read-only)
**PRD reference**: §3 FR-T2-3

**What to verify**:
1. CSS: load `https://<frontend-host>/_next/static/css/*.css` (or `apps/worldview-web/.next/...` after `pnpm build`) and grep for `--muted-foreground:240 4% 55%` in **both** `:root` and `.dark` rule blocks (or the prefers-contrast / system equivalents). Already verified in source at `apps/worldview-web/app/globals.css:74,177`.
2. Bundle: `pnpm -C apps/worldview-web build` then `grep -r "/\\\\\\/undefined" apps/worldview-web/.next/server/` to confirm the `_client.ts` guard survived minification (regex pattern preserved as a string literal).
3. EU-date: confirm `git log --oneline -- apps/worldview-web | grep f27e266b` shows the F-D4 fix on the current branch.

**Acceptance criteria**:
- [ ] All three checks documented in commit / tracking note.
- [ ] If any of the three is missing in the *deployed* bundle → flag as a deploy-pipeline issue, not a W9 task (escalate, don't patch in W9).

---

##### T-A-03: Document W9 baseline state in audit folder

**Type**: docs
**depends_on**: T-A-01, T-A-02
**blocks**: none
**Target files**: `docs/audits/2026-05-03-w9-pre-flight-baseline.md` (new)
**PRD reference**: §3 FR-T2-3, §3 FR-T3-1

**What to build**: A short markdown audit file (target ≤80 lines) recording what was verified in T-A-01/T-A-02 plus the "what is missing" list (Sentry not installed; no UptimeRobot; no status page) — this becomes the input to Waves C/D/E and the post-launch verification baseline.

**Acceptance criteria**:
- [x] File exists with the four PRD-referenced fixes' deployed-state explicitly checked.
- [x] File lists every observability artifact (Sentry/UptimeRobot/status page) as **MISSING — to be installed in Waves C/D/E**.

#### Pre-read

- `docs/specs/0034-mvp-launch-readiness-program.md` §3 FR-T2-3, FR-T3-1
- `services/nlp-pipeline/src/nlp_pipeline/application/blocks/embeddings.py:80-160` (BP-302 fix region)
- `apps/worldview-web/app/globals.css:60-180` (CSS variable region)
- `apps/worldview-web/lib/api/_client.ts:60-90` (`/undefined` guard region)
- `docs/audits/2026-05-01-qa-platform-stability-iter3.md` (BP-302 root-cause history)

#### Validation Gate

- [x] Read-only — no code/test changes.
- [x] Audit file committed under `docs/audits/`.

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|---------------|--------------|
| (none) | Read-only wave | n/a |

#### Regression Guardrails

- BP-302 (article-consumer hang): if T-A-01 finds the fix missing in image → escalate to a hot rebuild before any further W9 work. **Do not** silently bake more changes into a stale image.

---

### Wave B — Operational Cleanup: Redeploy + Offset Reset + Smoke ✅

**Goal**: Convert the merged-but-possibly-not-yet-effective code fixes into observable healthy production state. Reset the article-consumer offset only if Wave A flagged it stuck. Verify acceptance criteria from PRD-0034 §3 FR-T2-3.

**Depends on**: Wave A (T-A-01, T-A-02).
**Estimated effort**: 45–90 min (was 30–60; +15 min for T-B-04 EU economic-events offset reset per audit B-001/I-003).
**Status**: **DONE** — 2026-05-04 · 18 Playwright a11y tests pass · T-B-04 executed · FR-T2-3 verified.
**Architecture layer**: ops.

#### Tasks

##### T-B-01: Conditionally redeploy nlp-pipeline if image lacks BP-302 fix

**Type**: config
**depends_on**: T-A-01
**blocks**: T-B-02
**Target files**: `infra/compose/docker-compose.yml` (no edit unless rebuild needed); `services/nlp-pipeline/Dockerfile` (touch only if a layer-cache bust is required)
**PRD reference**: §3 FR-T2-3

**What to build**:
- If T-A-01 shows fix present in image: **skip** this task; record `SKIPPED` in commit.
- If absent: `docker compose build --no-cache nlp-pipeline && docker compose up -d nlp-pipeline` (or the gitops equivalent in `infra/gitops/`).

**Acceptance criteria**:
- [ ] Either skipped with audit note, or container runs new image whose `embeddings.chunk_section` contains `progress_made`.
- [ ] `nlp-pipeline` container is healthy (`/health` 200) after restart.

---

##### T-B-02: Conditionally reset article-consumer Kafka offset to skip the poison-pill message

**Type**: config
**depends_on**: T-A-01, T-B-01
**blocks**: T-B-03
**Target files**: none (Kafka admin command); record outcome in `docs/audits/2026-05-03-w9-pre-flight-baseline.md`
**PRD reference**: §3 FR-T2-3 ("redeploy + reset offset")

**What to build**:
Only if T-A-01 flagged a stuck offset:
1. Stop the consumer: `docker compose stop nlp-pipeline-article-consumer` (or the gitops equivalent).
2. Identify the stuck partition+offset from T-A-01 capture.
3. Reset to `--to-current` (preferred — resumes from latest, accepting some message loss for the corrupt one) **only if the messages from the poison-pill onward have been re-published** OR if loss is acceptable. **Default action**: `--shift-by 1` past the poison-pill to skip exactly one message.
4. Restart consumer.

**Logic & Behavior**:
- Idempotency: this operation is one-time. If consumer is already past the poison-pill (Wave A T-A-01 showed advancing offsets), **skip**.
- Error classification: if `kafka-consumer-groups` returns `Group has active members`, the consumer was not stopped — retry stop step.
- Audit trail: record exact partition/offset numbers before and after in the audit file.

**Acceptance criteria**:
- [ ] Either skipped or executed with before/after offsets recorded.
- [ ] Within 10 min after action, consumer lag begins decreasing (visible in Grafana Kafka dashboard from PLAN-0054).
- [ ] No new error logs in nlp-pipeline structlog stream within 15 min after action.

---

##### T-B-03: Smoke-verify FR-T2-3 acceptance criteria end-to-end

**Type**: test (manual / scripted operational)
**depends_on**: T-A-02, T-B-02, T-B-04
**blocks**: none (feeds into final E)
**Target files**: `docs/audits/2026-05-03-w9-pre-flight-baseline.md` (append)
**PRD reference**: §3 FR-T2-3 acceptance criteria

**What to build**: A 4-step smoke checklist run against the live cluster:

1. **WCAG AA contrast on `text-muted-foreground` — multi-route axe-core sweep (revised 2026-05-03 per Sam-alignment audit)**. Replaces the single Lighthouse-on-dashboard pass which validated ≈1% of the surface (the codebase has **876 `text-muted-foreground` usages** spread across chat citations, brief footnotes, fundamentals tables, screener, etc — Sam working a 10-hour day notices the long tail, not just the dashboard). Run a Playwright loop over the canonical Sam-routes (`/dashboard`, `/chat`, `/instruments/<sample-id>`, `/news`, `/screener`, `/workspace`, `/search?q=apple`, brief render) executing `@axe-core/playwright` with the `color-contrast` rule, asserting **zero violations on `text-muted-foreground`-derived elements specifically**. Same effort as Lighthouse (~5 min), real coverage. Script committed at `apps/worldview-web/e2e/a11y-muted-foreground.spec.ts`; CI-runnable so future regressions trip the pipeline.
2. **Zero `/undefined` 500-errors in 24h gateway logs**: query Loki `{service="api-gateway"} |= "/undefined" | json | status >= 500` over the last 24h — must return 0 rows. (If <24h since redeploy, run this in T-E-04 instead.)
3. **Article-consumer producing again**: check `relation_evidence_raw` row-count in `intelligence_db` is increasing over a 30 min window — this validates BP-302 fix actually unblocked the downstream cascade as predicted in `2026-05-01-qa-platform-stability-iter3.md`.
4. **F-D4 backend EU date parse fix verification (corrected 2026-05-03 audit)**: this is a **backend** check, not a frontend portfolio check. Two parts:
   - **(a) Unit-behaviour probe**: in a Python REPL inside the running `worldview-knowledge-graph` container, execute:
     ```python
     from knowledge_graph.infrastructure.messaging.consumers.economic_events_dataset_consumer import _parse_event_date
     dt = _parse_event_date("2026-04-30 12:15:00")
     assert dt is not None, "F-D4 regression: EU space-separated date returned None"
     assert dt.isoformat() == "2026-04-30T12:15:00+00:00", f"unexpected: {dt.isoformat()}"
     print("F-D4 OK")
     ```
     Must print `F-D4 OK`. Confirms the `replace(" ", "T", 1)` normalisation (line 102) is in the deployed image.
   - **(b) Live data probe**: query `intelligence_db` for `temporal_events` rows where `region` is one of the EU-mapped countries (`EU`, `DE`, `FR`, `IT`) AND `event_date >= now() - interval '24h'` — expect count > 0 once T-B-04's offset reset has executed (which is the operator-follow-up explicitly named in commit `f27e266b`'s message). If count is still 0, T-B-04 either has not run yet or did not rewind far enough. Record SQL + count.

**Acceptance criteria**:
- [ ] All 4 checks pass and recorded with timestamp + capture in audit doc.
- [ ] Step 4 (a) prints `F-D4 OK` in the container; step 4 (b) shows non-zero EU `temporal_events` after T-B-04.
- [ ] If any fail → open a follow-up issue **outside** W9 (do not block W9 on root-cause; record as deferred).

---

##### T-B-04: Reset `kg-economic-events-dataset-group` consumer offset to backfill EU events dropped pre-`f27e266b` (NEW — operator follow-up)

**Type**: config (Kafka admin command — operational)
**depends_on**: T-A-01 (verifies KG image has `_parse_event_date` fix); independent of T-B-01..T-B-03
**blocks**: T-B-03 (smoke step 4 (b) needs the rewind to have happened)
**Target files**:
- `docs/audits/2026-05-03-w9-pre-flight-baseline.md` (append before/after offsets + decision)
**PRD reference**: §3 FR-T2-3 (FR spirit — "redeploy + reset offset"); commit `f27e266b` message ("Operator follow-up: reset `kg-economic-events-dataset-group` consumer offsets to backfill the dropped events")

**Why this task exists** (per 2026-05-03 audit B-001 / I-003): The original draft of this plan misclassified F-D4 as a frontend bug. F-D4 is a backend EU date-parse fix in `services/knowledge-graph/.../economic_events_dataset_consumer.py:_parse_event_date`. The commit message of `f27e266b` explicitly names a required operator follow-up — rewind the consumer-group offset so the EODHD economic-events stream is replayed from before the drop window (live cluster logged 81 EU events ingested=0 at 2026-04-30 12:25:55). Without this rewind, the data loss is permanent in `temporal_events`. This is the **single highest-leverage operational fix** in W9 and was missing from the draft plan.

**What to build** (one-time admin action):

1. **Verify the image already has the fix** (precondition). T-A-01 confirms the running `worldview-knowledge-graph-economic-events-dataset-consumer-1` container's source contains the `replace(" ", "T", 1)` normalisation at line 102. If absent → image rebuild required FIRST (mirrors T-B-01 pattern but for KG service).

2. **Capture current offsets** (audit trail):
   ```bash
   docker compose exec kafka kafka-consumer-groups.sh \
     --bootstrap-server localhost:9092 \
     --describe \
     --group kg-economic-events-dataset-group
   ```
   Record `CURRENT-OFFSET` and `LOG-END-OFFSET` per partition in the audit doc.

3. **Stop the consumer** so the offset reset is accepted (Kafka rejects resets while the group has active members):
   ```bash
   docker compose stop knowledge-graph-economic-events-dataset-consumer
   ```
   (Service name per `infra/compose/docker-compose.yml` — verify exact name first; in production gitops, scale the deployment to 0 replicas instead.)

4. **Rewind the offset**. Default action: rewind by 24 hours' worth of messages — but Kafka does not natively support time-based rewinds via the CLI without `--to-datetime`. Use `--to-datetime` because the drop window is well-bounded (2026-04-30 ~12:00:00 UTC):
   ```bash
   docker compose exec kafka kafka-consumer-groups.sh \
     --bootstrap-server localhost:9092 \
     --group kg-economic-events-dataset-group \
     --topic ingestion.dataset.economic_events.v1 \
     --reset-offsets \
     --to-datetime 2026-04-30T00:00:00.000 \
     --execute
   ```
   (Replace topic name with the actual S2 → S7 economic-events dataset topic — verify in `infra/kafka/schemas/` and `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/economic_events_dataset_consumer.py` topic constant.)

5. **Restart the consumer**:
   ```bash
   docker compose start knowledge-graph-economic-events-dataset-consumer
   ```

6. **Verify**: within 10 min, `temporal_events` row-count for EU regions begins increasing. T-B-03 step 4 (b) is the dedicated probe.

**Logic & Behavior**:
- **Idempotency**: if step 2 shows `CURRENT-OFFSET` is already at or before the rewind target → **skip** (already replayed). Record `SKIPPED` in audit doc.
- **Error classification**: if `kafka-consumer-groups` returns `Group has active members`, step 3 was not effective — retry stop, then poll `--describe` until `MEMBERS = 0`.
- **Re-delivery safety**: replayed messages hit the same `_parse_event_date` path that now succeeds for EU shapes; downstream `INSERT … ON CONFLICT DO NOTHING` patterns in the migration ensure no duplicates appear in `temporal_events` (verify the consumer uses upsert semantics — read `economic_events_dataset_consumer.py` `_handle_message` to confirm before executing).

**Tests to write**: none (operational; audit-doc trail is the evidence).

**Acceptance criteria**:
- [ ] Either skipped with audit note explaining why, or executed with before/after `--describe` outputs recorded.
- [ ] Within 10 min after restart, KG container logs show non-zero EU events being processed (grep for `region=EU` or similar log line — confirm exact log format from `economic_events_dataset_consumer.py`).
- [ ] T-B-03 step 4 (b) returns count > 0 once T-B-04 completes.
- [ ] Topic name + reset-target datetime explicitly recorded in `docs/audits/2026-05-03-w9-pre-flight-baseline.md`.

**Regression guardrails**:
- **BP-001** (at-least-once / idempotency): replayed messages are upserted via `ON CONFLICT DO NOTHING`; no duplicate rows expected. Audit doc records the row-count before / after as a sanity check.
- The poison-pill pattern from T-B-02 does **not** apply here — T-B-04 rewinds past well-formed messages that previously failed the parser; with the parser fixed, they now ingest cleanly.

#### Pre-read

- Output of Wave A T-A-01/T-A-02
- `docs/audits/2026-05-01-qa-platform-stability-iter3.md` for BP-302 expected downstream effect
- Commit message of `f27e266b` (full text — explicitly names the operator follow-up)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/messaging/consumers/economic_events_dataset_consumer.py:_parse_event_date` (lines 84-109; line 102 `replace(" ", "T", 1)` is the fix)
- Topic constant in the same file (used in step 4 `--topic` arg)
- `infra/gitops/` (if production deploy) or `infra/compose/docker-compose.yml` (if local)

#### Validation Gate

- [x] All container restarts result in healthy `/health` 200.
- [x] No new structlog `error` events in 15 min post-action.
- [x] Smoke checklist all green or deferred items documented.

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|---------------|--------------|
| (none — operational only) | n/a | n/a |

If offset reset skips a message that downstream consumers expected: confirmed acceptable per PRD §10 ("partial completion is acceptable"); document as "1 message lost on YYYY-MM-DD partition N offset M" in audit doc.

#### Regression Guardrails

- **BP-007** (DB+Kafka dual writes): N/A — pure read.
- **BP-302** (article-consumer hang): the very pattern we are confirming is closed. T-B-03 step 3 directly probes for the documented downstream symptom (`relation_evidence_raw` stuck at 0).
- **BP-001** (Kafka consumer at-least-once / idempotency): offset reset by `--shift-by 1` skips one message. Acceptable because the message is a known poison-pill that **always** crashes processing — re-delivering will re-hang the consumer (loop). Record this as the conscious choice.

---

### Wave C — Backend Sentry Integration (libs/observability) ✅

**Goal**: Add Sentry SDK as a fourth observability pillar (alongside structlog/Loki, OTel/Tempo, Prometheus). Implementation is centralised in `libs/observability` so all 10 services pick it up by adding a single `init_sentry()` call at startup. Make it opt-in via `SENTRY_ENABLED=false` default so dev/test environments do not need a DSN.

**Depends on**: Wave A (baseline doc).
**Estimated effort**: 150–180 min (was 90–120; T-C-01 +30 for rate-limiter, T-C-05 +60 for S6 + S8 wiring per audit I-001/I-002).
**Status**: **DONE** — 2026-05-04 · 38 tests pass (28 observability + 10 service sentry_init) · ruff + mypy clean · 100 architecture tests pass
**Architecture layer**: infrastructure (libs).

#### Tasks

##### T-C-01: Add `sentry-sdk[fastapi]` to `libs/observability` deps and create `init_sentry()` module

**Type**: impl
**depends_on**: none (within Wave C; Wave A is plan-level prereq)
**blocks**: T-C-02, T-C-03
**Target files**:
- `libs/observability/pyproject.toml` (add dep)
- `libs/observability/src/observability/sentry.py` (new file, ~80 LOC)
- `libs/observability/src/observability/__init__.py` (re-export)
- `libs/observability/tests/test_sentry.py` (new file, ~120 LOC)

**PRD reference**: §3 FR-T3-1

**What to build**:

`init_sentry(service_name: str, *, settings: SentrySettings | None = None) -> bool` — single entry point all backend services call once at startup (in their FastAPI lifespan / `main.py`). Returns `True` if Sentry was actually initialised, `False` if disabled (so callers can log the decision).

**Entities / Components**:

- **Name**: `SentrySettings` (pydantic-settings)
- **Purpose**: Read DSN, environment, sample-rate, release from env vars with safe dev defaults.
- **Key attributes**:
  - `enabled: bool = False` (env: `SENTRY_ENABLED`; **default False** so unit tests / dev compose do not fire)
  - `dsn: SecretStr | None = None` (env: `SENTRY_DSN`; required when `enabled=True`)
  - `environment: str = "development"` (env: `SENTRY_ENVIRONMENT`)
  - `traces_sample_rate: float = 0.0` (env: `SENTRY_TRACES_SAMPLE_RATE`; **0 by default** — Tempo handles tracing already, do not double-pay)
  - `release: str | None = None` (env: `SENTRY_RELEASE`; usually set to the git SHA at deploy time)
- **Key methods**: pydantic v2 `model_validator(mode="after")` — if `enabled and not dsn` → raise `ValueError("SENTRY_DSN required when SENTRY_ENABLED=True")`. Catches misconfiguration loudly per BP feedback `feedback_audit_returned_value_persistence`.
- **Invariants**: when `enabled=False`, no SDK calls happen; the module is a true no-op.

- **Name**: `init_sentry`
- **Purpose**: One-line idempotent SDK init.
- **Logic**:
  1. If settings.enabled is False → log `sentry_disabled` and return False.
  2. Else call `sentry_sdk.init(dsn=str(dsn.get_secret_value()), environment=..., traces_sample_rate=..., release=..., attach_stacktrace=True, send_default_pii=False, before_send=_strip_pii)`.
  3. Set Sentry tag `service=<service_name>`.
  4. Log `sentry_initialised` (structlog) with masked DSN host only.
  5. Return True.
- **PII guard + per-fingerprint rate limiter `_before_send(event, hint)`** — single hook combining two concerns to satisfy audit I-002 (Sentry 5K free-tier quota safety):
  - **PII strip** (must run first; revised 2026-05-03 per Sam-alignment audit — adds URL-class scrubs which the prior list missed):
    - drop `event["request"]["cookies"]`, `event["request"]["headers"]["authorization"]`, `event["request"]["headers"]["x-internal-jwt"]`.
    - drop any `extra` key matching `r"(?i)(token|secret|password|api[_-]?key|jwt)"`.
    - if `event["user"]["email"]` exists → hash it with sha256 and replace value.
    - **Drop `event["request"]["query_string"]`** entirely (added 2026-05-03). Query strings carry Sam's research footprint — tickers, search queries, entity ids — which is portfolio-leakage-grade information for a paid analyst tool. The trace is still useful without it (path + status + stack frame); we lose only the query terms, which is the right trade.
    - **Rewrite `event["request"]["url"]`** path segments matching `/instruments/[A-Z]{1,5}/` (and similar entity-id slugs `/news/[uuid]/`, `/entities/[uuid]/`) to `<redacted>`. Don't ship which ticker Sam was looking at when the error fired.
    - **Scrub `breadcrumbs[].data.url`** the same way. Sentry's default breadcrumbs include `console.log` output and `fetch` URLs which are the noisiest leak vector — `/v1/instruments/AAPL/ownership` reveals Sam's research focus to a third-party SaaS.
    - **Never** ship full request bodies.
  - **Per-fingerprint rate limit** (run after PII strip): drop the event when the same fingerprint has already fired more than `_FINGERPRINT_MAX_EVENTS_PER_HOUR` (default `10`) in the last hour. Reference implementation:
    ```python
    from collections import deque
    from threading import Lock
    from time import monotonic

    _FINGERPRINT_WINDOW_SEC = 3600.0
    _FINGERPRINT_MAX_EVENTS_PER_HOUR = 10
    _fingerprint_counts: dict[str, deque[float]] = {}
    _fingerprint_lock = Lock()

    def _is_rate_limited(fingerprint: str) -> bool:
        """Token-bucket-style limiter keyed on Sentry fingerprint.

        Returns True when the caller should drop this event. Ages out
        timestamps older than the window before counting. Logs the drop
        via structlog so Loki retains visibility even when Sentry is
        being throttled.
        """
        now = monotonic()
        with _fingerprint_lock:
            stamps = _fingerprint_counts.setdefault(fingerprint, deque())
            while stamps and now - stamps[0] > _FINGERPRINT_WINDOW_SEC:
                stamps.popleft()
            if len(stamps) >= _FINGERPRINT_MAX_EVENTS_PER_HOUR:
                return True
            stamps.append(now)
            return False
    ```
    The fingerprint is derived from `event.get("fingerprint")` if present, else `(event.get("exception", {}).get("values", [{}])[0].get("type"), event.get("transaction"))` joined with `:`. **Reason for choosing per-fingerprint (not global) rate limit**: a single misconfigured query that throws on every request would otherwise burn the entire 5K monthly quota in <30 min, blinding us to subsequent unrelated incidents. Per-fingerprint caps ensure the first regression cannot starve the next one.
- **Idempotency**: the limiter state is per-process and lost on restart — acceptable because Sentry caps are monthly, not per-process; an HPA replica that restarts every 24 h still satisfies the spirit (≤10 events × 24 restarts × N replicas = bounded burst).

**Logic & Behavior**:
- **Idempotency**: `sentry_sdk.init` is itself idempotent within a process; calling twice is harmless but log a warning.
- **Error classification**: if `sentry_sdk.init` raises (network probe at init time) → log `sentry_init_failed` and **return False instead of crashing the service**. Sentry being down must never take down a worldview backend.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|------------------|------|
| `test_init_sentry_disabled_returns_false` | when `SENTRY_ENABLED=false`, returns False, no SDK call | unit |
| `test_init_sentry_enabled_without_dsn_raises` | settings model rejects enabled+no dsn | unit |
| `test_init_sentry_enabled_with_dsn_returns_true` | mock `sentry_sdk.init`; assert called once with attach_stacktrace=True, send_default_pii=False | unit |
| `test_init_sentry_init_failure_returns_false` | mock `sentry_sdk.init` to raise; assert returns False, error logged, no propagation | unit |
| `test_strip_pii_removes_authorization_header` | event with auth header → header dropped | unit |
| `test_strip_pii_removes_x_internal_jwt` | event with x-internal-jwt → dropped | unit |
| `test_strip_pii_hashes_user_email` | event with `user.email="x@y.z"` → replaced with sha256 hex | unit |
| `test_strip_pii_drops_token_keys_from_extra` | extra={"jwt_token": "abc"} → key dropped | unit |
| `test_strip_pii_drops_query_string` | (Sam-fit) `event.request.query_string="?q=AAPL"` → key removed entirely | unit |
| `test_strip_pii_redacts_instrument_ticker_in_url_path` | (Sam-fit) `event.request.url="/v1/instruments/AAPL/ownership"` → rewritten to `/v1/instruments/<redacted>/ownership` | unit |
| `test_strip_pii_redacts_breadcrumb_urls` | (Sam-fit) breadcrumbs[].data.url containing `/instruments/NVDA/` rewritten to `/instruments/<redacted>/` — covers Sentry's default fetch breadcrumbs | unit |
| `test_before_send_drops_excess_events_per_fingerprint` | fire 50 events with the same fingerprint within 1s; assert exactly `_FINGERPRINT_MAX_EVENTS_PER_HOUR` retained, the rest dropped (return value is None) | unit |
| `test_before_send_independent_fingerprints_not_throttled` | fire 10 events for fingerprint A and 10 for fingerprint B; all 20 retained | unit |
| `test_before_send_aged_stamps_evicted` | with monotonic mocked, fire `MAX_EVENTS` then advance >1h then fire 1 more; the new event is retained (window slid) | unit |
- Minimum test count: 14 (was 11; added 3 for URL-class scrubs per Sam-alignment audit)
- Edge cases: DSN with `SecretStr` wrapping, DSN env-var empty string vs missing (BP-179), idempotent double-init.
- Error paths: network error, malformed DSN.

**Downstream test impact**: none — additive new module, no existing callers.

**Acceptance criteria**:
- [ ] `pyproject.toml` adds `sentry-sdk[fastapi]>=2.18.0,<3` with **exact lower bound** to avoid drift.
- [ ] `init_sentry` returns False when disabled and never raises.
- [ ] PII guard verified by 4 unit tests; fingerprint rate-limit verified by 3 unit tests (total ≥11).
- [ ] `from observability import init_sentry, SentrySettings` works.
- [ ] `_FINGERPRINT_MAX_EVENTS_PER_HOUR` is module-level and tunable via env (`SENTRY_FINGERPRINT_RATE_LIMIT`, default 10) — documented in T-C-04.
- [ ] ruff + mypy strict clean.

---

##### T-C-02: Wire `init_sentry` into `register_error_handlers` so unhandled exceptions go to Sentry

**Type**: impl
**depends_on**: T-C-01
**blocks**: T-C-03
**Target files**:
- `libs/observability/src/observability/error_capture.py` (extend ~10 LOC)
- `libs/observability/tests/test_error_capture.py` (extend / new)

**PRD reference**: §3 FR-T3-1

**What to build**: Extend `unhandled_exception_handler` so it (a) keeps the existing structlog log (R10 unchanged), and (b) calls `sentry_sdk.capture_exception(exc)` if Sentry is initialised. Order: **structlog first, then Sentry**, so structlog's record exists even if Sentry capture errors.

**Logic & Behavior**:
- Use `sentry_sdk.Hub.current.client` to detect "is Sentry init'd". If None → skip Sentry call (covers tests / disabled).
- Wrap Sentry call in `try/except Exception: log.warning("sentry_capture_failed", exc_info=True)` so a Sentry outage never replaces the user's 500 with a different 500.
- Don't add a new Sentry breadcrumb — `capture_exception` does that itself.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|------------------|------|
| `test_handler_calls_sentry_when_initialised` | mock `sentry_sdk.capture_exception`; assert called once with the exc | unit |
| `test_handler_skips_sentry_when_not_initialised` | client=None; assert not called | unit |
| `test_handler_swallows_sentry_failures` | capture_exception raises → handler still returns JSONResponse 500, structlog has both records | unit |
- Minimum test count: 3 (added to existing file)
- Edge cases: `BaseException` subclasses (KeyboardInterrupt) — Sentry SDK already filters these; no extra handling.

**Downstream test impact**:
- All 10 services' tests that import `register_error_handlers` continue to pass. No call-site change.

**Acceptance criteria**:
- [ ] Adding Sentry capture is non-breaking — existing 1-test handler suite still passes.
- [ ] Sentry call is best-effort (failure never propagates).

---

##### T-C-03: Wire `init_sentry` at startup of api-gateway (S9) — pilot service

**Type**: impl
**depends_on**: T-C-01, T-C-02
**blocks**: T-C-04
**Target files**:
- `services/api-gateway/src/api_gateway/app.py` (add 3 lines in lifespan startup)
- `services/api-gateway/src/api_gateway/config.py` (mount `SentrySettings`)
- `services/api-gateway/tests/unit/test_sentry_init.py` (new, 1 test)

**PRD reference**: §3 FR-T3-1 ("Sentry integration on S9")

**What to build**:
- In `app.py` lifespan startup: `init_sentry(service_name="api-gateway", settings=SentrySettings())` — log result.
- In `config.py`: re-export `SentrySettings` from observability so the gateway exposes an explicit dependency.

**Tests to write**:
| Test Name | What It Verifies | Type |
|-----------|------------------|------|
| `test_lifespan_calls_init_sentry_with_service_name` | mock `init_sentry`; assert called once with `service_name="api-gateway"` | unit |
- Minimum test count: 1
- Edge cases: lifespan called twice (test client) — sentry init is idempotent.

**Downstream test impact**:
- `services/api-gateway/tests/` test fixtures that build a fresh app must not assert on Sentry not being called. If any do, update them.
- Specifically check `services/api-gateway/tests/unit/test_app.py` — likely passes through; verify.

**Acceptance criteria**:
- [ ] S9 starts cleanly with `SENTRY_ENABLED=false` (default).
- [ ] When `SENTRY_ENABLED=true` and a stub DSN is set in test, `init_sentry` is invoked.
- [ ] An intentional 500 (e.g. `/v1/_test/raise` test-only route — **do not** ship to prod) propagates to Sentry mock in test; documented manually.

---

##### T-C-04: Document Sentry env-var contract + add to gitops values

**Type**: docs + config
**depends_on**: T-C-03
**blocks**: T-C-05, T-E-01
**Target files**:
- `dev.local.env.example` (or repo equivalent)
- `infra/gitops/values/<env>.yaml` (PLAN-0024 chart values; add the 5 Sentry env vars under the `secrets:` section as **optional**)
- `docs/services/api-gateway.md` (1 paragraph under "Observability")
- `docs/libs/observability.md` (new section "Sentry integration")
- `RULES.md` (add a single bullet: "When importing `observability`, Sentry init is opt-in via `SENTRY_ENABLED`; default is disabled so unit tests are isolated")
- `docs/STANDARDS.md` §Observability (NEW subsection — applied inline per audit N-005, do NOT defer): document the canonical Sentry init pattern (default-off, PII `before_send` guard, per-fingerprint rate limit, idempotent init, returns bool that the call site logs). The pattern is broadly applicable; deferring its documentation risks the next service-author copying a slightly different shape.

**PRD reference**: §3 FR-T3-1, §4 NFR table

**What to build**:
- `dev.local.env.example` lines:
  ```
  # Sentry — leave disabled in dev; set to true + provide DSN in prod
  SENTRY_ENABLED=false
  SENTRY_DSN=
  SENTRY_ENVIRONMENT=development
  SENTRY_TRACES_SAMPLE_RATE=0.0
  SENTRY_RELEASE=
  SENTRY_FINGERPRINT_RATE_LIMIT=10  # per fingerprint per hour; protects 5K/month free-tier quota
  ```
- gitops values: same 6 keys under environment-specific overrides.
- Doc paragraph in `docs/libs/observability.md`: when, why, default-off rationale, PII guard description, fingerprint rate-limit rationale, free-tier 5k events/month from PRD §10.
- STANDARDS.md §Observability addition (~15 lines): canonical pattern code snippet + checklist for new services.

**Acceptance criteria**:
- [ ] All 6 docs touched; cross-reference to PRD-0034 §3 FR-T3-1.
- [ ] STANDARDS.md §Observability addition reviewed for accuracy against T-C-01 implementation.
- [ ] Pre-commit docs hook passes.

---

##### T-C-05: Wire `init_sentry` into nlp-pipeline (S6) and rag-chat (S8) — scope expansion per audit I-001

**Type**: impl
**depends_on**: T-C-03 (S9 pilot proven), T-C-04 (env vars + docs)
**blocks**: T-E-01
**Target files**:
- `services/nlp-pipeline/src/nlp_pipeline/api/main.py` or its FastAPI app/lifespan equivalent (read first to confirm exact entry point)
- `services/nlp-pipeline/src/nlp_pipeline/config.py` (mount `SentrySettings`)
- `services/nlp-pipeline/tests/unit/test_sentry_init.py` (new, 1 test)
- `services/rag-chat/src/rag_chat/api/main.py` or equivalent (read first)
- `services/rag-chat/src/rag_chat/config.py`
- `services/rag-chat/tests/unit/test_sentry_init.py` (new, 1 test)

**PRD reference**: §3 FR-T3-1; cross-plan dependency from PLAN-0063 (W5) Wave W5-5 metrics + PLAN-0064 (W6) `FatalSearchError` Sentry capture.

**Why this task exists** (per audit I-001): PLAN-0063 W5-5 emits 4 new Prometheus metrics from S6 (nlp-pipeline) and S8 (rag-chat). PLAN-0064 W6 explicitly references "+log + Sentry" on `FatalSearchError` raised in S6. Both downstream plans assume `init_sentry` is callable from those services. If W9 ships only the S9 pilot, the W5/W6 authors will either (a) duplicate Wave C's wiring in their own plans (rework), or (b) silently drop the Sentry calls (feature loss). Wiring all three at once costs ~30 min/service. The remaining 7 services stay deferred to the post-launch hardening sprint.

**What to build** (per service — same shape as T-C-03):
- In each service's FastAPI lifespan startup: `init_sentry(service_name="<service>", settings=SentrySettings())`. Log the returned bool. The lib does the heavy lifting; the per-service patch is ~3 lines.
- In each `config.py`: re-export `SentrySettings` (mirrors S9 pattern).

**Logic & Behavior**:
- **Idempotency**: `sentry_sdk.init` is process-idempotent.
- **Default-off**: with `SENTRY_ENABLED=false` (the default), startup is a no-op + 1 structlog line.
- **Service tag**: `service=<name>` Sentry tag is set automatically by `init_sentry`; downstream metric / cron emitters do not need to re-tag.

**Tests to write** (per service):
| Test Name | What It Verifies | Type |
|-----------|------------------|------|
| `test_lifespan_calls_init_sentry_with_service_name` (S6) | mock `init_sentry`; assert called once with `service_name="nlp-pipeline"` | unit |
| `test_lifespan_calls_init_sentry_with_service_name` (S8) | mock `init_sentry`; assert called once with `service_name="rag-chat"` | unit |
- Minimum test count: 2 (1 per service)

**Downstream test impact**:
- S6 + S8 unit suites must continue to pass with `SENTRY_ENABLED=false` (the default in test env). Verify by running each service's full pytest suite and confirming zero new failures (per audit N-003 — extend the validation gate explicitly to include all 8 services that import `register_error_handlers`, since T-C-02 also touches the lib's exception handler path).

**Acceptance criteria**:
- [ ] S6 starts cleanly with `SENTRY_ENABLED=false`; S8 starts cleanly with `SENTRY_ENABLED=false`.
- [ ] When `SENTRY_ENABLED=true` and stub DSN is set, both services invoke `init_sentry`.
- [ ] Each service's full unit suite passes after the change (no test asserting on lifespan side-effects breaks).
- [ ] PLAN-0063 W5-5 author can call `from observability import sentry_sdk_capture` (or equivalent — confirm the public surface) without further wiring.
- [ ] PLAN-0064 W6 author can raise `FatalSearchError` and have the existing `register_error_handlers` capture it via T-C-02.
- [ ] Total time for T-C-05: ~60 min combined (~30 min each).

---

##### T-C-05-EXT: Wire `init_sentry` into remaining 7 backend services (S1, S2, S3, S4, S5, S7, S10) — rev-2

**Type**: impl
**depends_on**: T-C-03 (S9 pilot proven), T-C-05 (S6 + S8 wired — confirms pattern is solid)
**blocks**: T-C-06
**Target files** (per service — same ~3-line patch each; read the actual lifespan before patching):
- `services/portfolio/src/portfolio/app.py` + `config.py` + `tests/unit/test_sentry_init.py`
- `services/market-ingestion/src/market_ingestion/app.py` + `config.py` + `tests/unit/test_sentry_init.py`
- `services/market-data/src/market_data/app.py` + `config.py` + `tests/unit/test_sentry_init.py`
- `services/content-ingestion/src/content_ingestion/app.py` + `config.py` + `tests/unit/test_sentry_init.py`
- `services/content-store/src/content_store/app.py` + `config.py` + `tests/unit/test_sentry_init.py`
- `services/knowledge-graph/src/knowledge_graph/app.py` + `config.py` + `tests/unit/test_sentry_init.py`
- `services/alert/src/alert/app.py` + `config.py` + `tests/unit/test_sentry_init.py`
**PRD reference**: §3 FR-T3-1; rev-2 decision: zero deferrals — all services wire Sentry now.

**Why this task exists**: Rev-1 deferred the remaining 7 services to a "post-launch hardening sprint". Rev-2 removes this deferral. Since `init_sentry()` is already in `libs/observability` (T-C-01), the per-service wiring is ~3 lines each: one `init_sentry(service_name=...)` call in the lifespan startup (after tracing, before any I/O), one `SentrySettings` re-export in `config.py`, one test. Doing all 7 now costs ~3.5 hours but means: (a) every unhandled exception in every backend goes to Sentry from day one; (b) no follow-up plan needed; (c) Sentry's "which services have exceptions" breakdown is immediately meaningful.

**What to build** (per service — identical pattern to T-C-03/T-C-05):
1. Read the service's lifespan function (verify it uses `@asynccontextmanager`).
2. Add after `configure_tracing(...)` call (or after `configure_logging` if tracing is absent): `init_sentry(service_name="<kebab-case-service-name>", settings=SentrySettings())`. Log the returned bool. The service name tags every Sentry event so you can filter by service in the dashboard.
3. In `config.py`: add `from observability.sentry import SentrySettings` and expose it (mirrors S9 pattern).
4. Write 1 unit test per service asserting `init_sentry` is called with the correct `service_name` when the lifespan runs.

**Service name tag mapping** (use these exactly for consistent Sentry filtering):
| Service dir | `service_name` arg |
|-------------|-------------------|
| `portfolio` | `"portfolio"` |
| `market-ingestion` | `"market-ingestion"` |
| `market-data` | `"market-data"` |
| `content-ingestion` | `"content-ingestion"` |
| `content-store` | `"content-store"` |
| `knowledge-graph` | `"knowledge-graph"` |
| `alert` | `"alert"` |

**Logic & Behavior**:
- **Default-off**: `SENTRY_ENABLED=false` (default in every env); lifespan proceeds normally, `init_sentry` returns `False` and logs one structlog line.
- **Local debugging**: a developer can set `SENTRY_ENABLED=true` + their own `SENTRY_DSN` in their local `configs/docker.env` to debug a specific service. `setup-dev.sh` copies the gitops `.env` file which has `SENTRY_ENABLED=false`; the developer overrides locally.
- **Idempotency**: `sentry_sdk.init` is process-idempotent (safe if test client restarts the lifespan).
- **Failure handling**: if `sentry_sdk.init` raises (network probe), `init_sentry` catches it, logs `sentry_init_failed`, returns `False`. The service starts normally. Sentry failure must never take down a worldview backend.

**Tests to write** (1 per service, 7 total):
| Test Name | Service | What It Verifies | Type |
|-----------|---------|------------------|------|
| `test_lifespan_calls_init_sentry_with_service_name` | portfolio | mock `init_sentry`; assert called with `service_name="portfolio"` | unit |
| `test_lifespan_calls_init_sentry_with_service_name` | market-ingestion | called with `service_name="market-ingestion"` | unit |
| `test_lifespan_calls_init_sentry_with_service_name` | market-data | called with `service_name="market-data"` | unit |
| `test_lifespan_calls_init_sentry_with_service_name` | content-ingestion | called with `service_name="content-ingestion"` | unit |
| `test_lifespan_calls_init_sentry_with_service_name` | content-store | called with `service_name="content-store"` | unit |
| `test_lifespan_calls_init_sentry_with_service_name` | knowledge-graph | called with `service_name="knowledge-graph"` | unit |
| `test_lifespan_calls_init_sentry_with_service_name` | alert | called with `service_name="alert"` | unit |

**Downstream test impact**:
- Run full `pytest` suites on all 7 services after patching. Zero new failures expected since `SENTRY_ENABLED=false` is the test-env default and `init_sentry` is a no-op when disabled.
- Check each service's lifespan test (if any) for assertions that now need a `mock_init_sentry` fixture.

**Acceptance criteria**:
- [ ] All 7 services start cleanly with `SENTRY_ENABLED=false` (run `docker compose up <service>` and check `/health`).
- [ ] All 7 unit tests pass.
- [ ] All 7 full service pytest suites: zero new failures.
- [ ] `ruff check` + `mypy` clean across all 7.
- [ ] Total time: ~3.5 h (30 min/service — reading lifespan, 3-line patch, 1 test, run suite).

---

##### T-C-06: worldview-gitops env vars for all 10 services + docs + STANDARDS.md — rev-2

**Type**: config + docs
**depends_on**: T-C-05-EXT (all services wired before env vars committed)
**blocks**: T-E-01
**Target files** (worldview-gitops repo):
- `worldview-gitops/env/dev/portfolio.env` (add Sentry block)
- `worldview-gitops/env/dev/market-ingestion.env` (add Sentry block)
- `worldview-gitops/env/dev/market-data.env` (add Sentry block)
- `worldview-gitops/env/dev/content-ingestion.env` (add Sentry block)
- `worldview-gitops/env/dev/content-store.env` (add Sentry block)
- `worldview-gitops/env/dev/nlp-pipeline.env` (add Sentry block)
- `worldview-gitops/env/dev/knowledge-graph.env` (add Sentry block)
- `worldview-gitops/env/dev/rag-chat.env` (add Sentry block)
- `worldview-gitops/env/dev/api-gateway.env` (add Sentry block)
- `worldview-gitops/env/dev/alert.env` (add Sentry block)
- `worldview-gitops/values/portfolio.yaml` (add Sentry env vars — disabled default)
- `worldview-gitops/values/market-ingestion.yaml` (add Sentry env vars)
- `worldview-gitops/values/market-data.yaml` (add Sentry env vars)
- `worldview-gitops/values/content-ingestion.yaml` (add Sentry env vars)
- `worldview-gitops/values/content-store.yaml` (add Sentry env vars)
- `worldview-gitops/values/nlp-pipeline.yaml` (add Sentry env vars)
- `worldview-gitops/values/knowledge-graph.yaml` (add Sentry env vars)
- `worldview-gitops/values/rag-chat.yaml` (add Sentry env vars)
- `worldview-gitops/values/api-gateway.yaml` (add Sentry env vars)
- `worldview-gitops/values/alert.yaml` (add Sentry env vars)

Also in worldview repo:
- `docs/libs/observability.md` (new section "Sentry integration", ~20 lines)
- `docs/services/api-gateway.md` (1 paragraph under "Observability")
- `docs/STANDARDS.md` §Observability (NEW subsection — do NOT defer; applied inline per audit N-005)
- `RULES.md` (add single bullet about Sentry opt-in contract)

**PRD reference**: §3 FR-T3-1, §4 NFR table

**What to add to each `env/dev/<service>.env`**:
```bash
# Sentry — disabled by default for local dev.
# To debug a specific service locally: set SENTRY_ENABLED=true and provide SENTRY_DSN.
# In production: SENTRY_ENABLED=true + real DSN (set in values/<service>.yaml via SOPS).
# worldview-gitops is PRIVATE — DSN is safe to store here.
SENTRY_ENABLED=false
SENTRY_DSN=
SENTRY_ENVIRONMENT=development
SENTRY_TRACES_SAMPLE_RATE=0.0
SENTRY_RELEASE=
SENTRY_FINGERPRINT_RATE_LIMIT=10
```
The env var name is NOT service-prefixed (unlike `API_GATEWAY_*`) because `SentrySettings` reads the bare `SENTRY_*` names — this is intentional (shared naming across services; same DSN, same project).

**What to add to each `values/<service>.yaml`** (K8s Helm values):
```yaml
sentry:
  enabled: "false"          # override to "true" in prod values
  dsn: ""                   # fill via SOPS secret in prod
  environment: "production" # override per environment
  traces_sample_rate: "0.0"
  release: ""               # set to git SHA at deploy time
  fingerprint_rate_limit: "10"
```

**STANDARDS.md addition** (§Observability, new subsection — ~20 lines):
```
### Sentry — Opt-in Exception Capture

Every backend service calls `init_sentry(service_name=..., settings=SentrySettings())` once
at lifespan startup (after `configure_tracing`, before any I/O). Rules:

1. Default-off: `SENTRY_ENABLED=false` — unit tests and local dev never send real events.
2. PII guard: `before_send` hook strips auth headers, cookies, query strings, entity slugs in URLs,
   and hashes `user.email`. Never ship raw request bodies.
3. Fingerprint rate limit: `SENTRY_FINGERPRINT_RATE_LIMIT=10` events/fingerprint/hour prevents a
   single regression from exhausting the 5K free-tier monthly quota.
4. Returns bool: the call site logs the returned value (True = initialised, False = disabled/failed).
   Never silently discard.
5. Init failure is non-fatal: if `sentry_sdk.init` raises, `init_sentry` catches, logs
   `sentry_init_failed`, returns False. Sentry down must never take down a worldview service.
6. Traces sample rate = 0: tracing is handled by Tempo/OTel; avoid double-billing.
```

**Acceptance criteria**:
- [ ] All 10 `env/dev/<service>.env` files have the `SENTRY_*` block.
- [ ] All 10 `values/<service>.yaml` files have the `sentry:` section.
- [ ] `setup-dev.sh` requires no change (it copies all env files verbatim; the new vars are just new lines in existing files).
- [ ] STANDARDS.md §Observability section committed.
- [ ] `RULES.md` bullet added.
- [ ] `docs/libs/observability.md` Sentry section committed.

#### Pre-read

- `libs/observability/src/observability/error_capture.py` (existing)
- `libs/observability/src/observability/__init__.py` (re-export style)
- `services/api-gateway/src/api_gateway/app.py` (lifespan structure)
- `services/api-gateway/src/api_gateway/config.py` (pydantic-settings pattern)
- `docs/STANDARDS.md` (env-var conventions)
- `docs/BUG_PATTERNS.md` BP-179 (`Optional[SecretStr]` empty-string trap)
- BP-271 (per memory: trace_id injected into structlog) — preserve

#### Validation Gate

- [ ] `cd libs/observability && pytest -q` — all new + existing tests pass; minimum +14 new tests (11 sentry [8 PII + 3 rate-limit] + 3 error_capture).
- [ ] `ruff check libs/observability services/api-gateway services/nlp-pipeline services/rag-chat` clean.
- [ ] `mypy libs/observability services/api-gateway services/nlp-pipeline services/rag-chat` clean.
- [ ] `cd services/api-gateway && pytest -q` — all existing tests still pass + 1 new.
- [ ] `cd services/nlp-pipeline && pytest -q` — all existing tests still pass + 1 new.
- [ ] `cd services/rag-chat && pytest -q` — all existing tests still pass + 1 new.
- [ ] **Per audit N-003**: smoke-run `pytest -q` on **each of the 8 services that calls `register_error_handlers`** (api-gateway, nlp-pipeline, rag-chat, knowledge-graph, alert, content-ingestion, content-store, market-data — confirm exact list with `grep -rl register_error_handlers services/`) and confirm zero new failures from the T-C-02 lib extension. Estimated +20 min.
- [ ] No architecture violations (`tests/architecture/...` still pass).
- [ ] Docs updated.

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|---------------|--------------|
| `libs/observability/pyproject.toml` lock | new dep `sentry-sdk` | run `uv lock` or `pip-compile`; commit lockfile change |
| `services/api-gateway/tests/unit/test_app.py` (suspected) | new lifespan call to `init_sentry` may be visible in test that introspects lifespan | update test to mock `init_sentry` if asserting on lifespan side-effects |
| `services/nlp-pipeline/tests/...` lifespan test (if any) | same shape | mock `init_sentry` |
| `services/rag-chat/tests/...` lifespan test (if any) | same shape | mock `init_sentry` |
| `dev.local.env.example` reference in any test | none expected, but verify | update if needed |
| **All remaining 7 services** (knowledge-graph, alert, content-ingestion, content-store, market-data, market-ingestion, portfolio): the T-C-02 lib extension to `register_error_handlers` lands in their imports automatically. Their lifespan tests (if any) need a `mock_init_sentry` fixture added. `init_sentry` is explicitly wired in all 7 via T-C-05-EXT. | The Sentry-capture branch in `unhandled_exception_handler` is no-op when `SENTRY_ENABLED=false` (default) — existing tests pass unchanged. Only tests that introspect the lifespan call list need updating. | Add `mock_init_sentry` fixture to any lifespan test that asserts on startup calls. |

#### Regression Guardrails

- **BP-179** (`Optional[SecretStr]` empty-string trap): pydantic-settings parses empty `SENTRY_DSN=` as `SecretStr("")` not `None`. Guard via `if settings.enabled and (not settings.dsn or not settings.dsn.get_secret_value())` — explicit `not` truthiness check.
- **BP-313** (mark_processed before commit): irrelevant here (no Kafka consumer added).
- **R10** (structlog only): preserved — Sentry runs in addition to, not instead of, structlog.
- **`feedback_audit_returned_value_persistence`** (returned diagnostic values must be persisted): `init_sentry` returns `bool`; the call site logs it. Do not silently discard.
- **BP-148** (Avro schema invalid default): N/A.
- Sentry quota / cost: PRD §10 — free tier 5K events/month sufficient for MVP. `before_send` PII guard enforces minimum payload — confirm the guard drops cookies and JWT headers.

---

### Wave D — Frontend Sentry (Next.js) — Parallel-Safe with Wave B/C

**Goal**: Install `@sentry/nextjs` in `apps/worldview-web`, wire it via `instrumentation.ts`, scope it via `sentry.client.config.ts` + `sentry.server.config.ts`, and wrap the React tree in `Sentry.ErrorBoundary` so user-facing exceptions are captured with stack traces. Default-disabled in dev.

**Depends on**: Wave A (T-A-02 — confirms current frontend has no existing Sentry).
**Estimated effort**: 60–90 min.
**Architecture layer**: frontend / instrumentation.

#### Tasks

##### T-D-01: Install `@sentry/nextjs` (exact-pinned) and configure for Next.js 15.5.15

**Type**: config + impl
**depends_on**: none (within Wave D)
**blocks**: T-D-02, T-D-03
**Target files**:
- `apps/worldview-web/package.json` (add dep — exact, no caret)
- `apps/worldview-web/pnpm-lock.yaml` (lockfile bump)
- `apps/worldview-web/instrumentation.ts` (new)
- `apps/worldview-web/sentry.client.config.ts` (new)
- `apps/worldview-web/sentry.server.config.ts` (new)
- `apps/worldview-web/sentry.edge.config.ts` (new — minimal; edge runtime not heavily used but Next 15 expects it)
- `apps/worldview-web/next.config.ts` (wrap with `withSentryConfig`)

**PRD reference**: §3 FR-T3-1 ("Sentry integration on … worldview-web")

**What to build**:

Per memory rule `feedback_frontend_pnpm` — pnpm only, exact versions, no caret. Pick `@sentry/nextjs@8.45.0` or whatever the latest stable v8 is at install time. Pin exactly. Run `pnpm audit` after install — must be 0 CVEs.

**Configs**:
- `sentry.client.config.ts`: `Sentry.init({ dsn: process.env.NEXT_PUBLIC_SENTRY_DSN, environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ?? 'development', tracesSampleRate: 0, replaysSessionSampleRate: 0, replaysOnErrorSampleRate: 0, beforeSend: stripPiiClient })`. **No replay** for MVP — privacy-conservative; can enable post-launch.
- `sentry.server.config.ts`: same DSN + `tracesSampleRate: 0`, `beforeSend: stripPiiServer`. PII guard mirrors backend: drop `cookies`, `authorization` header, `x-internal-jwt` header, hash any `user.email`.
- `instrumentation.ts`: per Next 15 convention, exports `register()` that imports the right config based on `process.env.NEXT_RUNTIME`.
- `next.config.ts` integration (per audit I-006 — verified against current 185-LOC file at `apps/worldview-web/next.config.ts`):
  - Existing invariants that MUST be preserved:
    1. Top-of-file `throw new Error(...)` for `ws://` in production server (lines 27–34) — security hardening from PLAN-0059 W0 F-016. Top-level executes top-to-bottom, so this `throw` runs **before** the `withSentryConfig` wrap regardless of conditional.
    2. `rewrites()` (lines 108–117) — `/api/:path*` → `${apiGatewayUrl}/:path*`. The Sentry tunnel route (if used) must NOT collide with `/api/`. Recommend leaving Sentry direct-DSN (no tunnel) for MVP.
    3. `headers()` (lines 126–146) — security headers including `X-Frame-Options`, CSP via middleware. Sentry's webpack plugin injects no headers.
    4. `experimental.reactCompiler` + `optimizePackageImports` — confirm `withSentryConfig` does not override `experimental` (it merges; verify with `pnpm build`).
    5. `productionBrowserSourceMaps: false` — currently false (PLAN-0059 W0 F-014). Must flip to `true` only when `SENTRY_AUTH_TOKEN` is set so the Sentry build plugin can upload them; pair with `withSentryConfig({ hideSourceMaps: true, sourcemaps: { deleteSourcemapsAfterUpload: true } })` so `.map` files do NOT remain reachable at `/_next/static/chunks/*.js.map` after upload.
  - Final shape (replace the bottom `export default nextConfig;` line):
    ```typescript
    // Sentry wrap — applied ONLY when SENTRY_AUTH_TOKEN is set (build-time
    // sourcemap upload). When unset, we fall back to the plain config so
    // local `pnpm dev` and CI builds without Sentry credentials still work.
    // The existing `throw` for `ws://` at lines 27–34 runs FIRST (top-level
    // module evaluation order) — this is intentional: a misconfigured WS
    // protocol must take down the build before Sentry's plugin sees it,
    // otherwise the user gets a confusing Sentry error instead of the
    // intended security failure.
    import { withSentryConfig } from "@sentry/nextjs";

    const sentryEnabled = Boolean(process.env.SENTRY_AUTH_TOKEN);

    // Override productionBrowserSourceMaps when Sentry is on so the build
    // emits `.map` files for upload; pair with `hideSourceMaps: true` so
    // they are NOT served at /_next/static/chunks/*.js.map publicly.
    const finalConfig: NextConfig = sentryEnabled
      ? { ...nextConfig, productionBrowserSourceMaps: true }
      : nextConfig;

    export default sentryEnabled
      ? withSentryConfig(finalConfig, {
          silent: true,
          org: process.env.SENTRY_ORG,
          project: process.env.SENTRY_PROJECT,
          hideSourceMaps: true,
          sourcemaps: { deleteSourcemapsAfterUpload: true },
        })
      : nextConfig;
    ```

**Logic & Behavior**:
- **Default-disabled**: if `NEXT_PUBLIC_SENTRY_DSN` is empty / undefined, `Sentry.init` is a no-op (the SDK supports `dsn: ""` → disabled mode).
- **No replay session capture** — MVP privacy default.
- **PII guard** is mandatory: do not send body; strip auth headers; hash emails.

**Tests to write** (Vitest):
| Test Name | What It Verifies | Type |
|-----------|------------------|------|
| `test_strip_pii_client_drops_authorization_header` | event with header → dropped | unit (vitest) |
| `test_strip_pii_client_hashes_user_email` | event with email → sha256 | unit |
| `test_strip_pii_server_drops_x_internal_jwt` | event with x-internal-jwt → dropped | unit |
- Minimum test count: 3
- Place tests in `apps/worldview-web/__tests__/sentry-pii.test.ts` (new).

**Downstream test impact**:
- `apps/worldview-web/next.config.ts` — wrapping with `withSentryConfig` may change module shape; verify `pnpm test` / `pnpm build` both succeed.
- ESLint may flag the new `instrumentation.ts` if `app/` is the canonical location — confirm Next.js 15 expects it at the project root, not under `app/`.

**Acceptance criteria**:
- [ ] `pnpm audit` reports 0 CVEs.
- [ ] **Build matrix per audit I-006** — run `pnpm -C apps/worldview-web build` in three configurations and confirm expected behaviour in each:
  - **(a)** `NEXT_PUBLIC_SENTRY_DSN=""`, `SENTRY_AUTH_TOKEN` unset, `NEXT_PUBLIC_WS_BASE_URL=wss://...`, `NODE_ENV=production`, `NEXT_PHASE=phase-production-build` → build succeeds, no Sentry plugin runs, `productionBrowserSourceMaps` stays false.
  - **(b)** `NEXT_PUBLIC_SENTRY_DSN=https://...`, `SENTRY_AUTH_TOKEN=fake-stub`, `SENTRY_ORG=worldview`, `SENTRY_PROJECT=worldview-web`, `NEXT_PUBLIC_WS_BASE_URL=wss://...` → build succeeds, Sentry plugin attempts sourcemap upload (will fail auth with the stub but the build itself completes — confirm `hideSourceMaps: true` removes `.map` files from `out/` after the failed-but-non-fatal upload).
  - **(c)** `NEXT_PUBLIC_WS_BASE_URL=ws://localhost:8010` (plaintext), `NODE_ENV=production`, `NEXT_PHASE=phase-production-server` → start (not build) MUST throw the WS hardening error verbatim. The Sentry wrap must NOT replace this error with a Sentry-side error message.
- [ ] All 3 PII-guard tests pass.

---

##### T-D-02: Wrap React root with `Sentry.ErrorBoundary` and add Sentry test trigger (dev-only)

**Type**: impl
**depends_on**: T-D-01
**blocks**: T-D-03
**Target files**:
- `apps/worldview-web/app/providers.tsx` (extend — wrap the existing tree)
- `apps/worldview-web/app/(app)/dev-tools/sentry-test/page.tsx` (new — dev-only route; **path corrected per audit I-005**: previous draft used `_dev` which is a Next.js private-folder convention (underscore prefix) and is intentionally non-routable. With `_dev` the synthetic-error probe in T-E-04 could not fire because the URL would 404 even in development. `dev-tools` is a regular folder; the dev-only gate is enforced at the page component level via `if (process.env.NODE_ENV === "production") notFound()` — server-component check at request time, not build time, ensures the route 404s in production while remaining reachable in dev/staging where Sentry is wired)

**PRD reference**: §3 FR-T3-1 acceptance criterion ("a synthetic exception in worldview-web is captured in Sentry within 60s")

**What to build**:

In `providers.tsx`: wrap the **outermost** child of the existing provider stack in `<Sentry.ErrorBoundary fallback={<GlobalErrorFallback />} showDialog={false}>`. Per memory `feedback_frontend_comments` — every line annotated with **why**, since user is new to Next.js.

`GlobalErrorFallback`: simple component — "Something went wrong. The error has been reported." + a "Reload" button. Comment-heavy (≥30% comment density per memory).

Dev-only route `/(app)/dev-tools/sentry-test` (corrected from `_dev` per audit I-005): a button that throws `new Error("W9 Sentry smoke test " + new Date().toISOString())`. The page component is a Server Component that calls `notFound()` at request time when `NODE_ENV === "production"` — this is the canonical Next.js 15 way to make a route 404 in production while keeping it reachable in dev/staging. Note: `notFound()` must be called BEFORE any rendering side-effects; the underscore-prefix folder convention (`_dev`) would have made the route non-routable at the file-system level and is the wrong tool for this use case.

**Tests to write** (Vitest + jsdom):
| Test Name | What It Verifies | Type |
|-----------|------------------|------|
| `test_error_boundary_renders_fallback_on_throw` | child throws → fallback rendered | unit |
| `test_error_boundary_invokes_sentry_capture` | mock `Sentry.captureException`; child throws → called once | unit |
| `test_dev_route_404_in_production` | `NODE_ENV=production` → notFound | unit |
- Minimum test count: 3
- Place in `apps/worldview-web/__tests__/error-boundary.test.tsx`.

**Downstream test impact**:
- All existing component tests rendered through `providers.tsx` now mount under an extra `ErrorBoundary` — confirm Vitest snapshots don't break (run `pnpm test:update` only if a benign wrapper diff appears; **never** auto-update if assertion-bearing diffs).

**Acceptance criteria**:
- [ ] Wrapping does not break any of the 1,354+ existing frontend tests.
- [ ] Synthetic-error route works in dev; returns 404 in prod build.
- [ ] Comment density ≥30% on new TSX files (per `feedback_frontend_comments`).

---

##### T-D-03: Frontend env-var contract + docs

**Type**: docs + config
**depends_on**: T-D-02
**blocks**: T-E-01
**Target files**:
- `apps/worldview-web/.env.example` (or repo equivalent)
- `apps/worldview-web/README.md` (Sentry section, ~10 lines)
- `docs/apps/worldview-web.md` (1 paragraph under "Observability")
- `docs/ui/DESIGN_SYSTEM.md` (no-op unless `GlobalErrorFallback` should be a documented component — recommended add 2 lines)

**PRD reference**: §3 FR-T3-1, §4 NFR

**What to build**:
```
NEXT_PUBLIC_SENTRY_DSN=
NEXT_PUBLIC_SENTRY_ENVIRONMENT=development
SENTRY_AUTH_TOKEN=     # build-time only — for sourcemap upload
SENTRY_ORG=
SENTRY_PROJECT=
```

**Acceptance criteria**:
- [ ] `.env.example` lists all 5 keys with comments.
- [ ] README and service docs cross-reference PRD-0034 §3 FR-T3-1.

#### Pre-read

- `apps/worldview-web/app/providers.tsx` (current provider stack — PLAN-0059 C-3 wired `useApiClient`)
- `apps/worldview-web/next.config.ts`
- `apps/worldview-web/package.json` (pinning style — exact, no caret)
- `docs/ui/frontend-migration.md`
- `feedback_frontend_pnpm.md`, `feedback_frontend_comments.md` (from MEMORY.md)

#### Validation Gate

- [ ] `pnpm -C apps/worldview-web test` — all tests pass (baseline 1,354+, +6 new).
- [ ] `pnpm -C apps/worldview-web typecheck` clean.
- [ ] `pnpm -C apps/worldview-web lint` clean.
- [ ] `pnpm -C apps/worldview-web build` clean (with empty DSN — production build must succeed even when Sentry is disabled).
- [ ] `pnpm -C apps/worldview-web audit` 0 CVEs.

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|---------------|--------------|
| `apps/worldview-web/next.config.ts` | wrapped with `withSentryConfig` | preserve existing config — wrap, don't replace |
| `apps/worldview-web/__tests__/*.test.tsx` rendering through providers | new `ErrorBoundary` ancestor | only update if a snapshot diff is benign and review-approved |
| `pnpm-lock.yaml` | new transitive deps | commit |

#### Regression Guardrails

- **`feedback_frontend_pnpm`**: exact pin only (no `^`). pnpm audit must be 0 CVEs.
- **`feedback_frontend_comments`**: heavy inline comments on all new TSX/TS files (user is new to Next.js).
- Sentry replay disabled (privacy) — confirm no `replaysSessionSampleRate > 0`.
- Sourcemap upload only when `SENTRY_AUTH_TOKEN` set — local builds must not fail.
- Default-off contract: `NEXT_PUBLIC_SENTRY_DSN=""` → Sentry no-op. Verify in build output.

---

### Wave E — UptimeRobot + Public Status Page + Final FR-T3-1 Verification

**Goal**: Stand up an external uptime probe and a public status page, then run the FR-T3-1 acceptance test (synthetic exception captured in Sentry within 60s; status page shows live uptime).

**Depends on**: Wave C (T-C-05, T-C-05-EXT, T-C-06), Wave D (T-D-03), Wave B (T-B-03, T-B-04).
**Estimated effort**: 240 min (rev-2: +60 for T-E-03 Grafana dashboard, +60 for T-E-04 Sentry alert setup + runbook, +30 for T-E-05 PRD amendment, +30 for verification of all 10 service probes).
**Architecture layer**: ops + minimal frontend.

#### Tasks

##### T-E-01: Configure UptimeRobot monitor (manual, doc-tracked)

**Type**: config (manual external action, recorded in repo)
**depends_on**: T-C-04 (S9 deployed with health route confirmed)
**blocks**: T-E-04
**Target files**:
- `docs/runbooks/uptime-monitoring.md` (new, ~50 LOC)

**PRD reference**: §3 FR-T3-1, §4 NFR ("≥99% uptime measured by UptimeRobot for 30 days post-launch")

**What to build** (revised 2026-05-03 per Sam-alignment audit — TWO monitors, not one):
- Create UptimeRobot account (free tier — 50 monitors, 5-min interval).
- **Monitor 1 — `/healthz` liveness (process-up):**
  - **URL**: `https://<prod-domain>/healthz` — corrected per audit B-002. The previous draft's `/v1/health` does NOT exist on api-gateway. Verified at `services/api-gateway/src/api_gateway/routes/health.py:12` (`@router.get("/healthz")` returns `{"status": "ok"}`) and `app.py:216` mounts the health router with **no prefix**.
  - Interval: 5 min (free-tier minimum).
  - Keyword: `"status":"ok"` — confirmed present in `/healthz` response body.
  - Alert contacts: founder email; alert threshold 1 failure (page immediately when process down).
  - Surfaces as the canonical "is the gateway up" signal on the status page.
- **Monitor 2 — `/readyz` readiness (dependency health) — added 2026-05-03 per Sam-alignment audit:**
  - **URL**: `https://<prod-domain>/readyz` — already exists per `services/api-gateway/src/api_gateway/routes/health.py:18`, returns 200 when Valkey is reachable, 503 with `{"status": "degraded", ...}` otherwise.
  - Interval: 15 min (lower frequency to dampen alarm-fatigue without losing the signal).
  - Alert threshold: 3 consecutive failures (≈45 min of sustained dependency failure before paging — captures genuine degradation, ignores transient blips).
  - **Why two monitors**: `/healthz` flags Sam-relevant outages immediately (gateway dead → no UI); `/readyz` flags the slower-burning class (Valkey down → caching broken → briefs stale or 503-ing) without the false-positive cost. The original "process-up only" decision is correct for the page-Sam-immediately signal but leaves dependency degradation invisible. Two monitors at zero marginal cost (free tier supports 50) gets both signals.
  - Surfaces as a separate per-component pill on the status page (T-E-02 revised below).
- **Generate a monitor-scoped read-only API key** (NOT the main account key) for the status page proxy in T-E-02. Capture as `UPTIMEROBOT_READONLY_API_KEY`. Per audit B-003, this is server-only — never set as `NEXT_PUBLIC_*`.
- Record monitor ID and public-status URL in env: `UPTIMEROBOT_MONITOR_ID`, `STATUS_PAGE_URL`.
- Document the steps in `docs/runbooks/uptime-monitoring.md` so this is reproducible. The runbook MUST include:
  - The decision rationale `/healthz` vs `/readyz`.
  - That the API key is **monitor-scoped read-only** (not main account).
  - The rotation procedure (regenerate in UptimeRobot dashboard → update `UPTIMEROBOT_READONLY_API_KEY` in `infra/gitops/values/<env>.yaml` via SOPS → roll the worldview-web deployment).
  - That the key is **never** set as `NEXT_PUBLIC_*` (would expose it client-side).

**Inline contract test** (per audit recommendation in original Wave E §guardrails — keep as part of T-E-01 since it directly protects this monitor): add `services/api-gateway/tests/contract/test_health_keyword_stability.py` asserting that `GET /healthz` returns 200 AND the body contains the literal substring `"status":"ok"`. This is a **monitoring contract**, not a functional API contract: if a future PR changes the response shape (e.g. wraps it in `{"data": {"status": "ok"}}`), UptimeRobot's keyword check would silently fail. The test catches this at PR time. Ship in same commit as T-E-01 setup.

**Acceptance criteria**:
- [ ] Monitor active and reports `up` for 30 consecutive min before close.
- [ ] Test alert: temporarily change keyword to `"status":"impossible"` → alert fires within 10 min → revert.
- [ ] Runbook committed; mentions `/healthz` decision, key scoping, rotation.
- [ ] `test_health_keyword_stability.py` ships and passes; counts in api-gateway test suite (+1).

---

##### T-E-02: Public status page — in-tree Next.js page with server-only proxy (Option A locked per audit I-004)

**Type**: impl
**depends_on**: T-E-01 (UptimeRobot monitor + read-only API key generated)
**blocks**: T-E-04
**Target files**:
- `apps/worldview-web/app/(public)/status/page.tsx` (new, ~120 LOC) — public Server Component, NO direct UptimeRobot fetch.
- `apps/worldview-web/app/(public)/status/api/uptime/route.ts` (new, ~80 LOC) — Next.js Route Handler (Node runtime); the **only** place that holds `UPTIMEROBOT_READONLY_API_KEY` and calls UptimeRobot.
- `apps/worldview-web/__tests__/status-page.test.tsx` (new, 4 tests; Vitest)
- `apps/worldview-web/__tests__/status-uptime-route.test.ts` (new, 3 tests targeting the Route Handler)
- `docs/runbooks/uptime-monitoring.md` (extend with the proxy architecture)

**PRD reference**: §3 FR-T3-1 ("status.<domain> via the free Statuspage tier (or simple custom page)") — clarification per audit I-004 below.

**Audit-driven design decisions** (locked):

- **Option A (custom in-tree page) is locked, not a per-execution choice** — per audit I-004:
  - Atlassian Statuspage free tier was **discontinued**.
  - Current third-party alternatives (Better Uptime, Instatus) are paid beyond a tiny tier and add a vendor dependency.
  - The in-tree page is ~200 LOC total (page + route handler) and keeps the surface in our own codebase.
  - PRD §3 FR-T3-1 wording is updated by Wave E T-E-05 (single-line PRD amendment) to reflect this.

- **Server-only API key proxy (per audit B-003)** — the previous draft suggested the page could fetch UptimeRobot directly. This is **rejected** even when the key is "read-only" because:
  - Even a monitor-scoped read-only key, if exposed in client-side network logs, lets attackers (a) exhaust the rate-limit window, (b) enumerate alert-contact PII, and (c) potentially extract internal probe paths or staging hostnames from monitor configuration.
  - PRD §9 security row explicitly says "Status page shows uptime only, not error details or stack traces" — leaking the API key would directly violate this intent.
  - **Architectural rule**: `UPTIMEROBOT_READONLY_API_KEY` is read **only** in `app/(public)/status/api/uptime/route.ts` (Node runtime). It is **never** set as `NEXT_PUBLIC_*`. The page (`app/(public)/status/page.tsx`) fetches `/api/uptime` from same-origin.

**For `app/(public)/status/api/uptime/route.ts`** — Next.js Route Handler:
- Reads `process.env.UPTIMEROBOT_READONLY_API_KEY` (Node runtime — confirmed not edge); throws `500` if missing in production.
- Calls `https://api.uptimerobot.com/v2/getMonitors` with `api_key=<key>` and `custom_uptime_ratios=30`.
- **Whitelisted response projection** — return ONLY (per monitor):
  - `monitor_id` (numeric id; safe to expose for cross-reference)
  - `friendly_name` (e.g. "API Gateway — liveness", "API Gateway — readiness")
  - `component_label` (derived field added 2026-05-03 — see "Per-component pills" below; lets the page render meaningful Sam-facing labels like "Search", "AI Briefs" instead of raw `friendly_name`)
  - `status` (numeric 2 = up, 9 = down, 8 = seems down, 0 = paused)
  - `custom_uptime_ratio` (string like `"99.97"`)
  - `daily_buckets` — per-day up/down array for the last 30 days (derive from `logs` field, strip every other field)
  - **Strip**: `url`, `alert_contacts`, `interval`, `keyword_value`, `keyword_type`, `last_error`, every other field. This is defense-in-depth (also enforced at render in the page, but the API boundary is the canonical strip point).
- Cache the response 60 seconds via `revalidate = 60` and an in-process LRU keyed on `null` so we do not hammer UptimeRobot's free-tier API quota.
- **Reads `app/(public)/status/incidents.json`** (added 2026-05-03 per Sam-alignment audit): a small in-tree file (committed, edited by hand during incidents) of shape `[{title: string, severity: "info"|"warn"|"critical", started_at: ISO, resolved_at: ISO | null}]`. The route returns `{monitors: [...], incidents: [...]}` so the page can render an incident banner above the monitor pills. Empty array = no banner. **Why in-tree**: the audit's "trust contract" finding — "Operational" with no incident comms is worse than no status page during a real outage. A 15-line file commit is the cheapest way to publish "AI brief generation degraded — investigating" to Sam without standing up a CMS.

**For `app/(public)/status/page.tsx`** — Server Component:
- Fetches `/api/uptime` from same-origin (no API key in scope).
- **Per-component pills (revised 2026-05-03 per Sam-alignment audit)**: surface monitors as Sam-facing components, not as raw monitor names. The audit's HIGH finding was that "API Gateway: up" leaks an internal architecture term and means nothing to a paying analyst — they see "all green" while AI briefs are silently broken. Mapping (declared in `app/(public)/status/components.ts`):
  - `monitor_id == UPTIMEROBOT_MONITOR_ID_HEALTHZ` → component_label `"Platform"` (process liveness, page-immediately).
  - `monitor_id == UPTIMEROBOT_MONITOR_ID_READYZ` → component_label `"Caching & rate limits"` (Valkey readiness, dependency degradation).
  - Future: as we add monitors for S6 search and S8 brief generation, label them `"Search"`, `"AI Briefs"`. Today, surface those as `"Coming soon"` pills with a muted style so the page reflects current observability honestly. Once W6 and W4 are live, add their monitors and the pills auto-light.
- Renders: an incident banner at top (when `incidents` non-empty); below, a per-component grid of: component label + current status pill (green=up, amber=degraded if status=8 or readyz=503, red=down, grey=coming-soon/paused) + 30-day uptime % + a 30-day strip of daily checkmarks.
- Comment density ≥30% per `feedback_frontend_comments`.
- Defense-in-depth: even if the route handler accidentally returns a stripped field, the page renders ONLY the whitelisted projection — never spreads the response object into JSX.

**Tests to write** (Vitest):

For `__tests__/status-page.test.tsx`:
| Test Name | What It Verifies | Type |
|-----------|------------------|------|
| `test_status_page_renders_up_state` | mock `/api/uptime` → 1 monitor status=2 → green pill | unit |
| `test_status_page_renders_down_state` | mock fetch → status=9 → red pill | unit |
| `test_status_page_renders_30_day_strip` | mock 30 daily buckets → 30 cells rendered | unit |
| `test_status_page_does_not_call_uptimerobot_directly` | spy on `global.fetch`; assert no call to `api.uptimerobot.com` from the page | unit |

For `__tests__/status-uptime-route.test.ts` (Route Handler — guards the security boundary):
| Test Name | What It Verifies | Type |
|-----------|------------------|------|
| `test_uptime_route_strips_url_field` | UptimeRobot mock returns a monitor with `url: "https://internal-staging.example/healthz"`; route response MUST NOT contain that string | unit (defense in depth — matches audit B-003 step 3) |
| `test_uptime_route_strips_alert_contacts` | mock includes `alert_contacts: [{email: "x@y.z"}]`; route response MUST NOT contain it | unit |
| `test_uptime_route_500_when_api_key_missing` | env without `UPTIMEROBOT_READONLY_API_KEY` → 500 in production | unit |
| `test_uptime_route_returns_incidents_when_file_present` | (Sam-fit) `incidents.json` with one open incident → response includes `incidents: [{title, severity, started_at, resolved_at: null}]` | unit |
| `test_uptime_route_returns_empty_incidents_when_file_missing` | (Sam-fit) no file → `incidents: []`, no 500 | unit |
| `test_status_page_renders_incident_banner_when_present` | (Sam-fit) page render with `incidents: [{severity: "warn", title: "AI briefs degraded"}]` → amber banner above monitor pills with the title | unit (in status-page.test.tsx) |
| `test_status_page_renders_per_component_labels` | (Sam-fit) monitor with `friendly_name: "API Gateway — readiness"` mapped to component_label `"Caching & rate limits"` → page shows `"Caching & rate limits"`, NOT raw monitor name | unit (in status-page.test.tsx) |

- Minimum test count: 11 (was 7 — added 4 for incident banner + per-component label rendering per Sam-alignment audit).

**Downstream test impact**: none.

**Acceptance criteria**:
- [ ] Route accessible at `/status`; cached 60s server-side.
- [ ] UptimeRobot API call lives ONLY in the Route Handler.
- [ ] No `NEXT_PUBLIC_UPTIMEROBOT*` env var anywhere in the codebase (`grep -r 'NEXT_PUBLIC_UPTIMEROBOT' apps/worldview-web/` returns 0 results).
- [ ] Whitelisted-projection unit tests pass (URL + alert-contacts stripped).
- [ ] Page satisfies PRD §3 acceptance ("status page shows live uptime for last 30 days").

---

##### T-E-03: Grafana error-observability dashboard — rev-2 NEW

**Type**: impl
**depends_on**: T-C-06 (Sentry init logged to structlog in all services)
**blocks**: T-E-06
**Target files**:
- `infra/grafana/dashboards/error-observability.json` (new, ~250 LOC Grafana JSON)
- `docs/runbooks/error-observability.md` (new, ~40 LOC)

**PRD reference**: §3 FR-T3-1 ("full observability"), §4 NFR table

**What to build**: A new Grafana dashboard (follows the style of existing dashboards in `infra/grafana/dashboards/` — read any existing file, e.g. `api-gateway.json`, for the JSON envelope shape, UID conventions, and data-source reference) that visualises error and Sentry health from **Loki logs** (the structlog events that `init_sentry`, `register_error_handlers`, and the `before_send` rate-limiter emit). No new Prometheus metrics required — all signals are already in Loki.

**Dashboard UID**: `worldview-error-observability`. Title: `"Error Observability"`. Folder: same as other dashboards.

**Panels** (4 required, in order):

1. **Unhandled exception rate per service** (Logs panel or Time series)
   - Loki query: `{job=~".+"} |= "unhandled_exception" | json | event = "unhandled_exception" | unwrap __error__ | rate[5m]`  or simpler: count_over_time on `event="unhandled_exception"` grouped by `service` label.
   - Read the log format from `libs/observability/src/observability/error_capture.py` to confirm the exact structlog field name.
   - Goal: show which services have elevated unhandled exception rates. Baseline should be near-zero in healthy operation.

2. **Sentry events rate-limited / dropped** (Stat + Time series)
   - Loki query: `{job=~".+"} |= "sentry_event_dropped" | json | event = "sentry_event_dropped"`
   - Each drop event includes the fingerprint (from the rate-limiter structlog call in `_before_send`). Stat panel shows total drops in the last 24h. Time series shows when rate-limiting kicked in.
   - Goal: catch cases where a single regression is generating so many Sentry events it would exhaust the free-tier quota.

3. **Sentry initialisation status** (Stat panel — health check)
   - Loki query: count of `event="sentry_initialised"` vs `event="sentry_init_failed"` vs `event="sentry_disabled"` per service in the last 1h.
   - Goal: confirm all 10 services that should have Sentry enabled (in prod) actually initialised it. If a service shows `sentry_disabled` in prod, someone forgot to set the env var.

4. **Top exception types (last 24h)** (Table panel)
   - Loki query: extract `exc_type` from structlog `unhandled_exception` events (if the field is logged — verify in `error_capture.py`). Group by `exc_type` + `service`. Top 10 rows.
   - Goal: give the on-call a quick "what is failing and where" view without opening Sentry.

**Implementation notes**:
- Follow the exact JSON structure of an existing dashboard (copy `api-gateway.json` envelope, replace panels). The Grafana provisioning config in `infra/` already picks up all JSON files in `infra/grafana/dashboards/` — no extra config needed (verify by checking how existing dashboards are provisioned).
- Dashboard variable: `$service` multi-select (values: all 10 service names) to filter panels. Add a "Refresh" interval of 1m.
- The Loki data-source UID: check an existing dashboard to get the correct `uid` string (e.g. `loki` or a UUID — do NOT hardcode a guess).

**Runbook** (`docs/runbooks/error-observability.md`):
- How to open the dashboard in Grafana.
- How to interpret each panel.
- What to do when panel 2 (rate-limited) goes above 0 ("one of your services has a repeating exception; check Sentry for the fingerprint, then find and fix the regression").
- How to drill from this dashboard into Sentry (link to Sentry project URL).

**Acceptance criteria**:
- [ ] `infra/grafana/dashboards/error-observability.json` committed and parseable by Grafana (validate by importing into a running Grafana instance or with `grafana-cli` lint if available).
- [ ] All 4 panels present with correct Loki queries.
- [ ] Dashboard variable `$service` works — selecting a service filters all panels.
- [ ] Runbook committed.
- [ ] No hardcoded data-source UIDs that don't match the actual Loki UID in the stack.

---

##### T-E-04: Configure Sentry issue-alert email notification to arnaurodondev@gmail.com — rev-2 NEW

**Type**: config (manual external action, documented in runbook)
**depends_on**: T-C-01 (Sentry project created and DSN captured), T-E-01 (Sentry account confirmed working)
**blocks**: T-E-06
**Target files**:
- `docs/runbooks/sentry-alerts.md` (new, ~50 LOC)

**PRD reference**: §3 FR-T3-1 ("full observability"), §4 NFR ("alerting on critical errors")

**Why this task exists (rev-2)**: The original plan only configured the Sentry 80%-quota usage alert as a safety net. It had NO alert for new errors or regressions — meaning a brand-new exception class could fire silently for hours before anyone checked the Sentry dashboard. Rev-2 closes this gap.

**What to build** — configure the following in the Sentry SaaS UI (free-tier project settings → Alerts):

**Alert Rule 1 — New Issue Created**:
- Name: `"New issue — email arnaurodondev"`
- Trigger: "A new issue is created" (fires once per new fingerprint, not on every occurrence)
- Action: Send email to `arnaurodondev@gmail.com`
- All environments: yes (including prod and staging if Sentry is wired there)
- Frequency: maximum 1 email per issue (Sentry deduplicates by fingerprint — this does not spam)
- **Why**: first time a new exception class appears, you want to know immediately. The `before_send` rate-limiter means Sentry only sees ≤10 events/fingerprint/hour anyway — the deduplicated alert will not spam.

**Alert Rule 2 — Issue Regression**:
- Name: `"Regression — email arnaurodondev"`
- Trigger: "An issue that has been resolved is seen again" (regression)
- Action: Send email to `arnaurodondev@gmail.com`
- **Why**: a previously-fixed bug reappearing is high-signal.

**Alert Rule 3 — High Volume (spike)**:
- Name: `"Error spike — email arnaurodondev"`
- Trigger: "An issue occurs more than 50 times in 1 hour"
- Action: Send email to `arnaurodondev@gmail.com`
- **Why**: complements the new-issue alert for cases where a known error suddenly spikes (e.g. a config change makes an existing error much more frequent).

**Alert Rule 4 — Monthly quota 80%** (already in plan; confirm it is set):
- Name: `"Sentry quota 80%"`
- Trigger: Monthly event usage > 80%
- Action: Email `arnaurodondev@gmail.com`
- Located in: Organisation settings → Subscription → Usage alerts (not in the project alert rules)

**Email used**: `arnaurodondev@gmail.com` — current personal dev address. The runbook notes this should be updated to a company support/ops email when one is created (future: e.g. `ops@meshx.io`).

**WhatsApp / additional channels**: not configured for MVP (Sentry free tier supports email and limited Slack; Slack channel not yet set up for worldview ops). Document as a follow-up in the runbook.

**Document in `docs/runbooks/sentry-alerts.md`**:
- The 4 alert rules above with exact UI paths (Sentry → Project → Alerts → Issue Alerts → New Alert Rule).
- The email address in use + update procedure (change the recipient in Sentry UI; no code change needed).
- When to expect each alert type and what action to take (runbook escalation ladder).
- Note: Sentry free tier supports 1 email recipient per rule on the free plan — confirm this limit before adding more recipients.

**Acceptance criteria**:
- [ ] All 4 alert rules configured in Sentry SaaS UI and confirmed active (each rule shows "Active" status in the Alerts list).
- [ ] Test Rule 1: trigger a synthetic exception via the dev-tools Sentry test route (T-D-02); confirm a "New Issue" email arrives at `arnaurodondev@gmail.com` within 5 min. Screenshot.
- [ ] Runbook committed with exact UI paths.
- [ ] Runbook notes the email-update procedure for when a company ops email is ready.
- [ ] No hard-coded email addresses in the codebase (alert destination is configured only in Sentry UI, not in code or env vars).

---

##### T-E-05: PRD-0034 §3 FR-T3-1 single-line amendment per audit I-004 (NEW)

**Type**: docs
**depends_on**: T-E-02
**blocks**: T-E-04 (close-out report references the amended PRD)
**Target files**:
- `docs/specs/0034-mvp-launch-readiness-program.md` §3 FR-T3-1 (single-line edit)

**PRD reference**: PRD-0034 §3 FR-T3-1.

**What to build**: A targeted single-line amendment to PRD-0034 §3 FR-T3-1. Current wording references "free Statuspage tier" which is no longer available (Atlassian discontinued). Update the bullet to:

> Original: "status.<domain> via the free Statuspage tier (or simple custom page)"
>
> Amended: "status.<domain> rendered as an in-tree Next.js page with a server-only Route Handler proxying UptimeRobot (Atlassian Statuspage free tier was discontinued; paid third-party alternatives like Better Uptime / Instatus are deferred unless the in-tree page proves insufficient)"

This is a clarification (not a scope change), so it qualifies for a single-line edit in Wave E rather than a full `/revise-prd` cycle.

**Acceptance criteria**:
- [ ] PRD-0034 §3 FR-T3-1 line edited; reference to Atlassian Statuspage removed.
- [ ] Cross-reference comment in the PRD section pointing to this audit + plan T-E-02 (so a future reader knows the choice is locked).
- [ ] Pre-commit docs hook passes.

---

##### T-E-07: Add `/status` link to footer + ensure status URL is discoverable

**Type**: impl
**depends_on**: T-E-02
**blocks**: T-E-06
**Target files**:
- `apps/worldview-web/components/shell/Footer.tsx` (or equivalent — find existing footer location first)
- 1 footer test if one exists; else skip

**PRD reference**: §3 FR-T3-1

**What to build**: Add a footer link "Status" → `/status` (Option A) or external URL (Option B). Per PRD §3 the page is meant to be public — must be discoverable.

**Acceptance criteria**:
- [ ] Footer has a "Status" link visible in the deployed frontend.
- [ ] Link works when not authenticated (status page is public, no auth required).

---

##### T-E-06: Final FR-T2-3 + FR-T3-1 acceptance verification + W9 close-out report — rev-2

**Type**: test (manual operational + automated where feasible)
**depends_on**: T-B-03, T-B-04, T-C-05, T-C-05-EXT, T-C-06, T-D-03, T-E-01, T-E-02, T-E-03, T-E-04, T-E-05, T-E-07
**blocks**: none — final wave gate
**Target files**:
- `docs/audits/2026-05-04-w9-completion-report.md` (new, ~150 LOC)

**PRD reference**: PRD-0034 §3 FR-T2-3 + FR-T3-1 acceptance criteria

**What to build**: Run the canonical acceptance test suite for W9 and record evidence:

**FR-T2-3** (recap from Wave B; capture again at end of W9 since 24h may have elapsed):
1. WCAG AA on every `text-muted-foreground` cell — Playwright axe-core sweep; screenshot.
2. Zero `/undefined` 500-errors in **24h** gateway logs — Loki query.
3. Article-consumer offset healthy + `relation_evidence_raw` increasing.
4. **F-D4 backend EU date parse — corrected per audit B-001**: confirm `_parse_event_date("2026-04-30 12:15:00")` returns the ISO-T form (REPL probe in container per T-B-03 step 4 (a)) AND `temporal_events` count for EU regions over the last 24h is non-zero (T-B-04 offset reset has executed and replayed dropped events).

**FR-T3-1** (new):
5. **Sentry capture probe (frontend)**: hit dev-only `/(app)/dev-tools/sentry-test` route with `NEXT_PUBLIC_SENTRY_DSN` set in a staging env. Confirm event lands in Sentry inbox within **60 s** (PRD acceptance). Screenshot.
6. **Backend Sentry probe (all 10 services)** — rev-2 expanded: trigger an unhandled exception in each of the 10 backend services and confirm capture in Sentry. For S9, use the `/v1/_test/raise` test-only route from T-C-03. For the remaining 9, use `docker compose exec <service> python -c "raise RuntimeError('W9 sentry probe')"` against the running container. Each probe should produce a Sentry event within 60s. Screenshot one representative event per service (or confirm via the Sentry "Issues" list filtered by `service:` tag).
7. **Status page live**: navigate to `/status` and confirm 30-day uptime visible; verify in browser DevTools that `UPTIMEROBOT_READONLY_API_KEY` does NOT appear in any client-side network request, response, or JS bundle. Screenshot.
8. **Grafana dashboard live**: open `Error Observability` dashboard in Grafana; confirm all 4 panels load with data (may be near-zero if the system is healthy — the panel loading without error is the acceptance criterion). Screenshot.
9. **Sentry alert rules active**: open Sentry → Project → Alerts → Issue Alerts; confirm 4 alert rules are listed and Active. Screenshot.
10. **Sentry email delivery test**: trigger a synthetic exception via dev-tools route (step 5); confirm "New Issue" alert email arrives at `arnaurodondev@gmail.com` within 5 min. Screenshot.
11. **UptimeRobot delivery**: review email inbox for the test-alert from T-E-01. Confirm received. Screenshot.
12. **Sentry quota usage alert**: in Sentry org settings, confirm the 80% monthly events alert is active. Screenshot.

**Acceptance criteria**:
- [ ] All 12 evidence captures recorded in close-out report.
- [ ] Any failed item → either fixed in a sub-commit or recorded as a deferred follow-up issue.
- [ ] Close-out report cross-links PRD-0034 §3 acceptance bullets + audit `docs/audits/2026-05-03-revise-plan-0065-w9.md` + rev-2 changes summary.

#### Pre-read

- `services/api-gateway/src/api_gateway/routes/health.py` (verify response body shape)
- `apps/worldview-web/components/shell/` (footer location)
- `docs/runbooks/` (existing runbook style)
- UptimeRobot API docs: `https://uptimerobot.com/api/`
- Output of Wave B T-B-03

#### Validation Gate

- [ ] All 12 acceptance evidence items captured (rev-2: +Grafana dashboard, +Sentry alert rules, +email delivery test, +all 10 service Sentry probes).
- [ ] `pnpm -C apps/worldview-web test` passes (status page + error-boundary tests).
- [ ] Grafana `error-observability.json` committed and provisioned.
- [ ] 4 Sentry alert rules active; email delivery confirmed.
- [ ] All Wave A/B/C/D outputs referenced in close-out report.

#### Break Impact

| Broken File | Why It Breaks | Fix Required |
|-------------|---------------|--------------|
| (none — additive only) | Footer link is additive; status page is a new route | n/a |

#### Regression Guardrails

- **PRD §9** (status page leakage): status page shows uptime only. Test `test_status_page_strips_error_details` enforces this.
- **UptimeRobot free-tier quota**: 50 monitors total / 10 alerts. We use 1 monitor + 1 alert contact — well under.
- **`/healthz` keyword stability** (corrected from `/v1/health` per audit B-002): if a future PR changes the response shape (e.g. adds nested `checks: {...}` and removes `"status":"ok"` literal), UptimeRobot will alert silently. The contract test `services/api-gateway/tests/contract/test_health_keyword_stability.py` is shipped under T-E-01 (above) and asserts the literal string is in the `GET /healthz` response — a monitoring contract.

---

## 5. Cross-Cutting Concerns

| Concern | Impact | Resolution |
|---------|--------|-----------|
| **Avro schema changes** | none | W9 introduces no event schema changes |
| **DB migrations** | none | W9 introduces no DDL |
| **Kafka topic changes** | none | W9 only resets one consumer-group offset (operational) |
| **New env vars** | 10 (6 backend Sentry + 1 frontend DSN + 2 ops [`UPTIMEROBOT_MONITOR_ID`, `STATUS_PAGE_URL`] + 1 server-only proxy key [`UPTIMEROBOT_READONLY_API_KEY`]); added to all 10 service `.env` files in worldview-gitops `env/dev/` and all 10 `values.yaml`. | All documented in T-C-06 + T-D-03 + T-E-01 + T-E-02 |
| **Grafana dashboard** | New `infra/grafana/dashboards/error-observability.json` — Loki-based; 4 panels | T-E-03 |
| **Sentry alert rules** | 4 rules → email `arnaurodondev@gmail.com`; no code change; Sentry SaaS UI only | T-E-04 |
| **Documentation** | 6 doc files updated/created | Listed per task |
| **Architecture invariants** | preserved (no domain layer touched, no cross-service DB access added) | Verified by 95-test architecture suite at every wave gate |
| **Free-tier dependency cost** | $0 (Sentry free 5K events/month, UptimeRobot free 50 monitors, custom status page is in-tree) | PRD §10 confirms |
| **PII handling** | Sentry sees stacktraces of unhandled exceptions | `before_send` PII guard + no replay + no PII in tags |

---

## 6. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Sentry quota exhausted (5K/month) | MED | MED | **Per audit I-002 — primary defence is per-fingerprint `before_send` rate limiter** (≤10 events/fingerprint/hour, T-C-01); secondary is Sentry's own 80% usage alert (T-E-04 step 9). Without the rate limiter, a single misconfigured query firing per-request can exhaust 5K events in <30 min and blind us to subsequent unrelated incidents. Risk likelihood/impact upgraded LOW→MED post-audit. |
| Sentry init crashes a backend at startup | LOW | HIGH | T-C-01 wraps `sentry_sdk.init` in `try/except` returning False; service starts even if Sentry is unreachable |
| Frontend build breaks when Sentry env unset | MED | HIGH | T-D-01 enforces `withSentryConfig` only wrapped if `SENTRY_AUTH_TOKEN` is set; default DSN is `""` → SDK no-op |
| BP-302 fix not actually deployed | LOW | HIGH | T-A-01 introspects the running image; if missing, T-B-01 forces rebuild |
| Article-consumer offset reset skips a real (non-poison) message | LOW | MED | T-B-02 default is `--shift-by 1` (skip exactly one); audit doc records before/after offsets so a follow-up replay is possible |
| UptimeRobot keyword changes silently break monitoring | MED | MED | T-E-01 adds a contract-style test in S9 asserting the keyword string is in `/healthz` response (route corrected per audit B-002) |
| Status page leaks error details OR exposes UptimeRobot API key | LOW | HIGH | **Per audit B-003 — defense in depth**: (1) UptimeRobot API call lives ONLY in `app/(public)/status/api/uptime/route.ts` Route Handler (Node runtime); (2) `UPTIMEROBOT_READONLY_API_KEY` is server-only — no `NEXT_PUBLIC_*` exposure; (3) Route Handler returns ONLY a whitelisted projection (monitor_id, friendly_name, status, custom_uptime_ratio, daily_buckets) — strips `url`, `alert_contacts`, `last_error`, etc.; (4) 4 unit tests enforce stripping at the API boundary; (5) page never spreads response into JSX. PRD §9 reinforced. |
| PII leaked to Sentry | LOW | HIGH | Both backend and frontend `before_send` PII guards (T-C-01 + T-D-01); 4+3 unit tests cover each removal class |
| W9 collides with W4/W5/W6 in S6/S8/S9 wiring | LOW | LOW | W9 only adds a single `init_sentry` call in each lifespan startup (S9 + S6 + S8 per audit I-001); W4/W5/W6 add routes/metrics — disjoint. PLAN-0063 W5-5 metrics + PLAN-0064 W6 `FatalSearchError` Sentry capture both inherit from W9's lib + lifespan wiring with zero extra code. |

**Critical path**: Wave A (verification) is mandatory before Wave B (operational changes). Wave C (backend Sentry) and Wave D (frontend Sentry) can run in parallel with each other and with Wave B once Wave A is green. Wave E gates final close-out.

**Rollback strategy**: Per PRD §12: each workstream independently revertable. W9-specific:
- Backend Sentry: set `SENTRY_ENABLED=false` env var → SDK is a no-op; no code revert needed.
- Frontend Sentry: leave `NEXT_PUBLIC_SENTRY_DSN=""` → SDK is a no-op.
- UptimeRobot: pause monitor in dashboard.
- Status page: deploy without `/status` route or remove footer link.

No destructive operations; all rollbacks are config-only.

---

## 7. Open Questions / Risks Surfaced During Planning

1. **OQ-W9-01** *(RESOLVED 2026-05-03 audit I-004)*: Status page is **Option A in-tree Next.js page only**. Atlassian Statuspage discontinued; paid alternatives deferred. PRD §3 FR-T3-1 amended via T-E-05.
2. **OQ-W9-02** *(non-blocking)*: Confirm Sentry org/project naming convention — affects `withSentryConfig` config. Default: `worldview` org, separate `worldview-backend` and `worldview-web` projects.
3. **OQ-W9-03** *(RESOLVED 2026-05-03 audit I-001)*: Sentry pilot covers **S9 + S6 + S8** (was S9-only in draft). PLAN-0063 (W5) and PLAN-0064 (W6) both depend on Sentry being initialized in S6 and S8. Wiring all three at once costs ~+1 h on W9 budget; the alternative (defer) creates duplicate init churn in W5/W6 plans. The remaining 7 backends stay deferred to the post-launch hardening sprint.
4. **OQ-W9-04** *(RESOLVED per audit N-004 recommendation)*: Wave A/B run against the **local-dev compose stack** (operational verify); Wave C/D are code-only and execute in any environment; Wave E (UptimeRobot + status page) targets **the staging/prod environment** where UptimeRobot can actually reach a public URL. This split is documented in §8 Suggested Execution Order.
5. **Risk-W9-01** *(RESOLVED 2026-05-03 audit I-002 — upgraded from DEFERRED)*: Per-fingerprint `before_send` rate limiter is now **required** (T-C-01), not deferred. Reasoning: a single misconfigured query that throws per-request would exhaust the 5K/month quota in <30 min and blind us to subsequent incidents. Default cap = 10 events/fingerprint/hour; tunable via `SENTRY_FINGERPRINT_RATE_LIMIT`. 3 unit tests added in T-C-01.
6. **Risk-W9-02**: The "all 4 PRD-cited code fixes already in `f27e266b`" finding means W9's PRD literal language may be partially redundant. The plan handles this by reframing Wave A/B as **verification + operational** rather than **code-fix**. The audit closed the F-D4 sub-issue: F-D4 is a backend KG consumer fix, not a frontend fix; the smoke test was rewritten in T-B-03 step 4 and the offset reset added as T-B-04. If the user wants W9 to additionally apply other defects discovered in QA reports since 2026-05-01, this plan does **not** cover them — that would be a scope expansion (recommend separate `/qa` then `/fix-bug`).

---

## 8. Suggested Execution Order

Environment split per audit N-004 (RESOLVED):

```
1. /implement PLAN-0065 Wave A           (30–45 min, single agent, sequential)   [LOCAL-DEV compose]
2. /implement PLAN-0065 Wave B           (45–90 min, single agent, sequential)   [LOCAL-DEV compose; T-B-04 may also need staging if economic-events run there]
3. /implement PLAN-0065 Wave C           (~150 min, single agent, sequential)    [code-only — any env]
   /implement PLAN-0065 Wave D           (60–90 min, parallel-safe agent, separate worktree) [code-only — any env]
4. /implement PLAN-0065 Wave E           (90 min, single agent, sequential — gates close-out) [STAGING/PROD — UptimeRobot needs a public URL]
5. /qa PLAN-0065                         (final QA pass; verify all 9 acceptance items)
```

Estimated total wall-clock: ~6 hours single-developer, ~4.5 hours with Wave C/D parallelisation (was 5 / 3.5 — added ~1 h for T-B-04 and T-C-05 + ~30 min for T-E-02 server-proxy refactor + ~30 min for I-006 build matrix). Matches PRD §15 W9 estimate of 1.5 dev-days (12h budget) with comfortable margin for unforeseen friction.

---

## 9. Compounding Notes

The `/plan` skill self-check (per skill template + 2026-05-03 audit revision pass):
- **BUG_PATTERNS.md**: a new pattern surfaces from audit I-005 — "underscore-prefixed Next.js folder is private (non-routable)". Add as `BP-3xx` candidate in T-D-02 commit; the dev-only sentry-test route would have silently failed without this fix. **Not auto-applied** — captured for the implementer.
- **STANDARDS.md**: per audit N-005, the Sentry init pattern is documented **inline at T-C-04** (do NOT defer): default-off, PII `before_send` guard, per-fingerprint rate limiter, idempotent init, returns bool that the call site logs. Pattern is broadly applicable; deferring risks the next service-author copying a slightly different shape.
- **HIGH_RISK_PATTERNS.md**: per audit B-003, "third-party API keys for client-facing pages MUST live in server-only Route Handlers; `NEXT_PUBLIC_*` is reserved for non-secret values". Add to T-E-02 commit.
- **REVIEW_CHECKLIST.md**: per audit B-001 root-cause, the `/plan` skill should "verify each codebase-state row by reading the actual diff (not just `git show --stat`)" — added to compounding follow-ups for the skill maintainer.
- **MASTER_PLAN.md**: no architectural change.
- **Service `.claude-context.md`**: api-gateway, nlp-pipeline, and rag-chat all gain a new lifespan startup call after T-C-03 / T-C-05 — update each context as part of T-C-04 docs.

**Compounding decision**: STANDARDS.md updated inline at T-C-04 (per audit N-005). Bug pattern files updated in their respective wave commits.

---

## 15. Follow-ups (deferred from 2026-05-03 audit revision pass)

These items were surfaced by the 2026-05-03 audit (`docs/audits/2026-05-03-revise-plan-0065-w9.md`) and are intentionally deferred — they are out-of-scope for W9 itself and either belong to a different skill / audit or are cosmetic.

| ID | Source | Item | Why deferred | Owner |
|----|--------|------|--------------|-------|
| FU-001 | Audit N-001 | Plan numbering collision: `0062-w4-structured-ai-brief-plan.md` and `0062-kafka-avro-enforcement-migration-plan.md` share the number `0062`. TRACKING.md needs reconciliation; PRD-0034 §6 W4 calls W4 "0062-structured-brief-plan.md". | Outside W9 scope; affects multiple plans. Track via `/docs-audit`. Recommend renaming `0062-kafka-avro-enforcement-migration-plan.md` → `0062b-…` or bumping the number entirely. | `/docs-audit` skill maintainer |
| FU-002 | Audit N-002 | Plan §2 Phase-0.5 recency check wording is tautological ("PRD created 2026-05-02; today 2026-05-03 → no `/revise-prd` needed"). Should be replaced with a stronger gate ("any cross-PRD conflict found?"). | Cosmetic; affects the `/plan` skill template, not this specific plan. | `/plan` skill maintainer |
| FU-003 | Audit B-001 root-cause | `/plan` skill Phase 3 (codebase-state verification) should be strengthened to "verify each codebase-state row by reading the actual diff (not just `git show --stat`)". The F-D4 misclassification was caused by relying on the file-list summary instead of the patch hunks. | Skill-level improvement; not a plan-level fix. | `/plan` skill maintainer |
| FU-004 | Audit (cross-cutting) | Wire Sentry into the **other 7 backends** (knowledge-graph, alert, content-ingestion, content-store, market-data, market-ingestion, portfolio). The lib's `register_error_handlers` extension already routes their unhandled exceptions to Sentry once `init_sentry` is called in their lifespan. | W9 already exceeds budget with the +1 h S6+S8 expansion. The remaining 7 services don't have downstream-plan dependencies on Sentry availability (W5/W6 only need S6/S8). Defer to the post-launch hardening sprint. | Post-launch hardening sprint owner |

---

## 10. References

- PRD-0034 `docs/specs/0034-mvp-launch-readiness-program.md` §3 FR-T2-3, FR-T3-1, §6 W9, §10, §15
- **Audit revision report `docs/audits/2026-05-03-revise-plan-0065-w9.md` (3 BLOCKING + 6 IMPORTANT + 5 NICE-TO-HAVE — applied this pass)**
- Commit `f27e266b` (BP-302, F-VISUAL-002, F-E8, F-D4 baseline fixes — F-D4 is a backend KG fix per audit B-001 reattribution)
- `docs/audits/2026-05-01-qa-platform-stability-iter3.md` (BP-302 root-cause)
- `libs/observability/src/observability/error_capture.py` (existing exception handler — extension point)
- `apps/worldview-web/app/providers.tsx` (current provider stack — extension point)
- `feedback_frontend_pnpm.md`, `feedback_frontend_comments.md`, `feedback_audit_returned_value_persistence.md` (memory-pinned constraints)
- PLAN-0024 (production deployment — env-var injection target)
- PLAN-0054 (existing observability stack — Sentry is additive, not a replacement)
