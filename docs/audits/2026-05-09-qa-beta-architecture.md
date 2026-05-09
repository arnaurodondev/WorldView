# PLAN-0087 Beta-Readiness — Architecture Decision Lead Review

**Date**: 2026-05-09
**Auditor**: Architecture Decision Lead (read-only specialist agent)
**Scope**: 19 commits since `974f4f1d` on `feat/content-ingestion-wave-a1` (11 PLAN-0087-era + 8 PLAN-0064 tail). Specifically the 11 PLAN-0087 commits called out in the prompt.
**Sources read**: `RULES.md` (R1–R34), `AGENTS.md`, `PR_INVESTIGATION_PROTOCOL.md`,
`INVARIANT_ANALYSIS.md`, `2026-05-09-qa-standards-rules-review.md`, plus
direct inspection of: `infra/kafka/schemas/nlp.article.enriched.v1.avsc`,
`libs/messaging/src/messaging/kafka/consumer/base.py`,
`libs/contracts/src/contracts/events/nlp/article_enriched.py`,
`scripts/import_guards/{rules,allowlist}.yaml`,
`services/{rag-chat,knowledge-graph,api-gateway,intelligence-migrations}`,
`apps/worldview-web/app/(app)/settings/`, `infra/compose/docker-compose.yml`,
`docs/{services,libs,architecture/decisions}/`.

> Numbering convention: findings are F-NNN. SEV scale: **B** = beta-blocking,
> **H** = high (fix before public demo), **M** = medium (post-demo cleanup),
> **L** = low (note for future).
>
> The prior audit (`2026-05-09-qa-standards-rules-review.md`) covered R3 docs
> gap and missing tests for 9 commits. **This report does not re-litigate
> those findings** — see §11 for the explicit re-confirmation. It focuses on
> architecture-decision aspects: layer boundaries, ports, forward-compat,
> PRD/ADR alignment, cross-cutting consistency, runbook + onboarding
> coverage, and the multi-tenant story.

---

## 0. Executive Summary

| Category | Status |
|---|---|
| Layer boundaries (R25) | 13 IG-LAYER-002 violations remain — **all pre-existing**, none introduced this session. |
| Port pattern | Correctly preserved; `BriefArchiveWriteAdapter` cleanly implements `BriefArchivePort` Protocol. |
| Forward-compat (R5) | `source_name` addition is correctly nullable + default null. **Operational gap**: Schema Registry must be re-registered (commit msg flags this). |
| PRD-0087 alignment | Acceptance criteria satisfied per commit; D-R3-NARR + migration 0038 still missing tests (already in prior audit §SF-2). |
| Cross-cutting consistency | Strong; one weakness — `path_insight_seeder.py` reads env directly via `os.environ.get` instead of via `Settings`. |
| Event envelope | `event_id`/`event_type`/`schema_version`/`occurred_at` all present on enriched.v1 contract. |
| Shared lib usage | structlog, common.ids, common.time used consistently in changed files. |
| Config (R13) | Mostly compliant; one outlier (path_insight_seeder env-var read). |
| Init container ordering | `intelligence-migrations` correctly gated by `service_completed_successfully`; downstream services depend correctly. |
| Documentation drift | **Significant** — `libs/messaging/.claude-context.md` does not exist; `intelligence-migrations/.claude-context.md` does not mention 0037 or 0038; cooperative-sticky default is undocumented platform-wide. |
| **R3 doc gap (re-confirmed)** | Confirmed — **no doc update in any PLAN-0087 commit**. See §11. |
| **ADR coverage** | **Missing ADR for cooperative-sticky** (platform-default change). See F-006. |
| **Onboarding** | README.md has Quick Start; **no operator runbook** for post-`make dev` ops (restart wedged consumer, clear cache, replay topic). See F-013. |
| **Settings UI** | Theme works; brokerage management lives at `/portfolio` (not `/settings/integrations` which is a placeholder); alert prefs are a placeholder mock. |
| **Multi-tenant story** | PLAN-0086 + PRD-0075 cover the technical work; **no canonical user-facing description** in `MASTER_PLAN.md` beyond a one-line mention. See F-014. |

Overall: the runtime correctness of the session is high; the gaps are
documentation, operator-runbook coverage, and one pre-existing IG-LAYER-002
backlog the audit must surface for the beta review even though it predates
this session.

