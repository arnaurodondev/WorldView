# Bottleneck Audit — KG Entity/Relation Dedup + Worker Crashloop Resilience Cluster

**Date:** 2026-07-23
**Scope:** READ-ONLY investigation of `services/knowledge-graph` source + tests. No
code changed. This file is the only artifact produced.
**Author:** automated audit (Claude)

---

## TL;DR

The mined bottleneck hypothesis is **correct and independently verified against
current source**: knowledge-graph's ~20 Kafka consumers and 2 standalone
daemon-loop/sweep workers each hand-roll their own resilience for three concerns
(schema-evolution-safe deserialize, loop-level backoff, per-row LLM attempt
capping), with no shared abstraction enforcing any of the three. I traced the
exact code path in `libs/messaging/src/messaging/kafka/consumer/base.py` that
turns an undecodable old-schema record into a `dead_letter_cap` crash-loop, and
confirmed by direct grep that **7 of 9 comparable consumers still lack the
fix** two siblings already received.

**Important correction to the input framing**: `docs/BUG_PATTERNS.md` (BP-736,
BP-737, BP-738), `.claude/review/checklists/REVIEW_CHECKLIST.md`, and
`.claude/review/heuristics/HIGH_RISK_PATTERNS.md` (HR-060, HR-062, the
standalone-loop-backoff entry, the sweep-worker-attempt-cap entry) **already
document all three recurrences** in the working tree — this appears to be the
output of a prior compounding pass, not yet committed. The documentation-side
gap the mined report describes is therefore **closed**. What remains open is
the **code-side** gap: no shared base class/mixin/architecture-test exists yet
to make the documented pattern structurally hard to forget, and 7 consumers
are still exposed.

**Bottom line per recurrence:**

| # | Recurrence | Classification | Severity/Likelihood as-is |
|---|---|---|---|
| 1 | Resilient-deserialize hand-copied per consumer | **BOTH** (test gap on 7 files + no class-wide test; implementation gap = no shared mixin) | **High / High** — will recur on the next backward-compatible Avro field append (R11 guarantees this happens) |
| 2 | Standalone daemon-loop backoff hand-rolled | **IMPLEMENTATION_GAP** (the one instance is well-tested; the *class* of bug has no structural guard) | **Medium / Low-Medium** — only 1 file has this shape today, but nothing stops a 2nd from being added the same way |
| 3 | Per-row LLM-sweep attempt-capping reinvented per worker | **IMPLEMENTATION_GAP** (same — instance well-tested, class unguarded) | **Medium / Medium** — 4 independent mechanisms already exist; a 5th sweep worker is a routine kind of change in this codebase |

---

## Recurrence 1 — Resilient Avro-deserialize handling

### What I verified in current source

