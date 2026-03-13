# Failure Mode Analysis

> **Purpose**: A structured procedure for enumerating failure modes of every
> function in a code change. Used as a sub-procedure within
> [PR_INVESTIGATION_PROTOCOL.md](PR_INVESTIGATION_PROTOCOL.md) (Steps 2–3).

---

## Procedure

For **every function** in the change surface:

### 1. List all failure modes

Break the function into numbered steps (see Step 3 of the protocol).
For each step, enumerate what can go wrong:

```
Function: <name>

Steps:
  1. <step description>
  2. <step description>
  ...
  N. <step description>

Failure modes:
  [Step 1] — <failure description>
  [Step 2] — <failure description>
  ...
  [Step N] — <failure description>
  [Cross-step] — <failure that spans multiple steps, e.g., partial write>
```

### 2. For each failure mode, determine

```
Resulting system state:
  - What external state is left behind? (files, DB rows, S3 objects, Kafka messages)
  - Is the state consistent or partially written?

Recovery possible:
  - Can the caller retry safely?
  - Is there a cleanup mechanism?
  - Does the caller know the failure occurred?

Caller-visible outcome:
  - Exception raised? (type, message)
  - Silent failure? (returns None, returns empty, logs and continues)
  - Incorrect success? (returns success but state is wrong)
```

---

## Severity Classification

| Severity | Criteria |
|----------|----------|
| CRITICAL | Silent data corruption, partial writes visible to readers, security boundary bypass |
| HIGH | Unhandled exception that crashes the process, retry causes duplicate writes, invariant violated |
| MEDIUM | Exception swallowed with no re-raise, cleanup skipped on failure path, idempotency not guaranteed |
| LOW | Missing log context, performance degradation under load, edge case with no data impact |

---

## Common Failure Mode Templates

### Template: Multi-step storage operation

```
Function: <upload_X / save_X / write_X>

Failure modes:
  [Step 1 — create temp resource] failure:
    State: no temp resource exists — clean
    Recovery: safe to retry
    Caller sees: exception

  [Step 2 — write/serialize] failure:
    State: temp resource exists but is empty or partial
    Recovery: cleanup must run; if it does, safe to retry
    Caller sees: exception (if cleanup succeeds) or corrupted temp

  [Step 3 — upload/copy] failure midway:
    State: partial objects in destination prefix
    Recovery: must delete partial destination; risky if not implemented
    Caller sees: exception, but partial destination may persist

  [Step 4 — finalize/rename/copy to final] failure:
    State: temp exists (complete), final may be partial
    Recovery: must roll back final; very risky without atomicity
    Caller sees: exception, but final prefix may be corrupted

  [Step 5 — cleanup temp] failure:
    State: final is complete; temp still exists (orphaned)
    Recovery: temp garbage; functionally correct but leaks resources
    Caller sees: exception masking success — severe
```

### Template: Spark operation

```
Function: <spark_job / pipeline_step>

Failure modes:
  [Driver-side setup] failure:
    State: job not submitted
    Recovery: safe to retry
    Caller sees: exception

  [Executor-side execution] failure:
    State: partial output may exist (depends on write mode)
    Recovery: depends on output mode (overwrite vs. append)
    Caller sees: SparkException / job failure

  [collect() on large dataset] OOM:
    State: driver OOM killed
    Recovery: not possible without restart
    Caller sees: process crash, no exception in code

  [Non-deterministic join] on retry:
    State: different row ordering in output
    Recovery: outputs differ — silent correctness issue
    Caller sees: no error
```

### Template: Exception handling

```
Function: <any function with try/except>

Failure modes:
  [Exception caught, not re-raised]:
    State: external side effects may be partial
    Recovery: caller assumes success — cannot retry correctly
    Caller sees: None / empty / False — silent failure

  [Cleanup exception in finally]:
    State: original exception replaced by cleanup exception
    Recovery: original failure cause is lost
    Caller sees: wrong exception type and message

  [Broad except clause]:
    State: unexpected exceptions silently swallowed
    Recovery: none — failure is invisible
    Caller sees: apparent success
```

---

## Output Format

For each function, produce a table:

| Step | Failure mode | System state | Recovery | Caller sees | Severity |
|------|-------------|-------------|---------|-------------|---------|
| 1 | ... | ... | ... | ... | ... |
| 2 | ... | ... | ... | ... | ... |

Attach the table to the finding in the final report.
