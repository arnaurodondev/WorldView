# Bug Patterns — Async & Concurrency

> **Category**: async-concurrency
> **Description**: asyncio event loops, coroutine lifecycle, concurrency bugs, threading, async context managers, React concurrent mode
> **Count**: 12 patterns
> **Back to index**: [BUG_PATTERNS.md](../BUG_PATTERNS.md)

---

## BP-003 — `RuntimeError: Event loop is closed` at session-scoped async fixture teardown

**Date discovered**: 2026-03-10
**Services affected**: `portfolio`, `market-ingestion` (any service with e2e tests)
**Prompts updated**: none yet — catch this at implementation time

### Symptom

All e2e tests pass but produce `ERROR at teardown` for the last test in the session:

```
RuntimeError: Event loop is closed
  ...
  at tests/e2e/conftest.py:NN in e2e_client
    async with AsyncClient(base_url=_BASE_URL, timeout=30.0) as ac:
```

This cascades: tests that actually pass show `ERROR` status, and unrelated unit
tests that run after the e2e teardown can also error (e.g. `test_frozen_dataclass`,
`TestQuantity`) due to the corrupted asyncio state.

### Root cause

pytest-asyncio (mode=auto) creates a **new event loop per test function** by
default. A `scope="session"` async fixture's setup runs in the first test's loop
but its teardown (the `async with` exit) runs after that loop is already closed.
Any `await` inside teardown — including closing an `httpx.AsyncClient`'s
connection pool — raises `RuntimeError: Event loop is closed`.

```python
# WRONG — session fixture torn down on a closed per-function loop
@pytest.fixture(scope="session")
async def e2e_client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(base_url=_BASE_URL, timeout=30.0) as ac:
        yield ac  # teardown: AsyncClient.__aexit__ → runs on closed loop → crash
```

### Correct implementation pattern

Set `asyncio_default_fixture_loop_scope = "session"` in `pyproject.toml`. This
tells pytest-asyncio to keep ONE event loop alive for the entire session, so
session-scoped async fixtures always have a live loop for both setup and teardown.

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "session"   # ← REQUIRED when using session-scoped async fixtures
```

This setting must be present in **every service** that has `scope="session"` async
fixtures. It is harmless for services that only use function-scoped fixtures.

### Test to add (prevents regression)

No specific regression test — the failure only manifests at teardown reporting
time. The fix is purely in `pyproject.toml`.

### Files changed in fix

| File | Change |
|------|--------|
| `services/portfolio/pyproject.toml` | Added `asyncio_default_fixture_loop_scope = "session"` |
| `services/market-ingestion/pyproject.toml` | Added `asyncio_default_fixture_loop_scope = "session"` |

---

---

## BP-025 — Blocking DNS resolution in async context

**Date discovered**: 2026-03-27
**Service affected**: `content-ingestion` (found during PLAN-0001-B-R4 QA review)

### Symptom

Under slow or failing DNS, the entire FastAPI service freezes. Requests time out across all endpoints because a single blocked `socket.getaddrinfo()` call holds the event loop.

### Root cause

`socket.getaddrinfo()` is a blocking synchronous call. When called directly inside a Pydantic `field_validator` (which runs synchronously during request validation in an async handler), it blocks the asyncio event loop for the duration of the DNS lookup.

### Correct implementation pattern

```python
# WRONG — blocks the event loop
@field_validator("url")
def validate_url(cls, v: str) -> str:
    addrs = socket.getaddrinfo(hostname, None)  # blocks!
    ...