---

## 1. Layer Boundaries (R25 / IG-LAYER-002)

**Question 1 of mandate**: domain importing from infrastructure? API
importing from infrastructure?

### F-001 — Pre-existing IG-LAYER-002 violations (13 net-new in guard report)
**SEV**: H — pre-existing, unrelated to this session, but visible in the
beta gate.
**Source**: `python scripts/import_guards/check_import_guards.py` →
13 net-new + 3 baselined.

| File | Count | Likely cause |
|---|---|---|
| `services/content-ingestion/src/content_ingestion/api/routes/documents.py` | 7 | local imports inside route functions (deferred-import factory pattern) |
| `services/nlp-pipeline/src/nlp_pipeline/api/routes/search_documents.py` | 3 | direct Prometheus metric imports from `infrastructure.metrics.prometheus` |
| `services/rag-chat/src/rag_chat/api/routes/public_briefings.py` | 2 | local repository imports inside two route handlers |
| `services/rag-chat/src/rag_chat/api/routes/chat.py` | 1 | already allowlisted (SSE generator scope, justified) |
| `services/market-data/src/market_data/api/routers/quotes.py` | 1 | already allowlisted (cache-aside pattern, justified) |

**Proof none are new this session**:
- `git log 974f4f1d..HEAD -- services/content-ingestion/src/content_ingestion/api/routes/documents.py` → empty.
- `git log 974f4f1d..HEAD -- services/nlp-pipeline/src/nlp_pipeline/api/routes/search_documents.py` → empty.
- `git log 974f4f1d..HEAD -- services/rag-chat/src/rag_chat/api/routes/public_briefings.py` → empty.

**Recommendation**: do not block beta on these — but acknowledge in the
review that `make qa` already fails on this guard. Either:
(a) refactor these 13 imports into proper application-layer use-cases (estimated 4–6 h, low risk)
or (b) add explicit allowlist entries with justifications (15 min, but technical debt).
Mixing the two is fine — `nlp-pipeline/api/routes/search_documents.py:145` is
the easy win (Prometheus metrics belong in `infrastructure/`, but the import
in the route body is for the metric *identifier*, not for storage; lift them
to module top in a metrics façade or move the increment into the use case).

### F-002 — Domain layer purity holds (R21, IG-LAYER-001)
**SEV**: NONE (informational). All 9 services that have a `domain/errors.py`
correctly define `DomainError(Exception)` as the root and inherit subclasses
from it. No domain → infrastructure imports detected in this session's diff.

---

## 2. Port Pattern (Question 2)

### F-003 — Port discipline preserved on `BriefArchiveWriteAdapter`
**SEV**: NONE (informational, +). The new
`services/rag-chat/src/rag_chat/infrastructure/clients/brief_archive_write_adapter.py`
is a clean `BriefArchivePort` Protocol implementation:
- ABC-style: `BriefArchivePort` is a `@runtime_checkable Protocol` (per the
  worldview convention recorded in PLAN-0083, BP-405).
- The adapter takes a session **factory** (not a session) — the right call
  for fire-and-forget asyncio.shield use-cases (R24-aware: each save opens
  + closes its own session).
- Owns its transaction boundary (R26: explicit `commit()`; the underlying
  `BriefArchiveRepository` does not commit) — correct.
- Errors are caught + logged, not raised — correct because the use case
  treats archival as best-effort under `asyncio.shield`.

This adapter is the **single most architecturally clean piece of work in
the session** and the right reference for future write-side adapters that
need session-scoped lifetime control.

### F-004 — Tool executor pattern correctly per-request (R30)
**SEV**: NONE (informational). The `ToolExecutorFactory + ToolExecutor`
split (BP-406, PLAN-0067) is preserved — `tool_executor.py` line 64+ keeps
the `for_request(...)` shape. The 8d8e6519 fix only touched
`build_default_registry()` and `execute_sync()` — no new singleton state was
introduced.

### F-005 — Mixed Protocol vs ABC port styles (consistency observation)
**SEV**: L. Inside `services/rag-chat/src/rag_chat/application/ports/` the
codebase mixes both:
- Protocol: `brief_archive`, `brief_feedback`, `intent_classifier`, `metrics`, `embedding`, …
- ABC: `thread_repository`, `entity_context_loader`, …

