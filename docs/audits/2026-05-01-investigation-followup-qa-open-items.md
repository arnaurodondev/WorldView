# Investigation: Open & Deferred Items from PLAN-0057 Follow-up QA

**Date**: 2026-05-01
**Investigator**: Claude (investigation skill)
**Severity**: LOW (none of the items break user-facing behaviour today)
**Status**: All root causes identified; concrete fix paths proposed

---

## 1. Issue Summary

The strict QA agent on the 4 PLAN-0057 follow-up waves (A/B/C/D) reported `SHIP_WITH_FOLLOWUPS` and recorded 4 open MINOR/NIT items plus 1 explicitly deferred item. Two of those (F-004, F-005) were closed in commit `04f4d771`. This investigation covers the remaining four:

| ID | Source | Type | Today's risk |
|----|--------|------|--------------|
| **F-001** | Wave A | Cosmetic — commit-message inaccuracy | None |
| **F-002** | Wave A | Defensive correctness — service JWT `tenant_id="system"` literal | None today; latent |
| **F-003** | Wave C | Test infrastructure — frontend cold-start vitest flake | Intermittent CI noise |
| **DS-007** | Wave D | Architectural fragility — InstrumentDiscoveredConsumer dual-UoW | None today; latent for future maintainers |

---

## 2. Per-item Investigation

### 2.1 F-001 — Wave A commit message references nonexistent helper

#### Root cause
Commit `3091bea7` body claims the new endpoint mints via "the existing `jwt_utils.encode_internal_jwt` helper". The implementation actually adds a NEW helper (`issue_service_jwt`); `encode_internal_jwt` does not exist anywhere in the codebase. Pure documentation drift in past git history.

#### Evidence
```bash
$ grep -rn "encode_internal_jwt" .
# (no matches)

$ grep -n "issue_service_jwt" services/api-gateway/src/api_gateway/jwt_utils.py
83:def issue_service_jwt(
```

#### Fix options

| Option | Effort | Verdict |
|--------|--------|---------|
| A. Force-push amended commit message | 5 min | **Reject** — destructive, violates the no-force-push hard rule, and the commit is already pushed. |
| B. Note the inaccuracy in a follow-up commit's body / changelog entry | 1 min | **Reject** — adds noise; the commit message has zero behavioural impact. |
| C. Do nothing | 0 min | **Accept** — documentation drift in past git history. The actual code is correct. |

#### Recommendation: **Option C — do nothing**.

This is informational only. The implementation is correct; only the commit message is aspirational.

---

### 2.2 F-002 — Service JWT carries `tenant_id="system"` literal instead of nil UUID

#### Root cause
`services/api-gateway/src/api_gateway/jwt_utils.py:110` sets `"tenant_id": "system"` in the service-JWT payload. Sibling `issue_public_jwt` correctly uses `_NIL_UUID = "00000000-…"`. Backends that downcast `tenant_id` to UUID would crash on `"system"`.

#### Why it doesn't break today
1. The only consumer of the new service-token endpoint is `MarketDataClient` calling market-data REST endpoints. Those endpoints don't filter by `tenant_id` (instruments are global).
2. Where backends do read `tenant_id`, they uniformly use `contextlib.suppress(ValueError, AttributeError)` around the `UUID(...)` cast, so `"system"` becomes `None` rather than crashing. Confirmed in `services/nlp-pipeline/src/nlp_pipeline/infrastructure/messaging/consumers/article_consumer.py:209-212`.
3. `InternalJWTMiddleware` stores `tenant_id` as a raw string on `request.state` — no coercion, no crash.

#### Why it matters
The next service that adopts the service-token endpoint (almost certainly nlp-pipeline-relevance-scoring or rag-chat) might write directly to a tenant-scoped table without the defensive cast. That handler would 500. The existing `issue_public_jwt` proves the team already knows the right pattern (nil UUID); the divergence in `issue_service_jwt` is a footgun, not a functional bug.

#### Hypotheses

**H-1**: `issue_service_jwt` author wanted `tenant_id="system"` to be greppable in logs as a "this is a service call" marker.
- **Evidence for**: Several internal logs already key on `role="system"` for the same purpose, and the literal `"system"` does read better than a UUID in `s7_kg_request_total{tenant_id=…}` Prometheus labels.
- **Evidence against**: `oidc_sub="service:<service_name>"` already provides the service-call marker; `tenant_id` is the wrong field for that semantic.
- **Verdict**: Plausible motivation, but the wrong field carries the marker.

