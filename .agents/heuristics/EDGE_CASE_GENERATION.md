# Edge Case Generation

> **Purpose**: A systematic procedure for generating hypothetical inputs that reveal
> hidden failure modes. Used in Step 9 of
> [PR_INVESTIGATION_PROTOCOL.md](../investigation/PR_INVESTIGATION_PROTOCOL.md).
>
> For each function under review, apply every applicable generator below and document
> the expected vs. actual behavior.

---

## Generator 1 — Data Volume Edge Cases

Apply to any function that processes a collection (list, DataFrame, queryset, stream).

| Input | Test | Expected behavior | Actual (code reading) |
|-------|------|------------------|-----------------------|
| Empty collection (`[]`, empty DataFrame) | Call function with zero elements | Should return empty result or raise explicit error | |
| Single-element collection | Call function with exactly one element | Should process correctly | |
| Two-element collection | Useful for off-by-one boundary | Should process correctly | |
| Maximum expected size | Call with production-scale data | Should not OOM or timeout | |
| 10× maximum expected size | Stress test | Should fail gracefully, not silently corrupt | |

**High-risk patterns to check**:

```python
# WRONG — crashes on empty input
first = collection[0]        # IndexError on empty
result = sum(x) / len(x)     # ZeroDivisionError on empty

# WRONG — wrong result on single element
result = collection[:-1]     # returns empty for single-element input

# CORRECT — guard against empty
if not collection:
    return []
first = collection[0] if collection else default_value
```

---

## Generator 2 — Null / None Edge Cases

Apply to any function that receives external data (user input, API response, DB row, Kafka message).

| Input | Test | Expected behavior |
|-------|------|------------------|
| `None` in a required field | Pass `None` where a value is expected | Should raise `ValueError` / `ValidationError`, not `AttributeError` or `TypeError` |
| `None` in an optional field | Pass `None` where `None` is a valid sentinel | Should handle gracefully |
| Empty string `""` in a required field | Pass `""` where a non-empty string is expected | Should validate and reject |
| `0` in a numeric field | Pass `0` where a positive number is expected | Should validate (if 0 is invalid) or handle correctly (if 0 is valid) |
| `NaN` in a float field | Pass `float('nan')` | Should validate and reject, not silently propagate |

**High-risk patterns**:

```python
# WRONG — AttributeError if value is None
result = value.strip()

# WRONG — NaN silently propagates through arithmetic
total = price * quantity   # NaN if either is NaN

# CORRECT — validate at boundary
if value is None:
    raise ValueError("value is required")
```

---

## Generator 3 — Timestamp and Time Edge Cases

Apply to any function that processes timestamps, dates, or time ranges.

| Input | Test | Expected behavior |
|-------|------|------------------|
| Unix epoch (`1970-01-01 00:00:00 UTC`) | Boundary value test | Should handle without underflow |
| Far future (`2099-12-31`) | Boundary value test | Should handle without overflow |
| Naive datetime (no timezone) | Pass `datetime.now()` without `tzinfo` | Should raise or convert — never silently treat as UTC |
| Timezone mismatch (EST vs UTC) | Compare timestamps across timezones | Should normalize before comparison |
| Out-of-order timestamps | Pass timestamps not in ascending order | Should sort or reject depending on contract |
| Duplicate timestamps | Pass two events at the exact same instant | Should handle correctly (upsert or reject) |
| `start > end` range | Pass an inverted date range | Should raise `ValueError`, not return empty silently |

---

## Generator 4 — Schema and Type Edge Cases

Apply to any function that processes structured data (DataFrame, dict, Pydantic model, ORM model).

| Input | Test | Expected behavior |
|-------|------|------------------|
| Missing required column / field | Omit a required key | Should raise `KeyError` / `ValidationError` — not `None` default |
| Extra unexpected column / field | Add an unrecognized key | Should ignore or raise — not silently process |
| Wrong type (`str` where `int` expected) | Pass `"123"` instead of `123` | Should validate and raise — not silently coerce |
| Integer overflow | Pass `2^63` or `2^64` | Should validate or handle via `NUMERIC` type |
| Very long string | Pass 10,000-character string in a `VARCHAR(255)` field | Should truncate or raise — not silently corrupt |
| Special characters in string fields | Pass `"'; DROP TABLE --"` | Should not cause SQL injection (parameterized queries only) |
| Unicode edge cases | Pass `"\x00"` (null byte), RTL characters, emoji | Should handle or reject without crash |

---

## Generator 5 — Concurrency and Retry Edge Cases

Apply to any function that can be called concurrently or retried.

| Scenario | Test | Expected behavior |
|---------|------|------------------|
| Same call made simultaneously by two threads/workers | Concurrent execution | Should not produce duplicate writes, race conditions, or deadlocks |
| Call retried immediately after network failure | Retry with same inputs | Should produce identical final state (idempotent) |
| Call retried after partial completion (step 3 of 5 succeeded) | Retry mid-operation | Should not duplicate the already-completed steps |
| Two outbox workers claiming the same record | Concurrent claim | One should succeed; the other should receive 0 rows updated (not both succeed) |
| Kafka consumer restarted after processing but before offset commit | Replay last message | Should not produce duplicate DB row |

---

## Generator 6 — Resource and Environment Edge Cases

Apply to any function that accesses external resources.

| Scenario | Test | Expected behavior |
|---------|------|------------------|
| S3/MinIO unreachable | Network timeout on upload | Should raise, cleanup staging, not leave partial final prefix |
| DB connection lost mid-transaction | Connection reset during `commit()` | Should raise, not silently succeed |
| Disk full | `write()` fails mid-file | Should raise, not return partial file as complete |
| Missing env var | Config key not set | Should raise `ConfigurationError` at startup, not at runtime |
| Missing credentials | S3 / Kafka auth fails | Should raise explicit `AuthenticationError`, not `NullPointerException` |
| Container restart during long operation | Process killed mid-operation | External state should be clean or clearly partial — not corrupt |

---

## Generator 7 — Numeric Edge Cases

Apply to any function that performs arithmetic or financial calculations.

| Input | Test | Expected behavior |
|-------|------|------------------|
| Division by zero | Pass `0` as divisor | Should guard with explicit check — not raise unhandled `ZeroDivisionError` |
| Negative value where positive required | Pass `-1` as quantity or price | Should validate and raise — not silently produce negative output |
| Very large `Decimal` | Pass `Decimal("999999999999999.99999999")` | Should not overflow `NUMERIC(18,8)` — validate precision |
| Floating-point precision | Compare `0.1 + 0.2 == 0.3` | Should use `Decimal` or `pytest.approx` — never direct float equality |
| `Decimal` vs `float` coercion | Mix `Decimal` and `float` | Should raise `TypeError` on mixed arithmetic — not silently coerce |

---

## Output Format

For each edge case that reveals a failure, produce a finding:

```
Edge case: <generator N — description>
Function:  <function_name>
Input:     <exact test input>
Expected:  <what should happen>
Actual:    <what the code actually does — based on code reading>
Severity:  <CRITICAL / HIGH / MEDIUM / LOW>
Fix:       <specific recommendation>
```

Pass all CRITICAL and HIGH edge case findings to `senior_pr_reviewer`.
