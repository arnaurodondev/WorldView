---
id: PLAN-0123
title: "Empirically-Fit Per-Type Decay Half-Lives — Implementation Plan"
prd: PRD-0120
status: in-progress
created: 2026-07-14
updated: 2026-07-14
---

# PLAN-0123 — Empirically-Fit Per-Type Decay Half-Lives

## Overview
PRD: [PRD-0120](../specs/0120-empirical-decay-half-life.md)
Review: [2026-07-03-prd-0120-review.md](../audits/2026-07-03-prd-0120-review.md) — SS-1 identification-error fix is incorporated into Wave 2 below (locked decision, not deferred).
Services affected: intelligence-migrations (DDL owner, R24), knowledge-graph / S7 (lookup change + new offline fitter module)
Total estimated waves: 4 (matches PRD §15 W1-W4)
Deploy target for this pass: local docker-compose only.

## Dependency Graph
Single sequential plan, 4 waves, strict chain: **W1 → W2 → W3 → W4**. No parallel plans — this is a single-service (S7) + single-migration-owner (intelligence-migrations) change. W1 is the only wave that touches production code paths that run today; W2-W4 are additive/offline until W3's write-back is explicitly enabled.

Cross-plan note: PRD-0119 (PLAN-0119, status `draft`, 0/5 waves — not started) also evolves `relation_type_registry` and is *not* in progress, so there is no live collision. Whoever implements PLAN-0119 later must re-run the Phase -1 alembic HEAD check (do not assume 0067 — this plan claims it).

## Codebase State Verification (Phase 1.3 — read 2026-07-14)

| PRD Reference | Type | Service | Actual Current State (from code) | PRD Expected State | Delta |
|---|---|---|---|---|---|
| `relation_type_registry` | DB table | intelligence-migrations | `services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py:222-258` — no `decay_alpha`/`half_life_days`/`alpha_fit_n`/`alpha_fit_method`/`alpha_fit_at` columns | add 5 nullable columns (FR-1) | migration needed |
| Alembic HEAD | migration | intelligence-migrations | `0066_prediction_event_type_and_exposure_polarity.py`, `down_revision="0065"` | — | new revision `0067`, `down_revision="0066"` |
| `RelationTypeRegistryRepository.find_exact` | SQL query | S7 | `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_type_registry.py:32-38` — `SELECT ... dcc.decay_alpha FROM relation_type_registry rtr JOIN decay_class_config dcc ON dcc.decay_class = rtr.decay_class ...` (class value only, no per-type override) | registry-first, class-fallback (FR-2) | query change: `COALESCE(rtr.decay_alpha, dcc.decay_alpha) AS decay_alpha` |
| `RelationTypeRegistryRepository.find_by_embedding` | SQL query | S7 | same file, lines 87-97, same `dcc.decay_alpha`-only pattern | same | same COALESCE change |
| `RelationTypeRegistryRepository.find_exact_simple` | SQL query | S7 | lines 53-72 — does not join `decay_class_config` at all, no `decay_alpha` in result | out of scope (PRD does not use this path) | none — verify no caller relies on it for confidence math |
| `confidence.py` | domain module | S7 | `services/knowledge-graph/src/knowledge_graph/domain/confidence.py` — `compute_confidence_beta` reads `decay_alpha` at l.359 (support), l.373 (contradiction); v1 `compute_confidence` reads it at l.148 (`eff_alpha = decay_alpha`) | zero diff (NFR-1) | **none** — reference only, do not edit arithmetic |
| `relations.decay_alpha` denormalization | upsert path | S7 | `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation.py:79` `ON CONFLICT ... decay_alpha = EXCLUDED.decay_alpha` — **only fires on upsert**, i.e. new evidence; a relation that receives no new evidence never re-resolves its alpha (review-confirmed: the "lazy refresh via confidence-stale" claim in PRD §6.4 is false) | denormalize registry-first, class-fallback (FR-2); PRD assumed lazy refresh sufficed | query change (same COALESCE, applied where `decay_alpha` param is resolved before calling `upsert`) **+ explicit backfill UPDATE task in W3** (elevates OQ-7) |
| `relation.py:150` `upsert_relation()` wrapper | convenience fn | S7 | hardcodes `decay_alpha=0.000950` unconditionally (DURABLE) | not mentioned by PRD | **out of scope** — enumerate as pre-existing hardcode, not touched (not a `TEMPORAL_CLAIM` write path) |
| `graph_write.py:598` | application block | S7 | `decay_alpha=decay_alpha if decay_alpha is not None else 0.000950,` inside `relation_repo.upsert(...)` | PRD FR-2 changes "wherever decay_alpha/decay_class are denormalized" | this IS the primary FR-2 injection point — the `decay_alpha` value fed in here must come from the new COALESCE-based registry lookup, not stay `None`-then-hardcoded |
| `entity_consumer.py:340`, `entity_enrichment_adapter.py:416`, `fundamentals_refresh.py:70/74/1070/1111` | misc write sites | S7 | all hardcode `decay_alpha` for `RELATION_STATE` types (DURABLE 0.000950 / sector 0.0 / industry 0.000950) | review flagged these as bypassing the registry | **out of scope** (P-3: fitting is `TEMPORAL_CLAIM`-only; none of these 5 sites write a `TEMPORAL_CLAIM` type) — W1 includes a verification task, not a code change |
| `relations_history` | DB table | intelligence-migrations | `0056_relations_history_bitemporal.py:66-78` — columns include `decay_class` but **no `decay_alpha` column** | PRD §6.6 lists it as a "secondary" supersession-lifetime source | fitter design change: read time-to-supersession directly from `relations.first_evidence_at`/`latest_contra_at`/`valid_to` (already denormalized on `relations`), do not depend on `relations_history` for alpha |
| Fitter module | new code | S7 | confirmed: no `analytics/`, `fitter/`, or `survival/` directory exists anywhere under `services/knowledge-graph/src/` | new offline module (FR-3) | net-new: `src/knowledge_graph/application/analytics/decay_fitting/` |
| `.claude-context.md` | doc | S7 | `services/knowledge-graph/.claude-context.md:23-26` describes the **stale v1** `compute_confidence` 4-step formula and falsely claims "TEMPORAL_CLAIM always uses 0.02310" — contradicts current code (l.148: `eff_alpha = decay_alpha` unconditionally) | PRD §12 asks for a decay-fitting doc update | W4 doc task must fix this **pre-existing** drift too (independent bug, not introduced by this plan) |

## Name Verification (BP-405 guard)

