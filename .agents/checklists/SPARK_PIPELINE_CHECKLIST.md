# Spark Pipeline Checklist

> **Purpose**: Spark-specific checks applied by `distributed_systems_reviewer` and
> `data_pipeline_reviewer` on any PR containing PySpark code.
> Supplement to [REVIEW_CHECKLIST.md](REVIEW_CHECKLIST.md).

---

## Section 1 — Context Safety

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 1.1 | Lambdas and UDFs do not reference driver-side variables (file handles, DB sessions, logger instances, env vars read at module level) | | |
| 1.2 | Any driver-side object needed in executors is broadcast via `sc.broadcast()` | | |
| 1.3 | Closures do not capture `self` from a class with non-serializable fields | | |
| 1.4 | Static methods or module-level functions are used instead of bound instance methods where serialization is required | | |

---

## Section 2 — Data Collection Safety

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 2.1 | No `.collect()` without a preceding `.limit(N)` or documented size guarantee | | |
| 2.2 | `.toPandas()` is not called on DataFrames that scale with data volume | | |
| 2.3 | Driver memory assumptions are documented if `collect()` is intentional | | |
| 2.4 | `.count()` is used instead of `len(df.collect())` | | |
| 2.5 | `.first()` / `.take(N)` is used instead of `.collect()[0]` where only the first row is needed | | |

---

## Section 3 — Action Efficiency (N+1 Problem)

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 3.1 | No Spark action (`.collect()`, `.count()`, `.toPandas()`, `.first()`, `.show()`) called inside a Python loop | | |
| 3.2 | Per-column statistics use a single `.describe()` or aggregation pass, not per-column calls | | |
| 3.3 | Feature importances are extracted as a single array, not per-feature | | |
| 3.4 | Joins are performed once and the result reused, not re-executed per use | | |

---

## Section 4 — Ordering and Determinism

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 4.1 | Join results are not consumed with an assumed ordering unless `ORDER BY` is explicit | | |
| 4.2 | `groupBy().agg()` results that feed into array-aligned operations have deterministic ordering enforced | | |
| 4.3 | No positional indexing (`df.collect()[i]`) on join or aggregate results without explicit ordering | | |
| 4.4 | Random sampling uses a fixed seed if reproducibility is required | | |

---

## Section 5 — Write Mode Correctness

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 5.1 | Write mode (`overwrite` vs `append`) is explicit and matches the intended behavior | | |
| 5.2 | `overwrite` is used for idempotent pipeline retries (not `append`, which duplicates on retry) | | |
| 5.3 | `append` is used only where it is intentional and idempotency is externally guaranteed | | |
| 5.4 | Output path existence is checked before writing (or `overwrite` mode handles it) | | |

---

## Section 6 — UDF and Schema Safety

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 6.1 | UDF return types are explicitly typed (not inferred) | | |
| 6.2 | UDFs are not used where built-in Spark functions exist (UDFs disable Catalyst optimization) | | |
| 6.3 | Input schema is validated before pipeline execution (not silently processed with wrong types) | | |
| 6.4 | Schema evolution (added/removed columns) is handled explicitly, not silently | | |
| 6.5 | `StringType` is not used for columns that should be `TimestampType`, `DateType`, or `DecimalType` | | |

---

## Section 7 — Resource and Session Management

| # | Check | Pass / Fail / N/A | Notes |
|---|-------|------------------|-------|
| 7.1 | `SparkSession` is obtained via `getOrCreate()` — not created with `builder.getOrCreate()` inside a loop | | |
| 7.2 | `SparkContext` is not stopped inside a function that may be called multiple times | | |
| 7.3 | Cached DataFrames (`df.cache()` / `df.persist()`) are unpersisted after use | | |
| 7.4 | Temporary views are dropped after use (not left to accumulate across pipeline runs) | | |

---

## Scoring

All sections must be fully PASS or N/A before the PR can be approved.

FAIL in Sections 1–4 is typically a HIGH finding.
FAIL in Sections 5–7 is typically a MEDIUM finding.
