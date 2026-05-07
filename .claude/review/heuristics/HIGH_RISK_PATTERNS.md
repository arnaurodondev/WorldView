# High-Risk Patterns

> Code patterns that signal elevated risk. When detected, investigate before approving.

## RED — Must Investigate and Fix

### HR-001: Broad Exception Suppression
```python
# BAD
except Exception:
    pass  # or: return None / return default
```
**Risk**: Silently masks bugs, data corruption, security issues.
**Fix**: Catch specific exceptions. Log and re-raise or classify as RetryableError/FatalError.

### HR-002: Empty Except Block
```python
# BAD
except:
    ...
```
**Risk**: Catches SystemExit, KeyboardInterrupt — masks everything.
**Fix**: Always specify exception type. Never use bare `except:`.

### HR-003: Direct Write to Final Path
```python
# BAD — partial write on failure
with open(final_path, 'w') as f:
    f.write(data)
```
**Risk**: Interrupted write leaves corrupted file.
**Fix**: Write to temp file first, then atomic rename.

### HR-004: Dual Write Without Outbox
```python
# BAD
await db.commit()
await kafka.send(event)  # Separate transaction!
```
**Risk**: DB committed but Kafka fails = data inconsistency.
**Fix**: Use outbox pattern from `libs/messaging`.

### HR-005: Hardcoded Credentials
```python
# BAD
password = "my_secret_123"
api_key = "sk-..."
```
**Risk**: Credential exposure in source control.
**Fix**: Use environment variables via pydantic-settings.

### HR-006: F-String SQL
```python
# BAD
query = f"SELECT * FROM users WHERE id = '{user_id}'"
```
**Risk**: SQL injection.
**Fix**: Use parameterized queries or SQLAlchemy ORM.

## ORANGE — Investigate Before Approving

### HR-007: Broad Except in Finally
```python
# SUSPICIOUS
finally:
    try:
        cleanup()
    except Exception:
        pass
```
**Risk**: Masks cleanup failures, may hide resource leaks.
**Action**: Verify cleanup failure is truly non-critical. At minimum, log it.

### HR-008: Return Inside Except
```python
# SUSPICIOUS
except SomeError:
    return default_value
```
**Risk**: May hide the fact that an error occurred from callers.
**Action**: Verify this is intentional and the caller expects this behavior.

### HR-009: External API Call Inside DB Transaction
```python
# SUSPICIOUS
async with session.begin():
    result = await external_api.call()  # Holds transaction!
    await session.add(Entity(data=result))
```
**Risk**: Long transaction hold; external timeout = DB connection exhaustion.
**Fix**: Call external API first, then open transaction for DB write.

### HR-010: Unbounded Collection
```python
# SUSPICIOUS
all_items = await repo.get_all()  # How many?
results = [process(item) for item in all_items]
```
**Risk**: OOM on large datasets.
**Fix**: Use pagination, streaming, or bounded batch size.

### HR-011: Naive Datetime
```python
# SUSPICIOUS
from datetime import datetime
now = datetime.now()  # No timezone!
```
**Risk**: Timezone bugs, comparison failures.
**Fix**: `datetime.now(tz=timezone.utc)` or `common.time.utc_now()`.

### HR-012: Direct UUID4
```python
# SUSPICIOUS
import uuid
entity_id = uuid.uuid4()
```
**Risk**: Non-time-sortable IDs, violates project convention.
**Fix**: Use `common.ids.new_uuid7()`.

## YELLOW — Note for Review

### HR-013: Complex Conditional Without Tests
```python
if a and (b or (c and not d)) and e:
    # Complex branch
```
**Action**: Verify this branch has dedicated test cases.

### HR-014: Magic Numbers
```python
if retry_count > 3:  # Why 3?
    timeout = 0.5  # Why 0.5?
```
**Action**: Extract to named constants with documentation.

### HR-015: Duplicated Logic
```python
# Same pattern in multiple places
result = transform(data)
validated = validate(result)
await publish(validated)
```
**Action**: Check if existing lib utilities cover this pattern.

### HR-016: Direct Logging Import
```python
import logging
logger = logging.getLogger(__name__)
```
**Risk**: Bypasses structlog; violates project convention.
**Fix**: `import structlog; logger = structlog.get_logger()`

---

## RED — Added from S4 QA Review (2026-03-26)