This is **not a bug** — both are documented as acceptable in PLAN-0083 — but
the choice is per-author rather than per-rule. Consider standardising in
STANDARDS.md §1 with a clear "use Protocol unless you need shared default
behaviour" rule. Estimated 15 min once decided.

---

## 3. Forward-Compat / Avro (R5, R28) — Question 3

### F-006 — `source_name` Avro change is forward-compatible **but Schema Registry must be re-registered**
**SEV**: B — operational blocker. Code is correct; runtime is not.

The diff to `infra/kafka/schemas/nlp.article.enriched.v1.avsc`:
```jsonc
{"name": "source_name", "type": ["null", "string"], "default": null, "doc": "..."}
```
satisfies R5 (nullable union with default null). The matching contract
(`libs/contracts/src/contracts/events/nlp/article_enriched.py`) correctly
adds `tenant_id: str | None = None` AND `source_name`, with both `from_dict`
and `to_dict` handling absent fields.

**However**, commit `493dcb4e`'s own commit message says:
> Schema Registry note: this fix updates the local .avsc file. The running
> Schema Registry still has the old version; the operator must re-register
> the new subject and restart the affected producers/consumers (nlp-pipeline
> article-consumer, knowledge-graph enriched-consumer) before the field
> flows end-to-end.

This is a beta-blocker if not actioned before the demo. The Schema Registry
contract is the *runtime* contract; the .avsc file is the source-of-truth
for next deploy. After `make dev-rebuild`, the registered schema will be
updated by `register-schemas.py` (per `docs/services/intelligence-migrations.md`
boot order). Recommendation:
1. Confirm `make dev-rebuild && make dev` was run since `493dcb4e`.
2. If not, run it before any demo rehearsal — otherwise KG enriched_consumer
   keeps logging `evidence_source_metadata_missing` with no `source_name`,
   defeating the point of the fix.

### F-007 — Field-count drift detection (good practice, +)
**SEV**: NONE. The fix in `tests/contract/test_avro_schemas.py` bumped the
expected field count for `nlp.article.enriched.v1` from 23 to 25 and
**caught a pre-existing drift from PLAN-0086 tenant_id work** (was 24, not
23). This is exactly the kind of contract test that catches schema sprawl.
No new finding — flagged here as a positive that should be replicated for
every event schema (currently only `nlp.article.enriched.v1` is field-count
asserted).

---

## 4. PRD-0087 Acceptance Alignment (Question 4)

### F-008 — Per-commit acceptance: PASS, with two carry-forwards
| Defect | Commit | Acceptance met? | Carry-forward |
|---|---|---|---|
| D-INIT-6 | 493dcb4e | ✅ source_name flows, R7 violation removed | F-006 (Schema Registry op) |
| D-R1-001/002/005 | 8d8e6519 | ✅ to_tool_definitions implemented, schemas filled, errors propagated | None |
| D-P3-006/009 | 92915986 | ✅ cooperative-sticky default + max.poll.records propagated | F-009 (ADR missing) |
| D-F3-001..011 | a630d62f | ✅ token sweep + architecture test guard | None |
| D-R3-001/D-P1-002 | 8bbd7480 + 0f96c81c | ⚠ runtime fixed but no repository-level integration test (prior audit SF-2) | Tests still missing |
| D-R3-003/005, D-R4-002/003/004, D-F1-007/009, D-F2-001 | 97153b36 | ✅ runtime fixed | Tests for 5 of 8 missing (prior audit SF-2) |
| D-R3-007/D-F2-005/D-R4-010 | 5e1b18f5 | ✅ 8 demo entities seeded | **No migration test** (prior audit SF-2 + F-010) |
| D-R3-NARR | 1ef95ee9 + 066068cd | ✅ runtime fixed AND 066068cd added the regression test the prior audit asked for | None |
| D-Q-002/D-Q-003 | 5940b477 | ✅ citation marker prompt + today's-date anchor | None |
| HF-10 currency / titles / UUID leak | 2b359f73 | ✅ implemented | None |

**Net**: 11 commits, 11 acceptance criteria met functionally. The two
*architecture-relevant* gaps that the prior audit already raised are
re-confirmed (F-009, F-010 below). 066068cd post-fixed the highest-priority
prior-audit ask (D-R3-NARR test) so that gap is now closed.

