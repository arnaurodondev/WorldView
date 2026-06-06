---
id: PLAN-0101
title: ITER-10 TPS Metric Redesign + BP-612/613 Grader/Harness Fixes + BP-610 Touch-At Flush
prd: inline (see §0)
status: complete
created: 2026-05-28
updated: 2026-05-28
retroactive: true
source_audits:
  - docs/audits/2026-05-28-plan-0101-tps-metric-redesign.md (W3 TPS metric redesign)
  - docs/audits/2026-05-28-plan-0101-bp-610-touch-at.md (W2 BP-610 freshness-column flush)
related_commits:
  - 91a363a0 — feat(chat-eval): PLAN-0101 W3 — TPS metric redesign + BP-612/613 fixes
  - 096ebc5d — fix(market-data): PLAN-0101 / BP-610 — flush touch_fundamentals_ingest_at inside repo
  - ca9e4dc7 — fix(market-data): PLAN-0101 / BP-610 — flush touch_fundamentals_ingest_at inside repo (rebase variant)
---

# PLAN-0101 — ITER-10 TPS Metric Redesign + Grader Hardening + Touch-At Flush

> **Retroactive plan**: PLAN-0101 was implemented across `feat/plan-0099-w4`
> on 2026-05-28 with a TRACKING.md row and three commits, but the plan
> file itself was never created. PLAN-0102 W7 fills this gap; this
> document is reconstructed from the TRACKING.md row, the two source
> audits, and the linked commits.

## §0 — Inline PRD

### Problem statement

Three failure classes surfaced after PLAN-0100 W2 and W4 landed:

1. **TPS metric collapsed to tool-latency** — PLAN-0100 W2 broadened
   TTFT to "first user-visible event" (the harness picks the first
   `tool_call`/`status`/`token`/`delta` frame). The legacy formula
   `tps = output_tokens / (latency_s - ttft_s)` had been calibrated
   against a TTFT that fired only on real synthesised tokens. After the
   broadening, the denominator absorbed the entire tool-fanout window;
   on legit tool-heavy questions the metric collapsed to **1-3 tok/s**
   (median) — well below the legacy `tps_p50 ≥ 30` gate and indistinguishable
   from a real degradation. Continuing to ship the legacy gate would
   either (a) fail every chat-eval run or (b) require dropping the gate
   entirely. Neither defends the latency invariant we care about
   (streaming throughput during synthesis).

2. **Grader honest-quote exemption window too narrow (BP-612)** —
   PLAN-0100 W1 BP-604/605 fixes trained the model to emit explicit
   "X does not appear in the retrieved results for Y" refusals when
   tools return empty. The grader's revenue-cap honest-quote exemption
   (introduced PLAN-0097 W2 BP-580) used a ±60 char window around the
   disputed numeric claim and matched only the singular phrase `"do
   not appear"`. PLAN-0101 chat-eval Q4 v3 (NVDA fundamentals) produced
   the plural-form "NVIDIA and AMD do not appear" sitting ~95 chars
   after the AMD revenue-cap test value; the marker fell outside the
   window AND the plural-form was not in the marker set, so the verdict
   pipeline classified an honest refusal as a HARMFUL fabrication.

3. **Harness `final_answer` empty when token stream falls through (BP-613)** —
   PLAN-0099 W1 BP-595 SSE chunk streaming emits only `delta` frames
   on the direct-answer branch; the terminal `done` event no longer
   carries an aggregate `final_answer` payload. The harness's legacy
   assembly took `done.data.final_answer` verbatim and therefore
   recorded `final_answer=""` for streamed-direct answers, scoring
   them USELESS even when the streamed tokens contained a complete,
   well-formed answer.

4. **`last_fundamentals_ingest_at` NULL across 629 instruments (BP-610)** —
   surfaced as a diagnostic side-finding in PLAN-0100 W4 (AMD freshness)
   and tagged for PLAN-0101. The PLAN-0096 T-W1-02 wiring landed in
   source on commit `8450666b` but the running Docker image predated
   it; even after a rebuild, the repo method's `update()` was unflushed
   and survived in the UoW only by accident of the surrounding success
   path. Any try/except-swallowed exception downstream would silently
   drop the freshness UPDATE.

### Goals

1. Replace the collapsed `tps` gate with a synthesis-phase throughput
   metric that measures what we actually care about (W3).
