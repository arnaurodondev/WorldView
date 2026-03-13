# Distributed System Patterns

> **Purpose**: Structural failure patterns specific to distributed execution environments —
> Spark, Kafka, async microservices, and multi-node scheduling.
> Cross-reference with [STORAGE_ATOMICITY_PATTERNS.md](STORAGE_ATOMICITY_PATTERNS.md)
> for storage-specific patterns.

---

## Pattern DS-001 — Driver/Executor Context Confusion

**Symptom**: Code that works in local mode fails on a cluster, or behaves differently
per executor.

**Root cause**: Code running on the Spark driver accesses resources (files, env vars,
credentials, loggers, DB connections) that are not available on executors, or vice versa.

**High-risk patterns**:

```python
# WRONG — filesystem path valid on driver; does not exist on executors
rdd.map(lambda x: open("/local/driver/path/file.txt").read())

# WRONG — logger initialized on driver; not serializable to executors
logger = logging.getLogger(__name__)
rdd.foreach(lambda x: logger.info(x))  # serialization error or silent failure

# WRONG — env var read on driver; not propagated to executors
API_KEY = os.environ["API_KEY"]
rdd.map(lambda x: call_api(API_KEY, x))  # may fail on executors
```

**Correct patterns**:

```python
# CORRECT — read file contents on driver, broadcast to executors
file_content = sc.broadcast(open("/local/path/file.txt").read())
rdd.map(lambda x: process(file_content.value, x))

# CORRECT — use structlog with Spark-compatible serialization
# or initialize logger inside the lambda (per-executor init)
rdd.foreach(lambda x: structlog.get_logger().info("event", value=x))
```

---

## Pattern DS-002 — Non-Deterministic Join Ordering

**Symptom**: Join output order varies across runs; downstream code assumes stable ordering
and produces incorrect results.

**Root cause**: SQL / Spark joins do not guarantee output ordering unless `ORDER BY` is
explicit. Shuffle partitioning introduces non-deterministic ordering.

**High-risk patterns**:

```python
# WRONG — no ORDER BY; output order is non-deterministic
result = spark.sql("SELECT * FROM a JOIN b ON a.id = b.id")
first_row = result.collect()[0]  # may differ per run

# WRONG — assumes positional alignment after join
df_joined = df_a.join(df_b, "id")
values = [row.value for row in df_joined.collect()]
labels = original_labels  # alignment broken if ordering changed
```

**Correct patterns**:

```python
# CORRECT — explicit ORDER BY guarantees deterministic output
result = spark.sql("SELECT * FROM a JOIN b ON a.id = b.id ORDER BY a.id")

# CORRECT — carry labels through the join instead of relying on position
df_a_with_labels = df_a.join(df_b.select("id", "label"), "id")
```

---

## Pattern DS-003 — `collect()` on Unbounded Dataset (OOM)

**Symptom**: Spark job fails with driver OOM; or succeeds locally (small data) but crashes
in production (large data).

**Root cause**: `collect()` pulls all partitions to the driver. If the dataset grows
beyond driver memory, the driver is killed.

**High-risk patterns**:

```python
# WRONG — pulls entire dataset to driver; OOM at scale
rows = df.collect()
for row in rows:
    process(row)

# WRONG — count via collect (use df.count() instead)
n = len(df.collect())
```

**Correct patterns**:

```python
# CORRECT — process in distributed fashion
df.foreach(process_row)

# CORRECT — use Spark's native count
n = df.count()

# CORRECT — if collect is necessary, limit first and document the assumption
sample = df.limit(1000).collect()
```

---

## Pattern DS-004 — Per-Column Spark Actions (N+1 Problem)

**Symptom**: Pipeline runs extremely slowly; Spark UI shows thousands of jobs.

**Root cause**: A loop calls a Spark action (`.collect()`, `.count()`, `.toPandas()`)
for each column individually, triggering a full DAG execution per iteration.

**High-risk patterns**:

```python
# WRONG — triggers a full Spark job per column
for col in df.columns:
    stats[col] = df.select(col).describe().collect()

# WRONG — triggers a full Spark job per feature
for feature in feature_list:
    importance = model.featureImportances[feature_index[feature]]
```

**Correct patterns**:

```python
# CORRECT — single pass over all columns
stats = df.describe().collect()

# CORRECT — extract all importances at once
importances = model.featureImportances.toArray()
importance_map = {f: importances[i] for i, f in enumerate(feature_list)}
```

---

## Pattern DS-005 — Kafka Consumer Non-Idempotency

**Symptom**: Re-delivered Kafka messages cause duplicate DB rows, duplicate Kafka publishes,
or duplicate side effects.

**Root cause**: Consumer does not check whether the event has already been processed.
At-least-once delivery guarantees re-delivery on consumer restart or rebalance.

**High-risk patterns**:

```python
# WRONG — no idempotency check; duplicate on re-delivery
async def handle_event(event: IngestEvent):
    await repository.create(parse(event))
    await uow.commit()
```

**Correct patterns**:

```python
# CORRECT — check event_id dedup before processing
async def handle_event(event: IngestEvent):
    if await ingestion_event_repo.exists(event.event_id):
        logger.info("duplicate_event_skipped", event_id=event.event_id)
        return
    await repository.create(parse(event))
    await ingestion_event_repo.create(IngestionEvent(event_id=event.event_id))
    await uow.commit()
```

---

## Pattern DS-006 — Race Condition in Claim/Dispatch Pattern

**Symptom**: Two outbox dispatcher workers claim and dispatch the same event; downstream
consumer receives duplicate messages.

**Root cause**: Claim operation is not atomic, or lease expiry is not enforced before
re-claim.

**High-risk patterns**:

```python
# WRONG — non-atomic read-then-claim; two workers can claim the same record
events = await repo.find_pending()
for event in events:
    await repo.update_status(event.id, "CLAIMED")  # race window here
```

**Correct patterns**:

```python
# CORRECT — atomic claim using SELECT ... FOR UPDATE SKIP LOCKED
# or using a WHERE clause that checks current status
await repo.claim(event_id, worker_id, lease_expires_at)
# claim() uses: UPDATE outbox_events SET status='CLAIMED', claimed_by=:worker
# WHERE id=:id AND status='PENDING'
# returning 0 rows = already claimed by another worker
```

---

## Pattern DS-007 — Serialization Failure in Distributed Closure

**Symptom**: Spark job fails with `PicklingError` or `SerializationException` when
a lambda or function is distributed to executors.

**Root cause**: The closure captures an object that is not serializable (e.g., a DB
connection, a logger, a file handle, a lambda with a bound `self`).

**High-risk patterns**:

```python
# WRONG — DB session captured in closure; not serializable to executors
session = create_session()
df.foreach(lambda row: session.add(parse(row)))

# WRONG — class method used as lambda; captures self (may be non-serializable)
df.foreach(self.process_row)
```

**Correct patterns**:

```python
# CORRECT — create connection inside executor (per-partition)
def process_partition(rows):
    session = create_session()
    for row in rows:
        session.add(parse(row))
    session.commit()

df.foreachPartition(process_partition)

# CORRECT — use static method or module-level function
df.foreach(process_row_static)
```
