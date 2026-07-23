# Review Checklist

> Point-by-point checklist for code review. All sections must PASS or N/A for approval.
> A FAIL in sections 1-6 blocks approval.

## 1. Resource Management

- [ ] Resources acquired in try blocks have matching finally/cleanup
- [ ] Temporary files/objects are cleaned up on all paths (success AND failure)
- [ ] Partial failure doesn't leave orphaned resources (DB connections, file handles)
- [ ] Async context managers properly used for DB sessions
- [ ] Advisory/distributed locks do not span external I/O (fetch outside lock, write inside)
- [ ] Lock duration is bounded and predictable (milliseconds, not seconds)
- [ ] **GLiNER (or any native-process ML) inference-loop change** (batching, thread count, sequence length): confirm the per-forward-pass activation budget still bounds peak RSS and that no new long-lived per-thread allocation pattern reintroduces glibc-arena fragmentation OOM (distinct mechanism from Postgres pooling OOM — process RSS growth, not DB planner/pooling)

## 2. Exception Handling

- [ ] No bare `except:` or `except Exception:` without re-raise
- [ ] Errors classified: `RetryableError` vs `FatalError` (per libs/messaging)
- [ ] `except` blocks don't swallow errors silently (at minimum, log them)
- [ ] `finally` blocks don't mask original exceptions with new ones
- [ ] Async callbacks have proper error handling (not fire-and-forget)
- [ ] **Standalone daemon-loop workers (own `while True`, not APScheduler, not `BaseKafkaConsumer`)**: the loop body — including any call that opens a fresh DB/broker session — is wrapped in try/except with capped exponential backoff; only `asyncio.CancelledError` propagates for shutdown. APScheduler jobs get crash isolation for free; bespoke loops (e.g. `path_insight_worker.py`) don't unless explicitly added.

## 3. Storage Atomicity

- [ ] Multi-step writes use staging→final pattern (or single transaction)
- [ ] DB + Kafka dual writes use outbox pattern (never separate transactions)
- [ ] Failure during multi-step operations has cleanup or is idempotent
- [ ] MinIO writes use claim-check pattern for Kafka events
- [ ] Outbox payload field names match Avro schema exactly
- [ ] MinIO write before DB commit: compensating delete implemented on rollback (§4.4)
- [ ] Compensating GC failures logged as WARNING, original exception preserved and re-raised

## 4. Idempotency