| Name | Kind | Verification | Result |
|---|---|---|---|
| `relation_type_registry.py` `find_exact`/`find_by_embedding`/`find_exact_simple` | methods | read directly, confirmed lines 32-38 / 87-97 / 53-72 | existing |
| `confidence.py` `compute_confidence_beta` / `_temporal_weight` / `_days_since` | functions | read directly, lines 297-309 / 85-87 / 79-82 | existing |
| `graph_write.py` (`application/blocks/graph_write.py`) | file | read directly | existing |
| `relation.py` (`infrastructure/intelligence_db/repositories/relation.py`) `upsert()` | method | read directly, lines 32-42 | existing |
| `0066_prediction_event_type_and_exposure_polarity.py` | migration | `ls services/intelligence-migrations/alembic/versions/` | existing, confirmed HEAD |
| `0067_add_relation_type_decay_fit_columns.py` | migration | `ls` returned no match | **NEW — created in Wave 1** |
| `DecayFit`, `Lifetime` value objects | classes | `git grep` returned no hits | **NEW — created in Wave 2** |
| `src/knowledge_graph/application/analytics/decay_fitting/` | module path | `ls` returned no match | **NEW — created in Wave 2** |
| `relations_history` (`0056_relations_history_bitemporal.py`) | table | read directly, confirmed no `decay_alpha` column | existing (used read-only, not as an alpha source) |

---

## Wave 1: Nullable Columns + Registry-First/Class-Fallback Lookup (No-Op) ✅

**Status**: **DONE** — 2026-07-14 · 40 tests pass (27 KG unit + 13 migration static) · ruff + mypy + import-guards + architecture tests clean · `confidence.py` zero diff confirmed

**Goal**: Add the 5 nullable `relation_type_registry` columns and change the alpha resolution to registry-first/class-fallback. With all new columns NULL, resolved alpha is byte-identical to today — this wave is a safe substrate, not a behavior change.
**Depends on**: none
**Estimated effort**: 45-60 min
**Architecture layer**: infrastructure (migration) + infrastructure (repository queries)

**Implementation notes**:
- T-A-1-03 turned out to require zero code changes: `graph_write.py:598`'s `decay_alpha` local is populated upstream by `canonicalization.py` (`exact["decay_alpha"]`/`soft["decay_alpha"]`), which reads directly from `RelationTypeRegistryRepository`. Fixing the COALESCE at the repository layer (T-A-1-02) was sufficient for the value to flow through unmodified to `enriched_consumer.py` → `graph_write.py`. Verified with new passthrough tests in `test_canonicalization.py` using a fitted value (0.0088) distinct from any class constant.
- Full `knowledge-graph` unit suite (1787 tests) re-run post-change: 0 regressions.
- `intelligence-migrations` integration/naming tests require a live Postgres + `psycopg2` (pre-existing `tests/conftest.py` autouse fixture, unrelated to this change) — not runnable in this sandbox; will be exercised for real during the docker-compose deploy step.

#### Tasks

##### T-A-1-01: Alembic migration adding 5 nullable `relation_type_registry` columns

**Type**: schema
**depends_on**: none
**blocks**: [T-A-1-02, T-A-2-*, T-A-3-*]
**Target files**: `services/intelligence-migrations/alembic/versions/0067_add_relation_type_decay_fit_columns.py` (NEW)
**PRD reference**: §4 FR-1, §6.4

**What to build**: A single Alembic revision, `revision = "0067"`, `down_revision = "0066"`, adding 5 nullable columns to `relation_type_registry` (intelligence_db). All columns default NULL — no data migration, no backfill in this task.

**Columns** (exact per PRD §6.4):
- `decay_alpha FLOAT NULL`
- `half_life_days FLOAT NULL`
- `alpha_fit_n INTEGER NULL`
- `alpha_fit_method TEXT NULL`
- `alpha_fit_at TIMESTAMPTZ NULL`

**Logic**: `op.add_column("relation_type_registry", sa.Column(...))` × 5 in `upgrade()`; `op.drop_column(...)` × 5 in `downgrade()` (reverse order). No `server_default` needed since NULL is the correct default and the column is nullable (R11).

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| test_0067_upgrade_adds_five_nullable_columns | All 5 columns exist, all nullable, all NULL on existing 20 seed rows after upgrade | integration (testcontainers Postgres) |
| test_0067_downgrade_removes_columns | `downgrade()` drops all 5 columns cleanly, no orphaned constraints | integration |
| test_0067_revision_chain | `down_revision == "0066"`, no duplicate revision id in the versions dir | unit |

**Downstream test impact**: none — additive nullable columns, no existing test reads `relation_type_registry.*` by exhaustive column count (verify via `git grep -n "relation_type_registry" services/*/tests/` if any exists — none found in Explore pass).

**Acceptance criteria**:
- [ ] Migration applies cleanly on top of `0066` HEAD
- [ ] All 5 columns nullable, NULL default, no data loss
- [ ] `alembic downgrade -1` and `alembic upgrade head` both succeed (round-trip)
- [ ] Authored only under `services/intelligence-migrations/` (R24); S7 `ALEMBIC_ENABLED` stays `false`

##### T-A-1-02: Registry-first/class-fallback COALESCE in `relation_type_registry.py`

**Type**: impl
**depends_on**: [T-A-1-01]
**blocks**: [T-A-1-04, T-A-3-*]
**Target files**: `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_type_registry.py`
**PRD reference**: §4 FR-2

**What to build**: Change the `decay_alpha` projection in both `find_exact` (lines 32-38) and `find_by_embedding` (lines 87-97) from `dcc.decay_alpha` to `COALESCE(rtr.decay_alpha, dcc.decay_alpha) AS decay_alpha`. `find_exact_simple` (lines 53-72) is untouched — it does not resolve `decay_alpha` today and no caller depends on it for confidence math (verify via task acceptance criteria, not a code change).

**Logic & Behavior**:
- `find_exact`: change `SELECT rtr.type_id, rtr.canonical_type, rtr.semantic_mode, rtr.decay_class, rtr.base_confidence, dcc.decay_alpha` → `..., COALESCE(rtr.decay_alpha, dcc.decay_alpha) AS decay_alpha`.
- `find_by_embedding`: identical column-level change at the equivalent projection.
- No change to the `JOIN decay_class_config dcc ON dcc.decay_class = rtr.decay_class` clause — the join is still required as the fallback source.
- Read-only method: this is a read path (registry lookup), no `UnitOfWork` involved — no R25/R27 concern (this repository is called from `graph_write.py`, which is a write use case, but the lookup itself does not mutate).

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| test_find_exact_returns_class_value_when_type_alpha_null | A type with `decay_alpha IS NULL` returns the class's `decay_alpha` (today's behavior, unchanged) | unit/integration |
| test_find_exact_returns_type_value_when_set | A type with a non-NULL `decay_alpha` returns that value, NOT the class value, even when they differ | integration |
| test_find_by_embedding_same_coalesce_behavior | Same two cases for the ANN lookup path | integration |

