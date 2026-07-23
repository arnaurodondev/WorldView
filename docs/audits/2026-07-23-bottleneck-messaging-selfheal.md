# Bottleneck Audit — BaseKafkaConsumer Self-Heal Gate Accretion

**Date:** 2026-07-23
**Scope:** READ-ONLY investigation of `libs/messaging/src/messaging/kafka/consumer/base.py`
(self-heal / connectivity-probe path) and `services/nlp-pipeline` article-consumer
barrier, plus every test file that exercises them. No source was edited — this file
is the only change.
**Author:** automated audit (Claude)

---

## TL;DR

Six commits in ~48h (`d15adb082` → `a50755efa` → `ade21fdfb` → `84fbca340` →
`9938b0b37` → `19d5fbf3c`) each bolted one more boolean/timestamp discriminator onto
`BaseKafkaConsumer`'s self-heal decision to fix a false-fire or false-suppress the
previous commit's discriminator introduced. The root cause is structural: there is
no single state model for "why is this consumer not polling" — five independently
added signals (`_paused_partitions`, `_barrier_paused_partitions`,
`_last_progress_ts`, `_last_fetch_poll_ts`, a `max.poll.interval.ms` hard ceiling,
a fence-grace knob) are composed via nested boolean logic instead of one explicit
state transition.

Of the two recurrences named in the cluster:

1. **The five self-heal fire/suppress discriminator additions** (`d15adb082`
   through `9938b0b37`) are **BOTH** a test gap and an implementation gap — each
   commit *did* add tests, and those tests are real regression coverage for the
   specific gate they introduced, but every one of them pins all sibling signals to
   a fixed "safe" value, so no test ever exercised the full cross-product. The
   implementation gap is real too: the fire/suppress decision is genuinely a
   5-boolean composition with no structural guardrail forcing new cases to be
   reasoned about jointly.
2. **The `_resume_all_paused_partitions()` early-return omission** (fixed by
   `19d5fbf3c`) is a **pure TEST_GAP** — worse, it is a **zero-test fix**: the
   commit that introduced `_barrier_paused_partitions` (`9938b0b37`) added no test
   for `_resume_all_paused_partitions()` at all, and the follow-up fix
   (`19d5fbf3c`) itself added no test either. This is the highest-confidence,
   cheapest-to-close gap in the cluster.

Severity: **HIGH and still live**. Nothing in this cluster has closed the systemic
gap — a 6th "new deliberate-halt reason" would repeat the exact cycle. Likelihood of
recurrence: **high**, on the observed ~1–2 day cadence, until the state model is
unified.

---

## 1. Code as it stands today (verified by direct read, not just commit messages)

`libs/messaging/src/messaging/kafka/consumer/base.py` (2,607 lines) currently
carries, in the self-heal path alone:

- `_paused_partitions: set[TopicPartition]` (backpressure pause, line 514)
- `_barrier_paused_partitions: set[TopicPartition]` (RC-B barrier pause, line 527)
- `_last_progress_ts` (BP-700 liveness heartbeat, line 542) — **deliberately kept
  fresh during a barrier halt**, which is exactly what defeated the original Gate 2
  and forced the dedicated fetch-poll timestamp below
- `_last_fetch_poll_ts` (line 553) — set only on an actual `consumer.poll()`
  return, to distinguish "still polling, idle" from "stopped polling"
- `_lag_stall_selfheal_fence_grace_seconds` (line 2112, env
  `KAFKA_LAG_STALL_SELFHEAL_FENCE_GRACE_S`, default 180s)
- `max_poll_interval_ms` hard ceiling comparison (line 2329-2332,
  `poll_stale_past_max_poll`)

The final `should_force_exit` decision (`_connectivity_probe_loop`, lines
2279-2333) is:

```python
paused_keys = {... for tp in (self._paused_partitions | self._barrier_paused_partitions)}
wedged = [(k, lag) for k, lag in stalled if k not in paused_keys]
secs_since_poll = self.seconds_since_fetch_poll()
poll_loop_active = secs_since_poll is not None and secs_since_poll < self._probe_interval_seconds
secs_since_progress = self.seconds_since_progress()
consumer_fenced = (
    not poll_loop_active
    and secs_since_progress is not None
    and secs_since_progress >= self._lag_stall_selfheal_fence_grace_seconds
)
max_poll_interval_seconds = self._config.max_poll_interval_ms / 1000.0
poll_stale_past_max_poll = secs_since_poll is not None and secs_since_poll > max_poll_interval_seconds
should_force_exit = poll_loop_active or consumer_fenced or poll_stale_past_max_poll
```

This is a 3-term OR over three independently-timed signals, gating a single
`os._exit(2)` action, with the pause/barrier exclusion computed separately just
above it. It is exactly the "accreting pile of independently-added boolean signals"
described in the cluster summary — confirmed by direct read, not just the commit
messages.

Separately, `_resume_all_paused_partitions()` (line 1887) now reads:

```python
if not self._paused_partitions and not self._barrier_paused_partitions:
    return
partitions = list(self._paused_partitions)
...
self._paused_partitions.clear()
self._resume_barrier_paused()
```

— i.e. the `19d5fbf3c` fix is applied and correct today. The guard now checks both
sets, so barrier-only pauses are released on rebalance/shutdown. But the fix itself
is the whole diff — no test accompanies it (verified: `git show --stat 19d5fbf3c`
touches exactly one file, one line changed, zero test files).

---

## 2. Per-recurrence classification

### Recurrence A — Five self-heal discriminator additions (`d15adb082`, `a50755efa`, `ade21fdfb`, `84fbca340`, `9938b0b37`)

**Classification: BOTH (TEST_GAP *and* IMPLEMENTATION_GAP).**

Verified via `git show --stat` on each commit — every one of the five *did* add or
extend tests in `libs/messaging/tests/unit/test_connectivity_probe.py` (and, for
`ade21fdfb`/`84fbca340`/`9938b0b37`, in nlp-pipeline's
`test_article_consumer_liveness.py` / `test_article_consumer_db_fence.py` /
`test_article_consumer_pipelined.py`). Reading the actual test classes today
(`TestLagStallSelfHeal`, `TestLagStallSelfHealFenceRecovery`,
`TestLagStallSelfHealMaxPollCeiling` in `test_connectivity_probe.py`, lines
515-999) confirms each test:

- sets up **exactly the one signal** the commit introduced (e.g.
  `test_fenced_consumer_both_signals_stale_self_heals` sets both
  `seconds_since_progress` and `seconds_since_poll` stale, `test_poll_stale_past_max_poll_with_fresh_heartbeat_force_exits`
  pins the heartbeat artificially fresh while only `seconds_since_poll` exceeds
  `max.poll.interval.ms`), and
- pins every *other* signal (paused partitions, barrier partitions, heartbeat) to a
  fixed "safe" constant rather than looping over the state space.

There is **no test anywhere in the suite** that asserts the full cross-product of
`{backpressure-paused, barrier-paused, heartbeat-fresh, heartbeat-stale,
fetch-poll-fresh, fetch-poll-stale-within-max-poll, fetch-poll-stale-past-max-poll}`.
Each commit's own regression test is real and would catch a regression of *that*
specific gate, but the combinatorial gap the cluster mined is real too: nothing
would have caught, e.g., a *sixth* new halt reason interacting badly with the
existing five.

The implementation gap is also real, independent of test coverage: the decision is
a 3-clause boolean OR over three independently-timed floats plus a separately
computed exclusion set. There is no single function whose signature is "what state
is this consumer in and why" — so every future halt reason must be reasoned about
against the existing boolean soup by hand, which is precisely why five fixes
landed in 48 hours instead of one.

### Recurrence B — `_resume_all_paused_partitions()` early-return omission (`19d5fbf3c`, following `9938b0b37`)