2. Stop the grader from misclassifying honest refusals as HARMFUL
   fabrications (W3 — BP-612).
3. Stop the harness from emitting empty `final_answer` when the stream
   ships only token frames (W3 — BP-613).
4. Stop the `last_fundamentals_ingest_at` UPDATE from buffer-and-drop
   on any consumer-layer try/except (W2 — BP-610).

### Non-goals

- New PRD features.
- Backend phase-emit changes — the `llm_synthesis_streaming` label was
  already shipped by PLAN-0099 W1-T03 and is now formalised as a
  public contract by docs only.
- Model swap (deferred to PLAN-0100 W6).
- Full Grafana panel for freshness bucketing (deferred to a later
  PLAN-0102+ wave).

## §1 — Dependency Graph

```
W1 (audit + diagnosis) ──► W2 (BP-610 flush)        ─► live verification
                       └─► W3 (TPS redesign + BP-612 + BP-613)
```

W2 and W3 are independent code-wise (different services, different
test suites) and were shipped within the same day on the same branch
(`feat/plan-0099-w4`).

## §2 — Codebase Verification

| Citation | File:line | Verified |
|---|---|---|
| TPS metric harness | `tests/validation/chat_eval/harness.py` | ✅ exists; legacy `tps` field retained as diagnostic |
| TPS gate | `tests/validation/chat_eval/test_aggregate_score.py` | ✅ exists |
| Grader honest-quote branch | `tests/validation/chat_eval/grading.py:581-706` | ✅ verified post-commit |
| Backend phase wrapper (read-only) | `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py:1687,1696` | ✅ verified PLAN-0099 review; emits `llm_synthesis_streaming` label |
| Phase plumbing | `services/rag-chat/src/rag_chat/application/observability/phase_timings.py` | ✅ exists (PLAN-0099 W1-T03) |
| Repo touch method | `services/market-data/src/market_data/infrastructure/db/repositories/instrument_repo.py::touch_fundamentals_ingest_at` | ✅ exists post-PLAN-0096 |
| Consumer call site | `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer.py:589` | ✅ verified |
| Migration | `services/market-data/alembic/versions/021_*.py` | ✅ applied live |

## §3 — Sub-plans

### Wave 1 — Audit + Diagnosis (✅ SHIPPED 2026-05-28)

#### Tasks

- **T-W1-01 — TPS metric redesign audit**
  - Produce `docs/audits/2026-05-28-plan-0101-tps-metric-redesign.md`
    documenting:
    - Why legacy `tps` collapsed after PLAN-0100 W2 (TTFT broadened to
      include tool_call/status frames; denominator now absorbs full
      tool-fanout window).
    - Why `llm_synthesis_streaming` wall-clock is the correct
      denominator (it measures what users perceive as streaming
      throughput, independent of tool latency).
    - Calibration target: DeepInfra DeepSeek-R1-Distill-32B baseline
      observed at ~25-40 tok/s — set the gate at 20 tok/s to avoid
      flapping on the lower bound.
  - Deliverable: audit doc. ✅

- **T-W1-02 — BP-610 freshness-column audit**
  - Produce `docs/audits/2026-05-28-plan-0101-bp-610-touch-at.md`
    walking the H1→H4 elimination tree:
    - H1: migration applied? ✓
    - H2: PG triggers blocking? ✗
    - H3: failed_tasks / DLQ? ✗
    - H4: image staleness? ✓ (primary)
    - Latent: repo method missing explicit `flush()`? ✓ (defensive fix)
  - Deliverable: audit doc. ✅ (created retroactively under PLAN-0102 W7 T-W7-01).

### Wave 2 — BP-610 Flush Fix (✅ SHIPPED 2026-05-28, commits `096ebc5d` / `ca9e4dc7`)

#### Tasks

- **T-W2-01 — Add `await self._session.flush()` to `touch_fundamentals_ingest_at`**
  - File: `services/market-data/src/market_data/infrastructure/db/repositories/instrument_repo.py`
  - Pain point: SQLAlchemy Core `update()` against the async session is
    buffered until commit; a downstream try/except can swallow the
    exception that would otherwise force a flush, silently dropping
    the UPDATE. Matches repo-wide convention (`content-store`, `alert`,
    `rag-chat`, `content-ingestion` all flush inside repo writes).
  - Regression test: `services/market-data/tests/integration/test_repositories.py::TestPgInstrumentRepository::test_touch_fundamentals_ingest_at_persists`
    — inserts a fresh instrument, awaits the touch, opens a sibling
    session to verify the column is non-NULL without an explicit test-side
    flush.