- [ ] Kafka consumers handle duplicate events (event_id dedup or upsert)
- [ ] Processing is safe to retry (no double-counting, no duplicate notifications)
- [ ] Idempotency key checked before side effects
- [ ] Database operations use upsert or check-before-insert
- [ ] Outbox payload includes all required Avro envelope fields (event_id, event_type, schema_version, occurred_at)
- [ ] **Atomic dedup**: `is_duplicate` + `process_message` + `mark_processed` are NOT in separate transactions — use BP-035/BP-045 `INSERT…ON CONFLICT DO NOTHING RETURNING` inside the same UoW as business logic; `is_duplicate()` → `return False`; `mark_processed()` → no-op (HR-021)
- [ ] **All storage steps have skip-if-exists (D-008)**: if `_store_bronze` has an `exists()` guard, `_store_canonical` and any other storage steps must have the same guard — partial guards break retry idempotency (BP-048)
- [ ] **Use case wired in `app.py` lifespan**: if a new use case updates a Prometheus metric, launches a cron, or returns a computed value, grep for at least one caller in `app.py` / `lifespan` / `_wire_*`; a use case with no caller is silently dead (BP-412)
- [ ] **Cache has a refresh loop**: if a new class has a `refresh()` method or a startup-populated cache, search for either a `_refresh_loop()` background task or a Kafka invalidation consumer; startup-only population goes stale after first fill (BP-414)
- [ ] **ValkeyDedupMixin — no hand-rolled is_duplicate/mark_processed**: if a `BaseKafkaConsumer` subclass overrides `is_duplicate` or `mark_processed` with direct Valkey calls, verify try/except wrapping on every Valkey call; better: migrate to `ValkeyDedupMixin` (BP-421, HR-050)
- [ ] **Valkey cache swap uses Lua not MULTI/EXEC**: if code uses `pipeline(transaction=True)` with `pipe.delete(key)` + `pipe.sadd(key, ...)` on the same key, require a Lua script for true server-side atomicity — MULTI/EXEC can wipe the key on network drop (BP-422, HR-051)
- [ ] **Retry loop uses exponential backoff**: any `while True` loop with `except Exception: await asyncio.sleep(CONSTANT)` must be replaced with `min(2**failures × base, ceiling)` backoff + Prometheus counter; fixed-interval loops cause log spam on sustained outages (BP-423, HR-052)
- [ ] **ON CONFLICT assertions check compiled SQL**: test assertions for `INSERT … ON CONFLICT DO NOTHING` must check compiled SQL text for `"ON CONFLICT"` and `"DO NOTHING"` strings, not the private `_post_values_clause` attribute (QA-007, STANDARDS.md §20.7)
- [ ] **Prometheus tests use isolated_registry fixture**: any test that asserts on Prometheus gauge/counter values must use an `isolated_registry` fixture, not the global `REGISTRY` singleton (BP-425, STANDARDS.md §20.6)
- [ ] **New Kafka consumer writing to a shared table: does the Avro schema carry tenant_id?** — If the event schema has no `tenant_id` field, the consumer cannot populate it in the destination table; the data becomes globally scoped and leaks across tenants. All user-attributable events must carry `{"name": "tenant_id", "type": ["null", "string"], "default": null}`. Market data / instrument discovery events are excluded (global reference data). (HR-054)
- [ ] **Vector/HNSW search query: is it filtered by tenant_id?** — Any `cosine_distance`, `l2_distance`, or `max_inner_product` query against a table that has a `tenant_id` column MUST include `WHERE tenant_id = :tid OR tenant_id IS NULL`. Missing this filter causes cross-tenant data leaks via semantic similarity. (HR-053)
- [ ] **Change to `BaseKafkaConsumer` self-heal/connectivity-probe path (`_connectivity_probe_loop`, `_evaluate_lag_stall`, `_force_process_exit`, pause/resume state)**: test matrix covers the cross-product of all known halt reasons (backpressure pause, barrier pause, downstream-outage halt, true fence) — not just the new gate in isolation (messaging-selfheal cluster)
- [ ] **New sibling tracking collection added as a variant of an existing one** (e.g. `_barrier_paused_partitions` alongside `_paused_partitions`): grep every early-return guard, resume/cleanup path, and exclusion check referencing the ORIGINAL collection and confirm each was updated to also consider the new one — a guard written before the sibling existed silently ignores it forever

## 4b. Unit of Work / Transaction Integrity (R26)

- [ ] UoW `__aexit__`: no `else: await self.commit()` — only rolls back on exception (R26, HR-025)
- [ ] Every mutating use case calls `await uow.commit()` explicitly before returning (not relying on `__aexit__`)
- [ ] Rollback is wrapped in try/except; session close is in the `finally` block (prevents session leak when rollback raises)
- [ ] Post-commit hooks run INSIDE `commit()` via `_drain_post_commit_hooks()` — NOT in `__aexit__()` (see STANDARDS.md §17.3)
- [ ] Post-commit hook failures are caught and logged — never propagated (a cache-flush failure must not dead-letter a successfully-committed message)
- [ ] Dual-session consumers: does each session's commit failure trigger a re-raise (nack) or is it swallowed? Swallowed failures + early-skip = permanent data loss (BP-419, HR-048)
- [ ] After-commit Kafka produce: is it inside an outbox transaction or fire-and-forget? For one-time lifecycle events (entity promotion, entity deletion, first-established relation), outbox is required (BP-418, HR-049)
- [ ] No nested `async with session_factory()` inside a method called within an already-open session — creates two independent transactions (BP-417)