**Classification: TEST_GAP (pure).**

`9938b0b37` introduced `_barrier_paused_partitions` as a new tracking set parallel
to the pre-existing `_paused_partitions`, and updated the fire/suppress decision
(Recurrence A) correctly — but did not add or update any test for
`_resume_all_paused_partitions()`, which is a completely separate code path
(rebalance-revoke / shutdown cleanup, not the probe-loop decision). The stale guard
(`if not self._paused_partitions: return`, pre-dating `_barrier_paused_partitions`
by definition) silently skipped `_resume_barrier_paused()` whenever only barrier
pauses were active — a barrier-only halt (the exact nlp article-consumer
saturated-window case both `ade21fdfb` and `9938b0b37` were themselves written to
handle) would leave the barrier-paused partitions still paused for the *next* group
member after a rebalance.

This is a textbook implementation-would-have-been-caught-by-a-test bug, not a
design gap: `_resume_all_paused_partitions()` and `_resume_barrier_paused()` are
simple, deterministic, pure-Python state mutations with no timing/async
non-determinism — a unit test asserting "barrier-only pause state is released by
`_resume_all_paused_partitions()`" would have failed immediately on `9938b0b37`'s
diff, before it ever reached prod or a human reviewer. No test existed before the
bug, and **no test was added by the fix itself either** — confirmed by `git show
--stat 19d5fbf3c` showing a single one-line change to `base.py` and nothing else.
This means the exact same omission class (a third pause-tracking mechanism added
later, without updating this guard) can recur today with zero regression coverage.

---

## 3. Concrete remediation

### 3a. Test gap — close immediately, cheap, no design change required

Add to `libs/messaging/tests/unit/test_connectivity_probe.py` (new test class,
e.g. `TestResumeAllPausedPartitions`, sibling to the existing `TestLagStallSelfHeal*`
classes):

1. `test_resume_all_paused_partitions_releases_barrier_only_state` — set
   `_barrier_paused_partitions = {tp}`, leave `_paused_partitions` empty, call
   `_resume_all_paused_partitions()`, assert `consumer.resume` was called with `tp`
   and `_barrier_paused_partitions` is empty afterward. This is the exact
   regression `19d5fbf3c` fixed and is the single highest-value test to add — it
   currently does not exist.
2. `test_resume_all_paused_partitions_releases_both_sets_independently` — populate
   both sets with disjoint partitions, assert both are cleared and both partitions
   passed to `resume` (across the two internal calls).
3. `test_resume_barrier_paused_does_not_unpause_backpressure_held_partition` —
   populate a partition in *both* `_paused_partitions` and
   `_barrier_paused_partitions`, call `_resume_barrier_paused()` directly, assert
   that partition is NOT in the `resume()` call args (the existing exclusion logic
   at line 1959) and remains in `_paused_partitions`.
4. A combinatorial fire/suppress test for the probe loop itself:
   `test_selfheal_matrix_across_all_halt_reasons` — parametrize over the 6-8 cell
   cross-product of {paused-only, barrier-only, both, neither} × {heartbeat
   fresh/stale} × {fetch-poll fresh / stale-within-max-poll / stale-past-max-poll},
   assert `should_force_exit` matches the documented truth table for every cell,
   not just the cells each historical commit happened to test. This is the test
   that would have caught a *future* sixth discriminator's interaction bugs, not
   just today's known ones.

### 3b. Implementation gap — structural fix, not urgent but recommended before the next new halt reason is added

Replace the boolean/timestamp pile with one explicit state computation, e.g.:

```python
class ConsumerLivenessState(enum.Enum):
    ACTIVE_POLLING = "active_polling"
    HALTED_BACKPRESSURE = "halted_backpressure"
    HALTED_BARRIER = "halted_barrier"
    HALTED_DOWNSTREAM_OUTAGE = "halted_downstream_outage"
    FENCED = "fenced"

def _consumer_liveness_state(self) -> ConsumerLivenessState:
    """The ONLY place any pause/halt mechanism may register a suppression reason."""
    ...
```