### HR-017: Python `hash()` for Distributed Coordination
```python
lock_id = hash(f"s4:fetch:{source.name}")
await session.execute(text(f"SELECT pg_try_advisory_lock({lock_id})"))
```
**Risk**: `hash()` is randomized per process (PEP 456). Different pods compute different lock IDs, defeating mutual exclusion.
**Fix**: Use `hashlib.sha256` for deterministic cross-process hashing. See `messaging.pg.advisory_lock`.

---

## ORANGE — Added from S4 QA Review (2026-03-26)

### HR-018: `setattr` with User-Controlled Keys Without Allowlist
```python
for key, value in kwargs.items():
    setattr(model, key, value)
```
**Risk**: Mass-assignment vulnerability — callers can overwrite internal fields (`id`, `created_at`, `status`) if not constrained.
**Fix**: Define `_MUTABLE_FIELDS = frozenset({"name", "enabled", "config"})` and reject keys not in the set.


---

## ORANGE — Added from PLAN-0001-B-R4 QA Review (2026-03-27)

### HR-019: Blocking I/O in Pydantic Validators
```python
@field_validator("url")
@classmethod
def validate_url(cls, v: str) -> str:
    addrs = socket.getaddrinfo(hostname, None)  # BLOCKS THE EVENT LOOP
    requests.get(url)                           # BLOCKS THE EVENT LOOP
    open(path).read()                           # BLOCKS THE EVENT LOOP
    ...
```
**Risk**: Pydantic validators called from async FastAPI handlers run synchronously on the event loop. Any blocking I/O (DNS, HTTP, file I/O) freezes the entire service for the duration of that operation.
**Fix**: Only do fast, CPU-bound checks in Pydantic validators (scheme check, regex, literal IP check). Move DNS/HTTP/file I/O to the async route handler using `asyncio.to_thread`.

### HR-020: SSRF With IPv4-Only IP Range Checks
```python
_PRIVATE = [ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("127.0.0.0/8")]
def is_private(addr):
    return any(addr in net for net in _PRIVATE)  # misses ::ffff:127.0.0.1
```
**Risk**: IPv4-mapped IPv6 addresses (e.g., `::ffff:127.0.0.1`) bypass manual IPv4 range lists because the list entries are `IPv4Network` objects but `addr` is `IPv6Address`.
**Fix**: Use `addr.is_private or addr.is_reserved or addr.is_loopback or addr.is_multicast`, and unwrap IPv4-mapped IPv6 first: `if isinstance(addr, IPv6Address) and addr.ipv4_mapped: addr = addr.ipv4_mapped`.

---

## ORANGE — Added from PLAN-0001-E QA Review (2026-03-28)

### HR-021: Non-atomic Consumer Dedup (Separate UoW per Phase)
```python
async def is_duplicate(self, event_id):
    async with await self.get_unit_of_work() as uow:
        return await uow.idempotency.exists(uid)   # transaction 1

async def process_message(self, ...):
    async with await self.get_unit_of_work() as uow:
        await uow.things.upsert(...)               # transaction 2

async def mark_processed(self, event_id):
    async with await self.get_unit_of_work() as uow:
        await uow.idempotency.record(uid)          # transaction 3
```
**Risk**: Concurrent consumers both pass `is_duplicate` → double-process the same event (BP-045).
**Fix**: Apply BP-035 — single transaction with atomic `INSERT … ON CONFLICT DO NOTHING RETURNING` inside `process_message`. Set `is_duplicate()` → `return False`; `mark_processed()` → no-op.

### HR-022: Cache Invalidation Before `uow.commit()` (M-005 Violation)
```python
async def process_message(self, ...):
    await uow.quotes.upsert(quote)          # DB write (uncommitted)
    await self._cache.invalidate(id)        # ← called before commit
    # base class commits uow later
```
**Risk**: A client read between invalidation and commit caches the OLD stale DB value (BP-046). After commit, cache serves stale data until TTL expiry.
**Fix**: Use `uow.schedule_post_commit(cache.invalidate(id))`. The hook drains after `write_session.commit()`.

### HR-023: `readyz` Endpoint Returning Raw Exception String
```python
except Exception as exc:
    checks["db"] = f"error: {exc}"   # leaks DSN, password, host info
```
**Risk**: Clients (or proxies that log 503 bodies) receive internal connection strings including database host, port, user, and potentially password (BP-047).
**Fix**: `checks["db"] = "error"` — opaque string in HTTP; log full details via structured logger internally only.