## 5. Data Integrity

- [ ] UUIDv7 for all new entity IDs (`common.ids.new_uuid7()`)
- [ ] UTC-only timestamps (`common.time.utc_now()`, no naive datetimes)
- [ ] Foreign key integrity maintained (or documented as logical-only)
- [ ] Enum values validated at system boundaries
- [ ] Null handling explicit (no implicit None propagation)

## 6. Security

- [ ] Input validated at all API boundaries (Pydantic models)
- [ ] No SQL injection (parameterized queries or ORM only)
- [ ] No hardcoded secrets, tokens, or API keys
- [ ] No PII or secrets in log output
- [ ] Multi-tenant isolation: all queries filter by tenant_id
- [ ] Error messages don't leak internal details to clients — **`/readyz` and `/healthz` endpoints return opaque `"error"` strings in HTTP body, never raw exception messages** (BP-047, HR-023)
- [ ] Token comparisons use `hmac.compare_digest()` (not `==`)
- [ ] Query pagination has upper bound (max limit parameter)
- [ ] **External-API pagination loop does not treat "page shorter than requested limit" as end-of-data** unless the provider contract guarantees it — some providers (e.g. Polymarket) silently cap page size below the requested limit, which a naive short-page check misreads as pagination end and truncates results (content-ingestion-pagination cluster)
- [ ] URL inputs validate scheme and reject private IP ranges (SSRF prevention)
- [ ] **JWT decode passes `issuer=` parameter** — `jwt.decode(token, key, algorithms=["RS256"], issuer=expected_issuer)` — missing issuer= enables issuer-spoofing auth bypass (BP-145, HR-026)
- [ ] **One-time-use Valkey state (PKCE codes, nonces) uses atomic `GETDEL`**, not `GET` then `DEL` — two-command pipeline creates replay window (BP-146, HR-027)
- [ ] **Middleware reads `app.state` inside `dispatch()`, not at `__init__` time** — constructors run before lifespan, capturing `None` permanently disables features (BP-144, HR-028)
- [ ] **Repository `save()` methods do NOT call `session.rollback()`** — repo-level rollback poisons the shared session; only the use-case `async with session_factory()` context owns rollback (BP-141, HR-029)
- [ ] **`InternalJWTMiddleware` is mounted on all services that accept internal requests** — adding a new service without it bypasses auth entirely (PLAN-0025 pattern)
- [ ] JWT/token values NOT passed as CLI arguments or environment variable substitutions in shell command strings (`--header "X-JWT: ${TOKEN}"`) — process-list visible; use httpx in Python or curl `--config` file instead (BP-419, HR-048 context, S-012)
- [ ] CB `record_failure()`: does it distinguish 4xx (client error) from 5xx/network (service fault)? Counting 4xx inflates CB failure count causing false-positive circuit opens (S-003)

## 6b. Schema & Data Pipeline Integrity