with `_connectivity_probe_loop` reduced to `if state == ConsumerLivenessState.FENCED:
self._force_process_exit(2)`. Concretely, this means:

- Every existing pause-tracking collection (`_paused_partitions`,
  `_barrier_paused_partitions`) and every future one funnels into this single
  function instead of being read ad hoc at the call site.
- Adding a new deliberate-halt reason becomes "add one enum member + one branch in
  `_consumer_liveness_state()`", not "grep base.py for every existing exclusion set,
  guard, and early-return and hope you found them all" — which is exactly the
  failure mode that produced Recurrence B.
- The combinatorial test in 3a.4 becomes a table-driven test directly over
  `_consumer_liveness_state()`'s truth table, rather than over the probe loop's
  side effects, making it trivial to extend when a 6th halt reason is added.

This is a moderate refactor (isolated to `base.py`, well-covered by existing tests
per commit history) and should be done as its own `/refactor` pass with the
existing 200+ messaging unit tests as the regression harness — not bundled into the
next feature fix, per the repo's small-focused-diff rule.

---

## 4. Severity / likelihood assessment

| Axis | Assessment |
|---|---|
| **Current prod risk** | Low right now — the `19d5fbf3c` fix is live and correct (verified by direct read of `_resume_all_paused_partitions` above). No known active bug in this cluster today. |
| **Regression risk without 3a** | **High** — the exact omission class (new pause-tracking collection, unaudited pre-existing guard) has zero regression coverage; a 7th signal added the same way as `_barrier_paused_partitions` was could reintroduce the same or a sibling bug silently. |
| **Recurrence-of-the-meta-pattern risk without 3b** | **High** — six commits in 48h is empirical evidence of a ~1-2 day patch cadence per new deliberate-halt use case discovered in prod. Nothing has removed the structural cause; the next new halt reason (in nlp-pipeline or any other `BaseKafkaConsumer` subclass) will go through the same cycle: bolt on a signal, discover it breaks an existing gate, bolt on another to fix that. |
| **Blast radius** | Platform-wide — `BaseKafkaConsumer` is shared by every Kafka consumer in every service, so a self-heal false-fire (kills a healthy-but-slow consumer) or false-suppress (leaves a truly fenced consumer wedged for hours, as observed live on 2026-07-21) affects any service, not just nlp-pipeline. |
| **Recommended priority** | 3a (test additions) should land immediately — it is cheap, isolated, and closes the exact class of gap that already bit prod once. 3b (state-machine refactor) should be scheduled as the next messaging-lib hardening pass, before the next new deliberate-halt use case is added anywhere in the codebase. |

---

## 5. Cross-references

- Not yet documented in `docs/BUG_PATTERNS.md` — BP-699/BP-700 (2026-06-15) cover
  the original lag-stall detector and its alerting gap; BP-727 (2026-07-15) covers
  the liveness-heartbeat-goes-stale-on-long-handler case. None cover this Jul 21-23
  self-heal-gate cluster or the recurring "new discriminator breaks a prior one"
  meta-pattern. Recommend a new BP entry per the cluster's suggested text.
- Not yet in `.claude/review/heuristics/HIGH_RISK_PATTERNS.md` — recommend the
  suggested HR entry: any diff touching `_connectivity_probe_loop`,
  `_evaluate_lag_stall`, `_resume_all_paused_partitions`, or `_force_process_exit`,
  or adding a new `_<adjective>_paused_partitions` / `_last_<x>_ts` signal, requires
  (1) grepping every sibling pause/halt-tracking collection and confirming every
  guard/early-return/resume/exclusion site was updated for all of them, and (2) a
  combinatorial test per §3a.4.
- Not yet in `.claude/review/checklists/REVIEW_CHECKLIST.md` — recommend adding the
  checklist line from the cluster: self-heal changes require a test matrix over the
  full cross-product of known halt reasons, not just the new one in isolation.