**H-2** (winning): The author overlooked the established pattern. `issue_public_jwt` was written first with `_NIL_UUID`; `issue_service_jwt` was added without re-reading the sibling.
- **Verdict**: Most likely.

#### Fix options

| Option | Description | Effort | Long-term verdict |
|--------|-------------|--------|-------------------|
| **A** | Change `tenant_id` to `_NIL_UUID` in `issue_service_jwt`; add `service_name` to the JWT (already there) for the "this is a service call" marker. | 10 min | **Best long-term** — matches `issue_public_jwt`, eliminates the footgun. |
| B | Document in comment + `.claude-context.md` that service tokens carry `tenant_id="system"` and consumers must defensively coerce. | 5 min | Doc-only; doesn't address the latent bug for new adopters. |
| C | Add a contract test in `libs/messaging` or `services/api-gateway` that asserts every internal-JWT type carries a UUID-castable `tenant_id`. | 30 min | Best at preventing recurrence but doesn't fix the existing token. Ship alongside A. |

#### Recommended: **A + C** combined
1. Swap `"tenant_id": "system"` → `"tenant_id": _NIL_UUID` in `issue_service_jwt`.
2. Add a unit test in `services/api-gateway/tests/unit/test_jwt_utils.py` that asserts every helper's output payload has a UUID-castable `tenant_id`.

#### Effort: ~30 min total
#### Risk: Low — `service_name` claim still carries the "this is a service call" semantic; no consumer reads `tenant_id` for that purpose.

---

### 2.3 F-003 — Frontend vitest cold-start flake on `alias-types.test.tsx`

#### Symptom
First `pnpm vitest run` after a long idle period intermittently reports 2 failures referencing `collectTests`; immediate re-run is 1179/1179 green.

#### Root cause hypothesis chain

**H-1**: `vi.useFakeTimers()` in `beforeEach` of `AliasPill — copy interaction` describe leaks across test files because vitest's `restoreAllMocks` doesn't auto-restore real timers.
- **Evidence**: `afterEach` calls `vi.useRealTimers()` BUT only inside that describe; if a prior test file in the same vitest worker process left fake timers active and crashed before its own `afterEach` fired, this file's first test inherits broken timer state.
- **Test**: Add `vi.useRealTimers()` at module load (top of file, before any describe). Verdict: HIGH likelihood.

**H-2**: vitest worker pool reuse across test files leaves `navigator.clipboard` defined on `globalThis` after our `beforeEach` installs it; the `delete` in `afterEach` fires only if originalClipboard was undefined; subsequent tests in another file see a stale `vi.fn().mockResolvedValue(undefined)` instead of the real (or absent) clipboard.
- **Evidence**: `Object.defineProperty(navigator, "clipboard", {configurable: true, ...})` then `delete navigator.clipboard` only when `originalClipboard === undefined`.
- **Test**: Always restore via `Object.defineProperty(navigator, "clipboard", originalClipboard ?? {value: undefined, configurable: true})`. Verdict: MEDIUM likelihood.