### F-009 — `cooperative-sticky` is platform-wide default change without ADR
**SEV**: H. Commit `92915986` flips the consumer-protocol default for *every
service in the monorepo*. Per RULES.md R4:
> MUST write an ADR before adding a new service or major architectural
> change.

The change is documented as a code comment in `libs/messaging/.../consumer/base.py:95–106`,
in the prior audit (§3 BP-442), and in BUG_PATTERNS.md BP-442. It is not
documented in:
- `docs/architecture/decisions/` (no ADR).
- `docs/libs/messaging.md` (no Defaults section).
- `libs/messaging/.claude-context.md` (file does not exist).

**Recommendation**: add `docs/architecture/decisions/0007-kafka-cooperative-sticky-default.md`
recording: context (partial-assignment wedge symptom), decision, alternatives
(`range`, `roundrobin`, `sticky`), consequences (incremental rebalance =
KIP-429 behaviour for every consumer). Estimated 30 min. This is the single
highest-leverage post-audit fix because the next reviewer rediscovers the
question every time someone hits a rebalance issue.

### F-010 — Migration 0038 still has no test file
**SEV**: H — same finding as prior audit SF-2; re-confirmed.
`services/intelligence-migrations/tests/test_migration.py` covers migrations
0001–0037 but does not have a section for 0038.
- 0037 got a 128-line dedicated `test_migration.py` block in commit
  97153b36.
- 0038 got 0 lines (5e1b18f5 was migration-only).

A pure seed-only migration is low-risk in principle, but the seeded IDs use
a `0195daad-d001-...` UUIDv7-shaped pattern, and a bug in any of the 8 INSERT
blocks would silently miss an entity that the chat A7 prompt and B5 deep-dive
demo *require*. Add at least:
- one test asserting all 8 canonical_entities rows exist after upgrade,
- one test asserting `entity_aliases` rows are present for each (TICKER + display name),
- one downgrade-then-upgrade idempotency test.

Estimated 30 min.

---

## 5. Cross-Service Consistency (Question 5)

### F-011 — `path_insight_seeder.py` reads `os.environ` directly
**SEV**: M. `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/path_insight_seeder.py:39`:
```python
_HUB_MIN_RELATIONS = int(os.environ.get("PATH_INSIGHT_HUB_MIN_RELATIONS", "2"))
```
Every other config read in `services/knowledge-graph/` goes through the
pydantic-settings `Settings` class. R13 only forbids secrets, not all
hardcoding, so this is not a strict violation — but it is a **cross-cutting
inconsistency**:
- The module-level `int(...)` happens at import time, not at instantiation,
  so changing `PATH_INSIGHT_HUB_MIN_RELATIONS` requires container restart
  (not just a config reload) — surprising behaviour.
- It bypasses the `Settings.path_insight` nested model that would naturally
  hold this knob.

**Recommendation**: move into `KnowledgeGraphSettings.path_insight.hub_min_relations` and
wire via DI like every other knob in this service. Estimated 20 min.

### F-012 — Naming + error consistency: PASS
**SEV**: NONE. Every service's `domain/errors.py` defines `DomainError`
(R21). Every Avro topic name in this session matches `<domain>.<entity>.<verb_past>`.
Env var prefix convention (`KG_*`, `RAG_CHAT_*`, `NLP_PIPELINE_*`) holds.
structlog is used in 100% of changed Python files this session. No stdlib
`logging.getLogger()` regressions.

---

## 6. Event Envelope & Shared Libs (Questions 6, 7)

### F-013 — Event envelope on `nlp.article.enriched`: PASS
All four envelope fields present on `CanonicalNlpArticleEnriched`:
- `event_id` (str, UUIDv7 by convention)
- `event_type` (default `"nlp.article.enriched"`)
- `schema_version` (int, default 1)
- `occurred_at` (str, ISO-8601 UTC)

`source_name` correctly added as a *payload* field, not an envelope field.

### F-014 — `common.ids.new_uuid7()` / `common.time.utc_now()` usage in changed files: PASS
Spot-checked `clients.py` (gateway), `generate_briefing.py` (rag-chat),
`generate_narrative.py` (kg), `brief_archive_write_adapter.py` — all use
`datetime.now(tz=UTC)` or `common.time.utc_now()`. No naive datetimes
introduced.