### HR-025: UoW `__aexit__` Auto-Commit (R26 Violation)

```python
# BAD — Option A (auto-commit in __aexit__)
async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
    try:
        if exc_type is not None:
            await self.rollback()
        else:
            await self.commit()   # ← FORBIDDEN
    ...
```

**Risk**: BLOCKING — silent writes on every clean context exit. Read-only use cases commit
empty transactions. Double-commit bugs are invisible (second `session.commit()` is a no-op).
Discovered as a live bug in market-ingestion `SqlaUnitOfWork` (F-DS-004/PLAN-0008).

**Grep pattern**:
```bash
grep -rn "else.*commit\|__aexit__.*commit" services/*/src/*/infrastructure/db/unit_of_work.py
```

**Fix**: Remove `else: await self.commit()` from `__aexit__`. Add explicit `await uow.commit()`
to every mutating use case. See STANDARDS.md §17 and RULES.md R26.

---

### HR-024: `asyncio.Event.set()` in librdkafka Delivery Callback Without `call_soon_threadsafe`
```python
def _cb(err, _msg):
    delivery_event.set()   # asyncio primitive mutated from C thread
loop = asyncio.get_event_loop()  # too late — after _cb definition
```
**Risk**: librdkafka delivery callbacks run on a C thread, not the asyncio event loop thread. Direct `event.set()` is not thread-safe (BP-050). Rare deadlocks under contention.
**Fix**: Capture `loop` before defining `_cb`; use `loop.call_soon_threadsafe(delivery_event.set)` inside the callback.

---

## RED — Added from PLAN-0025 QA Review (2026-04-12)

### HR-026: JWT Decode Without Issuer Validation
```python
# BAD — issuer parameter missing
payload = jwt.decode(token, public_key, algorithms=["RS256"])
# attacker can forge a token signed with their own key and a spoofed "iss" claim
```
**Risk**: Without `issuer=expected_issuer`, a valid JWT from any other provider (or an attacker with their own RS256 key) is accepted (BP-145). Issuer spoofing = auth bypass.
**Fix**: Always pass `issuer=oidc_config.issuer` (or equivalent) to `jwt.decode()`. Verify both `iss` and `aud` claims.
**Grep pattern**:
```bash
grep -rn "jwt.decode(" services/ --include="*.py" | grep -v "issuer="
```

### HR-029: Repository `save()` Calls `session.rollback()` — Poisons Shared Session
```python
# BAD — repo-level rollback poisons the shared session context
async def save(self, entity):
    try:
        self._session.add(entity)
        await self._session.flush()
    except IntegrityError:
        await self._session.rollback()  # ← kills the shared session
        raise DuplicateEntityError(...)
```
**Risk**: `session.rollback()` inside a repository method rolls back the shared session created by the outer `async with session_factory() as session:` context manager. Any code that continues after catching the domain error operates on a dead session, causing `InvalidRequestError` (BP-141).
**Fix**: Remove `session.rollback()` from repository `save()` methods. Let the exception propagate; the use-case `async with session_factory()` context manager owns rollback via `__aexit__`.

---

## ORANGE — Added from PLAN-0025 QA Review (2026-04-12)

### HR-027: Non-transactional Pipeline for Atomic State Removal (Valkey/Redis)
```python
# BAD — GET + DEL are two separate commands — window between them allows replay
async def retrieve_and_delete(self, key: str):
    value = await self._client.get(key)
    await self._client.delete(key)
    return value
```
**Risk**: Two concurrent requests both execute `GET` before either `DEL` runs (BP-146). Both receive the value (e.g., a PKCE code verifier), enabling replay attacks on one-time-use state.
**Fix**: Use `GETDEL` (atomic single command, Redis 6.2+/Valkey 7+) or a Lua script. Never use `GET` + `DEL` in a pipeline for security-sensitive one-time tokens.
**Grep pattern**:
```bash
grep -rn "\.get(" services/ --include="*.py" -A2 | grep "\.delete("
```

