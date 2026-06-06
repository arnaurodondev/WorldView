# Investigation: AGE TemporalEvent Sync Failure

**Date:** 2026-05-26
**Finding:** F-DB-002 (CRITICAL) — 0 of 14,822 TemporalEvent nodes labeled in AGE after T-B-1-01 fix deployed.
**System:** Knowledge Graph Service (S7), Apache AGE property-graph extension on PostgreSQL
**Commits involved:** T-B-1-01 `_bootstrap_age_labels`, T-B-1-02 per-phase watermarks, T-B-1-03 stall detector

---

## Symptom

External QA at commit `53b2c8a1` reported: `age_sync_worker` logs "age_sync_labels_bootstrapped" + "age_sync_temporal_events_complete" (suggesting 2000 nodes synced per cycle), yet:

```bash
SELECT COUNT(*) FROM cypher('worldview_graph', $$ MATCH (n:TemporalEvent) RETURN count(n) $$)
# Returns: 0
```

Meanwhile:
```sql
SELECT COUNT(*) FROM temporal_events  # SQL table
# Returns: 14,822
```

The relational table has 14,822 rows; the AGE property graph has zero TemporalEvent vertices. **This violates the idempotent MERGE contract.** If the SQL rows existed before the fix was deployed, `_bootstrap_age_labels` should have created the vlabel, and the next MERGE should have populated AGE. The 100% failure rate suggests **labels never took effect** or **MERGE silently fails without error**.

---

## Bootstrap Code Path

### Entry Point
1. `KnowledgeGraphScheduler._register_jobs()` (scheduler.py:168) registers "age_sync" job with 120-second boot delay
2. `scheduler_main.py:208` calls `scheduler.start()`, which invokes `_register_jobs()` → APScheduler adds the job
3. After 120 seconds, APScheduler calls `AgeSyncWorker.run()`

### Bootstrap Execution (`age_sync_worker.py:238–282`)

```python
async def run(self) -> None:
    if not self._settings.cypher_enabled:
        logger.debug("age_sync_worker_disabled")
        return

    # T-B-1-01: bootstrap on first run only
    if self._labels_bootstrap_pending:
        try:
            await self._bootstrap_age_labels(session)  # ← executed once per process lifetime
            self._labels_bootstrap_pending = False
        except ProgrammingError as exc:
            # AGE extension missing → skip entire cycle
            logger.warning("age_sync_age_unavailable", ...)
            return  # ← exits early if bootstrap fails

    # If bootstrap succeeded, proceed to three phases
    entities_synced = await self._run_phase(phase='entities', ...)
    relations_synced = await self._run_phase(phase='relations', ...)
    temporal_events_synced = await self._run_phase(phase='temporal_events', ...)
```

### Bootstrap Implementation (`age_sync_worker.py:447–483`)

```python
async def _bootstrap_age_labels(self, session: AsyncSession) -> None:
    statements = [
        f"SELECT create_vlabel('{_AGE_GRAPH_NAME}', 'entity')",
        f"SELECT create_vlabel('{_AGE_GRAPH_NAME}', 'TemporalEvent')",
        *[f"SELECT create_elabel('{_AGE_GRAPH_NAME}', '{lbl}')" for lbl in sorted(_VALID_EDGE_LABELS)],
    ]
    await _setup_age_session(session)
    for stmt in statements:
        try:
            await session.execute(text(stmt))
        except ProgrammingError as exc:
            msg = str(exc).lower()
            if "already exists" in msg:
                continue  # ← idempotent: swallow "label already exists"
            raise  # ← re-raise other ProgrammingErrors
    await session.commit()  # ← single commit at end
    logger.info("age_sync_labels_bootstrapped", vlabels=2, elabels=len(_VALID_EDGE_LABELS))
```

---

## Reproduction

### Step 1: Check AGE Label Existence
```bash
docker exec worldview-postgres-1 psql -U worldview -d intelligence_db -c \
  "SELECT label, count(*) FROM ag_catalog.ag_label WHERE name='TemporalEvent' GROUP BY label;"
```

Expected output if bootstrap succeeded:
```
 label | count
-------+-------
  true |     1
```

Actual (from QA finding): **0 rows** → label never registered.

### Step 2: Check SQL Table Count
```bash
docker exec worldview-postgres-1 psql -U worldview -d intelligence_db -c \
  "SELECT COUNT(*) FROM temporal_events;"
```

Expected: 14,822 rows (existing data)

### Step 3: Try Direct Cypher Query
```bash
docker exec worldview-postgres-1 psql -U worldview -d intelligence_db << 'SQL'
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT * FROM cypher('worldview_graph', $$
  MATCH (n:TemporalEvent)
  RETURN count(n) AS cnt
$$) AS (cnt agtype);
SQL
```