# CORRECT — move DNS to async handler with timeout
async def check_url_ssrf_async(url: str) -> None:
    try:
        addr_infos = await asyncio.wait_for(
            asyncio.to_thread(socket.getaddrinfo, hostname, None),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        raise ValueError(f"DNS timeout for {hostname}")
```

The Pydantic validator should only check scheme (http/https) and reject literal private IPs. DNS resolution moves to the async route handler.

### Test to add (prevents regression)

```python
async def test_async_dns_timeout():
    with patch("socket.getaddrinfo", side_effect=lambda *a, **kw: time.sleep(10)):
        with pytest.raises(ValueError, match="Could not resolve"):
            await check_url_ssrf_async("http://slow.example.com/article")
```

### Files changed in fix

| File | Change |
|------|--------|
| `services/content-ingestion/src/content_ingestion/api/schemas.py` | Removed DNS from validator; added `check_url_ssrf_async` |
| `services/content-ingestion/src/content_ingestion/api/routes/internal.py` | Call `check_url_ssrf_async` in handler |

---

---

## BP-058 — UoW `__aexit__` Auto-Commit Causes Double-Commit Side Effects

**Severity**: MEDIUM — silent in SQLAlchemy sessions, but double-fires post-commit hooks (e.g., outbox notifier, on_commit callbacks)
**Service**: portfolio (S1) — any service using the `UnitOfWork` context manager
**Resolved by**: PLAN-0001-E-R1 Wave 2 (Option B, QA-006)

### Symptom

- `on_commit` hook (e.g., outbox dispatcher wake signal) is called twice per request
- Post-commit side effects (cache invalidation, metrics increment) execute twice on clean exit
- No crash — SQLAlchemy's `AsyncSession.commit()` is idempotent for already-committed sessions

### Cause

`UnitOfWork.__aexit__` auto-commits on clean exit:
```python
async def __aexit__(self, exc_type, exc_val, exc_tb):
    if exc_type is None:
        await self.commit()  # WRONG — fires even when use case already called commit()
```

Use cases that call `await uow.commit()` explicitly (e.g., before cache invalidation) get the
commit called a **second time** by `__aexit__`, triggering any side effects attached to `commit()`
a second time.

### Fix (Option B)

Remove auto-commit from `__aexit__`. All mutating use cases must call `await uow.commit()` explicitly:
```python
async def __aexit__(self, exc_type, exc_val, exc_tb):
    if exc_type is not None:
        await self.rollback()
    # no auto-commit — explicit commit() required in each use case
```

### Detection

```bash
# Find any UoW __aexit__ that calls self.commit() unconditionally
grep -n "await self.commit" services/*/src/**/*unit_of_work*.py
```

Add the regression guard test:
```python
async def test_aexit_does_not_auto_commit_on_clean_exit(mock_session_factory, mock_session):
    async with SqlAlchemyUnitOfWork(mock_session_factory):
        pass  # no explicit commit
    mock_session.commit.assert_not_called()
```

### Prevention

- Review checklist item: "Does `UnitOfWork.__aexit__` auto-commit? If so, verify all callers are aware of the side effect."
- Every mutating use case must end with `await uow.commit()` before returning
- New use case template must include the commit call

---

## BP-059 — Use Case Calls `async with self._uow:` on Already-Entered UoW

**Category**: Architecture | **Severity**: Runtime error / silent data loss risk
**Discovered**: 2026-03-29 — PLAN-0001-E-R1 Wave 3 (QA-013)

### Pattern

When a service's dependency injection framework already enters the UoW before yielding it
(e.g., `async with uow_factory() as uow: yield uow`), any use case that wraps its body
in `async with self._uow:` will trigger a nested context manager entry:

```python
# WRONG — double-enters the UoW when get_uow yields an already-entered instance
class GetInstrumentUseCase:
    async def execute(self, instrument_id: str):
        async with self._uow:             # ← second __aenter__ — undefined behaviour
            return await self._uow.instruments_read.find_by_id(instrument_id)
```

### Root Cause

Two different UoW entry conventions exist across services:
1. **market-data** (S3): `get_uow` dependency yields an *already-entered* UoW
   (`async with SqlAlchemyUnitOfWork(...) as uow: yield uow`)
2. **portfolio** (S1): `get_uow` dependency yields an *uninitialized* factory — use cases
   enter it themselves

If a use case written for S1's convention is used in S3 (or vice versa), the double-entry
will either re-open the session (wasting connections) or raise a runtime error.

### Fix

Check the service's `api/dependencies.py` to determine which convention it uses.
For S3-style (already-entered), use cases must NOT wrap in `async with self._uow:`:

```python
# CORRECT for market-data — call repo methods directly, no context manager
class GetInstrumentUseCase:
    async def execute(self, instrument_id: str):
        return await self._uow.instruments_read.find_by_id(instrument_id)
```

### Detection

```bash
# In a service that yields pre-entered UoW: grep for use cases wrapping in async with
grep -n "async with self._uow" services/market-data/src/**/use_cases/*.py
```

### Prevention

- Service `.claude-context.md` must document which UoW convention is in use
- Use case template for market-data omits the `async with self._uow:` wrapper

---

---

## BP-081 — httpx `AsyncClient` double-open: `RuntimeError: Cannot open a client instance more than once`

**Affected areas**: Integration/E2E tests using `httpx.AsyncClient` fixtures

**Symptom**

Test fails immediately with:

```
RuntimeError: Cannot open a client instance more than once
```

**Root Cause**

An `AsyncClient` instance that was already opened (e.g., by a pytest fixture using `async with AsyncClient(...) as client:`) is used again as a context manager inside a test:

```python
# Fixture already opens the client:
@pytest.fixture
async def integration_client():
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

# Test tries to open it again — WRONG:
async def test_something(integration_client):
    async with integration_client as client:  # ← raises RuntimeError
        resp = await client.get("/endpoint")
```

**Fix**

Use the pre-opened client directly without wrapping it in `async with`:

```python
async def test_something(integration_client):
    resp = await integration_client.get("/endpoint")  # ← correct
```

**Prevention**

- Never use `async with <fixture_client> as client:` in tests — the fixture already manages the lifecycle
- Code review checklist: flag any `async with` usage on a variable that was received as a fixture parameter

---

---

## BP-088 — `asyncio.Event` patch causes infinite recursion in entrypoint tests

**Context**: Unit testing standalone consumer `main()` functions that create an `asyncio.Event` for shutdown signalling.

**Symptom**: `RecursionError: maximum recursion depth exceeded` inside `unittest.mock`. The stack shows repeated calls to the side_effect function from inside itself.

**Root cause**: The `side_effect` helper calls `asyncio.Event()` to create a pre-set event, but `asyncio.Event` has already been patched by `patch("asyncio.Event", side_effect=helper)`. The helper therefore calls itself recursively.

**Fix**: Capture the real `asyncio.Event` class at module level BEFORE any test patches it:
```python
_REAL_ASYNCIO_EVENT = asyncio.Event  # module-level, before any patches

def _preset_event(*_args, **_kwargs):
    e = _REAL_ASYNCIO_EVENT()  # real class, not the patch
    e.set()
    return e
```

**Prevention**: Any `side_effect` function that instantiates a class being patched must hold a reference to the original class captured before the patch context is entered.

---

---

## BP-106 — `asyncio.shield()` Around Stop-Event Wait Leaks Background Tasks

**Category**: Resource leak / asyncio
**Affected areas**: Background scheduler loops, any `asyncio.wait_for` around an `asyncio.Event.wait()`

**Symptom**: `asyncio.shield(self._stop_event.wait())` creates a detached background task that is never cancelled when `wait_for` raises `TimeoutError`. The coroutine lingers until the event fires, which may be long after the enclosing function has returned.

**Root cause**: `asyncio.shield()` is intended to protect a coroutine from cancellation when the *parent* is cancelled. It does not protect against `TimeoutError` — `wait_for` will still raise, but the shielded inner coroutine continues executing independently. This creates an uncollected task and `ResourceWarning: coroutine was never awaited`.

**Fix**: Remove `asyncio.shield()` — use `await asyncio.wait_for(self._stop_event.wait(), timeout=...)` directly. The `wait_for` timeout cancels the inner coroutine on timeout by default, which is the correct behaviour for a tick-loop sleep.

**First seen**: QA-S4S5-INFRA-001 (2026-04-07), S4 `scheduler_main.py:63`.

---

---

## BP-107 — `asyncio.timeout` Wraps Semaphore Acquisition, Not Just Execution

**Category**: Correctness / asyncio
**Affected areas**: Worker processes using `asyncio.Semaphore` with `asyncio.timeout`

**Symptom**: Tasks time out while waiting for a concurrency slot (semaphore), before they even begin executing. Timeout budget is consumed by queue wait time, not actual work.

**Root cause**: Placing `asyncio.timeout(T)` outside `async with self._semaphore:` starts the timeout clock when the task *arrives at the semaphore*, not when it *acquires* the semaphore. If `worker_concurrency` tasks are all busy, the `(concurrency + 1)`th task times out after `T` seconds of waiting even though it never ran.

**Fix**: Swap the nesting — acquire the semaphore first, then apply the timeout around the actual execution:
```python
async with self._semaphore:
    try:
        async with asyncio.timeout(self._task_timeout):
            await self._execute_task(task)
    except TimeoutError:
        ...
```

**First seen**: QA-S4S5-INFRA-001 (2026-04-07), S4 `worker.py:_execute_with_semaphore`.

---

---

## BP-108 — Read Engine Not Disposed in Process Entrypoints (Dual-URL Split)

**Category**: Resource leak / infrastructure
**Affected areas**: All standalone process entrypoints that call `_build_factories()` (dispatcher_main, consumer_main, worker)

**Symptom**: When `DATABASE_URL_READ` is set to a distinct endpoint, the read engine connection pool is never closed on shutdown. Under load, this exhausts PostgreSQL connection slots over time.

**Root cause**: Entrypoints copy `_engine.dispose()` but forget the conditional `_read_engine.dispose()`. The `app.py` lifespan correctly checks `if read_engine is not engine: await read_engine.dispose()`, but this pattern is not replicated in standalone process entrypoints.

**Fix**: Add after `await _engine.dispose()` in every process entrypoint:
```python
if _read_engine is not _engine:
    await _read_engine.dispose()
```
Also update test mocks: `return_value=(mock_engine, mock_engine, ...)` rather than `(mock_engine, MagicMock(), ...)` so the condition is False and `MagicMock().dispose()` is never awaited.

**First seen**: QA-S4S5-INFRA-001 (2026-04-07), S4/S5 dispatcher_main + S5 article_consumer_main.

---

---

## BP-268 — asyncio.create_task() Without done_callback Silently Swallows Consumer Crashes

**Category**: Distributed Systems / Kafka consumers
**Severity**: BLOCKING
**Affected areas**: All `*_consumer_main.py` files across S5, S6, S7, S8, S10, and market-data consumers
**First seen**: 2026-04-28 (observability audit)

**Symptoms**:
- Kafka consumer stops processing without the process exiting
- No ERROR log at the consumer-crash level
- Messages accumulate in Kafka topic without any alert firing
- Detection only via `ServiceDown` after Docker healthcheck fires (30–60s blind spot)

**Root Cause**:
`asyncio.create_task(consumer.run())` returns a Task whose exception is stored in the future result. The main coroutine blocks on `stop_event.wait()` and never awaits the consumer task. If the consumer exits via an unhandled exception, the exception is silently stored — the main coroutine continues to wait. The process does not exit and Docker does not restart the container.

**Fix Applied**:
Add a `done_callback` to every consumer task:
```python
def _on_consumer_exit(task: asyncio.Task) -> None:
    if not task.cancelled() and not stop_event.is_set():
        exc = task.exception()
        if exc is not None:
            log.error("consumer_task_fatal", error=str(exc), exc_info=exc)
            sys.exit(1)

consumer_task = asyncio.create_task(consumer.run())
consumer_task.add_done_callback(_on_consumer_exit)
```

**Prevention**:
- Never use `asyncio.create_task()` without either awaiting the task or adding a `done_callback`
- All consumer main functions must follow this pattern

---

---

## BP-299 — HotkeyContext Scope Push/Pop Non-Atomic in React 18 Concurrent Mode

**Category**: Frontend / React 18 / concurrency
**Severity**: MEDIUM (theoretical; only manifests with two simultaneous scope-push calls)
**Affected areas**: `HotkeyContext.tsx` `pushScope`/`popScope` callbacks that read-then-write `scopeCountsRef.current`.
**First seen**: 2026-04-30 (PLAN-0059-B DS review).

**Symptoms**:
- Two dialogs mounting simultaneously both push `"modal"` scope.
- Both callbacks read `prev === 0`, so both call `setActiveScopes` with `prev === 0` condition true.
- One of the two increment operations is lost — effective count is 1 not 2.
- On unmount of the first dialog: `popScope` decrements to 0 and removes the modal scope.
- Second dialog is now open but global chords are no longer suppressed → pressing `g d` navigates away while the dialog is visible.

**Root Cause**:
`useRef`-based mutable counters read and written in `useCallback` are not atomic in React 18's concurrent rendering model. Two effects can interleave their reads before either has written.

**Fix**:
Use `useState` with a functional updater for the scope count map — functional updaters are queued and applied serially:
```ts
const [scopeCounts, setScopeCounts] = useState<Map<HotkeyScope, number>>(new Map());
const pushScope = useCallback((scope: HotkeyScope) => {
  setScopeCounts(prev => {
    const count = prev.get(scope) ?? 0;
    return new Map(prev).set(scope, count + 1);
  });
}, []);
```
Derive `activeScopes` from `scopeCounts` via `useMemo`.

**Prevention**:
- Any ref-based counter that must be consistent across concurrent renders should be `useState` with functional updater.
- Add `__tests__/hotkey-context.test.tsx` with concurrent push/pop tests using `act()` to catch regressions.

---

## BP-306 — `useEffect` Dependency on Derived-Array Identity → Spurious or Infinite Fires

**Affected areas**: any component that derives an array via `.map(...)` / `getXxxRowModel().rows.map(...)` inside `useMemo` and uses that derived array as a `useEffect` dep. Originated in `apps/worldview-web/components/ui/data-table/data-table.tsx` (`onSelectionChange` notification effect).

**First seen**: 2026-05-01 (PLAN-0059 Wave F QA iter-1, correctness agent).

**Symptoms**:
- `selectedRows = useMemo(() => table.getSelectedRowModel().rows.map(r => r.original), [rowSelection, data])`.
- Parent passes a new `data` reference each render (extremely common with TanStack Query refetches).
- New `data` → memo recomputes → new `selectedRows` array identity → `useEffect([selectedRows])` fires `onSelectionChange` even though selection didn't change.
- If the consumer's `onSelectionChange` triggers parent state that changes `data`, the loop becomes infinite.

**Root Cause**:
Effect dep is a derived-array reference, not the underlying state that drives it. Array literal `===` comparison fails on every render that recreates the array.

**Fix**:
Depend on a STABLE STRING KEY of the underlying state:
```ts
const selectionKey = useMemo(() => Object.keys(rowSelection).sort().join(","), [rowSelection]);
useEffect(() => {
  const sel = table.getSelectedRowModel().rows.map(r => r.original); // recompute lazily
  onSelectionChange?.(sel);
}, [selectionKey, table, onSelectionChange]);
```

**Prevention**:
- For `useEffect` deps, prefer the SCALAR state that drives the derived value.
- For arrays of stable IDs, derive a key string (`ids.sort().join(",")`).
- Lint rule: flag `useEffect` deps that are array-typed and produced inside the same render.

---

---