### HR-028: Middleware / Dependency Reads App State at Construction Time (Stores `None`)
```python
# BAD — valkey_client captured at startup before app.state is populated
class RateLimitMiddleware:
    def __init__(self, app, valkey_client):
        self.valkey = valkey_client  # None if app.state not ready at __init__

    async def dispatch(self, request, call_next):
        if self.valkey is None:  # always None — rate limiting permanently disabled!
            return await call_next(request)
```
**Risk**: FastAPI lifespan populates `app.state` after middleware is instantiated. If the middleware captures `app.state.x` (or a DI argument that resolves to `None`) at `__init__` time, the feature is silently disabled for the entire process lifetime (BP-144).
**Fix**: Read from `request.app.state` inside `dispatch()`, not in `__init__`:
```python
async def dispatch(self, request, call_next):
    valkey = getattr(request.app.state, "valkey", None)
    if valkey is None:
        return await call_next(request)
```

---

## RED — Frontend Patterns (Next.js / TypeScript)

### HR-030: Direct Backend Service URL in Frontend
```typescript
// BAD — bypasses S9 auth, CORS, rate limiting, and gateway contract
const res = await fetch('http://localhost:8006/v1/entities')
const res = await fetch(process.env.NLP_PIPELINE_URL + '/entities')
```
**Risk**: The frontend MUST only call S9 API Gateway at `/api/*`. Direct backend URLs bypass authentication (no `X-Internal-JWT`), break in production (services not publicly exposed), and violate the gateway contract (R14).
**Fix**: Use `gatewayClient.<method>()` which always calls `/api/*` (proxied to S9 via `next.config.ts`).

### HR-031: `dangerouslySetInnerHTML` Without Sanitization
```typescript
// BAD — XSS attack vector
<div dangerouslySetInnerHTML={{ __html: article.content }} />
<div dangerouslySetInnerHTML={{ __html: userInput }} />
```
**Risk**: If `content` contains `<script>` tags or event handlers injected by a malicious news source or user input, this executes arbitrary JavaScript (XSS).
**Fix**: Sanitize with DOMPurify before rendering: `DOMPurify.sanitize(content)`. Or render as plain text. Only use `dangerouslySetInnerHTML` for trusted static content.

### HR-032: `any` Type in TypeScript
```typescript
// BAD — defeats type system
const data: any = await gatewayClient.getCompanyOverview(id)
const handler = (event: any) => { ... }
```
**Risk**: `any` silences type errors, leading to runtime `TypeError` crashes and undefined behavior when API response shapes change. Violates the no-`any` rule (AGENTS.md §TypeScript Strictness).
**Fix**: Define the interface from the gateway response or import the generated type. Use `unknown` + type narrowing if the shape is genuinely dynamic.

### HR-033: `useState + useEffect` for Server Data Fetching
```typescript
// BAD — no caching, no deduplication, no loading state management
const [data, setData] = useState(null)
useEffect(() => {
  fetch('/api/companies').then(r => r.json()).then(setData)
}, [])
```
**Risk**: Race conditions on unmount, duplicate in-flight requests, no stale-while-revalidate, no error state, no retry.
**Fix**: Use TanStack Query v5: `const { data, isLoading, error } = useQuery({ queryKey: [...], queryFn: ... })`.

### HR-034: Missing Loading / Error / Empty States
```typescript
// BAD — blank panel while loading, no feedback on error
function DataPanel({ id }: { id: string }) {
  const { data } = useQuery(...)
  return <Table data={data} />  // crashes if data is undefined
}
```
**Risk**: Users see blank panels, UI crashes (`TypeError: Cannot read properties of undefined`), or silent failures with no recovery path. Violates the required pattern (DESIGN_SYSTEM.md §6.1).
**Fix**: Handle all three states explicitly: `if (isLoading) return <Skeleton />; if (error) return <ErrorCard />; if (!data) return <EmptyState />`.

### HR-035: Access Token in `localStorage`
```typescript
// BAD — XSS-accessible storage
localStorage.setItem('access_token', token)
const token = localStorage.getItem('access_token')
```
**Risk**: Any XSS vulnerability (HR-031, injected third-party script) can steal the access token from `localStorage`, leading to account takeover.
**Fix**: Store `access_token` in React state only (in-memory). The `refresh_token` is stored in an httpOnly cookie, which is XSS-immune. On page reload, re-acquire via `POST /api/v1/auth/refresh`.

## ORANGE — Frontend Patterns