- [ ] Migration DDL matches ORM columns exactly — names, types, defaults, nullability (BP-008, BP-019)
- [ ] `move_to_dead_letter` INSERTs a DLQ row with original payload (not just status update) (BP-020)
- [ ] DLQ `requeue()` preserves original `aggregate_id`, `aggregate_type`, `event_type` from stored DLQ columns — never hardcode or use outbox PK as `aggregate_id` (BP-024)
- [ ] DNS resolution in async context uses `asyncio.to_thread(socket.getaddrinfo, ...)` with explicit timeout — never blocking `socket.getaddrinfo` directly on event loop (BP-025)
- [ ] SSRF IP check uses `addr.is_private or addr.is_reserved or addr.is_loopback or addr.is_multicast` — covers IPv4-mapped IPv6 (`::ffff:`) after extracting `addr.ipv4_mapped` (BP-026)
- [ ] Avro contract tests exist for every schema a service produces
- [ ] `doc_id` in outbox payloads is a per-document UUIDv7 (not source/aggregate ID)
- [ ] SSRF URL validation resolves DNS hostnames, not just IP literals
- [ ] LSH/cache writes happen AFTER DB commit, not before (prevents phantom entries on rollback)
- [ ] **Cache invalidation uses `schedule_post_commit(cache.invalidate(id))`**, never `await cache.invalidate(id)` inside `process_message()` — invalidating before commit enables stale-read-into-cache races (BP-046, HR-022, M-005)
- [ ] **Avro record names are valid Java identifiers (PascalCase)** — no dots, no version suffixes in `"name"` field; dots belong in `"namespace"` only (BP-051)
- [ ] **Avro namespace uses canonical format `com.worldview.<service>.events`** — all schemas in a service share the same namespace; inconsistent namespaces create divergent Schema Registry subjects (BP-052)
- [ ] **`schema_version` base class default is `1`, not `0`** — default 0 means subclasses that forget to override emit version-0 events silently (BP-053)
- [ ] **`asyncio.Event.set()` in confluent-kafka delivery callbacks uses `loop.call_soon_threadsafe(event.set)`** — direct `event.set()` from librdkafka C thread is not thread-safe (BP-050, HR-024)
- [ ] **Repositories with read/write session splitting: `get_or_create` reads back via write session after INSERT** — never call `self.get()` (read session) immediately after INSERT on write session (BP-049)
- [ ] **Kafka `producer.produce(...)` calls pass `key=` for any topic with per-entity ordering semantics** — without `key=`, sticky/round-robin partitioning means two events for the same `entity_id` can land on different partitions and be reordered downstream (F-DATA-06, PLAN-0057 deferred). Acceptable today only because all consumers use ON CONFLICT idempotency; fails the moment a destructive event ships.
- [ ] **LLM prompts that interpolate untrusted text use explicit delimiters AND validate output charset/length** — `f"... {description} ..."` without `<<<DELIMITER>>>...<<<END>>>` wrappers + an output denylist permits prompt-injection attacks where a poisoned `description` makes the LLM emit attacker-chosen aliases/claims that downstream code persists (F-SEC-02, PLAN-0057 deferred).
- [ ] **Query against a table with a PARTIAL index** (search migrations for `CREATE INDEX ... WHERE`) that filters on the indexed predicate column: confirm the predicate value is either a literal (allow-listed if user-influenced) or accompanied by an EXPLAIN-verified Index Scan regression test — a bound parameter on that column will NOT match the partial index and silently falls back to Seq Scan / exact-sort, risking `work_mem` OOM (BP-717/BP-730)
- [ ] **Change to a service's `infrastructure/db/session.py` connect_args** (statement_timeout, command_timeout, prepared-statement caching, pool sizing): check whether the SAME setting needs propagating to the other services with their own hand-rolled `session.py` (no shared session-factory exists yet) — list them and confirm parity or file a follow-up
- [ ] **Avro schema field appended (even nullable/backward-compatible) for a topic already in production**: verify EVERY consumer group reading that topic has resilient handling for `EOFError`/`struct.error`/malformed-record errors on old-schema backlog records, not just the consumer being actively modified
- [ ] **New prompt directive added or version bumped in a versioned prompt file** (e.g. `libs/prompts/src/prompts/chat/tool_use.py`): validated via a live A/B run against the existing regression question set — including at least one question shape UNRELATED to the one motivating the change — not just unit tests of the prompt string; broad imperative directives have previously regressed unrelated tool-selection paths one commit later (rag-chat-grounding cluster)
- [ ] **New APScheduler (or similar) sweep worker that calls an LLM or other paid/rate-limited API per-row on a recurring interval**: confirm it tracks a durable per-row attempt counter, excludes at-cap rows from future sweeps, and does NOT count transient provider errors against the cap — don't reinvent a bespoke mechanism per worker (kg-entity-worker-quality cluster)

## 7. Architecture Compliance