`libs/messaging/src/messaging/kafka/consumer/base.py:1079-1100` (`_handle_message`,
single-message path — the default for every consumer with
`consume_batch_size == 1`) wraps **any** exception from `deserialize_value()`
into `MalformedDataError` (a `FatalError`/`ConsumerError`). Back up the call
stack, the `run()` loop's `except ConsumerError as exc: await
self._handle_failure(msg, exc)` (line ~2578) routes `FatalError` straight to
`dead_letter()` — no retry — and once `_dead_letter_count > dead_letter_cap`
(default 5000, checked at base.py:783) it raises `RuntimeError` to force a
container restart **before the offset commits**. That is the exact mechanism
BP-736 documents, and I confirmed it by reading the code, not by citing the
doc.

(Aside, confirmed while reading: the **batched** path, `_handle_batch()` at
line 1196, already skips per-message deserialize failures inline — line
1212-1217 — with no override needed. So this whole bug class only applies to
consumers on the single-message path, which is most of them.)

Grep results, read in full (not just grepped for the marker string):

- **Fixed** (override `_handle_message`, catch
  `(MalformedDataError, EOFError, struct.error)`, skip+log, do **not**
  dead-letter): `prediction_enriched_consumer.py:235-259`,
  `enriched_consumer.py:185-229`.
- **Unfixed, confirmed exposed**:
  - `structured_enrichment_consumer.py` — `deserialize_value` (line 358) calls
    `deserialize_confluent_avro` directly with no try/except of its own; any
    raw decode error propagates to the base wrapper unchanged → same
    crash-loop path.
  - `temporal_event_consumer.py` — same shape (`deserialize_value` at line
    285-290, no try/except).
  - `entity_consumer.py` — `deserialize_value` (line 175-198) wraps its own
    `KeyError` into `MalformedDataError` for a *business-rule* validation
    (missing field), but a raw Avro decode failure is not caught there either
    — it still surfaces as base-wrapped `MalformedDataError`, un-skipped.
  - `fundamentals_consumer.py` — `deserialize_value` (line 253-263) is a bare
    call to `deserialize_confluent_avro`, no guard at all.
  - `provisional_queued_consumer.py` — same (line 362-378).
  - `instrument_consumer.py` and `instrument_discovered_consumer.py` — these
    two look different at first glance (`deserialize_value` catches
    `Exception` and "falls back to JSON", lines 772-782 and 354-364
    respectively) but I verified this does **not** actually protect them: for
    a real truncated/misaligned Avro binary payload, `json.loads(raw)` will
    itself raise (the bytes are not valid JSON), and that second exception
    propagates out of `deserialize_value` uncaught, hits the base's
    `except Exception as exc: raise MalformedDataError(...)` wrapper exactly
    the same way, and is dead-lettered exactly the same way. The JSON
    fallback exists for **tooling/test convenience** (per its own docstring),
    not for old-schema-backlog resilience — it does not change the
    crash-loop exposure.

### Was there a test that should have caught this?

**Yes, on two axes — TEST_GAP confirmed, in addition to the implementation
gap:**

1. **Per-file regression test, missing on all 7 unfixed consumers.** I read
   the existing test files for the two *fixed* consumers
   (`tests/unit/infrastructure/consumer/test_enriched_consumer.py:858-910`,
   `test_prediction_enriched_consumer.py:532-...`) — both have an explicit
   `test_undecodable_old_schema_record_is_skipped_not_raised` /
   `test_undecodable_record_is_skipped_not_raised` test that patches
   `deserialize_value` to raise `EOFError`/`struct.error` and asserts the
   consumer logs a skip and does **not** call `dead_letter`. I then read the
   corresponding test files for the 7 unfixed consumers
   (`test_structured_enrichment_consumer.py`, `test_temporal_event_consumer.py`,
   `test_instrument_consumer.py`, `test_entity_consumer.py`,
   `test_fundamentals_consumer.py`, `test_instrument_discovered_consumer.py`,
   and `tests/unit/infrastructure/workers/test_provisional_queued_consumer.py`)
   — none contain an `EOFError`/`struct.error` decode-poison test. The
   `MalformedDataError` tests that do exist in these files (e.g.
   `test_entity_consumer.py:91-98`, `test_instrument_discovered_consumer.py:216-244`)
   assert a **different, intentional** behavior — a business-rule validation
   (missing `event_id`/`symbol`) that is *supposed* to dead-letter — and would
   pass unchanged whether or not the crash-loop fix exists. They give zero
   coverage of the decode-poison path.

   **Concrete tests to add** (one per file, following the exact pattern
   already proven in `test_enriched_consumer.py:858`):
   - File: `services/knowledge-graph/tests/unit/infrastructure/consumer/test_structured_enrichment_consumer.py` — new test `test_undecodable_old_schema_record_is_skipped_not_raised`: patch `deserialize_value` to raise `EOFError("short read")`, call `_handle_message(msg)`, assert no exception propagates, `dead_letter` is never called, and a structured skip log is emitted.
   - Same pattern, same new test name, in: `test_temporal_event_consumer.py`, `test_instrument_consumer.py`, `test_entity_consumer.py`, `test_fundamentals_consumer.py`, `test_instrument_discovered_consumer.py`, `tests/unit/infrastructure/workers/test_provisional_queued_consumer.py`.
   - For `instrument_consumer.py`/`instrument_discovered_consumer.py` specifically, additionally assert that a raw (non-JSON) undecodable payload does **not** silently succeed via the JSON fallback with garbage data — i.e. that `deserialize_value` re-raises (as `MalformedDataError`/`EOFError`) rather than returning a nonsense dict from a lucky `json.loads` partial parse.

2. **Class-wide architecture test, missing entirely.** I confirmed (via
   `find`/`grep`) there is **no** test anywhere under
   `services/knowledge-graph/tests/` that enumerates every
   `BaseKafkaConsumer` subclass in the service and asserts each one either
   (a) overrides `_handle_message` with the resilient catch, or (b) uses
   `consume_batch_size > 1` (which is already safe per the base class). This
   is exactly the kind of test that would have caught all 7 gaps at once and
   would fail immediately the day someone adds consumer #21 without it.
   **Add**: `services/knowledge-graph/tests/unit/infrastructure/consumer/test_consumer_resilience_invariants.py` — import every consumer module under `infrastructure/messaging/consumers/`, collect `BaseKafkaConsumer` subclasses, and for each one not on the batch path, assert (via `inspect.getsource` or a marker attribute — see structural fix below) that it has decode-poison protection.

### Structural fix (implementation gap, the part no test alone would prevent)

Per-file tests stop *known* files from regressing but do nothing for the
*next* consumer someone writes next month — that is what "hand-copied, not
centralized" means, and it is why the fix recurred once already (2 months
apart) even with the first instance's test in place. The codebase already has
the right shape for this: `libs/messaging/src/messaging/kafka/consumer/dedup.py`
defines `ValkeyDedupMixin`, a mixin precedent for exactly this kind of
cross-cutting concern. The same pattern should be applied here:

- Add `ResilientDeserializeMixin` (or fold the behavior into
  `BaseKafkaConsumer._handle_message` directly, gated by a config flag
  `skip_undecodable_records: bool = True` defaulting to the safe behavior) to
  `libs/messaging/src/messaging/kafka/consumer/base.py` — catch
  `(MalformedDataError, EOFError, struct.error)` **at the base class level**,
  log `..._deserialize_skipped` with topic/partition/offset, and return
  without dead-lettering. This removes the need for every subclass to
  hand-write the override at all — the 2-months-apart recurrence becomes
  structurally impossible because there is no override to forget.
- If a genuine backward-compat reason exists to keep this opt-in per
  consumer (e.g. some consumer wants records DLQ'd, not skipped), then at
  minimum add the architecture test from item 2 above so opting OUT is a
  conscious, reviewed choice rather than a silent default.

---

## Recurrence 2 — Standalone daemon-loop backoff (`path_insight_worker.py`)

### What I verified

`services/knowledge-graph/src/knowledge_graph/infrastructure/workers/path_insight_worker.py`:
`run_loop()` (line 190) now wraps its entire iteration body — including the
`_claim_batch()` call that opens its own DB session — in try/except with
capped exponential backoff (`_ERROR_BACKOFF_INITIAL_SECONDS` →
`_ERROR_BACKOFF_MAX_SECONDS`, doubling per failure, reset to initial on
success), and deliberately does not catch `asyncio.CancelledError`. This
matches BP-737 exactly.

### Test coverage for the fixed instance

`tests/unit/infrastructure/workers/test_path_insight_worker.py:394-434` has
`test_run_loop_survives_transient_claim_error`: it monkeypatches `_claim_batch`
to raise a `ConnectionDoesNotExistError`-shaped exception on the first call,
asserts `run_loop()` does not propagate it, and asserts a backoff sleep
occurred. **This is solid, specific regression coverage** — re-introducing the
unguarded call in this file would be caught immediately.

### Classification: IMPLEMENTATION_GAP (not a test gap for the known instance)

No test would have prevented the *original* bug without the fix already
existing to test against — the sibling `_reclaim_loop` in the same file
already had the correct pattern, so a reasonable reviewer glancing at
`run_loop()` next to it should have caught the asymmetry, but nothing
mechanical (lint rule, base class, architecture test) enforced it. This is a
structural gap: **there is no `BaseLoop`/`BaseDaemonWorker` class** analogous
to `BaseKafkaConsumer` that any hand-written `while True` daemon entrypoint
must extend, so the guard-the-whole-iteration discipline lives only in one
person's memory of one past incident.

Today only `path_insight_worker.py` has this standalone-loop shape in
knowledge-graph (verified: no other `run_loop`/bespoke `while True` daemon
entrypoint exists under `infrastructure/workers/*_main.py` outside
APScheduler-registered jobs and `BaseKafkaConsumer` subclasses — grepped and
manually checked the `_main.py` files). That caps blast radius today, which is
why I rate likelihood **Medium** rather than High — but the moment a second
standalone loop worker is added (a plausible near-term need, e.g. a
batch-reprocessing daemon), it inherits none of this protection unless its
author remembers to copy `path_insight_worker.py`'s pattern by hand.

**Structural fix**: extract a small `BaseDaemonLoop` abstract class (in
`libs/common` or a new `libs/messaging` submodule, following the
`ValkeyDedupMixin` precedent again) that owns the `while not stop_event`
skeleton, the try/except-with-capped-backoff wrapper around a single
abstract `_iteration()` method, and the `asyncio.CancelledError` passthrough.
`path_insight_worker.run_loop`/`_reclaim_loop` become two `_iteration()`
implementations rather than two hand-written loops. This makes the "wrap the
WHOLE iteration, not just the per-item body" lesson unforgettable by
construction, rather than a comment for the next author to notice.

**Test to add** (belt-and-suspenders, cheap): a repo-wide grep-based
architecture test — e.g.
`services/knowledge-graph/tests/unit/infrastructure/workers/test_daemon_loop_invariants.py`
— that fails if any `*_main.py` under `infrastructure/workers/` defines an
async function containing `while` with no enclosing `try` in its AST, so a
second bespoke loop can't ship unguarded even before the `BaseDaemonLoop`
refactor lands.

---

## Recurrence 3 — Per-row LLM-sweep attempt-capping reinvented per worker

### What I verified

`entity_retype.py`'s `record_retype_attempts()` / `list_unknown_entities()`
(per BP-738) bump a `retype_attempts` counter in
`canonical_entities.metadata` JSONB and exclude at-cap rows from the next
sweep's `SELECT`, with a same-day follow-up fix so transient LLM errors are
not counted against the cap. I confirmed three genuinely divergent existing
mechanisms for the identical problem:
`provisional_enrichment.py` (`retry_count` column + `next_retry_at`, DEF-033),
`narrative_refresh.py` (`failure.attempt` field), `fundamentals_refresh.py`
(Valkey key `s7:fundamentals:backoff:{ticker}`). Four total independently
invented solutions to "don't re-bill a permanently-failing row to a paid LLM
forever."

### Test coverage for the fixed instance

`tests/unit/infrastructure/workers/test_entity_retype.py:257-295`
(`test_transient_llm_error_does_not_increment_attempts`) specifically asserts
the exact defect the same-day follow-up fixed — a transient-error row is
excluded from `record_retype_attempts` calls. `max_attempts`
forwarding/filtering is also covered (lines 308-408). **This instance is
well-tested.**

### Classification: IMPLEMENTATION_GAP

Same shape as Recurrence 2: the specific worker that was caught in the
2026-07-16 audit is now solid, but nothing stops sweep-worker #5 from
shipping with zero attempt cap — there is no shared utility, decorator, or
architecture test enforcing "every APScheduler sweep worker that calls an
LLM per-row must track a durable per-row attempt count and exclude at-cap
rows." I rate this **Medium/Medium** (not High) because APScheduler jobs
already get crash isolation for free (per-job exceptions don't propagate),
so the failure mode here is silent cost waste, not an outage — it is real
money (confirmed pattern: caught only via a manual audit, not automatically)
but not a page.

**Structural fix**: extract a shared `CappedRetryTracker` utility (e.g.
`libs/common/retry.py` or similar) parameterized by (a) a durable per-row
storage backend (JSONB column vs. Valkey key — both current backends could
implement one small `AttemptStore` protocol), (b) `max_attempts`, and (c) a
`is_transient(exc) -> bool` classifier so the "don't count transient errors"
lesson is enforced by the utility's own API shape rather than something each
new worker's author has to remember and re-derive (as the entity_retype
same-day follow-up shows happened even for the worker that DID get a cap on
day one).

**Test to add**: an architecture test enumerating APScheduler-registered jobs
in `scheduler.py` that call into an LLM client (grep for `ml_clients`/`llm`
import inside the job's call chain, or a lighter-weight convention: require
every such job to be registered with a `has_attempt_cap: bool` marker checked
at scheduler-registration time) and asserting each one either uses the shared
`CappedRetryTracker` or is explicitly allow-listed with a comment explaining
why not (grandfathering the 3 pre-existing bespoke mechanisms until they're
migrated).

---

## Summary table (explicit answers to the 4 audit questions)

| Recurrence | Q1: Classification | Q2/Q3: What to add | Q4: Severity/Likelihood |
|---|---|---|---|
| 1. Deserialize resilience | **BOTH** — TEST_GAP (7 missing per-file regression tests + 1 missing architecture test) and IMPLEMENTATION_GAP (no shared mixin/base-class default) | Per-file: `test_undecodable_old_schema_record_is_skipped_not_raised` × 7 files (see list above). Structural: fold the catch into `BaseKafkaConsumer._handle_message` (or a `ResilientDeserializeMixin`) so it's on by default; add a service-wide architecture test enumerating consumer subclasses. | **High/High** — R11 (forward-compatible schemas) guarantees Avro fields keep getting appended; 7 of 9 comparable consumers are exposed *today*, verified by reading their source, not just grepping. |
| 2. Standalone loop backoff | **IMPLEMENTATION_GAP** (instance well-tested; class unguarded) | Structural: extract `BaseDaemonLoop`. Cheap interim: AST-based grep test forbidding an unguarded `while` in `*_main.py` daemon entrypoints. | **Medium/Low-Medium** — only 1 file has this shape today; risk is latent until a 2nd standalone loop worker is added. |
| 3. LLM-sweep attempt capping | **IMPLEMENTATION_GAP** (instance well-tested; class unguarded, 4 divergent bespoke mechanisms already exist) | Structural: shared `CappedRetryTracker` utility with a transient-error classifier baked into its API. Test: architecture check that every LLM-calling sweep job either uses the tracker or is explicitly grandfathered. | **Medium/Medium** — silent cost waste, not an outage; caught historically only by manual audit, so it can persist for weeks before anyone notices. |

## Note on documentation state

`docs/BUG_PATTERNS.md` (BP-736/737/738), `REVIEW_CHECKLIST.md`, and
`HIGH_RISK_PATTERNS.md` (HR-060/HR-062 + two more unnumbered entries) already
contain thorough write-ups of all three recurrences, including the exact list
of 7 unfixed consumer files, in the current (uncommitted) working tree. That
compounding work appears to have already happened in a prior pass and does
not need to be repeated here. What is still missing, and is the actual
residual bottleneck, is the **code**: the shared base classes/mixins/utility
described above, and the architecture tests that would make each documented
invariant self-enforcing instead of reviewer-memory-dependent.