### HR-036: Non-exact pnpm Dependency Versions
```json
// BAD
{ "next": "^15.0.0", "react": "~18.3.0" }
```
**Risk**: `^` and `~` allow automatic minor/patch upgrades that can introduce breaking changes, CVEs, or subtle behavior differences between installs (pnpm enforcement rule).
**Fix**: Use exact versions: `"next": "15.1.3"`. Run `pnpm audit` after any version change; it must show 0 vulnerabilities.

### HR-037: Color Outside CSS Variables (Dark Theme Violation)
```typescript
// BAD — hardcoded hex bypasses dark theme system
<div style={{ backgroundColor: '#0f172a' }} />
<div className="bg-slate-950" />  // OK but prefer var
```
**Risk**: Hardcoded colors don't respond to CSS variable changes, make theme maintenance brittle, and violate the design system constraint (DESIGN_SYSTEM.md §2).
**Fix**: Use CSS variable utilities: `bg-background`, `text-foreground`, `text-muted-foreground`, `border-border`, etc.

### HR-038: WebSocket Without Auth Token (Post-PRD-0025)
```typescript
// BAD — after PRD-0025, user_id query param is an auth bypass
const ws = new WebSocket(`/api/v1/alerts/stream?user_id=${userId}`)
```
**Risk**: Any client can specify any `user_id` — no verification that the caller is that user. This is an auth bypass (ADR-F-02 addressed this).
**Fix**: Pass `?token=<access_token>` instead: `new WebSocket(\`/api/v1/alerts/stream?token=\${accessToken}\`)`.

### HR-039: SSE / Streaming Without `AbortController`
```typescript
// BAD — no way to cancel, stream leaks on component unmount
const es = new EventSource('/api/v1/chat/stream?q=' + message)
es.onmessage = (e) => setOutput(prev => prev + e.data)
// no cleanup, no cancel
```
**Risk**: If the component unmounts (user navigates away), the EventSource stays alive, callbacks fire on a dead component (state update on unmounted component warning → memory leak).
**Fix**: Use an `AbortController`; close the EventSource in the cleanup function of `useEffect`.

## ORANGE — Added 2026-04-13 (restart/idempotency investigation)

### HR-029: Consumer Entity PKs Are new_uuid7() + ON CONFLICT DO NOTHING on PK
```python
section_id=common.ids.new_uuid7(),  # generated fresh on every run
# ...
await session.execute(
    pg_insert(SectionModel).values(...).on_conflict_do_nothing(index_elements=["section_id"])
)
```
**Risk**: ON CONFLICT on `section_id` never fires on Kafka re-delivery because the ID is different each time. Duplicate rows accumulate silently (BP-149).
**Fix**: Either (a) derive IDs deterministically from input (`uuid5(namespace, f"{doc_id}:{index}")`), or (b) add an explicit pipeline-completion check before the write transaction (query a "sentinel" row like `routing_decisions.doc_id`).

### HR-030: Kafka Topic Without Explicit Retention Config
```bash
"content.article.stored.v1:12:1"   # no retention.ms set → 7-day broker default
```
**Risk**: Services down >7 days silently lose the backlog. Consumer resumes from oldest *remaining* message, skipping everything from the outage window (BP-150).
**Fix**: Add explicit `retention.ms=2592000000` (30 days) via `kafka-configs --alter` for all primary pipeline topics in `create-topics.sh`.

---

## RED — Added from Observability Audit (2026-04-23)

### HR-040: Shared Metrics Library Using `registry or CollectorRegistry()` Default
```python
# BAD — creates a new isolated registry every call; metrics never reach generate_latest()
def create_metrics(service_name: str, registry: CollectorRegistry | None = None):
    reg = registry or CollectorRegistry()   # ← WRONG: always isolated when None passed
    requests_total = Counter("...", registry=reg)
    return ServiceMetrics(registry=reg, ...)
```
**Risk**: All metrics registered in `reg` are invisible to `prometheus_client.generate_latest()`, which reads the global `REGISTRY` singleton. Every service using this helper ships with zero observable metrics — 10 services × 6 metric families = 60 dead metric families (BP-173).
**Fix**: Use `reg = registry if registry is not None else REGISTRY` (importing `REGISTRY` from `prometheus_client`). Tests that pass an isolated registry continue to work; production code uses the global registry.
**Grep pattern**:
```bash
grep -rn "registry or CollectorRegistry()" libs/ --include="*.py"
```