- [ ] Domain layer has zero infrastructure imports
- [ ] Application layer depends only on domain + ports (no direct DB/Kafka)
- [ ] Application layer has `application/ports/` directory with port ABCs (R20, DOMAIN-PORTS)
- [ ] Infrastructure layer implements port interfaces
- [ ] No cross-service DB access (use Kafka events or REST)
- [ ] Uses shared libs correctly (`common`, `contracts`, `messaging`, `storage`, `observability`, `ml-clients`)
- [ ] No direct imports of underlying packages (no `aiokafka`, `redis.asyncio`, `Minio`, `logging.getLogger`)
- [ ] Import guards pass: `python3 scripts/import_guards/check_import_guards.py --strict --baseline scripts/import_guards/baseline.json`
- [ ] `setattr` uses field allowlist, never user-controlled keys directly
- [ ] All Kafka consumers extend `BaseKafkaConsumer` — no direct `confluent_kafka.Consumer` (R20)
- [ ] All `market-ingestion` provider adapters extend `BaseProviderAdapter` (not `ProviderAdapter` directly) — ensures `_record_api_call()` is available and generic metrics are emitted (STANDARDS §18)
- [ ] `domain/errors.py` defines `DomainError(Exception)` — all other exceptions inherit from it (R21)
- [ ] Service-specific error alias defined as subclass, not assignment (e.g., `class MyServiceError(DomainError):`)
- [ ] **New/modified paginated external-API client within a provider family** (e.g. `polymarket*` adapters): check the other clients/adapters for the SAME provider family for pagination invariants already fixed there (`git log --grep=pagination -- <adapter-dir>`) — a fix applied to one client in a family must be ported or verified against its siblings, not left to be independently rediscovered (content-ingestion-pagination cluster)

## 7b. Docker Compose Completeness

- [ ] New consumer, worker, scheduler, or dispatcher entry points have corresponding entries in `infra/compose/docker-compose.yml` (profiles: `[infra, all]`) and `infra/compose/docker-compose.test.yml`
- [ ] New services have a Dockerfile, `configs/docker.env`, correct `build.context: ../..`, and healthcheck
- [ ] Build context is `../..` (repo root) — never the service directory alone (Dockerfiles COPY from `libs/`)
- [ ] When editing `docker-compose.prod.yml`: port overrides use `!override []` (not additive merge) — `ports:` without `!override` in an overlay file ADDS ports rather than replacing them, leaving infra ports exposed in production
- [ ] New public-facing services in production have Traefik labels (`traefik.enable=true`, router rule, TLS cert resolver, service port) and are added to the `traefik` network
- [ ] New services with `prod.env.example` added to `services/<name>/configs/` so worldview-gitops can provide prod values

## 7c. Observability Correctness