The pre-existing `services/nlp-pipeline/src/nlp_pipeline/infrastructure/nlp_db/models.py`
SQLAlchemy `default=uuid.uuid4` is a model-default for legacy tables — not
session-introduced.

---

## 7. Config / Secrets (Question 8)

### F-015 — pydantic-settings used everywhere: PASS (one exception)
Confirmed for `rag-chat`, `knowledge-graph`, `nlp-pipeline`,
`api-gateway`, `intelligence-migrations`. The single exception is F-011
above (`os.environ.get` in `path_insight_seeder.py`).

### F-016 — No secrets in code: PASS
Spot-checked the 11 PLAN-0087 commits — no API keys, JWTs, or DB passwords
in source. `JWT_AUDIENCE`, DB URLs, DeepInfra keys all sourced from env via
Settings.

---

## 8. Docker-Compose / Init Container Ordering (Question 9)

### F-017 — `intelligence-migrations` ordering: PASS
`infra/compose/docker-compose.yml`:
- `intelligence-migrations` runs once (build context = service dir).
- All consumers of `intelligence_db` (S6, S7, KG narratives worker, …) declare
  `depends_on: intelligence-migrations: condition: service_completed_successfully`.
- `kafka-init` and `schema-registry-init` similarly gated.

This is the right pattern and the file currently has it correct.

### F-018 — No new compose changes this session
**SEV**: NONE. None of the 11 PLAN-0087 commits modified
`infra/compose/docker-compose*.yml`. Migration 0038 piggybacks on the
existing init container — runtime correct.

---

## 9. Documentation Drift (Question 10)

### F-019 — `libs/messaging/.claude-context.md` does not exist
**SEV**: H. Every other shared library has one (`common.md`, `contracts.md`,
`messaging.md`, `ml-clients.md`, `observability.md`, `prompts.md`,
`storage.md` all live under `docs/libs/`), and every service has a
`.claude-context.md` — but `libs/messaging/.claude-context.md` does not.
This is the place where the cooperative-sticky default belongs (the
agent-routing context entrypoint per `CLAUDE.md` "Context Loading"), and
its absence means the next agent who reads BP-442 won't be steered to the
right file.

**Recommendation**: create `libs/messaging/.claude-context.md` with at least:
- header (purpose, owner)
- entry points (`BaseKafkaConsumer`, `BaseProducer`, `OutboxDispatcher`,
  `ValkeyDedupMixin`)
- defaults table (cooperative-sticky, max.poll.records=500, session_timeout=60s)
- pitfalls (BP-127 ruff, BP-302 watchdog, BP-415 dedup mixin, BP-442 wedge).
Estimated 30 min.

### F-020 — `intelligence-migrations/.claude-context.md` is stale
**SEV**: M. The file's "Tables Owned" section is up to date through
migration 0026, but does not mention:
- 0037 (recreate temporal_events idempotent, BP-393).
- 0038 (8 demo-critical canonical entities — exposed in chat A7 / B5 deep-dive).

Both shipped this session. The file should at least name 0038's seed
entities so the next agent looking at "why is OpenAI suddenly findable"
finds the answer in the context file rather than the migration body.
Estimated 15 min.

### F-021 — No `docs/services/*.md` updated this session
**SEV**: H — re-confirms prior audit §SF-1.
Per RULES.md R3: every API/event/schema/config change must update docs.
This session changed:
- public S9 endpoint behaviour (`/v1/instruments/{id}/page-bundle` now
  performs entity_id → ticker → instrument_id resolution).
- public S6 endpoint behaviour (`url` field on news items normalised;
  `legacy_sections=[]` always).
- platform-wide Kafka default (cooperative-sticky).
- forward-compat Avro field on `nlp.article.enriched.v1`.
- 8 newly-seeded canonical entities visible to S7/S8 demos.
- new `BriefArchiveWriteAdapter` wired in the S8 briefing flow.