### HR-041: Prometheus Metric Defined But Never Called
```python
# BAD — metric declared, never wired to any code that calls .inc()/.set()/.observe()
s5_articles_processed_total = Counter("s5_articles_processed_total", "...", ["tier"])
s5_processing_duration_seconds = Histogram("s5_processing_duration_seconds", "...", ["tier"])
# ... neither metric appears anywhere else in services/content-store/
```
**Risk**: Metric shows value `0` permanently. Dashboards that rely on it appear healthy ("no failures") rather than broken ("metric not instrumented"). Alerts built on it either never fire or always fire based on `absent()` behavior. Silent instrumentation gap (BP-174).
**Fix**: For every new metric definition, verify at least one `.inc()`/`.set()`/`.observe()` call site exists in the same service. If no call site exists, delete the metric definition.
**Grep pattern**:
```bash
# Find all metric variable names in a metrics module, then verify usage:
grep -rn "s5_articles_processed_total" services/content-store/src/ --include="*.py"
# Must return ≥2 lines: definition + call site.
```

---

## ORANGE — Added 2026-05-07 (Session failure analysis)

### HR-042: Running `pytest <touched-file>` Only After a Fix (Fix-Induced Regression Risk)
```bash
# BAD — only tests the changed file
python -m pytest tests/unit/test_my_worker.py

# GOOD — tests the entire service
python -m pytest tests/ -x -q
```
**Risk**: A fix that changes a shared utility, port interface, or consumer behavior can break tests in files that were not modified. Touched-file-only test runs never catch these regressions (BP-408). The fix ships appearing correct.
**Action**: After any fix commit, always run the full service test suite. If a broader test scope reveals failures, classify each as: (a) fix-induced regression → fix before proceeding, (b) pre-existing → file separately, (c) stale expectation → update with justification.
**Grep pattern**:
```bash
# Detect if only a single file was run in a pytest invocation
# Look for explicit file paths in pytest args (warning sign):
grep -rn "pytest tests/unit/test_" Makefile scripts/ --include="*.sh"
```

### HR-043: Commit Without `docker compose build` for a Runtime Behavior Fix
```bash
# BAD — commits fix but never rebuilds the container
git commit -m "fix: ..."
# <declares done — container still running old code>

# GOOD
git commit -m "fix: ..."
docker compose build <svc>
docker compose up -d --no-deps <svc>
# verify: docker compose logs <svc> | tail -20
```
**Risk**: Unit tests pass against source, but the live Docker container still has the old code because `docker compose build` was never run. The bug persists in the running service despite the source fix (BP-410). Related: BP-257 (`restart` does not swap image), BP-319 (stale Alembic image), BP-346 (missing module after build).
**Action**: For every commit that modifies service runtime behavior, verify that the Docker image is rebuilt. Check image build time against commit time: `docker inspect <container> | grep -i created`.
**Grep pattern**:
```bash
# Confirm image was rebuilt after last commit
docker inspect <container-name> --format '{{.Created}}'
git log -1 --format="%ci" HEAD
# Image Created timestamp must be AFTER the commit timestamp
```

### HR-044: Parallel Subagent Run Without Verifying Commits Landed in Main Branch
```bash
# BAD — orchestrator launches agents, checks "status: success", moves on
# Agents applied fixes in their worktrees but never committed

# GOOD — after parallel agents complete, always verify
git log --oneline -10          # confirm new commit messages from subagents
git diff HEAD~N --name-only    # confirm expected files were changed
git status                     # confirm no uncommitted changes remain
```
**Risk**: Subagents operating in isolated git worktrees can apply fixes without committing. The worktree is destroyed on cleanup, taking all changes with it. The orchestrator receives a success status but the main branch is unchanged (BP-409). Discovering this after multiple further commits makes recovery harder.
**Action**: Any time parallel agents are used with `isolation: "worktree"`, the orchestrating agent MUST verify the changes appear in the main working tree before proceeding to the test phase.