- [ ] **Prometheus metrics use the global registry**: any helper that accepts `registry=None` must default to `REGISTRY` (from `prometheus_client`), NOT `CollectorRegistry()` — `generate_latest()` reads the global registry only (BP-173, HR-040)
- [ ] **Every defined Prometheus metric has at least one call site**: grep for each new metric variable name; if `.inc()`/`.set()`/`.observe()` is not called anywhere in the service, delete the definition (BP-174, HR-041)
- [ ] **Prometheus scrape targets in `infra/prometheus/prometheus.yml` use the container-internal port** (right side of `host:container` port mapping), never the host-mapped port (BP-175)
- [ ] **New services added to `prometheus.yml`**: target uses the internal port from the service's `CMD` or `uvicorn --port` argument; verify with `docker compose exec prometheus wget -qO- http://<service>:<port>/metrics`
- [ ] **Alertmanager has at least one receiver with a working notification channel** — an empty `receivers:` list or a receiver with no `email_configs`/`slack_configs`/`webhook_configs` is a silent black hole; all alerts will be discarded (BP-176)
- [ ] **Template variables in Grafana dashboards are referenced in at least one panel query** — a variable declared in `templating.list` but never appearing in any `expr` field is dead (audit finding)
- [ ] **`tracing.configure_tracing()` receives a non-empty `otlp_endpoint`** in production config — empty string installs `NoOpTracerProvider` and emits zero traces despite Alloy+Tempo being configured
- [ ] **Any new LLM call site records real cost via the unified path + `cost_source`** — resolve cost with `ml_clients.pricing.resolve_cost(...)` (provider `usage.estimated_cost` → local → price matrix); NEVER hardcode `estimated_cost_usd=0.0` for a paid model. Persist `cost_source` (`provider`|`pricematrix`|`local`|`aggregate`) and thread `user_id`. Any new configured model id MUST be added to `ml_clients.model_registry.PLATFORM_MODEL_REGISTRY` (CI test `test_all_configured_models_priceable` blocks an unpriced model) and to `MODEL_PRICING`/`LOCAL_FREE_MODELS` as appropriate. The `llm_usage_log` write choke-point must call `observability.metrics.record_silent_zero_cost(<service>, …)` so a paid silent-zero trips `llm_usage_silent_zero_cost_total` (exempt only `local` + `aggregate`). (PLAN-0117 FR-4/FR-7, BP-715)

## 8. Test Coverage

- [ ] New public functions/methods have unit tests
- [ ] Happy path, edge cases, and error paths tested
- [ ] Tests use correct pytest markers (`unit`, `integration`, `contract`, `e2e`)
- [ ] Mocks are at port boundaries (not deep inside implementation)
- [ ] Tests verify side effects (events published, DB updated), not just return values
- [ ] No test interdependencies (each test is independent)
- [ ] **Blast radius verified**: if Avro schemas, DB schemas, or shared lib APIs changed, downstream tests outside the immediate scope have been identified and run (see implement skill §2.4). Key files to check: `libs/contracts/tests/test_avro_alignment.py`, `tests/contract/test_avro_schemas.py`
- [ ] **Full service suite run after fix** (not just touched files) — `python -m pytest tests/ -x -q` from the service root (HR-042, BP-408)
- [ ] New test failures classified: pre-existing / fix-induced regression / stale expectation
- [ ] Fix-induced regressions resolved before declaring done
- [ ] **New/modified external-API pagination or quota logic**: at least one test fixture reproduces the PROVIDER'S OBSERVED live response shape (not just the shape implied by its docs), e.g. a short-but-nonempty first page, and the loop does not terminate early on it; record the live verification (endpoint, params, observed row count vs requested limit) in the commit message or fixture comment (content-ingestion-pagination cluster)

## 8b. Deployment Verification

- [ ] If change affects service runtime behavior: Docker image rebuilt (`docker compose build <svc>`) and smoke tested
- [ ] Image build timestamp verified to be after commit timestamp: `docker inspect <container> | grep -i created` vs `git log -1 --format="%ci"` (HR-043, BP-410)
- [ ] `docker compose up -d --no-deps <svc>` used (not `docker compose restart`) to apply new image

## 8c. Parallel Agent Execution

- [ ] Each parallel agent committed its changes before returning (confirmed via `git log`) (HR-044, BP-409)
- [ ] Full test suite run after all parallel agents complete
- [ ] No changes left only in isolated worktrees — `git status` clean, expected files present in working tree

## 9. Test Integrity (R19 — blocks approval if violated)

- [ ] No tests were deleted to make the suite pass
- [ ] No tests were marked `skip` or `xfail` as a workaround for failures
- [ ] No assertions were weakened (e.g., `==` changed to `>=`, field counts removed)
- [ ] If a test was modified, the change is justified by a specification change (cite PRD section)
- [ ] Pre-existing test failures encountered during this change were investigated and fixed — not ignored
- [ ] Root cause is always assumed to be in the implementation first; test is only corrected after proving the test was wrong

## 10i. LLM Agent Loop (when modifying S8 or any tool-calling loop)

