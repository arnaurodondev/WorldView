# RULES.md — Hard Rules for the Worldview Platform

> **Purpose**: Non-negotiable rules for all contributors (human and AI).
> Every rule has a short "why" — understanding the reason prevents circumvention.

---

## Testing Rules

### R1: MUST add or update tests for every behavior change
**Why**: Untested code is unknown code. The thesis demo cannot afford regressions.
Every new function, endpoint, consumer, or domain rule needs at least one unit test.
Integration tests are required for database operations and Kafka flows.

### R2: MUST run `scripts/lint.sh` and `scripts/test.sh` before committing
**Why**: Broken code must never reach `main`. Lint catches style drift and security
issues. Tests catch logic errors. Both are enforced in CI, but catching locally saves
time and CI minutes.

---

## Documentation Rules

### R3: MUST update docs when behavior or contracts change
**Why**: Stale docs are worse than no docs — they actively mislead. If you change an
API, event schema, or internal workflow, the corresponding doc in `docs/services/`,
`docs/libs/`, or `docs/MASTER_PLAN.md` must be updated in the same PR.

### R4: MUST write an ADR before adding a new service or major architectural change
**Why**: Architectural decisions are expensive to reverse. An ADR forces you to
articulate context, alternatives, and consequences. Use `docs/architecture/decisions/ADR_TEMPLATE.md`.

---

## Contract Rules

### R5: MUST version Avro schemas and ensure forward compatibility
**Why**: Kafka consumers deployed independently. If a producer changes its schema
without forward compatibility, all consumers break simultaneously. Rules:
- Add new fields with **default values** only
- Never remove or rename existing fields
- Bump `schema_version` in the event envelope
- Run `scripts/gen-contracts.sh` to validate compatibility before merging

### R28: MUST use Avro for all Kafka contracts (no JSON on the wire)
**Why**: Pure JSON on Kafka silently accepts schema drift — a renamed or removed
field is invisible until the consumer crashes in production. Avro on the wire
with a registered `.avsc` makes every contract change explicit, validated by
`scripts/gen-contracts.sh`, and enforced by the architecture test
`tests/architecture/test_kafka_avro_enforcement.py` (which fails the build for
any consumer using `json.loads` without a paired `deserialize_confluent_avro`
path). PLAN-0062 codified this after every JSON-only consumer on the platform
was migrated. Rules:
- Every topic has exactly one `.avsc` file in `infra/kafka/schemas/`,
  registered with the schema registry by `register-schemas.py` at startup
- Every topic has a canonical model in `libs/contracts` mirroring the schema
  field-for-field (entity-shaped → `canonical/<event>.py`; trigger-event-shaped
  → `events/<domain>/<event>.py`)
- Producers serialise via `messaging.kafka.serialization_utils.serialize_confluent_avro`
  (or `serialize_avro` for non-Confluent envelopes) — never `json.dumps(...).encode()`
- Consumers' `deserialize_value` calls `deserialize_confluent_avro` (or
  `deserialize_avro`); a JSON fallback is allowed only as a temporary migration
  aid and must log every fallback hit so the residual JSON traffic is measurable
- The architecture test is unconditional — no baseline / escape hatch

### R6: MUST version REST API paths for breaking changes
**Why**: Clients (frontend, other services) depend on stable API contracts.
Non-breaking additions (new endpoints, new optional fields) are fine. Breaking changes
(renamed fields, changed semantics, removed endpoints) require a new version path
(`/api/v2/...`) and a deprecation period.

---

## Architecture Rules

### R7: MUST NOT access another service's database directly
**Why**: Database ownership is the foundation of microservice independence. If
service A queries service B's database, they are coupled at the schema level — any
migration in B can break A. Communicate via:
- **Kafka events** for async state propagation
- **REST API calls** for synchronous queries

### R8: MUST NOT perform dual writes (DB + Kafka in separate transactions)
**Why**: If the DB write succeeds but Kafka publish fails (or vice versa), the system
is in an inconsistent state. Use the **transactional outbox pattern** from
`libs/messaging`: write the event to the `outbox_events` table in the same DB
transaction, then let the dispatcher publish it to Kafka.