**None** of these landed a doc update. Minimum viable set (re-listing the
prior audit's recommendation, unchanged):
1. `docs/services/nlp-pipeline.md` § Events → add `source_name`.
2. `docs/services/knowledge-graph.md` § Consumers → R7 trap removed.
3. `docs/libs/messaging.md` → cooperative-sticky default + KIP-429 link.
4. `docs/services/api-gateway.md` § page-bundle → fallback chain.
5. `docs/services/rag-chat.md` § Brief archival → `BriefArchiveWriteAdapter`.
6. `docs/services/intelligence-migrations.md` § Seed data → migration 0038.

Estimated 45 min total.

### F-022 — `MASTER_PLAN.md` is silent on the multi-tenant story
**SEV**: H — beta-relevant. The only multi-tenant mention in `MASTER_PLAN.md`
is one bullet on line 338:
> Multi-tenant: Portfolio/watchlist/alert data scoped by tenant_id.
> intelligence_db is shared; tenant isolation enforced at query/delivery layer.

But PLAN-0086 + PRD-0075 add `tenant_id` to three Avro schemas
(`content.article.raw`, `content.article.stored`, `nlp.article.enriched`)
and to `documents` + `dedup_hashes` tables. The frontend has no UI surface
for tenant management. For a beta review the directorate-level reader needs:
- a paragraph in `MASTER_PLAN.md` § Architecture explaining the
  "public news with tenant_id=null + private uploads with tenant_id=UUID"
  design,
- a link to PRD-0075 (`docs/specs/0075-multi-tenant-content-pipeline-isolation.md`).

Estimated 15 min.

---

## 10. Beta-Specific Adds

### F-023 — No ADR for cooperative-sticky default — **see F-009** (duplicate by design; flagged separately because the beta gate cares about ADR coverage as a signal, not just the cooperative-sticky question itself).

### F-024 — Onboarding documentation is README-only
**SEV**: M. `README.md` has a `# Quick Start (< 10 minutes)` section that
walks through `bootstrap.sh → fetch-secrets → make dev → make seed → open
:3001 → Dev Login`. This is good for a developer first-clone.

What is **missing** for a beta-grade onboarding:
- No `docs/ONBOARDING.md` for non-developer reviewers (the thesis director,
  external evaluators, or a hypothetical second engineer).
- No explanation of "what to expect on first launch" (which containers will
  spin up slowly because they pull big ML images, which dev tools live at
  which port, what `make seed` actually populates).
- No "common first-run errors" troubleshooting (e.g. port 3001 already in
  use, Docker memory pressure, missing `worldview-config` repo for
  `make fetch-secrets`).

The `docs/runbooks/` directory has 9 runbooks, but they are all
*operator*-side (debugging-guide, hotfix-procedures, secrets-management,
sentry-alerts, uptime-monitoring) — none are *first-run reviewer*-side.

**Recommendation** (post-beta acceptable): create `docs/ONBOARDING.md`
covering: (1) what to expect, (2) what's in each dev tool URL, (3) common
first-run failures. Estimated 60 min.

### F-025 — Settings UI: theme works; brokerage + alert prefs are placeholders
**SEV**: M. `apps/worldview-web/app/(app)/settings/`:
- `appearance/page.tsx` → `AppearanceTab` — works (real theme toggle).
- `profile/page.tsx` → `ProfileTab` — works (calls `useAuth`).
- `integrations/page.tsx` → `SettingsPlaceholder` "TastyTrade brokerage sync
  (already wired in /portfolio)" — **placeholder** (so brokerage management
  IS available in the app, but it lives at `/portfolio`, not `/settings`).
- `notifications/page.tsx` → `NotificationsTab` — body has hardcoded
  `NOTIFICATION_TYPES` array (line 46+), no S10 prefs API integration.
- `data/page.tsx`, `security/page.tsx`, `preferences/page.tsx` —
  placeholders.

So technically: **a working settings page exists**, but the meaningful
sub-tabs (notifications, integrations, data) are scaffolded placeholders.
For a beta demo the user sees URLs that look complete but have "Coming via
PRD-0022"-style copy.

**Recommendation**: explicitly accept this as scope for beta (it is
documented as such in the placeholder copy) — but consider reordering the
left rail to put `Profile` and `Appearance` first (working) so a casual
demo navigator hits a working screen before a placeholder. Estimated 5 min.