- **T-W2-02 — Image rebuild + container recreate**
  - `docker compose build market-data && docker compose up -d --no-deps
    --force-recreate market-data-fundamentals-consumer`
  - Operator gate: live freshness column starts climbing within one
    consumer cycle.

- **T-W2-03 — Live verification**
  - First touched row: TSLA at `16:09:55Z`.
  - 11 rows non-NULL by `16:12:00Z`.
  - **198 rows** non-NULL by end of refresh cycle.
  - End-to-end full-platform verification deferred to QA round (manual
    refresh trigger requires an internal-JWT-signed POST to
    market-ingestion).

#### W2 acceptance gate

Post-rebuild: any new instrument fundamentals materialisation cycle
advances `instruments.last_fundamentals_ingest_at` for the affected
rows. ✅ verified live.

#### W2 compounding

- `docs/BUG_PATTERNS.md` BP-610 entry (FIXED status, regression test
  pointer, image-rebuild note).
- `services/market-data/.claude-context.md` pitfall: "every repo write
  method targeting a tracking/freshness column MUST flush inside the
  repo — never rely on consumer commit boundary alone".
- `docs/services/market-data.md` Freshness Tracking subsection updated.

### Wave 3 — TPS Metric Redesign + BP-612/613 (✅ SHIPPED 2026-05-28, commit `91a363a0`)

#### Tasks

- **T-W3-01 — Replace legacy `tps` gate with `tps_streaming`**
  - Harness: `tests/validation/chat_eval/harness.py`
    - New `_compute_tps_streaming(synthesis_phase_ms, output_tokens)`
      pure helper. Reads `done.data.phase_timings_ms.llm_synthesis_streaming`
      (PLAN-0099 W1-T03 plumbing). Returns `NaN` when wall-clock is
      missing or zero (cleanly distinguishable from a finite slow
      result).
    - `ChatRunResult` gains `tps_streaming: float | None` and
      `phase_timings_ms: dict[str, float]` fields.
    - `_events_to_result()` extracts `phase_timings_ms` from the
      `done` event body.
  - Grader: `tests/validation/chat_eval/grading.py`
    - `grade_response()` returns `tps_streaming` alongside `tps`.
  - Aggregate gate: `tests/validation/chat_eval/test_aggregate_score.py`
    - `_TPS_STREAMING_P50_MIN = 20.0`.
    - `_tps_streaming_gate_failures()` extracted as a pure helper for
      testability.
    - Legacy `tps` retained on artefacts as a diagnostic for historical
      comparison.

- **T-W3-02 — BP-612 grader honest-quote exemption widening**
  - Add plural-form marker `"do not appear"` (existing) + variants to
    `_REFUSAL_MARKERS` in `grading.py:584` area.
  - Widen the revenue-cap exemption window from ±60 chars to **±150
    chars** so refusals sitting ~95 chars after the offending number
    are still claimed.
  - Regression tests: 4 cases pinning marker positions at 0 / 95 / 149
    / 151 (last is the negative case: just outside the window).

- **T-W3-03 — BP-613 harness `final_answer` fallback**
  - When `done.data.final_answer` is empty or missing, the harness
    falls back to concatenating every `delta`/`token` event payload in
    order (`joined_tokens`).
  - Result: `final_answer` is chosen when present AND non-empty,
    otherwise `joined_tokens`.
  - Regression tests (4 in `TestBP613AnswerAssemblyFallback` at
    `tests/validation/chat_eval/test_harness_latency.py:106`):
    empty `final_answer` + tokens → fallback used; missing key +
    tokens → fallback used; present and non-empty → fallback ignored;
    both empty → result empty (graceful).

- **T-W3-04 — Docs sync**
  - `docs/services/rag-chat.md` Per-Phase Timing section gains a
    "phase-label is a public contract" warning — chat-eval depends on
    the `llm_synthesis_streaming` label being emitted unchanged.
  - `services/rag-chat/.claude-context.md` pitfall: "renaming any
    phase label inside `chat_orchestrator.py:1687/1696` will break
    chat-eval's `tps_streaming` metric silently — coordinate with
    `tests/validation/chat_eval/harness.py::_compute_tps_streaming` if
    you touch this".