### R9: MUST make Kafka consumers idempotent
**Why**: Kafka guarantees at-least-once delivery. Consumers will see duplicate events
during rebalances, retries, or network hiccups. Every consumer must:
- Inherit `ValkeyDedupMixin` from `libs/messaging.kafka.consumer.dedup` and set `_dedup_prefix` (unique per consumer class) and optionally `_dedup_ttl_seconds` (default 86 400 s) — this satisfies the `is_duplicate` / `mark_processed` contract with at-least-once fallback when Valkey is unavailable
- Use upsert (INSERT ON CONFLICT) for materializations so that Valkey fallback mode is safe
- Be safe to re-run on the same event (deterministic IDs or `INSERT … ON CONFLICT DO NOTHING`)

**Architecture test**: `tests/architecture/test_consumer_dedup_mixin_enforcement.py` (CONSUMER-DEDUP-001) enforces this rule automatically. Consumers that bypass `ValkeyDedupMixin` and instead rely solely on natural-key `INSERT … ON CONFLICT` idempotency must document this guarantee in a docstring near the class definition **and** be explicitly added to `tests/architecture/_consumer_dedup_allowlist.yaml` with an ADR justification. The allowlist has 14 grandfathered entries (legacy hand-rolled consumers, allowlisted in PLAN-0084 B-2); new entries beyond these require explicit architecture approval with justification. Hand-rolled `is_duplicate(…) → return False` stubs are forbidden and will be caught by the architecture test. See BP-415 for the failure pattern.