### F-026 — No operator runbook for post-`make dev` ops
**SEV**: H. `docs/runbooks/` covers:
- `debugging-guide.md`
- `error-observability.md`
- `hotfix-procedures.md`
- `market-data-operations.md`
- `market-ingestion-operations.md`
- `partition-retention.md`
- `secrets-management.md`
- `sentry-alerts.md`
- `uptime-monitoring.md`

None of these answer the questions the operator hits in the first hour of
running the platform:
- "How do I restart a wedged Kafka consumer?" (`docker compose restart <svc>`
  is fine; the runbook should also mention `kafka-consumer-groups --reset-offsets`).
- "How do I clear the Valkey cache for a single user / tenant?"
- "How do I replay a topic from the beginning to re-process a corrected
  schema?" (relevant to F-006 — the operator has to do this for the
  source_name fix to take effect).
- "How do I tail logs for a single user's session across all 10 services?"
- "Why is my brief still saying 'cold-start' after 5 minutes?" (links to
  S6 + S7 + S8 health + KG narrative scheduler).

**Recommendation**: a single new `docs/runbooks/post-make-dev-operations.md`
covering the top 5 first-hour operator questions with copy-pastable
commands. Estimated 60 min. This pairs with F-024 (onboarding) — they share
the "first-time user assumes things will work" failure mode.

### F-027 — Multi-tenant documentation: see F-022 (already flagged)

---

## 11. R3 Re-Confirmation From Prior Audit

The prior `qa-standards-rules-review.md` (§SF-1) listed 6 doc files that
must be touched. I re-checked each path → none have been modified since
that audit:

| Doc | Mentions `source_name`? | Mentions `cooperative-sticky`? | Mentions `BriefArchiveWriteAdapter`? | Mentions migration 0038? | Mentions page-bundle fallback chain? |
|---|---|---|---|---|---|
| `docs/services/nlp-pipeline.md` | NO | NO | N/A | N/A | N/A |
| `docs/services/knowledge-graph.md` | NO | NO | N/A | N/A | N/A |
| `docs/libs/messaging.md` | N/A | NO | N/A | N/A | N/A |
| `docs/services/api-gateway.md` | N/A | N/A | N/A | N/A | NO (`page-bundle` is mentioned but not the fallback chain) |
| `docs/services/rag-chat.md` | N/A | N/A | NO | N/A | N/A |
| `docs/services/intelligence-migrations.md` | N/A | N/A | N/A | NO | N/A |

R3 gap is fully re-confirmed. **No new doc updates have happened** since
the prior audit. Recommended fix list: F-019 + F-020 + F-021 + F-022 (one
unified ~2 h sweep).

---

## 12. Findings Summary

| ID | SEV | Title | Estimated fix |
|---|---|---|---|
| F-001 | H | 13 pre-existing IG-LAYER-002 violations visible in `make qa` | 4–6 h refactor or 15 min allowlist |
| F-002 | – | Domain layer purity holds | – |
| F-003 | – | `BriefArchiveWriteAdapter` is a clean port impl (positive) | – |
| F-004 | – | ToolExecutor factory split preserved | – |
| F-005 | L | Mixed Protocol vs ABC port styles | 15 min STANDARDS.md note |
| F-006 | **B** | Schema Registry must be re-registered for source_name to flow at runtime | confirm `make dev-rebuild` ran |
| F-007 | – | Avro field-count drift detection (positive) | – |
| F-008 | – | PRD-0087 acceptance: 11/11 functional, 2 carry-forwards | – |
| F-009 | H | No ADR for cooperative-sticky platform default | 30 min |
| F-010 | H | Migration 0038 has no test (re-confirms prior audit) | 30 min |
| F-011 | M | `path_insight_seeder.py` bypasses pydantic-settings | 20 min |
| F-012 | – | Cross-service naming + error consistency: PASS | – |
| F-013 | – | Event envelope on enriched.v1: PASS | – |
| F-014 | – | UUIDv7 + UTC + structlog usage: PASS | – |
| F-015 | – | pydantic-settings: PASS (one exception → F-011) | – |
| F-016 | – | No secrets in code: PASS | – |
| F-017 | – | Init container ordering: PASS | – |
| F-018 | – | No compose changes this session | – |
| F-019 | H | `libs/messaging/.claude-context.md` does not exist | 30 min |
| F-020 | M | `intelligence-migrations/.claude-context.md` is stale | 15 min |
| F-021 | H | No `docs/services/*.md` updated this session (R3 gap) | 45 min |
| F-022 | H | `MASTER_PLAN.md` silent on multi-tenant story | 15 min |
| F-023 | – | (duplicate of F-009) | – |
| F-024 | M | No `docs/ONBOARDING.md` for non-developer reviewers | 60 min |
| F-025 | M | Settings UI sub-tabs are placeholders | 5 min reorder |
| F-026 | H | No operator runbook for post-`make dev` ops | 60 min |
| F-027 | – | (duplicate of F-022) | – |