#### W3 acceptance gate

- `tps_streaming` is a finite float for every chat-eval question on a
  warm stack (replaces the NaN-prone legacy `tps`).
- BP-612 regression test covers ±150 char placement at four boundary
  values.
- BP-613 regression test covers four assembly-fallback states.
- Legacy `tps` continues to be recorded on the per-question artefact
  for historical comparison.
- All 1374 rag-chat unit tests + 18 chat-eval unit tests + 57 chat-eval
  grading tests pass.
- ruff + ruff-format + mypy clean on all 10 touched files.

#### W3 compounding

- `docs/BUG_PATTERNS.md` BP-612 (grader honest-quote window) + BP-613
  (harness assembly fallback) — filed retroactively under PLAN-0102 W7
  T-W7-02.
- `tests/validation/chat_eval/test_harness_latency.py` `TestBP613…`
  class.
- `tests/validation/chat_eval/test_grading.py` `TestGraderHonestRefusalExemption`.
- `docs/services/rag-chat.md` chat-eval gate table updated with the
  new `tps_streaming_p50 ≥ 20 tok/s` gate.

## §4 — Cross-cutting Acceptance Gate

After all 3 waves deploy:

1. **Chat-eval rerun** on rebuilt stack:
   - Verdict gates unchanged (`USEFUL ≥ 6`, `HARMFUL = 0`).
   - `tps_streaming_p50 ≥ 20 tok/s`.
   - Legacy `tps` recorded but not gated.

2. **Live freshness check**:
   - `SELECT COUNT(*) FROM instruments WHERE last_fundamentals_ingest_at IS NOT NULL`
     climbs each refresh cycle.
   - Sentinel: TSLA was the first row to advance (`16:09:55Z`).

## §5 — Risk Register

| Risk | Mitigation |
|---|---|
| `tps_streaming` returns NaN under all conditions (e.g. backend phase label silently renamed) | W3-T04 doc warning + .claude-context.md pitfall; PLAN-0102 W4 schedules a deeper trace + `record_once()` guard for the phase wrapper |
| BP-612 widened window swallows real fabrications sitting >150 chars from the value | The widening keeps the marker-set requirement; a fabrication still has to include a refusal marker to qualify — pure number-fabrications without any refusal language remain HARMFUL |
| BP-613 fallback ships rejected text with stale `[N#]` markers | Citation marker scrub deferred to PLAN-0102 W5 (BP-616 reservation); the immediate fix prefers `final_answer` when present and only falls back when it is genuinely empty |
| BP-610 image rebuild not propagated to all environments | Rebuild step documented in audit + the BP-610 entry NOTE field; QA round to verify across staging + prod |

## §6 — Compounding Steps

Per wave:
- **W1** — two audit docs.
- **W2** — BP-610 entry update + market-data docs + .claude-context.md pitfall.
- **W3** — BP-612 + BP-613 entries + rag-chat docs + .claude-context.md pitfall + chat-eval gate table.

## §7 — Owner

- **W1** — chat-eval owner (PLAN-0102 W7 owner retroactively filed the audit doc).
- **W2** — market-data owner.
- **W3** — chat-eval tooling owner.

## §8 — Status (retroactive)

| Wave | Status | Commit |
|---|---|---|
| W1 — Audits | ✅ SHIPPED (W1-T01 in same commit family as W3; W1-T02 retroactively created in PLAN-0102 W7 T-W7-01) | various |
| W2 — BP-610 flush | ✅ SHIPPED 2026-05-28 | `096ebc5d` / `ca9e4dc7` |
| W3 — TPS + BP-612 + BP-613 | ✅ SHIPPED 2026-05-28 | `91a363a0` |

## Estimated Effort (retroactive)

| Wave | Hours (actual) | Notes |
|---|---|---|
| W1 — Audits | ~2 | One audit shipped same-day, one retroactively |
| W2 — BP-610 flush | ~3 | Single-line fix + integration test + image rebuild + live verification |
| W3 — TPS + BP-612 + BP-613 | ~5 | Three independent fixes in same chat-eval commit |
| **Total** | **~10 h** | |