- [ ] **Tool scope injection**: `organization_id` and `user_id` are dispatch-injected (not LLM-visible in tool schema) — any tool accepting tenant scope as a positional arg is a cross-tenant injection vector (HR-046)
- [ ] **Citation egress**: final LLM answer is scrubbed — any entity_id / article_id / source reference in the answer must appear in at least one tool result from the current turn; references not grounded in tool outputs must be redacted before delivery to the client
- [ ] **Budget governance**: agent loop enforces token budget (per-turn), latency budget (cumulative tool wall-clock), per-tool timeout, iteration cap, and consecutive error limit — all five independently
- [ ] **User message persisted before loop**: user message is written to DB before `AgentLoop` starts (so LLM crash does not silently drop the request)
- [ ] **Input guard present**: at minimum regex-layer injection detection runs before agent loop entry; fail-closed on all error paths

## 10. Frontend / TypeScript (applies when `apps/frontend/` files are changed)

Mark N/A for pure backend changes.

### 10a. Architecture
- [ ] **Frontend only calls S9** — no direct backend service URLs anywhere in `apps/frontend/` (HR-030, R14)
- [ ] All API calls go through `gatewayClient.<method>()` in `src/lib/gateway-client.ts`
- [ ] New gateway endpoints are added as typed methods (no raw `fetch()` calls in components)
- [ ] Next.js app routes follow the `app/(protected)/` auth-guarded layout for all pages requiring auth

### 10b. TypeScript Correctness
- [ ] **No `any` types** — all gateway responses, hook return values, and handler params are typed (HR-032)
- [ ] `pnpm typecheck` passes with 0 errors
- [ ] Interfaces used for object shapes; `type` for unions/intersections

### 10c. State Management
- [ ] **TanStack Query for all server state** — no `useState+useEffect` for API calls (HR-033)
- [ ] `enabled: Boolean(id)` guard on all entity-specific queries
- [ ] Auth token stored in React state only — never `localStorage`, never client-accessible cookie (HR-035)

### 10d. UI States (Required — not optional)
- [ ] **Every data-dependent component handles all 3 states**: loading skeleton, error card with retry, empty state (HR-034)
- [ ] Skeletons match the shape of loaded content
- [ ] Error states include a recovery action (retry button, navigation link)
- [ ] **New public-facing UI surfaces define a casual-user default + progressive disclosure** before public exposure (PRD-0122 / audit §7). A Simple/Advanced (or any progressive-disclosure) split MUST be a prop-driven **render gate guarded by an Advanced-parity snapshot test**, never a duplicated component tree; flipping the default forces every old-default e2e to seed the old mode (DS §6.17)

### 10e. Security
- [ ] **No `dangerouslySetInnerHTML` without DOMPurify sanitization** (HR-031)
- [ ] No PII in `localStorage` or `sessionStorage`
- [ ] No secrets or API keys in `NEXT_PUBLIC_*` env vars or client-side code
- [ ] WebSocket auth uses `?token=<access_token>`, not `?user_id=` (HR-038, ADR-F-02)
- [ ] Direct WS connections to backend services use the **full registered path** (`/api/v1/...`), not the Next.js-rewrite-stripped path (`/v1/...`) — BP-248
- [ ] `switch` statements over string values from external APIs have a `default` branch — BP-250
- [ ] Python `StrEnum` values (lowercase) are normalized with `.toUpperCase()` before comparison against TypeScript uppercase unions — BP-250
- [ ] SSE streams use `AbortController` with cleanup on unmount (HR-039)
- [ ] **HTTPS-only headers (`upgrade-insecure-requests`, `Strict-Transport-Security`) are gated on actual HTTPS deployment, NOT `NODE_ENV === "production"`** — BP-324. Use `NEXT_PUBLIC_WS_BASE_URL.startsWith("wss://")` as the HTTPS signal. Sending these over HTTP breaks ALL static assets in Chrome/Safari (sub-resources silently upgraded to failing HTTPS).
- [ ] **`style-src` in CSP includes `'nonce-N'` when `x-nonce` is set in middleware** — BP-323. Next.js 15 auto-adds `nonce` to `<link rel="stylesheet">` elements; Safari blocks stylesheets if `style-src` has no matching nonce-source.
- [ ] **Root layout (and any layout using per-request nonces) calls `await headers()` or `await cookies()`** — BP-382. Without this, Next.js full-route cache serves stale HTML with old nonces; Safari blocks all stylesheets when nonce attribute on `<link>` doesn't match CSP `nonce-N` directive.
- [ ] **`TabsContent` with display-setting Tailwind classes (`flex`, `grid`, `block`) uses `data-[state=active]:flex` guard** — BP-381. Tailwind author-stylesheet `flex` overrides UA `[hidden]{display:none}`, making inactive tab panels visible as black rectangles.