**Beta-blocker count**: 1 (F-006 Schema Registry reload — likely already
addressed by `make dev-rebuild`; needs confirmation).
**High count**: 7 (F-001, F-009, F-010, F-019, F-021, F-022, F-026).
**Medium count**: 4 (F-011, F-020, F-024, F-025).
**Low count**: 1 (F-005).

---

## 13. Recommended Sequencing for Beta Gate

### Must (before next demo rehearsal) — total ≈ 4 h
1. **F-006**: confirm `make dev-rebuild` ran since `493dcb4e`; if not, do it
   and verify KG enriched_consumer log no longer says
   `evidence_source_metadata_missing` for new articles. **15 min**.
2. **F-009 + F-019**: write `0007-kafka-cooperative-sticky-default.md` ADR
   and create `libs/messaging/.claude-context.md`. **60 min**.
3. **F-021**: 6-doc R3 sweep (nlp-pipeline, knowledge-graph, messaging,
   api-gateway, rag-chat, intelligence-migrations). **45 min**.
4. **F-010**: migration 0038 test. **30 min**.
5. **F-022**: MASTER_PLAN multi-tenant paragraph. **15 min**.
6. **F-026**: post-make-dev operator runbook. **60 min**.
7. **F-020**: refresh intelligence-migrations context. **15 min**.

### Should (post-demo cleanup) — total ≈ 90 min
8. **F-001**: decide refactor vs allowlist for the 13 IG-LAYER-002
   violations and execute. **30–60 min** depending on path.
9. **F-011**: lift `_HUB_MIN_RELATIONS` into Settings. **20 min**.
10. **F-024**: ONBOARDING.md. **60 min** but post-beta acceptable.
11. **F-025**: settings tab reorder. **5 min**.

### Note (no fix needed)
12. **F-005**: STANDARDS.md note on Protocol vs ABC choice — let it accrue
    until the next standards revision.

---

## 14. Auditor's Summary

The 11 PLAN-0087 commits are architecturally sound at the **runtime** level:
ports are honoured, no domain → infrastructure leakage was introduced,
forward-compat held on the one Avro change, the new write adapter is the
cleanest port implementation in the session, the cooperative-sticky default
fix is well-reasoned (BP-442 captures the diagnostic chain), and the
8-defect bundle (97153b36) shipped without violating any hard rule.

The architectural-review weaknesses are all **above the code line**:
- One platform-default change (cooperative-sticky) shipped without an ADR.
- One shared library (`libs/messaging`) has no `.claude-context.md` despite
  every other lib having one — and this is the lib that just changed
  defaults for every consumer.
- Six service docs are stale on this session's contract changes (R3 gap,
  re-confirmed from prior audit).
- The multi-tenant story is in PRD-0075 + PLAN-0086 + an ADR but never
  surfaces in `MASTER_PLAN.md` — a thesis-director-level reader has no
  single page to learn it from.
- The settings UI works for theme + profile but is placeholder for the
  three tabs a beta evaluator is most likely to click (notifications,
  integrations, data).
- The runbooks cover production-grade operations but not the first-hour
  questions every reviewer hits after `make dev`.

The **single beta-blocker** is a runtime artefact, not a code defect:
F-006 (Schema Registry must be re-registered for the source_name flow to
take effect end-to-end). If `make dev-rebuild` has run since 2026-05-09
10:30 UTC, this is already resolved.

The **highest-leverage post-audit fix** is F-019 + F-009 (the missing
`libs/messaging/.claude-context.md` plus the cooperative-sticky ADR) —
together they close the loop that BP-442 opened, and they prevent the next
agent who hits a rebalance question from rediscovering the same diagnosis
the hard way.
