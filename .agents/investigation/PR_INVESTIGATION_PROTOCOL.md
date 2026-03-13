# PR Investigation Protocol

> **Purpose**: Define the structured reasoning procedure that AI agents must follow
> when analyzing code changes.
>
> Bug patterns alone are insufficient. Agents must perform structured analysis
> to discover new classes of bugs. The investigation must simulate production
> behavior and explore failure modes.

---

## Investigation Algorithm

Agents must perform the following procedure **in full** before reporting findings.
Skipping steps is not permitted. Steps 1–3 are always sequential. Steps 4–10
may surface findings from any earlier step.

---

## Step 1 — Map the Change Surface

List all modified components.

Identify:

- functions
- classes
- pipelines
- APIs
- configuration changes

For each change determine:

- side effects
- external dependencies
- resource creation
- persistence operations

Mark all locations where code:

- writes files
- writes to cloud storage (S3, MinIO, GCS)
- writes to databases
- logs artifacts (MLflow, W&B, etc.)
- spawns processes
- performs Spark actions

These locations are **high-risk zones**. Every high-risk zone must be
re-examined in Steps 3–7.

---

## Step 2 — Identify Side Effects

For every function, document:

```
Inputs:
  - <list all inputs>
Outputs:
  - <list all return values>
Side effects:
  - <list every external action: temp dir creation, file write, network call, etc.>
External systems touched:
  - <list every external system: DB, S3, Kafka, MLflow, etc.>
```

**Example**:

```
save_pipeline_model()

Inputs:
  - pipeline object
  - destination path

Outputs:
  - None (void)

Side effects:
  - temp directory creation
  - file serialization
  - upload to S3
  - copy to final destination prefix
  - temp prefix cleanup

External systems touched:
  - S3 / MinIO
```

Side effects define the failure surface. Every side effect becomes an input
to Step 3.

---

## Step 3 — Enumerate Failure Points

Break every multi-step operation into numbered steps.

**Example**:

```
upload_model():

1. create temp directory
2. serialize model to disk
3. upload artifacts to temp S3 prefix
4. copy temp prefix → final prefix (object by object)
5. delete temp prefix
```

For each step, evaluate:

```
failure before step N:
  - system state after failure?
  - partial side effects visible?
  - cleanup executed?
  - caller-visible outcome?

failure during step N:
  - same questions
```

Enumerate failures at **every** step boundary. Do not skip steps.

---

## Step 4 — Validate Invariants

Identify invariants — conditions that must always hold.

**Examples**:

- `len(X) == len(y)` — arrays must stay aligned
- final storage prefix contains either all artifacts or none
- Spark joins produce deterministic ordering
- MLflow runs reflect real experiment state
- outbox records are created in the same transaction as the domain write

Test each invariant under:

- empty inputs
- large inputs
- null / None values
- retry scenarios
- concurrent execution
- partial failure mid-operation

Document which invariants the code maintains and which it violates.

---

## Step 5 — Trace Exception Propagation

For every `try` / `except` / `finally` block, trace:

```
success path:
  - what executes?
  - what is returned?
  - what cleanup runs?

failure path:
  - what is caught?
  - what is logged?
  - what is re-raised?
  - what cleanup runs?

cleanup path (finally):
  - does cleanup execute on all exits?
  - can cleanup itself raise?
  - does a cleanup exception mask the original?
```

Check for:

- **Success masking**: exception caught and swallowed, success returned — caller
  never knows failure occurred.
- **Swallowed exceptions**: `except Exception: pass` or `except Exception: log(...)` with
  no re-raise — silently continues after failure.
- **Missing re-raise**: cleanup runs but original exception is lost.
- **Cleanup exception masking**: `finally` block raises, replacing the original exception.

---

## Step 6 — Evaluate Idempotency

Check whether operations are safe to run twice.

**Test scenarios**:

- retry after network failure
- job restart from checkpoint
- pipeline retry with same inputs

For each retry scenario, verify the operation does not cause:

- duplicate writes
- corrupted artifacts
- inconsistent metadata
- double-counted metrics

Document whether each operation is idempotent and, if not, what guards prevent
double-execution.

---

## Step 7 — Validate Storage Atomicity

Verify that readers never observe partial state.

For every operation involving staging → final destination:

```
verify:
  - partial writes do not leak to the final prefix
  - on failure, final destination is either complete or empty
  - copy loops clean up partially written objects on failure
  - no reader can observe an in-progress write
```

Check for:

- direct writes to final destination (no staging)
- copy loops without failure handling
- missing cleanup on exception
- readers using eventual-consistency assumptions incorrectly

---

## Step 8 — Environment Consistency

Evaluate whether behavior changes across environments.

Test assumptions about:

- filesystem (local vs. HDFS vs. object storage)
- working directory (`os.getcwd()` differs in containers)
- timezone (naive datetimes will behave differently by region)
- credentials (missing in CI, different in staging)
- region (S3 endpoint, latency, behavior)
- Spark driver vs. executor context (serialization, file access, logging)

Detect code that behaves differently in:

- local development
- CI / GitHub Actions
- Docker containers
- distributed Spark clusters

---

## Step 9 — Generate Edge Cases

For each function, test hypothetical inputs systematically.

See [../heuristics/EDGE_CASE_GENERATION.md](../heuristics/EDGE_CASE_GENERATION.md) for the
full generation procedure.

Quick checklist:

- empty dataset / empty collection
- single-element dataset
- extremely large dataset
- missing / extra columns
- invalid types
- out-of-order timestamps
- duplicate keys
- None / null values in required fields
- maximum and minimum numeric values

For each edge case, document:

- expected behavior
- actual behavior (based on code reading)
- whether a test covers this case

---

## Step 10 — Cross-check Known Bug Patterns

Before reporting, consult the knowledge base:

- [../knowledge/BUG_PATTERNS.md](../knowledge/BUG_PATTERNS.md)
- [../knowledge/DISTRIBUTED_SYSTEM_PATTERNS.md](../knowledge/DISTRIBUTED_SYSTEM_PATTERNS.md)
- [../knowledge/STORAGE_ATOMICITY_PATTERNS.md](../knowledge/STORAGE_ATOMICITY_PATTERNS.md)

For each known pattern, verify the reviewed code does not reintroduce the same class
of failure. If it does, cite the pattern ID in the finding.

---

## Output Requirements

Report only **realistic failure paths** — failures that can occur under plausible
production conditions.

**Do not report**:

- theoretical failures with no realistic trigger
- style issues unrelated to correctness
- performance concerns unless they cause functional failure

### Required format for each finding

```
Severity:    CRITICAL | HIGH | MEDIUM | LOW
Confidence:  HIGH | MEDIUM | LOW
Impact:      <one sentence — what breaks in production>
Root cause:  <precise technical explanation>
Fix:         <specific, actionable recommendation>
Pattern ref: <BP-NNN or pattern name if applicable, else N/A>
```

---

## Related Files

- [FAILURE_MODE_ANALYSIS.md](FAILURE_MODE_ANALYSIS.md) — structured failure enumeration procedure
- [INVARIANT_ANALYSIS.md](INVARIANT_ANALYSIS.md) — invariant identification worksheet
- [../roles/failure_mode_investigator.md](../roles/failure_mode_investigator.md) — role assignment
- [../roles/distributed_systems_reviewer.md](../roles/distributed_systems_reviewer.md) — distributed role
- [../checklists/REVIEW_CHECKLIST.md](../checklists/REVIEW_CHECKLIST.md) — final pre-report checklist
