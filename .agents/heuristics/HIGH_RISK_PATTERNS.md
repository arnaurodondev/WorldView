# High-Risk Patterns

> **Purpose**: A catalog of code patterns that signal elevated risk during PR review.
> When any of these patterns are spotted in a diff, immediately escalate to the
> full investigation protocol for the affected function.
>
> These are not automatically bugs — they are signals that require investigation.
> Treat each as a hypothesis: "this might be broken" until the investigation proves otherwise.

---

## Risk Level Classification

| Level | Meaning |
|-------|---------|
| RED | Almost always a bug. Block the PR and investigate immediately. |
| ORANGE | Frequently a bug. Investigate before approving. |
| YELLOW | Sometimes a bug, depending on context. Note and verify. |

---

## Category 1 — Exception Handling

### HR-001 (RED) — `except Exception` with no re-raise

```python
except Exception as e:
    logger.error(...)
    # no raise — execution continues
```

**Why red**: Caller assumes success. System state may be partial. Error is invisible upstream.

**Investigate**: What is the system state after this exception? Can the caller detect the failure?

---

### HR-002 (RED) — Empty except

```python
except Exception:
    pass
```

**Why red**: Exception is completely swallowed. No log, no raise, no signal.

---

### HR-003 (ORANGE) — Broad except in finally

```python
finally:
    try:
        cleanup()
    except Exception:
        pass  # or logger.warning(...)
```

**Why orange**: Can mask cleanup failures. Acceptable only if the original exception is already
propagated. Verify that the original exception takes precedence.

---

### HR-004 (ORANGE) — Return inside except

```python
except Exception as e:
    logger.error(...)
    return None  # or return False, or return {}
```

**Why orange**: Caller receives a "soft failure" response and may treat it as partial success.

---

## Category 2 — Storage Writes

### HR-005 (RED) — Direct write to final path in a loop

```python
for obj in objects:
    s3.copy(obj.key, f"{FINAL_PREFIX}/{obj.key}")
```

**Why red**: Partial write is visible to readers on failure midway. Violates SA-001.

---

### HR-006 (RED) — No `finally` block around resource acquisition

```python
tmp_dir = tempfile.mkdtemp()
upload_to_s3(tmp_dir, dest)  # if this fails, tmp_dir is never cleaned up
shutil.rmtree(tmp_dir)
```

**Why red**: Resource leak on failure. May also leave stale data for retries.

---

### HR-007 (ORANGE) — `session.add()` without `commit()` in scope

```python
session.add(entity)
# session.commit() not visible in this function
# caller may not commit either
```

**Why orange**: Data is buffered but not persisted. Connection close or rollback discards it silently.

---

### HR-008 (ORANGE) — DB write followed immediately by external write (no outbox)

```python
await session.commit()       # DB write confirmed
await kafka_producer.send()  # external write — can fail; DB already committed
```

**Why orange**: Violates SA-005. Dual-write without atomicity guarantee.

---

## Category 3 — Distributed Execution

### HR-009 (RED) — `.collect()` with no size guard

```python
rows = df.collect()
```

**Why red**: Driver OOM at scale. Violates DS-003.

**Look for**: Is there a `.limit(N)` before the collect? Is there a documented size assumption?

---

### HR-010 (RED) — Spark action inside Python loop

```python
for col in columns:
    stats = df.select(col).describe().collect()
```

**Why red**: N+1 Spark job problem. Violates DS-004.

---

### HR-011 (ORANGE) — Driver-side resource in closure

```python
logger = logging.getLogger()
df.foreach(lambda row: logger.info(row))
```

**Why orange**: Logger not serializable to executors. Violates DS-001.

---

### HR-012 (ORANGE) — Positional index on join result

```python
result = df_a.join(df_b, "id").collect()
first = result[0]  # assumes stable ordering
```

**Why orange**: Join output ordering is non-deterministic without `ORDER BY`. Violates DS-002.

---

## Category 4 — Kafka / Messaging

### HR-013 (RED) — Consumer handler with no duplicate check

```python
async def handle(event: Event):
    await repo.create(parse(event))
    await uow.commit()
    # no event_id dedup check
```

**Why red**: At-least-once delivery causes duplicate rows on re-delivery. Violates DS-005.

---

### HR-014 (ORANGE) — Outbox dispatcher claim with two queries

```python
events = await repo.find_pending()  # query 1
for event in events:
    await repo.update_status(event.id, "CLAIMED")  # query 2 — race window
```

**Why orange**: Race condition — two workers can claim the same record. Violates DS-006.

---

### HR-015 (RED) — `KafkaEventValueSerializer` used in outbox dispatcher

```python
value_serializer = KafkaEventValueSerializer(self._serializers)
```

**Why red**: Must use `OutboxEventValueSerializer` to extract `.payload` before Avro encoding.
Violates BP-001.

---

## Category 5 — Data Pipelines

### HR-016 (RED) — Scaler/encoder fit before train/test split

```python
X_scaled = scaler.fit_transform(X)  # fit on full dataset
X_train, X_test = train_test_split(X_scaled)
```

**Why red**: Data leakage — test set information influences the scaler.

---

### HR-017 (ORANGE) — Filter applied to features but not labels

```python
X = X[X["col"] > threshold]
# y not filtered — arrays now misaligned
```

**Why orange**: Silent label misalignment. Model trains on wrong label pairs.

---

### HR-018 (ORANGE) — MLflow `end_run()` before artifact upload

```python
mlflow.end_run()
upload_model(model, artifact_path)  # run already marked FINISHED
```

**Why orange**: If upload fails, run appears FINISHED but artifacts are missing.

---

## Category 6 — General Code Quality Signals

### HR-019 (YELLOW) — Naive datetime

```python
datetime.now()           # no timezone
datetime.utcnow()        # deprecated; still naive
```

**Why yellow**: Timezone-aware datetimes are required. `datetime.now(tz=timezone.utc)` or
`utc_now()` from `libs/common`.

---

### HR-020 (YELLOW) — `os.getcwd()` or relative path

```python
path = os.getcwd() + "/data"
path = "./config/settings.yaml"
```

**Why yellow**: Breaks in containers and CI where the working directory differs from
local development.

---

### HR-021 (YELLOW) — `print()` instead of `structlog`

```python
print(f"Processing {n} records")
```

**Why yellow**: Violates AGENTS.md logging standard. Structured logging required everywhere.