**H-3**: Module-import side-effects in `vitest.setup.ts` (the localStorage shim's `Object.defineProperty(window, "localStorage", {configurable: true, value: storage})`) race with worker initialisation if the file is imported twice on cold start (via setup + via test). The `configurable: true` guard prevents the second `defineProperty` from throwing, but a race between shim install and the first test's localStorage read could surface.
- **Evidence**: `vitest.setup.ts:65-74`. `configurable: true` is the right guard but the shim still creates a new `Map` per setup load — two parallel loads race on `storeMap.set`.
- **Test**: Move setup to a hook-based pattern that runs once per worker. Verdict: LOW.

#### Recommended fix: layered (small + cheap)

| Layer | Change |
|-------|--------|
| 1 (essential) | Hoist `vi.useRealTimers()` to the top of `__tests__/alias-types.test.tsx` so every run starts from a known timer state, regardless of what a prior test file did. |
| 2 (defensive) | In `afterEach`, always reinstall the original descriptor via `Object.defineProperty(navigator, "clipboard", originalClipboard ?? {value: undefined, configurable: true, writable: true})` — never call `delete` (which leaves the property in an inconsistent state across vitest worker reuse). |
| 3 (nice-to-have) | Add `cleanup()` from `@testing-library/react` in `afterEach` so every test starts with a fresh DOM root. RTL auto-injects this when `globals: true` is set in vitest config, BUT only for the file that imports `@testing-library/react`; explicit is safer. |

#### Effort: 15 min
#### Risk: Zero — pure test-infrastructure cleanup.

---

### 2.4 DS-007 — InstrumentDiscoveredConsumer dual-UoW pattern

#### Root cause
`process_message` (line 163) opens its own session via `async with self._sf() as session:` and commits at line 229. The base `BaseKafkaConsumer._handle_message` (line 333) wraps the call in its own `_NoOpUoW` (returned by `get_unit_of_work`), whose `commit`/`rollback` are no-ops. Net effect:

1. Base enters `_NoOpUoW` (no-op).
2. `process_message` runs, commits its own session.
3. Base calls `mark_processed(event_id)` (writes to Valkey).
4. If `mark_processed` raises, base calls `_NoOpUoW.rollback()` — silently passes (no-op).
5. Exception bubbles to `_handle_failure` → DLQ.
6. Re-delivery: process_message runs again; `ON CONFLICT DO NOTHING` keeps the canonical correct.

**Today**: safe because every write in `process_message` is idempotent (canonical via `ON CONFLICT (entity_id) DO NOTHING`; aliases via partial UNIQUE index). **Tomorrow**: any future maintainer who adds a non-idempotent write inside `process_message` (e.g., a counter increment, an outbox event, a side effect to MinIO) will silently double-write under re-delivery.

#### Why it exists
Historical: the consumer was added before the `BaseKafkaConsumer` framework formalised the UoW pattern. Older consumers (e.g., `instrument_consumer.py`) use the same dual pattern; the framework supports both via the no-op UoW escape hatch.

#### Fix options

| Option | Description | Effort | Risk | Long-term verdict |
|--------|-------------|--------|------|-------------------|
| **A** | Route writes through `self._current_uow.session` (a new `SessionScopedUoW` that the base accepts as `get_unit_of_work` return value). Drop the inner `async with self._sf() as session:`. | 1-2 hours | Medium — touches the base UoW protocol; needs broad test coverage. | **Best architecturally** — single source of truth, atomic commit. |
| B | Keep dual pattern; add a regression test asserting that re-delivery produces no duplicates (proves idempotency saves us). | 30 min | Low — proves the contract that today's code already satisfies. | Acceptable defensive layer but doesn't address the future-maintainer footgun. |
| C | Add a strict `# WARNING: process_message commits its own session before base UoW. Do not add non-idempotent writes here without first migrating to the SessionScopedUoW pattern.` block comment + a corresponding REVIEW_CHECKLIST.md entry. | 10 min | Zero | Cheapest — reduces footgun via process. |
| D | Refactor `BaseKafkaConsumer.get_unit_of_work` to receive `session_factory` and return a real session-bearing UoW; make `_NoOpUoW` an explicit opt-out for consumers that genuinely don't want one (rare). | 4-6 hours, multi-service | High — every consumer in the platform touches this. | Best architecturally but out of scope for a polish PR. |

#### Recommended: **B + C as a quick PR; D as a separate plan**

1. **B (regression test)** — `services/knowledge-graph/tests/integration/consumer/test_instrument_discovered_consumer_idempotency.py`: dispatch the same event twice via `_handle_message`; assert exactly one canonical row + one EXACT alias + one TICKER alias + 3 embedding-state rows after both deliveries; assert no DLQ entry.
2. **C (warning comment + checklist entry)** — add a 4-line `# WARNING:` block at the top of `process_message` AND add a REVIEW_CHECKLIST.md item under §6b: "If a Kafka consumer's `process_message` opens its own session and commits inline, every write inside MUST be idempotent (ON CONFLICT / upsert / Valkey SET NX). Non-idempotent writes require migrating to the SessionScopedUoW pattern."
3. **D (architectural refactor)** — file a separate plan PLAN-006X (TBD) for "BaseKafkaConsumer SessionScopedUoW migration" covering all 8+ consumers across services. Out of scope for the current polish-PR cadence.

#### Effort breakdown
- B + C: 45 min total
- D: separate plan, ~3-4 implementer-days

#### Risk: Low for B+C; Medium for D (reserved for a dedicated plan with full QA cycle).

---

## 3. Summary Table — Fix Approach Per Item

| Item | Recommended Fix | Effort | Long-term verdict |
|------|----------------|--------|-------------------|
| F-001 | Do nothing (cosmetic git history) | 0 min | Accept |
| F-002 | Swap to `_NIL_UUID` + add per-helper contract test | 30 min | Best — eliminates footgun; aligns with existing `issue_public_jwt` |
| F-003 | Hoist `vi.useRealTimers()` + always reinstall clipboard descriptor + explicit `cleanup()` | 15 min | Best — zero risk; defends against worker-pool reuse races |
| DS-007 | Idempotency regression test + warning comment + REVIEW_CHECKLIST entry; refactor in a separate plan | 45 min for B+C; 3-4 days for D | B+C now; D as PLAN-006X |

**Total quick-win effort**: ~90 min for F-002 + F-003 + DS-007 (B+C). All three can land in a single small "polish-followup" PR.

---

## 4. Strategic Recommendation

### Bundle into a single ~90-minute polish PR

**Wave E — PLAN-0057 polish-followup**:
- F-002: `tenant_id` → `_NIL_UUID` in `issue_service_jwt` + 2 unit tests (one per JWT helper) asserting UUID-castable `tenant_id`
- F-003: 3-layer test cleanup in `alias-types.test.tsx`
- DS-007 B + C: idempotency regression test on InstrumentDiscoveredConsumer + warning comment + REVIEW_CHECKLIST entry

### Defer to its own plan

**PLAN-006X — Consumer SessionScopedUoW migration**:
- DS-007 D: refactor `BaseKafkaConsumer.get_unit_of_work` to accept session_factory + return real session-bearing UoW
- Migrate all 8+ existing dual-UoW consumers (instrument_consumer, instrument_discovered_consumer, fundamentals_consumer, ohlcv_consumer, quotes_consumer, …)
- Cross-cutting refactor; needs strict QA on each consumer
- Estimated: 3-4 implementer-days + 1-2 QA iterations

### Why the split

The 90-minute polish PR captures the immediate value (eliminate footguns, fix flake, document fragility) without the risk of a multi-service refactor. The dedicated plan handles the architectural cleanup with the rigor it deserves.

---

## 5. Compounding Updates

These artefacts should land alongside the polish PR (or sooner if the PR is delayed):

| Document | Update |
|----------|--------|
| `docs/BUG_PATTERNS.md` | New entry: "JWT helper `tenant_id` field MUST be UUID-castable" (BP from F-002) |
| `.claude/review/checklists/REVIEW_CHECKLIST.md` §6b | New check: "If a Kafka consumer's `process_message` opens its own session, every write MUST be idempotent" (DS-007 C) |
| `.claude/review/checklists/REVIEW_CHECKLIST.md` §10 (Frontend) | New check: "Test files using `vi.useFakeTimers()` must hoist `vi.useRealTimers()` before any describe to neutralise leaked state from prior worker-pool tests" (F-003 prevention) |
| `services/api-gateway/.claude-context.md` | Note that `issue_service_jwt` and `issue_public_jwt` are the canonical patterns for system-scope tokens; both use `_NIL_UUID` for `tenant_id` |
| `libs/messaging/src/messaging/kafka/consumer/base.py` (docstring) | Document the dual-UoW escape hatch and when each pattern is appropriate |

---

## 6. Open Questions

1. **DS-007 D — should consumer writes use the same UoW the dispatcher uses?** That would couple consumer + outbox transactionally (good for "consume + emit downstream event" patterns but adds complexity). Worth discussing in PLAN-006X scoping.

2. **F-003 — is the cold-start flake actually `alias-types.test.tsx` or a different file that polluted the worker?** The QA agent's first run showed the failure but the second pass was green; without a deterministic repro, layered defence (H-1 + H-2 fixes) is the right hedge but we may not see the underlying culprit until it surfaces again.

3. **F-002 — should the new contract test enforce `_NIL_UUID` specifically, or just "UUID-castable string"?** The latter is more flexible; the former pins the convention. Recommend the former (`assert payload["tenant_id"] == _NIL_UUID for system-scope tokens`) since the convention is the point.

---

## Recommendations

1. **Now** — open a `Wave E polish-followup` ~90-min PR covering F-002 + F-003 + DS-007 B+C.
2. **Next sprint** — file PLAN-006X for DS-007 D (consumer SessionScopedUoW migration) as a dedicated multi-service refactor.
3. **Compounding** — add the 3 REVIEW_CHECKLIST entries (and 1 BP entry) so future PRs catch these patterns at review time.

Compounding check: 4 review-checklist additions noted above.
