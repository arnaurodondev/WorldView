# Storage Atomicity Patterns

> **Purpose**: Structural failure patterns specific to storage operations — S3/MinIO,
> local filesystem, and database writes. These patterns define when readers can
> observe partial state and how to prevent it.

---

## Pattern SA-001 — Partial Writes Visible to Readers

**Symptom**: A copy loop writes files to the final destination object by object.
A failure midway leaves an incomplete prefix. Downstream readers observe partial state
and silently process incomplete data.

**Impact**: Silent data corruption. Readers that check only for prefix existence
(not completeness) process partial artifacts and produce incorrect results.

**Anti-pattern**:

```python
# WRONG — copies objects directly to final prefix; partial write visible on failure
for obj in source_objects:
    s3.copy(obj.key, f"{final_prefix}/{obj.key}")
    # failure here: final_prefix contains some but not all objects
```

**Correct implementation**:

```python
# CORRECT — stage to temp prefix; copy to final; delete on failure
staging_prefix = f"{final_prefix}/_staging/{uuid4()}"
try:
    for obj in source_objects:
        s3.copy(obj.key, f"{staging_prefix}/{obj.key}")
    # all objects copied to staging — now atomic copy to final
    for obj in source_objects:
        s3.copy(f"{staging_prefix}/{obj.key}", f"{final_prefix}/{obj.key}")
except Exception:
    # roll back: delete anything written to final
    s3.delete_prefix(final_prefix)
    raise
finally:
    s3.delete_prefix(staging_prefix)
```

**Rule**: Final destination must be either **complete** or **empty**. Never partial.

---

## Pattern SA-002 — No Cleanup on Failure (Resource Leak)

**Symptom**: On failure, temp directories, temp S3 prefixes, or lock files are not
cleaned up. Over time, orphaned resources accumulate and consume storage.

**Secondary impact**: If a retry reuses the same temp path, it may find stale data
from the failed run and produce incorrect results.

**Anti-pattern**:

```python
# WRONG — no cleanup on failure
def upload_model(pipeline, dest):
    tmp_dir = tempfile.mkdtemp()
    serialize(pipeline, tmp_dir)
    upload_to_s3(tmp_dir, dest)
    shutil.rmtree(tmp_dir)  # never reached on upload failure
```

**Correct implementation**:

```python
# CORRECT — cleanup in finally block
def upload_model(pipeline, dest):
    tmp_dir = tempfile.mkdtemp()
    try:
        serialize(pipeline, tmp_dir)
        upload_to_s3(tmp_dir, dest)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
```

**Rule**: Resource creation must always be paired with cleanup in a `finally` block.
The `finally` block must handle its own exceptions (use `ignore_errors=True` or try/except
inside finally) to avoid masking the original exception.

---

## Pattern SA-003 — Cleanup Exception Masks Original Exception

**Symptom**: The caller receives a `FileNotFoundError` (from cleanup) instead of the
real `S3UploadError` (from the actual failure). The original failure cause is invisible.

**Anti-pattern**:

```python
# WRONG — finally block can raise, replacing the original exception
def upload_model(pipeline, dest):
    tmp_dir = tempfile.mkdtemp()
    try:
        upload_to_s3(tmp_dir, dest)  # raises S3UploadError
    finally:
        shutil.rmtree(tmp_dir)  # raises FileNotFoundError if dir already gone
        # FileNotFoundError replaces S3UploadError — original cause is lost
```

**Correct implementation**:

```python
# CORRECT — cleanup exceptions do not replace the original
def upload_model(pipeline, dest):
    tmp_dir = tempfile.mkdtemp()
    try:
        upload_to_s3(tmp_dir, dest)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)  # suppresses cleanup errors
```

---

## Pattern SA-004 — Silent Write Success (Return Value Ignored)

**Symptom**: Storage write appears to succeed (no exception) but the data was not
actually persisted. The write silently fails at a lower layer.

**Common triggers**:

- `boto3` S3 client returns a response dict; failures are indicated by HTTP status
  codes in the response, not exceptions, if error handling is misconfigured.
- SQLAlchemy `add()` + `flush()` without `commit()` — data is in the session but not
  persisted; rollback on connection close silently discards it.
- `asyncio` task fire-and-forget — write is dispatched but result never awaited.

**Anti-pattern**:

```python
# WRONG — write result never checked; silent failure possible
s3_client.put_object(Bucket=bucket, Key=key, Body=data)
# response contains {'ResponseMetadata': {'HTTPStatusCode': 403}} — ignored
```

**Correct implementation**:

```python
# CORRECT — check response status explicitly
response = s3_client.put_object(Bucket=bucket, Key=key, Body=data)
status = response["ResponseMetadata"]["HTTPStatusCode"]
if status != 200:
    raise StorageError(f"S3 put_object failed with status {status}")

# OR — use the high-level resource API which raises on error
s3_resource.Object(bucket, key).put(Body=data)
```

---

## Pattern SA-005 — Non-Atomic Database + External Write

**Symptom**: A DB write and an external write (S3, Kafka, MLflow) both succeed on the
happy path, but on failure, one succeeds and the other fails. The system enters an
inconsistent state that cannot be recovered by retry.

**Anti-pattern**:

```python
# WRONG — two separate writes; atomicity not guaranteed
async def save_run(run: MLRun):
    await db.save(run)           # DB succeeds
    await mlflow.log_params(run)  # MLflow fails — DB has record, MLflow does not
```

**Correct patterns**:

```python
# OPTION A — outbox pattern (preferred for Kafka)
async def save_run(run: MLRun):
    async with uow:
        uow.repo.add(run)
        uow.collect_event(RunCreated(run_id=run.id))
        await uow.commit()  # DB + outbox row are atomic
    # outbox dispatcher sends to Kafka asynchronously

# OPTION B — compensating transaction (for external services without outbox support)
async def save_run(run: MLRun):
    try:
        await mlflow.log_params(run)  # external write first
        await db.save(run)            # DB write second
    except Exception:
        await mlflow.delete_run(run.id)  # compensate external write
        raise
```

---

## Pattern SA-006 — Over-Broad Except Swallows Storage Errors

**Symptom**: A storage failure (disk full, S3 permission denied, DB connection lost)
is caught by a broad `except` clause, logged, and execution continues. The caller is
never informed of the failure.

**Anti-pattern**:

```python
# WRONG — storage errors silently suppressed
def save_artifact(data, path):
    try:
        with open(path, "wb") as f:
            f.write(data)
    except Exception as e:
        logger.warning("save_failed", error=str(e))
        # returns None — caller assumes success
```

**Correct implementation**:

```python
# CORRECT — log and re-raise
def save_artifact(data, path):
    try:
        with open(path, "wb") as f:
            f.write(data)
    except OSError as e:
        logger.error("save_artifact_failed", path=path, error=str(e))
        raise  # let caller decide how to handle

# OR — wrap in domain exception
def save_artifact(data, path):
    try:
        with open(path, "wb") as f:
            f.write(data)
    except OSError as e:
        raise StorageError(f"Failed to save artifact to {path}") from e
```

**Rule**: Storage errors are always fatal or retryable — never silently suppressed.