**Downstream test impact**: any existing test asserting the exact SQL text of `find_exact`/`find_by_embedding` (string-matching the query) will need updating — grep `services/knowledge-graph/tests/` for `"dcc.decay_alpha"` or a snapshot of the query string before editing.

**Acceptance criteria**:
- [ ] With all `relation_type_registry.decay_alpha` NULL (post-W1, pre-fit), every existing test in `services/knowledge-graph/tests/` passes unchanged (behavioral no-op)
- [ ] `find_exact_simple` confirmed unused for confidence resolution (grep its callers; none reach `confidence.py`)

##### T-A-1-03: Wire the resolved alpha into `graph_write.py`'s upsert call

**Type**: impl
**depends_on**: [T-A-1-02]
**blocks**: [T-A-1-04]
**Target files**: `services/knowledge-graph/src/knowledge_graph/application/blocks/graph_write.py`
**PRD reference**: §4 FR-2, §6.1

**What to build**: `graph_write.py:598` currently does `decay_alpha=decay_alpha if decay_alpha is not None else 0.000950,` — a hardcoded DURABLE fallback for when canonicalization yields no registry match at all (a different failure mode than "no per-type fit yet"). Confirm the `decay_alpha` local variable at this call site is populated from `RelationTypeRegistryRepository.find_exact`/`find_by_embedding` (T-A-1-02's COALESCE result) upstream in this same function — trace the assignment before this line. **No change to the `else 0.000950` fallback** (that guards total lookup miss, out of scope for FR-2, which is about per-type vs class, not about missing-registry-row miss).

**Logic & Behavior**: This task is primarily a verification + minimal wiring task: ensure the COALESCE'd value flows through unmodified from repository → `graph_write.py` → `relation_repo.upsert(...)`. If an intermediate transform strips or overrides it (e.g., a stale cache), fix that specific point — do not add new logic.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| test_graph_write_denormalizes_per_type_alpha_when_fitted | A `TEMPORAL_CLAIM` relation of a type with a fitted `decay_alpha` denormalizes onto `relations.decay_alpha` at upsert | integration |
| test_graph_write_denormalizes_class_alpha_when_not_fitted | Same type without a fit denormalizes the class value (today's behavior) | integration |

**Acceptance criteria**:
- [ ] `confidence.py` has zero diff (verified by `git diff --stat` showing no changes to that file)
- [ ] A relation of a `TEMPORAL_CLAIM` type **with** a fitted `decay_alpha` denormalizes the per-type value; a type **without** one denormalizes the class value

##### T-A-1-04: Scope-guard test — the 5 hardcoded call sites remain non-`TEMPORAL_CLAIM`

**Type**: test
**depends_on**: [T-A-1-02, T-A-1-03]
**blocks**: none
**Target files**: `services/knowledge-graph/tests/unit/infrastructure/test_decay_alpha_scope_guard.py` (NEW)
**PRD reference**: §9 (RELATION_STATE mistakenly fit), review §"FR-2 cleaner than stated"

**What to build**: A guard test asserting that the 5 hardcoded-alpha write sites (`relation.py:150` `upsert_relation()`, `entity_consumer.py:340`, `entity_enrichment_adapter.py:416`, `fundamentals_refresh.py:1070`, `fundamentals_refresh.py:1111`) only ever write `RELATION_STATE` semantic-mode relation types (sector/industry/DURABLE), never a `TEMPORAL_CLAIM` type from the fitter's target list (§4 FR-3's ~14 types). This documents the current scope boundary mechanically so a future PRD-0120 re-fit doesn't silently miss a type that moved to one of these hardcoded paths.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| test_hardcoded_alpha_sites_never_write_temporal_claim_types | Each of the 5 call sites' relation type is looked up in `relation_type_registry` and asserted `semantic_mode == 'RELATION_STATE'` | unit (static assertion against seed data / registry fixture) |

**Acceptance criteria**:
- [ ] Test fails loudly if any of the 5 sites is ever pointed at a `TEMPORAL_CLAIM` type in the future (regression tripwire, not a behavior change now)

#### Pre-read (agent must read before starting)
- `services/knowledge-graph/src/knowledge_graph/domain/confidence.py` (reference only — do not edit)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation_type_registry.py`
- `services/knowledge-graph/src/knowledge_graph/application/blocks/graph_write.py` (lines ~560-610)
- `services/intelligence-migrations/alembic/versions/0066_prediction_event_type_and_exposure_polarity.py` (as a migration-authoring template)
- `services/intelligence-migrations/alembic/versions/0001_create_intelligence_db.py` (lines 222-258, the table being altered)

#### Validation Gate
- [ ] ruff check passes on changed files
- [ ] mypy passes on changed packages
- [ ] Unit tests pass — minimum 8 new tests (3 migration + 3 lookup + 2 wiring/scope-guard)
- [ ] Integration tests pass (testcontainers Postgres, migration + lookup)
- [ ] Documentation updated: none required yet (W4 owns the doc pass) — but note the change in this plan's own status
- [ ] No architecture violations (domain has no infra imports; `confidence.py` untouched)

#### Architecture Compliance (MANDATORY)
- [ ] **R24** — migration authored only in `intelligence-migrations`; S7 `ALEMBIC_ENABLED=false` unchanged
- [ ] **R11** — all 5 columns nullable, NULL default, nothing removed/renamed
- [ ] **R27** — N/A (no new use case; this is a repository-query-level change inside an existing write path)
- [ ] **R32** — migration number `0067` verified against actual filesystem HEAD (`0066`), not assumed

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| any test string-matching the `find_exact`/`find_by_embedding` SQL text | query text changes from `dcc.decay_alpha` to `COALESCE(rtr.decay_alpha, dcc.decay_alpha)` | update the expected-SQL assertion (grep first; likely none exist since these are integration-tested by behavior, not SQL string) |

#### Regression Guardrails
- BP-XXX (R24 pattern): any DDL against `intelligence_db` outside `intelligence-migrations` is a hard violation — this wave's only DDL is the 0067 revision, confirmed owner-correct.
- "Confidence math untouched" guardrail (NFR-1): `git diff --stat` on `confidence.py` must show zero lines changed at the end of this wave and every subsequent wave.

---

## Wave 2: Offline Censored-Survival Fitter Core (SS-1 Fix Applied)

**Goal**: Build the offline, read-only fitter that estimates a per-`TEMPORAL_CLAIM`-type decay rate from two lifetime definitions, using the corrected (non-inter-arrival) estimator for corroboration. Shadow-only in this wave — no write-back yet (that's Wave 3).
**Depends on**: Wave 1 (registry columns must exist so the eventual write target is real, even though this wave doesn't write)
**Estimated effort**: 2-3 hours
**Architecture layer**: application (new analytics module) + domain (value objects)

### Locked design decision: SS-1 fix (supersedes PRD §4 FR-3(a) as literally written)

The PRD's definition (a) — "inter-arrival time of `evidence_date`, fit by exponential MLE" — estimates **mention rate**, not the decay parameter `α` in `exp(-α·age)` (review SS-1). A claim mentioned every 3 days forever and a claim mentioned every 3 days for one month then never both produce the same mean inter-arrival gap, yet they have wildly different relevance half-lives. This plan replaces it with:

**Corrected corroboration-decay estimator**: model each relation instance's mention timestamps as a realization of a **non-homogeneous Poisson process (NHPP)** with intensity `λ(t) = λ0 · exp(-α · t)`, where `t` = age in days since `first_evidence_at`. Fit `α` (and `λ0`) by maximum likelihood on the observed mention ages within an observation window `[0, T]` per relation instance (`T` = age at "now", i.e. right-censored at the observation cutoff — every relation instance contributes exposure up to `T` regardless of whether it was mentioned again). This directly estimates the quantity the confidence formula uses (`_temporal_weight`) instead of a proxy.

NHPP log-likelihood for one relation instance with mention ages `t_1 < t_2 < ... < t_k` observed in `[0, T]`:
```
ll(λ0, α) = Σ_i [ln(λ0) - α·t_i] - λ0 · (1 - exp(-α·T)) / α
```
(the integral of `λ0·exp(-α·t)` from 0 to T is `λ0·(1-exp(-α·T))/α`). Aggregate log-likelihood over all relation instances of a type; maximize numerically (no closed form) via a bounded scalar/2-param MLE (e.g. L-BFGS-B via `scipy.optimize.minimize`, bounds `α ≥ 0`, `λ0 > 0`). `α_hat` is the type's corroboration-decay estimate.

### Tasks

##### T-A-2-01: `Lifetime` and `DecayFit` domain value objects

**Type**: impl
**depends_on**: none
**blocks**: [T-A-2-02, T-A-2-03]
**Target files**: `services/knowledge-graph/src/knowledge_graph/domain/decay_fit.py` (NEW)
**PRD reference**: §6.5

**Entities / Components**:
- **`Lifetime`** — frozen dataclass: `duration_days: float`, `event_observed: bool` (False = right-censored). Used by the supersession estimator.
- **`MentionSeries`** — frozen dataclass: `canonical_type: str`, `relation_id: UUID`, `mention_ages_days: tuple[float, ...]` (ages of each `relation_evidence_raw.evidence_date` relative to the relation's `first_evidence_at`), `observation_window_days: float` (age at "now" — the NHPP censoring bound `T`). Used by the corrected corroboration estimator.
- **`DecayFit`** — frozen dataclass: `canonical_type`, `lifetime_definition: Literal["corroboration_nhpp", "supersession_mle"]`, `lambda_hat: float`, `half_life_days: float` (`ln(2)/lambda_hat`), `n: int` (event count — mention count for corroboration, terminal-event count for supersession), `exposure_time: float`, `censoring_rate: float`, `prior_alpha: float`, `shrinkage_weight: float | None` (populated in Wave 3), `alpha_final: float | None` (populated in Wave 3), `method: str`. Immutable; this is the report/write-back carrier.

**Invariants**: `lambda_hat > 0`; `half_life_days == math.log(2) / lambda_hat` (computed property, not stored redundantly — store only `lambda_hat`, derive `half_life_days` as a `@property`, to avoid drift between the two).

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| test_decay_fit_half_life_derived_from_lambda | `half_life_days` property matches `ln2/lambda_hat` for several values | unit |
| test_lifetime_frozen_immutable | dataclasses are frozen (raise on mutation attempt) | unit |

**Acceptance criteria**:
- [ ] No infra imports in this domain module (R25 domain-independence)

##### T-A-2-02: NHPP corroboration-decay estimator (SS-1 fix)

**Type**: impl
**depends_on**: [T-A-2-01]
**blocks**: [T-A-2-04, T-A-2-05]
**Target files**: `services/knowledge-graph/src/knowledge_graph/application/analytics/decay_fitting/nhpp_estimator.py` (NEW)
**PRD reference**: §4 FR-3(a) as corrected by review SS-1 (see locked design decision above)

**What to build**: `fit_nhpp(series: list[MentionSeries]) -> tuple[float, float]` returning `(lambda0_hat, alpha_hat)` — the MLE fit of `λ(t) = λ0·exp(-α·t)` pooled across all relation instances of one type. Uses `scipy.optimize.minimize` (L-BFGS-B, bounds `alpha >= 1e-6`, `lambda0 >= 1e-6`) on the negative aggregate log-likelihood (formula above, summed over all series). Numerically stable initial guess: `alpha0 = ln(2)/median(observation_window_days)`, `lambda0_0 = mean(mention count / observation_window_days)`.

**Logic & Behavior**:
- Per-entity normalization (FR-5) is applied **before** this fit, not inside it: the caller divides each relation instance's raw mention count by the subject entity's baseline mention rate over the same window (a separate small helper, `normalize_by_entity_baseline`, in the same module) before constructing `MentionSeries`. This estimator itself is normalization-agnostic — it just fits whatever intensity series it's given.
- Right-censoring is inherent to the NHPP formulation: every relation instance's `T` (observation window) already accounts for "still alive, no more mentions since" — there is no separate censoring flag needed for this definition (unlike the supersession definition, which needs explicit `Lifetime.event_observed`).
- Degenerate case: a relation instance with zero mentions in `[0,T]` beyond the founding one contributes only its exposure term (no event terms) — must not raise on empty mention lists, must still contribute to the aggregate exposure integral.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| test_nhpp_recovers_known_alpha_lambda0 | On synthetic data simulated from a known `(λ0, α)` NHPP, the MLE recovers both parameters within tolerance (e.g. ±15% at n=200 relation instances) | unit (HIGH priority, per PRD §11) |
| test_nhpp_rejects_inter_arrival_proxy | A dataset constructed so inter-arrival-MLE and NHPP-MLE diverge (bursty-then-silent mention pattern) — asserts the NHPP fit recovers the true decaying-relevance α while a naive inter-arrival exponential MLE (computed inline in the test for comparison, not shipped) does not | unit (HIGH — this is the test that proves the SS-1 fix matters) |
| test_nhpp_handles_zero_mention_relations | A relation instance with only its founding evidence (no re-mentions) contributes exposure without raising | unit |
| test_nhpp_entity_normalization_changes_estimate | A synthetic high-coverage-entity case: un-normalized fit is biased toward "fast decay"; normalized fit recovers the true (slower) α | unit (FR-5 acceptance criterion) |

**Acceptance criteria**:
- [ ] Estimator recovers known synthetic `(λ0, α)` within tolerance — this is the load-bearing correctness test for the entire fitter
- [ ] Never uses raw inter-arrival-gap MLE anywhere in the codebase (grep guard: no `numpy.diff(mention_dates)`-then-`exponential.fit` pattern)

##### T-A-2-03: Supersession/contradiction censored estimator

**Type**: impl
**depends_on**: [T-A-2-01]
**blocks**: [T-A-2-04, T-A-2-05]
**Target files**: `services/knowledge-graph/src/knowledge_graph/application/analytics/decay_fitting/supersession_estimator.py` (NEW)
**PRD reference**: §4 FR-3(b), review SS-3 (competing risks)

**What to build**: `fit_supersession(lifetimes: list[Lifetime]) -> float` — a standard right-censored exponential MLE: `λ_hat = (number of event_observed=True) / (sum of all duration_days, censored + uncensored)`. This is the textbook censored-exponential MLE (no need for the NHPP correction here — supersession genuinely is "time to first terminal event," not a repeated-mention-rate problem).

**Logic & Behavior**:
- **Cause-specific hazard (review SS-3)**: build `Lifetime` objects reading directly off `relations` (not `relations_history`, which lacks `decay_alpha` — see codebase-state table): `duration_days = (terminal_ts - first_evidence_at).days`, where `terminal_ts` is **whichever of `latest_contra_at` or `valid_to` occurs first** (the earliest terminal event — competing-risks censor-the-other convention), and `event_observed = True` iff at least one of them is non-NULL; else `duration_days = (now - first_evidence_at).days`, `event_observed = False`.
- Per PRD P-7 / FR-5: this definition is the "truth signal" and is preferred over corroboration **only when a type has enough supersession events** — that comparison/selection happens in Wave 3 (pooling), not here. This task only produces the raw `λ_hat` for whichever types have data.
- Confirm no dependency on `relations_history` (codebase-state table: that table has no `decay_alpha`, and is not needed — `relations.first_evidence_at`/`latest_contra_at`/`valid_to` already carry everything required).

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| test_censored_mle_recovers_known_lambda | Synthetic lifetimes with known λ and known censoring fraction — MLE recovers λ within tolerance | unit (HIGH, PRD §11) |
| test_naive_mean_lifetime_underestimates_halflife | On the same synthetic data, a naive mean-of-observed-lifetimes is demonstrably biased low vs. the MLE (documents *why* censoring-aware estimation is mandatory, P-4) | unit (HIGH, PRD §11) |
| test_competing_risks_earliest_terminal_wins | A relation with both `latest_contra_at` and `valid_to` set uses the earlier one as the terminal event | unit (SS-3 guard) |
| test_all_censored_type_returns_high_uncertainty | A type where every lifetime is censored still returns a (very small, high-variance) λ_hat without raising — flagged sparse downstream | unit |

**Acceptance criteria**:
- [ ] Estimator is censoring-aware; a naive-mean equivalent is explicitly shown wrong in the test suite (P-4)
- [ ] No read of `relations_history` for `decay_alpha`/lambda purposes (grep guard)

##### T-A-2-04: Read-only data extraction (replica-served)

**Type**: impl
**depends_on**: [T-A-2-01]
**blocks**: [T-A-2-05]
**Target files**: `services/knowledge-graph/src/knowledge_graph/application/analytics/decay_fitting/lifetime_extraction.py` (NEW)
**PRD reference**: §4 FR-3, §6.6, NFR-2

**Port interfaces**: this module depends on `ReadOnlyUnitOfWork` (R27) — it is 100% read traffic against `relation_evidence_raw` (pre-gating, P-5) and `relations` (for the supersession terminal timestamps). No write UoW anywhere in this task.

**What to build**: Two extraction functions:
- `extract_mention_series(type: str, uow: ReadOnlyUnitOfWork) -> list[MentionSeries]` — groups `relation_evidence_raw` rows by relation instance (subject/object/canonical_type), computes each mention's age relative to the group's earliest `evidence_date`, and sets `observation_window_days = (now - earliest evidence_date).days`.
- `extract_supersession_lifetimes(type: str, uow: ReadOnlyUnitOfWork) -> list[Lifetime]` — reads `relations` rows of the given `canonical_type`, applies the competing-risks rule from T-A-2-03.

**Logic & Behavior**: Both functions filter to `TEMPORAL_CLAIM` types only (scope guard, P-3) — assert `semantic_mode == 'TEMPORAL_CLAIM'` from the registry before extracting; raise/skip (log + report, do not crash the whole job) for a `RELATION_STATE` type passed in error.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| test_extract_mention_series_pre_gating_source | Extraction reads `relation_evidence_raw`, not `relation_evidence` (circularity guard, P-5) | integration (testcontainers Postgres) |
| test_extract_supersession_reads_relations_not_history | Extraction never queries `relations_history` | integration |
| test_relation_state_type_rejected | Passing a `RELATION_STATE` type is skipped/reported, not silently fit | unit |
| test_extraction_uses_readonly_uow | The function signature/dependency is `ReadOnlyUnitOfWork`, never `UnitOfWork` | unit (R27 static check) |

**Acceptance criteria**:
- [ ] 100% read-only; holds no long-lived write locks (NFR-2)
- [ ] Fits only on `relation_evidence_raw` (pre-gating) for corroboration, and `relations` for supersession — never confidence-gated `relations.confidence`-derived data as an *input* to the fit (P-5 circularity guard)

##### T-A-2-05: Fitter CLI/module entrypoint (shadow-only in this wave)

**Type**: impl
**depends_on**: [T-A-2-02, T-A-2-03, T-A-2-04]
**blocks**: [T-A-3-01]
**Target files**: `services/knowledge-graph/src/knowledge_graph/application/analytics/decay_fitting/run_fitter.py` (NEW)
**PRD reference**: §4 FR-3, §10 (rollout step 3)

**What to build**: An offline entrypoint (invoked as `python -m knowledge_graph.application.analytics.decay_fitting.run_fitter --shadow`) that, per target `TEMPORAL_CLAIM` type (the ~14 from PRD §4 FR-3), runs both estimators (T-A-2-02, T-A-2-03) via the extraction layer (T-A-2-04) and emits a structured per-type report (`DecayFit` objects, one per `(type, lifetime_definition)` pair) via structlog (R10) — **writes nothing to the database in this wave** (write-back is Wave 3's T-A-3-03).

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| test_shadow_run_writes_nothing | Running the entrypoint against a seeded test DB produces a report and zero `UPDATE`/`INSERT` statements (assert via a write-tracking test double on the session) | integration |
| test_shadow_run_covers_all_target_types | All ~14 target types produce a report entry (fitted or explicitly marked sparse — no silent drops) | integration |

**Acceptance criteria**:
- [ ] Shadow run emits a full per-type report and performs zero writes (FR-6 shadow-mode acceptance criterion, verified one wave early)
- [ ] Structured logging only (R10), no evidence text/PII logged (§8 security)

#### Pre-read (agent must read before starting)
- PRD §4 FR-3, FR-5, §6.5, §6.6, §11 (test strategy) — the full statistical spec
- Review §"CRITICAL — fix before implementing the fitter" (SS-1, SS-3, SS-4) — the corrected design this wave implements
- `services/knowledge-graph/src/knowledge_graph/domain/confidence.py` (to understand what `decay_alpha` is used for downstream — reference only)
- Any existing `ReadOnlyUnitOfWork` usage in S7 (e.g. an existing read-only worker) as the pattern to follow for T-A-2-04

#### Validation Gate
- [ ] ruff + mypy clean
- [ ] Unit tests pass — minimum 14 new tests (per the tables above)
- [ ] Integration tests pass against testcontainers Postgres seeded with synthetic `relation_evidence_raw`/`relations` rows
- [ ] `confidence.py` still zero diff

#### Architecture Compliance
- [ ] **R25** — no infra imports in `domain/decay_fit.py`
- [ ] **R27** — all extraction is `ReadOnlyUnitOfWork`-based
- [ ] **R10** — structlog only in the fitter entrypoint
- [ ] **R11/R7** — no new timestamp fields yet (Wave 3 adds `alpha_fit_at`, UTC there)

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| none | new module, no existing code imports it yet | — |

#### Regression Guardrails
- P-4 (naive mean is a bug): `test_naive_mean_lifetime_underestimates_halflife` is the mechanical guard against ever "simplifying" the estimator back to a mean.
- P-5 (circularity): `test_extract_mention_series_pre_gating_source` guards against silently switching to gated `relation_evidence`.
- SS-1 (this plan's core correction): `test_nhpp_rejects_inter_arrival_proxy` guards against a future refactor accidentally reintroducing the inter-arrival proxy the PRD originally specified.

---

## Wave 3: Partial Pooling + Min-n Gate + Provenance Write-Back + Backfill

**Goal**: Combine the two lifetime-definition estimates into one final per-type `alpha`, shrink toward the class prior for sparse types, and write back with full provenance — gated, reversible, and (per the review's elevated OQ-7) including an explicit backfill so existing `relations` rows actually pick up a newly-fitted alpha instead of waiting indefinitely for their next upsert.
**Depends on**: Wave 2 (needs `DecayFit` objects to pool/write)
**Estimated effort**: 1.5-2 hours
**Architecture layer**: application (pooling + write-back use case)

### Tasks

##### T-A-3-01: Partial pooling / empirical-Bayes shrinkage + signal preference

**Type**: impl
**depends_on**: [T-A-2-05]
**blocks**: [T-A-3-02]
**Target files**: `services/knowledge-graph/src/knowledge_graph/application/analytics/decay_fitting/pooling.py` (NEW)
**PRD reference**: §4 FR-4, FR-5, P-7

**What to build**: `pool_type_fit(corroboration: DecayFit | None, supersession: DecayFit | None, prior_alpha: float, min_n: int, pooling_k: int) -> DecayFit` — produces the final per-type `DecayFit` with `alpha_final` and `shrinkage_weight` populated.

**Logic & Behavior**:
1. **Signal selection (P-7/FR-5)**: if `supersession` exists and its `n >= min_n`, it is the primary estimate (`alpha_type_raw = supersession.lambda_hat`, `method = "mle_supersession"`); else fall back to `corroboration` (`method = "km_corroboration"` — actually `"nhpp_corroboration"` given the SS-1 fix, keep the method tag accurate to what was actually run); if neither has any data, `alpha_type_raw = prior_alpha`, `method = "pooled_prior"`, `n = 0`.
2. **Shrinkage**: `w = n / (n + pooling_k)` (config `pooling_k`, default per OQ-2 assumption `min_n = 30`, `pooling_k` similarly configurable); `alpha_final = w * alpha_type_raw + (1 - w) * prior_alpha`.
3. **Min-n gate**: if `n < min_n`, force `method = "pooled_prior"` regardless of the shrinkage math trending away from the prior (belt-and-suspenders — shrinkage alone should already pull small-n close to the prior, but the method *label* must say `pooled_prior` so provenance is honest per FR-4's acceptance criterion).

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| test_partial_pooling_monotonic_in_n | `w` increases monotonically as `n` increases (fixed `pooling_k`) | unit (HIGH, PRD §11) |
| test_min_n_gate_keeps_prior | `n < min_n` ⇒ `method == "pooled_prior"`, `alpha_final` within shrinkage tolerance of `prior_alpha` | unit (HIGH) |
| test_prefer_supersession_when_sufficient | With `supersession.n >= min_n`, `method` reflects supersession even if corroboration also has data | unit |
| test_fallback_to_corroboration_when_no_supersession | With zero supersession events, corroboration NHPP fit is used and reported as attention-signal-only | unit |

**Acceptance criteria**:
- [ ] Shrinkage weight monotonic in `n` (unit-tested)
- [ ] `alpha_fit_method` always one of the 3 documented tags, never ad-hoc strings

##### T-A-3-02: Write-back use case (shadow → write, gated, idempotent)

**Type**: impl
**depends_on**: [T-A-3-01]
**blocks**: [T-A-3-03]
**Target files**: `services/knowledge-graph/src/knowledge_graph/application/analytics/decay_fitting/write_back.py` (NEW)

**Port interfaces**: depends on `UnitOfWork` (R25/R27 — this is a write, not a read; uses `UnitOfWork`, not `ReadOnlyUnitOfWork`) scoped to `relation_type_registry` only.

**PRD reference**: §4 FR-6

**What to build**: `write_back_fit(fit: DecayFit, uow: UnitOfWork, mode: Literal["shadow", "write"]) -> None`. In `"shadow"` mode, logs the fit and returns without touching the DB. In `"write"` mode, and only when `fit.method != "pooled_prior"` OR an explicit `--force-prior-writeback` flag is set (writing an explicit prior is optional, mostly for observability consistency — default behavior per FR-6 is to leave `pooled_prior` types' columns NULL, which is behaviorally identical to writing the prior and simpler/safer), sets all 5 columns: `decay_alpha = fit.alpha_final`, `half_life_days = fit.half_life_days`, `alpha_fit_n = fit.n`, `alpha_fit_method = fit.method`, `alpha_fit_at = common.time.utc_now()` (R7).

**Logic & Behavior**: Idempotent — re-running write-back with the same `DecayFit` input produces byte-identical column values (deterministic given the same upstream data snapshot). Revert path: setting `decay_alpha = NULL` (a separate, simple admin operation, not part of this use case) instantly reverts that type to class-fallback via the Wave-1 COALESCE.

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| test_shadow_mode_writes_nothing | Shadow mode: zero DB writes | integration |
| test_write_mode_sets_all_five_columns_utc | Write mode sets all 5 columns; `alpha_fit_at` is tz-aware UTC | integration (R7 guard) |
| test_writeback_idempotent | Running write-back twice with the same fit produces identical column values | integration |
| test_pooled_prior_type_leaves_columns_null | A `pooled_prior`-method fit does not write non-NULL `decay_alpha` by default (leaves class-fallback intact) | integration |

**Acceptance criteria**:
- [ ] Write mode sets all five columns with correct provenance and UTC timestamp; idempotent
- [ ] DDL/writes go through `intelligence-migrations`-owned schema only via this governed use case — no ad-hoc SQL elsewhere

##### T-A-3-03: Explicit backfill UPDATE for existing `relations` rows (closes elevated OQ-7)

**Type**: impl
**depends_on**: [T-A-3-02]
**blocks**: [T-A-4-01]
**Target files**: `services/knowledge-graph/src/knowledge_graph/application/analytics/decay_fitting/backfill.py` (NEW)
**PRD reference**: §14 OQ-7 as elevated by the review ("Backfill gap... 'lazy/natural refresh picks up new alphas' is false")

**What to build**: The review found that `relations.decay_alpha` denormalizes **only on upsert** (`relation.py:79`, `ON CONFLICT ... EXCLUDED.decay_alpha`) — a relation with no new evidence since its last upsert never re-resolves, so the PRD's assumption of a "lazy confidence-stale refresh" is incorrect. This task adds an explicit, governed backfill: `backfill_relations_for_type(canonical_type: str, uow: UnitOfWork) -> int` — runs `UPDATE relations SET decay_alpha = :new_alpha, confidence_stale = true WHERE canonical_type = :type` for a type that just received a write-back, returning the row count touched. Setting `confidence_stale = true` (an existing column) causes the relation's `confidence` to be recomputed with the new alpha on its next natural refresh cycle, without needing new evidence.

**Logic & Behavior**: Runs immediately after a successful write-back for a given type (T-A-3-02), same transaction or an immediately-following one — not a separate scheduled job (keeps behavior simple: fit → write registry → backfill relations → done). Batched (`LIMIT`/`OFFSET` or a single `UPDATE ... WHERE` if row count is manageable — check expected row count per type via `COUNT(*)` first and log it; if very large, chunk to avoid a long-held write lock, per NFR-2's "no long write locks" spirit even though this is the one legitimately-write step in the whole feature).

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| test_backfill_updates_existing_relations_of_type | Relations of the fitted type that received no new evidence still get `decay_alpha` updated | integration |
| test_backfill_sets_confidence_stale | `confidence_stale` flips to true so the existing refresh mechanism recomputes confidence | integration |
| test_backfill_scoped_to_single_type | Relations of other types are untouched | integration |

**Acceptance criteria**:
- [ ] After write-back + backfill, a relation with no new evidence carries the new per-type alpha (verifying the review's gap is actually closed, not just documented)
- [ ] Backfill is scoped per-type, triggered by write-back, not a blind full-table scan

#### Pre-read (agent must read before starting)
- Review §"FR-2 cleaner than stated, but wider" (the backfill-gap finding this wave closes)
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/relation.py` (upsert + `confidence_stale` column usage)
- PRD §4 FR-4, FR-6, §10 rollout steps 3-5

#### Validation Gate
- [ ] ruff + mypy clean
- [ ] Unit + integration tests pass — minimum 11 new tests
- [ ] `confidence.py` still zero diff

#### Architecture Compliance
- [ ] **R25** — write-back/backfill use cases depend on `UnitOfWork`, are the only write paths in this feature; no infra imported into any use case's own module boundary incorrectly
- [ ] **R7** — `alpha_fit_at` is UTC via `common.time.utc_now()`
- [ ] **R24** — no new DDL in this wave (columns already exist from Wave 1); only DML

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| none | new write path, additive | — |

#### Regression Guardrails
- Elevated OQ-7 (review): `test_backfill_updates_existing_relations_of_type` is the direct regression guard against the PRD's incorrect "lazy refresh" assumption resurfacing.
- Min-n gate (FR-4): `test_min_n_gate_keeps_prior` (Wave 2/3 boundary) — a bad tiny-n fit must never overwrite a good prior.

---

## Wave 4: Held-Out Evaluation + Metrics + Documentation

**Goal**: Produce the thesis-grade evidence that fitted half-lives beat class priors where data allows, wire observability, and fix documentation (including the pre-existing stale `.claude-context.md` drift found during code-grounding).
**Depends on**: Wave 3 (needs written-back fits to evaluate against held-out data)
**Estimated effort**: 1.5 hours
**Architecture layer**: application (eval) + docs

### Tasks

##### T-A-4-01: Held-out evaluation report

**Type**: impl
**depends_on**: [T-A-3-03]
**blocks**: [T-A-4-03]
**Target files**: `services/knowledge-graph/src/knowledge_graph/application/analytics/decay_fitting/evaluation.py` (NEW)
**PRD reference**: §4 FR-7

**What to build**: `evaluate_fit_vs_prior(type: str, held_out_relations: ..., fitted_alpha: float, prior_alpha: float) -> EvalRow` — computes held-out log-likelihood (or KM-vs-model divergence) of the fitted vs. prior alpha against a held-out slice of relations for that type, per PRD FR-7. Sparse types (`n < min_n`) are reported as `"insufficient data"` — never as a claimed win (honesty requirement, explicit test).

**Tests to write**:
| Test Name | What It Verifies | Type |
|---|---|---|
| test_holdout_fitted_beats_prior_where_n_allows | On synthetic held-out data generated from a known true alpha, the fitted estimate (closer to true alpha) scores a better held-out likelihood than an intentionally-wrong prior | unit |
| test_sparse_types_never_reported_as_wins | A type with `n < min_n` is reported `"insufficient data"`, not a win/loss verdict | unit |

**Acceptance criteria**:
- [ ] Per-type eval table produced (n, censoring rate, prior/fitted/shrunk half-life, held-out metric, verdict) — the thesis-chapter deliverable

##### T-A-4-02: Observability metrics

**Type**: impl
**depends_on**: [T-A-3-02]
**blocks**: none
**Target files**: fitter entrypoint (`run_fitter.py`) + wherever S7 Prometheus metrics are registered
**PRD reference**: §13

**What to build**: Emit the 7 metrics from PRD §13: `decay_fit_alpha{canonical_type}`, `decay_fit_half_life_days{canonical_type}`, `decay_fit_sample_n{canonical_type}`, `decay_fit_censoring_rate{canonical_type}`, `decay_fit_shrinkage_weight{canonical_type}`, `decay_types_using_fitted_total`/`decay_types_using_prior_total`, `decay_fit_signal{canonical_type,signal}`.

**Acceptance criteria**:
- [ ] All 7 metrics present after a shadow or write run; no alerting required (offline/non-critical per PRD)

##### T-A-4-03: Documentation updates (mandatory, includes pre-existing drift fix)

**Type**: docs
**depends_on**: [T-A-4-01, T-A-4-02]
**blocks**: none
**Target files**:
- `docs/services/knowledge-graph.md`
- `services/knowledge-graph/.claude-context.md`
- `services/intelligence-migrations/.claude-context.md`
- `docs/BUG_PATTERNS.md`
- `docs/plans/TRACKING.md`

**What to build**:
- Document per-type `decay_alpha` (registry-first, class-fallback), the fitter, the two lifetime definitions (including the SS-1-corrected NHPP corroboration estimator — do **not** document the PRD's original inter-arrival proxy, since it was never built), pooling/min-n, shadow→write rollout.
- **Fix the pre-existing doc/code drift found during code-grounding**: `services/knowledge-graph/.claude-context.md:23-26` currently describes the stale v1 `compute_confidence` 4-step formula and falsely states "TEMPORAL_CLAIM always uses 0.02310" — this contradicts the actual current code (`eff_alpha = decay_alpha` unconditionally at `confidence.py:148`/`:359`/`:373`). Correct this block to describe `compute_confidence_beta` (the current default) and the registry-first/class-fallback alpha resolution. This is an independent pre-existing bug, not introduced by this plan, but it is directly adjacent to what this plan touches and should not be left stale.
- `docs/BUG_PATTERNS.md`: add "naive mean lifetime underestimates half-life under right-censoring" and "inter-arrival-gap MLE estimates mention rate, not decay rate, under a repeated-mention process — use an NHPP fit" (this plan's SS-1 lesson, worth compounding for future estimator work).
- `docs/plans/TRACKING.md`: mark PLAN-0123 waves 1-4 complete with a one-line summary per wave (following the existing table's style).

**Acceptance criteria**:
- [ ] `.claude-context.md` no longer contradicts the actual `confidence.py` code
- [ ] TRACKING.md updated with final wave completion status

#### Pre-read (agent must read before starting)
- PRD §7, §12, §13
- `services/knowledge-graph/.claude-context.md` (the stale block to fix)

#### Validation Gate
- [ ] ruff + mypy clean
- [ ] Unit tests pass — minimum 4 new tests
- [ ] Docs updated per the mandatory list above
- [ ] `confidence.py` still zero diff (final check across the whole plan)

#### Architecture Compliance
- [ ] **R15** — every schema/behavior change in this plan has a corresponding doc update (this wave is that closing step)

#### Break Impact
| Broken File | Why It Breaks | Fix Required |
|---|---|---|
| none | docs + eval only | — |

#### Regression Guardrails
- BP (new, to add in this wave): doc/code drift on `confidence.py`'s active formula — a future confidence-math change must update `.claude-context.md` in the same PR (this plan is itself the example of that drift going unnoticed for at least one full PRD cycle).

---

## Cross-Cutting Concerns

- **Contract changes**: none (no Avro/Kafka changes — PRD §6.3 confirms).
- **Migration needs**: single migration `0067` (Wave 1), owned by `intelligence-migrations` (R24). No other service needs a migration.
- **Event flow changes**: none.
- **Configuration**: new env-driven tunables (`min_n`, `pooling_k`, target-type list) — no secrets, plain config per R8.
- **Documentation**: Wave 4 is the dedicated doc wave; also fixes one pre-existing unrelated doc/code drift discovered during Phase 1.3 grounding.

## Risk Assessment

- **Critical path**: W1 → W2 → W3 → W4, strictly sequential (single service, single migration owner).
- **Highest risk**: Wave 2 (T-A-2-02, the NHPP estimator) — this is the one piece of genuinely novel statistical code and the plan's central correctness claim (SS-1 fix). `test_nhpp_recovers_known_alpha_lambda0` and `test_nhpp_rejects_inter_arrival_proxy` are the load-bearing tests; do not relax their tolerances to make them pass.
- **Rollback strategy**: every wave is independently reversible — W1's columns are inert while NULL; W2 writes nothing; W3's write-back reverts by nulling `decay_alpha` per type; W4 is docs/eval only. A failed wave can be reverted with a straight `git revert` with no data-loss risk (no destructive migrations anywhere in this plan).
- **Testing gaps**: real-world sample sizes for several of the ~14 `TEMPORAL_CLAIM` types are unknown until Wave 2's shadow run against real local data — expect several types to land on `pooled_prior` (PRD's own honest expectation, echoed in the review's opening line: "only ~3-5 of 14 types will clear the sample gate").

---

## Workflow Chain — Next Steps
`/implement PLAN-0123 Wave 1` → Wave 2 → Wave 3 → Wave 4, in strict sequence. After Wave 4, rebuild + deploy the `knowledge-graph` and `intelligence-migrations` containers to local docker-compose and run `/qa`.

## Compounding check
No updates to `BUG_PATTERNS.md`/`STANDARDS.md`/skills/agents/RULES.md are needed **at planning time** — Wave 4 (T-A-4-03) is where the two new `BUG_PATTERNS.md` entries (naive-mean-under-censoring, inter-arrival-proxy-vs-NHPP) and the `.claude-context.md` drift fix are scheduled to land, as part of implementation rather than planning.