Expected: 14,822
Actual (from QA): **0** or possibly **ERROR: label does not exist**

### Step 4: Inspect Watermark State
```bash
docker exec worldview-postgres-1 redis-cli -h worldview-valkey-1 GET "s7:age:sync:watermark:temporal_events"
```

If watermark is set but count is 0 → MERGE statements ran but didn't insert data.
If watermark is missing → phase never ran (bootstrap failed early).

---

## Root Cause Analysis

### Hypothesis 1: `_bootstrap_age_labels` never ran
- **Evidence:** No "age_sync_labels_bootstrapped" log entry
- **Mechanism:** Bootstrap is gated by `KNOWLEDGE_GRAPH_CYPHER_ENABLED` (default false; must be `true`)
- **Fix:** Check if the setting was actually true in the container's environment at startup
- **Probability:** HIGH if `cypher_enabled=false` in config

### Hypothesis 2: Bootstrap ran but `create_vlabel` silently failed
- **Evidence:** "age_sync_labels_bootstrapped" logged, but vertices never appear
- **Mechanism:** Line 469 executes `text(stmt)`, but:
  1. **AGE session not properly initialized:** `_setup_age_session(session)` calls `LOAD 'age'` and `SET search_path`, but if the session's **prepared statement handle is closed or reset after each commit**, the next Cypher query sees a fresh session that has NOT loaded AGE
  2. **Missing LOAD 'age' between bootstrap and phase execution:** Bootstrap commits (line 478), which may clear the AGE session state. `_run_phase` calls `_setup_age_session(session)` again (scheduler.py:358) **but only AFTER bootstrap completes** — if the original session's AGE is cleared by commit, the label creation might not persist to the logical graph object
  3. **Label creation and query target different graph names:** The bootstrap uses hardcoded `'worldview_graph'` (line 460), and the MERGE also uses `'worldview_graph'` (line 107). **If the string interpolation or graph name resolution differs**, they could be operating on separate logical graphs.

### Hypothesis 3: Transaction isolation issue — labels created but not committed visibly
- **Evidence:** Bootstrap successfully logs, but subsequent Cypher queries see 0 labels
- **Mechanism:**
  1. `session.commit()` at line 478 is an async commit on SQLAlchemy AsyncSession
  2. AGE Cypher MERGE statements at line 685 execute **in the same session context after bootstrap**
  3. If the session's transaction isolation level is not READ COMMITTED or the label creation happened in a nested savepoint that wasn't fully flushed, subsequent MERGEs could fail to see the labels
  4. **No intermediate flush between bootstrap and phase execution:** The bootstrap calls `session.commit()` (line 478), then _run_phase is called. Each _run_phase ALSO calls `_setup_age_session` (line 358) and `session.commit()` (line 360) after syncing. But **no intermediate commit occurs between bootstrap and the first MERGE in the temporal_events phase**. If AGE Cypher requires an explicit `LOAD 'age'` call AND a fresh transaction to see newly created labels, the labels might be invisible to the MERGEs.

### **Root Cause: Most Likely**

**Lines 238–282 execute bootstrap + phases in the same session, but AGE Cypher label creation requires that labels be queried in a **separate session or after an explicit schema refresh**.**

The flow is:
1. `_bootstrap_age_labels(session)` → creates `TemporalEvent` vlabel in session
2. `session.commit()` → commits the label creation
3. `_run_phase(..., session, ...)` → enters `_sync_temporal_events(session)`
4. Inside `_sync_temporal_events`, line 685 executes MERGE targeting `:TemporalEvent`
5. **But the session is the SAME AsyncSession object.** If PostgreSQL's plpgsql engine (which backs `ag_catalog.cypher()`) **caches the schema for that session**, the newly created label from step 2 may not be visible in step 4 until the session reconnects or the schema cache is invalidated.

**Evidence for this theory:**
- `_setup_age_session(session)` (line 465) is called ONCE before the bootstrap loop
- `_setup_age_session(session)` (line 358) is called again inside `_run_phase`, but **only AFTER the bootstrap has already completed**
- The label lookup for a MERGE in an AGE Cypher context may cache the schema at the moment `LOAD 'age'` is executed, which was during bootstrap
- **No explicit schema refresh between bootstrap and phase execution.**

### **Secondary Contributing Factor: Missing Idempotency Guard After Redeployment**

If the worker process was restarted with existing data (e.g., container restart, rolling deploy), `_labels_bootstrap_pending` is reset to `True` on each process startup. However:
- If the labels already exist in the graph (from a previous run), the bootstrap loop catches the "already exists" exception and continues
- But if **the session's schema cache doesn't see the existing labels** (same root cause as above), the bootstrap appears to succeed (no exception), logs "labels_bootstrapped", but the labels are still invisible to the MERGE statements in the same session