### R10: MUST use UUIDv7 for all entity IDs
**Why**: UUIDv7 is time-sortable (natural ordering in indexes), globally unique
(no coordination needed), and embeds a timestamp (useful for debugging). Never use
auto-increment integers (leak information, can't merge across services) or UUIDv4
(random, poor index locality).

### R11: MUST enforce UTC-only timestamps
**Why**: Timezone bugs are subtle and devastating in financial data. All timestamps
in the system are UTC timezone-aware (`datetime` with `tzinfo=timezone.utc`). Naive
datetimes raise `ValueError` via `libs/common` helpers. Database columns use
`TIMESTAMPTZ`. JSON serialization uses ISO-8601 with `Z` suffix.

### R12: MUST use claim-check pattern for large Kafka payloads
**Why**: Kafka is optimized for small messages (~1KB). Sending multi-MB payloads
(OHLCV datasets, full articles) through Kafka increases broker memory pressure,
consumer lag, and rebalance times. Store the payload in MinIO, send a pointer event
with `(bucket, key, content_type, etag)`.

---

## Security Rules

### R13: MUST NOT embed secrets in code or config files
**Why**: Secrets in code end up in Git history, CI logs, and error traces. Use:
- Environment variables loaded via `pydantic-settings`
- `configs/dev.local.env.example` as a template (never the actual `.env`)
- GitHub Actions secrets for CI

### R14: MUST sanitize logs — never log secrets, API keys, tokens, or PII
**Why**: Logs are stored, indexed, and often accessible to broad teams. A leaked API
key in a log line can be exploited. Use the log sanitization pattern from
`libs/observability` to strip `sk-*`, `Bearer *`, `api_key=*` patterns.

### R15: MUST validate and sanitize all external input
**Why**: The Content Service fetches from untrusted RSS feeds and web pages. The
RAG service processes user queries. Without validation:
- SSRF: a crafted URL could hit internal services
- Injection: malicious input could manipulate LLM prompts or SQL
- XSS: unsanitized HTML could execute in the frontend
Use Pydantic models for request validation, domain allowlists for URLs, and input
length limits for all user-facing text fields.

---

## Process Rules

### R16: MUST NOT add a new microservice without an ADR
**Why**: Each microservice adds operational overhead (deployment, monitoring, testing,
inter-service communication). The decision to split or merge services must be
deliberate and documented.

### R17: CI MUST pass before merge to main
**Why**: `main` is the deployable branch. A broken `main` blocks everyone. CI runs:
lint, type-check, unit tests, contract tests, and Avro schema compatibility checks.
No exceptions.

### R18: MUST follow the branching convention
**Why**: Consistent branch naming enables CI automation and makes the Git log readable.
- Feature branches: `feat/<short-description>`
- Bug fixes: `fix/<short-description>`
- Docs: `docs/<short-description>`
- Refactors: `refactor/<short-description>`

### R19: MUST NOT delete or skip tests to make the test suite pass
**Why**: Tests are evidence of intended behavior. A failing test — even a pre-existing
one unrelated to your current change — signals a real problem in the codebase. The
correct response to a test failure is always to fix the underlying issue:
1. **Assume the implementation is wrong** until proven otherwise.
2. If investigation confirms the test itself is wrong (testing outdated behavior, incorrect
   assertion), fix the test to reflect the correct expected behavior — document why.
3. Never use `pytest.mark.skip`, `@pytest.mark.xfail`, or test deletion as a workaround
   for a failing test. If a test cannot be fixed immediately, escalate to the user.
4. Pre-existing test failures encountered during unrelated work must still be fixed or
   explicitly reported — they are not someone else's problem.

### R20: MUST extend `BaseKafkaConsumer` for all Kafka consumers
**Why**: `BaseKafkaConsumer` enforces idempotency (`is_duplicate` check), DLQ routing,
retry/fatal error classification, and observability hooks. Rolling a custom consumer
loop bypasses all these safety nets and creates inconsistent behaviour across services.
Every class that consumes from a Kafka topic must extend
`messaging.kafka.consumer.base.BaseKafkaConsumer` and implement its abstract methods.
Enforced by `tests/architecture/test_consumer_enforcement.py`.

### R25: API layer MUST NOT import from the infrastructure layer
**Why**: Direct infrastructure imports in API routers couple the HTTP layer to specific
database drivers, ORM sessions, and repository implementations. This makes the API
untestable in isolation (requires real DB), prevents adapter substitution, and violates
hexagonal architecture. The correct call chain is:
`API router → Use Case (application layer) → Repository port (application layer) ← Infrastructure implementation`
Every read and write operation in an API router must go through a use case class. Use cases
receive an already-entered UoW from dependency injection and call repository methods directly.
Enforced by import guard rule `IG-LAYER-002` in `scripts/import_guards/rules.yaml`.
Exceptions (e.g. infrastructure cache objects that store API schema types) must be documented
in `scripts/import_guards/allowlist.yaml` with justification.

### R21: Domain exception base class MUST be named `DomainError`
**Why**: Architecture tests (`test_domain_error_enforcement.py`) assert that every
mature service defines a `DomainError(Exception)` class in `domain/errors.py` (or
`domain/exceptions.py`) and that all other exception classes in that module inherit
from it. A single canonical name enables cross-service tooling and log parsing without
service-specific knowledge. Services that want a descriptive alias (e.g.
`MarketDataError`) must define it as a subclass: `class MarketDataError(DomainError):`.

---

## Infrastructure Rules

### R26: UoW `__aexit__` MUST NOT commit — all commits must be explicit
**Why**: Auto-commit in `__aexit__` means silent writes on any code path that exits the
context manager without an explicit `commit()` call. It also makes double-commit bugs
undetectable (SQLAlchemy silently ignores the second commit on most drivers). This was
a live bug in market-ingestion `SqlaUnitOfWork` (F-DS-004) that committed empty
transactions on every read-only call. **Option B standard**: `__aexit__` MUST only roll
back on exception and close the session in `finally`. Every mutating use case MUST call
`await uow.commit()` explicitly before returning.
**Enforcement**: REVIEW_CHECKLIST §UoW. Any concrete `UnitOfWork.__aexit__` that calls
`commit()` in an `else` or unconditional branch is a BLOCKING review violation. See
STANDARDS.md §17 for the canonical implementation.

### R22: MUST run each concern as an independent process
**Why**: Embedding scheduler loops, worker loops, or outbox dispatchers inside the API
process creates coupling that prevents independent scaling and complicates signal handling.
Each concern (API, Scheduler, Worker, Dispatcher) MUST have its own entry point
(`python -m <service>.infrastructure.<component>.<module>`), its own signal handlers
(SIGINT/SIGTERM), and its own connection pool sizing. The API process MUST NOT start
background loops in its lifespan. Docker Compose uses the same image with different
`command` overrides. See STANDARDS.md §14 for implementation patterns.

### R23: MUST support dual database URLs (read/write split)
**Why**: Read-heavy workloads (dashboards, analytics, health checks) can be offloaded to
a read replica, reducing contention on the primary. Every service MUST accept two database
URLs: `DATABASE_URL` (write, required) and `DATABASE_URL_READ` (read, optional). When
the read URL is not configured, the read factory MUST fall back to the write URL (zero-cost
compatibility). Read-after-write operations and row-locking queries (`SELECT FOR UPDATE`)
MUST use the write session. Session factories MUST set `expire_on_commit=False` and
`pool_pre_ping=True`. See STANDARDS.md §15 for routing rules.

### R24: MUST NOT hold database sessions across external I/O
**Why**: Holding a database session (and its underlying connection) during HTTP requests,
MinIO operations, or Kafka publishes wastes pool resources and causes pool exhaustion under
load. Background processes (workers, schedulers, dispatchers) MUST split operations into
read → release → I/O → acquire → write phases. API routes using FastAPI `Depends()`
session-per-request are exempt because they are short-lived. Each process type MUST
configure pool sizes appropriate to its concurrency profile. See STANDARDS.md §16 for
patterns and pool size recommendations.

### R27: Read-only use cases MUST depend on `ReadOnlyUnitOfWork`
**Why**: Use cases that only query data (no mutations) MUST declare their dependency as
`ReadOnlyUnitOfWork` (not `UnitOfWork`). This ensures they use the read replica session
(R23 read/write split), preventing accidental writes and distributing read load away from
the primary. The `ReadOnlyUnitOfWork` has no `commit()` or `rollback()` methods — mypy
will catch any misuse at type-check time. API route handlers MUST use `ReadUoWDep` for
read-only endpoints and `UoWDep` for mutating endpoints.

### R29: MUST update `libs/tools/capability_manifest.yaml` for every tool change
**Why**: The capability manifest is the contract between the LLM and the tool layer.
When a tool is added, removed, or its parameters change, the LLM's system prompt must
reflect the current state — an out-of-sync manifest causes silent capability failures
where the LLM calls tools that no longer exist or passes invalid parameters (producing
a malformed tool response with no error surfaced to the user). Enforcement:
- Adding a new tool → add a YAML entry with `name`, `description`, `parameters`,
  `since` (manifest version), and at least 2 `example_queries` before the PR is merged.
  **Note**: as of PLAN-0079, per-tool `trust_weight` is no longer set on manifest
  entries — `TrustScorer` computes trust per-item at retrieval time from
  `SOURCE_AUTHORITY` × recency_decay × corroboration × extraction_confidence. The
  manifest references `source_type` so `TrustScorer` can look up authority.
- Changing a tool's parameters → update the YAML entry in the same commit
- Removing a tool → set `deprecated_at: <version>` on the YAML entry (do NOT delete —
  prior thread histories may reference it for replay/explanation); remove the handler
  from the executor in a follow-up release after deprecation window
Enforced by `tests/architecture/test_tool_manifest_sync.py` (checks that every function
registered in `ToolRegistry` has a corresponding YAML entry with a matching parameter
schema, and every YAML entry has a registered implementation OR is `deprecated_at`-set).

### R30: Per-request auth/scope context MUST NOT live in singleton `__init__`
**Why**: Per-request fields (`user_id`, `tenant_id`, `internal_jwt`, `entity_context`,
or any field that varies per HTTP request) can never be passed through a long-lived
singleton's constructor — they will be `None` (or stale) for every request after the
first. The result is silent: cross-tenant data leak risks, auth strips, scope
enforcement bypasses (M-1 entity-context bypass), and feature short-circuits that
return empty results without an error. Pattern: split into `<Class>Factory` (singleton,
holds shared collaborators) + `<Class>` (per-request, holds auth/scope). The factory
exposes `for_request(*, user_id, tenant_id, internal_jwt, entity_context, ...) -> Class`
and the route handler calls it once at the top of every request. Per-LLM-call (or
per-RPC-call) signatures stay clean — auth is bound at executor construction.
**Detection**: any `__init__` that takes `Optional[user_id|tenant_id|jwt]` is suspect;
either the class is stateless and shouldn't carry it, or the class is request-scoped
and needs a factory. See BP-406 for the canonical example (PLAN-0067 `ToolExecutor`).

---

## Operational Rules

### R31: MUST rebuild and verify containers after runtime fixes
**Why**: The running Docker container contains the image that was built at last `docker compose
build` time. Editing source files does NOT update the running container. Declaring a fix "done"
without rebuilding and verifying means the live system still has the old (broken) code, creating
a false sense of completion that is only discovered during the next session or demo.
After any fix that affects runtime behaviour (Python code, config, entrypoints):
1. `docker compose build <svc>` — rebuild the affected service image
2. `docker compose up -d <svc>` — replace the running container with the new image
3. `docker compose exec <svc> python -c "import <module>; ..."` or inspect logs to confirm
   the new code is present (e.g., check a new log line or function signature)
4. Only then declare the fix live in any session report or commit message
Applies equally to worker containers, scheduler containers, and consumer containers.

### R32: MUST check for the highest existing ID before assigning new IDs
**Why**: Assigning a rule number (R##), plan number (PLAN-XXXX), or worker/spec ID without
checking existing IDs causes collisions. Collisions force mid-edit renumbering that propagates
across plan files, TRACKING.md, BUG_PATTERNS.md, and commit messages — multiplying the cost
of a 30-second oversight into 30+ minutes of cleanup. The R18/R28 collision in this repository
(branching rule vs Avro rule, both originally assigned R18) is a documented example.
Before assigning any new ID:
- R##: `grep -n "^### R" RULES.md | sort -t'R' -k2 -n | tail -3` to find the current maximum
- PLAN-XXXX: check `docs/plans/TRACKING.md` for the highest plan row
- Worker IDs / spec IDs: check the relevant plan file section before adding a new worker
Pick `max + 1`. Never re-use or guess.

### R33: MUST run the full relevant test suite after every fix
**Why**: Targeted "touched-file only" testing misses cross-file regressions. When a fix
changes a mock, a shared fixture, a side_effect list, a global constant, or a serialisation
format, tests in unrelated files can break. These break silently when only the edited file's
tests are run, and surface only during the next full test run — typically at an inconvenient
moment (demo, CI, QA pass). Classification discipline:
1. Run the full suite for the affected service (`python -m pytest tests/ -v` from the service root)
2. Classify every new failure as one of:
   - **(a) Pre-existing** — was already failing before this session (document and skip if unrelated)
   - **(b) Fix-induced regression** — the fix broke something that was passing (FIX IMMEDIATELY)
   - **(c) Stale test expectation** — test was testing outdated behaviour that the fix correctly changes (update the test)
3. Resolve all (b) and (c) failures before reporting completion
4. Never report "all tests pass" without having run the full suite

### R34: Subagents MUST commit before returning; orchestrator MUST run full suite after all return
**Why**: Parallel subagents (fix agents, wave agents, QA agents) work in isolation. If a
subagent stalls, is interrupted, or its worktree is discarded, any uncommitted work is
permanently lost. Additionally, parallel subagents can introduce cross-agent regressions
(Agent A changes a shared fixture; Agent B adds a test depending on the old fixture;
each passes in isolation but the combined state fails).
Rules:
1. Every subagent MUST create a git commit (or at minimum stage all changes) before returning
   control to the orchestrator — not just "apply files"
2. If a subagent returns without committing, the orchestrator must immediately reapply the
   subagent's work directly from the reported diff before proceeding
3. After all parallel subagents return, the orchestrator MUST run the full test suite across
   all affected services to catch cross-agent regressions
4. Cross-agent regressions are the orchestrator's responsibility — never the subagent's
5. Worktree isolation is a convenience, not a safety net; commits are the only reliable
   persistence mechanism

---

## Summary Table

| Rule | Category | Severity |
|------|----------|----------|
| R1 | Testing | MUST |
| R2 | Testing | MUST |
| R3 | Documentation | MUST |
| R4 | Documentation | MUST |
| R5 | Contracts | MUST |
| R6 | Contracts | MUST |
| R7 | Architecture | MUST NOT |
| R8 | Architecture | MUST NOT |
| R9 | Architecture | MUST |
| R10 | Architecture | MUST |
| R11 | Architecture | MUST |
| R12 | Architecture | MUST |
| R13 | Security | MUST NOT |
| R14 | Security | MUST |
| R15 | Security | MUST |
| R16 | Process | MUST NOT |
| R17 | Process | MUST |
| R18 | Process | MUST |
| R19 | Testing | MUST NOT |
| R20 | Architecture | MUST |
| R21 | Architecture | MUST |
| R22 | Infrastructure | MUST |
| R23 | Infrastructure | MUST |
| R24 | Infrastructure | MUST NOT |
| R25 | Architecture | MUST NOT |
| R26 | Infrastructure | MUST NOT |
| R27 | Architecture | MUST |
| R28 | Contracts | MUST |
| R29 | Architecture | MUST |
| R30 | Architecture | MUST NOT |
| R31 | Operational | MUST |
| R32 | Operational | MUST |
| R33 | Operational | MUST |
| R34 | Operational | MUST |