### 10f. Dark Theme Compliance
- [ ] All colors use CSS variables from `docs/ui/DESIGN_SYSTEM.md §2` — no hardcoded hex (HR-037)
- [ ] Positive values use `--positive` (green), negative use `--negative` (red) — consistently
- [ ] `class="dark"` remains on `<html>` — no conditional theme switching
- [ ] No `style={{ color: "#hex" }}` inline styles — use Tailwind token classes (`text-primary`, `text-positive`, `text-negative`) instead (BP-202)
- [ ] No `rounded-full` on institutional UI elements — sharp 2px corners everywhere except status indicator dots
- [ ] No `animate-pulse` on status indicators — static color change conveys state without consumer-app animation
- [ ] No hardcoded hex in `className` strings (e.g. `border-[#FFD60A]`) — use `border-primary` and design token classes

### 10g. Dependencies
- [ ] **Exact version pins** in `package.json` (no `^` or `~`) (HR-036)
- [ ] `pnpm audit` shows 0 vulnerabilities after any dependency change
- [ ] No UI libraries added other than shadcn/ui (Radix primitives + Tailwind)
- [ ] `pnpm-lock.yaml` committed and in sync

### 10h. Tests
- [ ] Every new component has at minimum: loading state test + happy path test
- [ ] Gateway client is mocked at the `gatewayClient` boundary (not `fetch`)
- [ ] E2E test added for new pages (smoke + data flow)

### 10i. Frontend Mutations
- [ ] Every `useMutation` has `retry: 3` and `retryDelay` exponential backoff
- [ ] Server-side idempotency confirmed before enabling retry (unique constraints, idempotency_keys table, or upsert)
- [ ] Every new route has `loading.tsx` with route-appropriate skeleton + `error.tsx` with reset + back-to-dashboard

### 10j. Frontend Numerics & Design Tokens
- [ ] Every numeric value rendered to user uses `<FormattedNumber>` or explicit `font-mono tabular-nums` classes
- [ ] No hardcoded `#hex` colors outside `globals.css` token definitions — use `hsl(var(--token-name))`
- [ ] No hardcoded chart color constants (`COLOR_POSITIVE`, `COLOR_NEGATIVE`) — reference `--chart-positive`, `--chart-negative` CSS tokens

### 10k. Frontend Settings Pages
- [ ] Any new settings page is either: (a) fully wired to a backend endpoint, or (b) returns `notFound()` and hidden from sidebar nav
- [ ] No `console.log + toast("Coming soon")` patterns in settings pages

---

## Scoring

| Result | Meaning |
|--------|---------|
| All PASS or N/A | **APPROVE** |
| FAIL in sections 7-8 only | **APPROVE WITH NOTES** (improvements recommended) |
| FAIL in sections 1-6 | **REQUEST CHANGES** (must fix) |
| FAIL in section 9 | **BLOCK** (test integrity violation — R19) |
| FAIL in section 10a, 10b, 10e | **REQUEST CHANGES** (frontend arch/security violations) |
| Multiple FAIL in 1-6 | **BLOCK** (serious issues) |