---

## Fix Sketch

### Option A: Force Session Invalidation (Recommended)

After `session.commit()` in bootstrap (line 478), **explicitly invalidate or reconnect the session** so that AGE Cypher sees the updated schema:

```python
await session.commit()
# Force the session to drop its connection so the next MERGE sees fresh schema
await session.close()
# OR: restart the session by rolling back and re-entering a new transaction
await session.connection.invalidate()
```

Then, ensure `_run_phase` calls `_setup_age_session` on the **new session state**.

### Option B: Move Bootstrap to a Separate Session

Create a dedicated session just for bootstrap, separate from the phase-execution session:

```python
async with self._sf() as bootstrap_session:
    await self._bootstrap_age_labels(bootstrap_session)
    await bootstrap_session.commit()
    await bootstrap_session.close()

# Now run phases on a fresh session
async with self._sf() as phase_session:
    await self._run_phase(..., session=phase_session, ...)
    ...
```

This ensures the bootstrap and phases never share AGE session state.

### Option C: Add Explicit Label Verification After Bootstrap

After bootstrap, verify that labels exist before proceeding to phases:

```python
if self._labels_bootstrap_pending:
    try:
        await self._bootstrap_age_labels(session)
        # NEW: verify labels were created
        verify_sql = (
            "SELECT COUNT(*) FROM ag_catalog.ag_label "
            "WHERE name IN ('entity', 'TemporalEvent')"
        )
        result = await session.execute(text(verify_sql))
        count = result.scalar()
        if count < 2:
            raise ProgrammingError(
                f"Label bootstrap appears to have failed: "
                f"expected 2 vlabels, found {count}",
                "",
                ""
            )
        self._labels_bootstrap_pending = False
    except ProgrammingError as exc:
        # ... existing error handling
```

---

## Test Plan

### Unit Test (Minimal)

Add a test that:
1. Mocks the session and validator to track `_setup_age_session` call count
2. Invokes `worker.run()` with a fresh worker instance (`_labels_bootstrap_pending=True`)
3. Verifies:
   - `session.commit()` is called at least 2 times (once for bootstrap, once for first phase)
   - Bootstrap's `_setup_age_session` and the first phase's `_setup_age_session` are called on **different session contexts** (if using Option B) or the same session is **reconnected/invalidated** between calls (if using Option A)

```python
async def test_bootstrap_separate_from_phases():
    """Verify that label bootstrap and phase execution don't share AGE session state."""
    worker = AgeSyncWorker(...)
    worker._labels_bootstrap_pending = True

    # Track session.execute calls
    execute_call_count = 0
    original_execute = worker._sf().__aenter__.execute

    async def tracked_execute(*args, **kwargs):
        nonlocal execute_call_count
        execute_call_count += 1
        return original_execute(*args, **kwargs)

    # Mock + verify
    with patch.object(worker._sf(), 'execute', tracked_execute):
        await worker.run()

    # Verify bootstrap happened
    assert worker._labels_bootstrap_pending == False
    assert execute_call_count > 2  # bootstrap + phases
```

### Integration Test (QA)

On a fresh intelligence_db instance:
1. Start the scheduler with `KNOWLEDGE_GRAPH_CYPHER_ENABLED=true`
2. Seed temporal_events table with 10 rows
3. Wait for the first `age_sync` worker cycle to complete (120s boot delay + execution)
4. Query: `SELECT COUNT(*) FROM cypher('worldview_graph', $$ MATCH (n:TemporalEvent) RETURN count(n) $$)`
5. Assert count == 10 (or close, allowing for timing differences)

### Stress Test

Verify idempotency under worker restarts:
1. Deploy schema with 100 seeded temporal_events
2. Restart the scheduler container (which resets `_labels_bootstrap_pending=True`)
3. Run the worker cycle 3 times in a row
4. Assert AGE count stays stable (no duplicates, no loss)

---

## Severity

**P0 (Critical)**

- **Impact:** 100% of TemporalEvent data is unreachable via Cypher path queries
- **Scope:** Any AGE graph traversal for entity relationships fails silently
- **User-facing:** Path discovery (`GET /entities/{id}/paths`) returns 0 results instead of the correct neighborhood
- **Duration:** Deployed in PLAN-0093 Wave B-1 (commit ~53b2c8a1); fix window TBD

---

## Next Steps

1. **Confirm hypothesis** — Check logs for "age_sync_labels_bootstrapped" + first-run timestamps
2. **Test Option B or A** in a staging container
3. **Update unit tests** to catch the session isolation bug
4. **Add monitoring** — Instrument the label-existence check so future QA audits surface this instantly