### HR-045: Assigning a New R##, BP-NNN, or PLAN-XXXX by Incrementing from Memory
```markdown
<!-- BAD — author estimated next BP number from memory -->
## BP-185 — Some New Pattern
<!-- BP-185 was already assigned to "Content-Ingestion TokenBucket..." -->

<!-- GOOD — grep first -->
# grep -o 'BP-[0-9]\+' docs/BUG_PATTERNS.md | sort -t- -k2 -n | tail -1
# → BP-411  →  use BP-412
```
**Risk**: ID collision creates two entries with the same number, making all references to that ID ambiguous. The quick-lookup table acquires duplicate rows. Cross-document references (plans citing BP numbers, checklists citing HR numbers) become unreliable (BP-411).
**Action**: Before assigning any new numbered ID, grep the canonical file for the current maximum. Use `highest + 1`. Never estimate from memory in a fast-moving document.
**Grep pattern**:
```bash
# Highest BP number
grep -o 'BP-[0-9]\+' docs/BUG_PATTERNS.md | sort -t- -k2 -n | tail -1
# Highest R-rule number
grep -o '^R[0-9]\+' RULES.md | sort -t R -k2 -n | tail -1
# Highest HR number
grep -o 'HR-[0-9]\+' .claude/review/heuristics/HIGH_RISK_PATTERNS.md | sort -t- -k2 -n | tail -1
# Highest PLAN number
grep -o 'PLAN-[0-9]\+' docs/plans/TRACKING.md | sort -t- -k2 -n | tail -1
```

### HR-046: `is_duplicate(self, event_id) -> bool: return False` Stub (or Ad-Hoc Valkey Dedup)
```python
# BAD — stub or hand-rolled dedup (CONSUMER-DEDUP-001 will flag this)
class MyConsumer(BaseKafkaConsumer[None]):
    async def is_duplicate(self, event_id: str) -> bool:
        return False  # silent no-op; every event is reprocessed on replay
    async def mark_processed(self, event_id: str) -> None:
        pass

# ALSO BAD — hand-rolled Valkey logic
class MyConsumer(BaseKafkaConsumer[None]):
    async def is_duplicate(self, event_id: str) -> bool:
        return bool(await self._valkey.exists(f"my_key:{event_id}"))

# GOOD — inherit mixin; set prefix + optional TTL
class MyConsumer(ValkeyDedupMixin, BaseKafkaConsumer[None]):
    _dedup_prefix = "my_service:dedup:my_consumer"
    _dedup_ttl_seconds = 86400
```
**Risk**: `return False` stub disables dedup entirely — every duplicate event is processed on replay. Hand-rolled logic diverges in TTL policy, key naming, and error handling from the standard mixin, making cross-service reasoning unreliable (BP-415, R9).
**Action**: Any `is_duplicate` or `mark_processed` implementation that does not delegate to `ValkeyDedupMixin` is a yellow flag. Require either: (a) `ValkeyDedupMixin` inheritance, or (b) a docstring documenting the natural-key idempotency guarantee AND an allowlist entry in `tests/architecture/_consumer_dedup_allowlist.yaml`.
**Grep pattern**:
```bash
# Find consumers with hand-rolled or stub is_duplicate
grep -rn "async def is_duplicate" services/ | grep -v ".pyc"
# Cross-check against mixin usage
grep -rn "ValkeyDedupMixin" services/ | grep -v ".pyc"
```

### HR-047: Circuit Breaker `is_open()` Without HALF_OPEN Probe Gating
```python
# BAD — cooldown expiry admits ALL concurrent callers at once
async def is_open(self) -> bool:
    state = await self._valkey.get(self._state_key)
    return state == "open"  # no probe slot → stampede when cooldown expires

# GOOD — SETNX probe key admits only the first caller per probe_ttl window
async def is_open(self) -> bool:
    state = await self._valkey.get(self._state_key)
    if state != "open":
        return False
    # Try to acquire the probe slot; only the first caller in the TTL window succeeds
    probe_acquired = await self._valkey.set_nx(
        self._probe_key, "1", ex=self._probe_ttl_seconds
    )
    return not probe_acquired  # True = still open (probe taken by another); False = this caller probes
```
**Risk**: When a circuit-breaker cooldown expires, every in-flight coroutine simultaneously transitions from "open" to "probing" and hammers the recovering downstream service. This typically retrips the breaker before the first probe response returns, creating an oscillation loop (BP-413).
**Action**: Any circuit-breaker `is_open()` that compares state without a SETNX probe slot is a red flag when `cool_down_seconds >= 60` (high-concurrency paths). Require a probe key with `probe_ttl_seconds` (recommended 5 s). Flag during review; do not merge without the probe gate.
**Grep pattern**:
```bash
# Find is_open implementations that lack a probe/SETNX step
grep -A 10 "async def is_open" services/ -r | grep -v "set_nx\|setnx\|probe"
```
