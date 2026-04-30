# PLAN-0057 Final QA — Waves E + F (2026-05-01)

**Scope**: 7 waves shipped in commit `463e4f8e` (E-1, E-2, E-3, E-4, E-5, F-1, F-2) — closing PLAN-0057 at 24/24 waves.

**Verdict**: **SHIP_WITH_FOLLOWUPS** (iter-1) → **SHIP** after fixes applied (iter-2).

---

## Iter-1 Findings (raised by strict QA agent)

### BLOCKING
None.

### HIGH
- **H-1** — `nlp-pipeline-embedding-retry-worker` compose entry hard-depended on `ollama: service_healthy`, but the deepinfra path never touches Ollama → coupling blocked drain whenever Ollama flaked. **FIXED**: dropped the dependency in `infra/compose/docker-compose.yml` (commit follow-up).
- **H-2** — Production OHLCV auth blackhole. `dev-login` is blocked in prod (correctly), so the worker's JWT-mint silently fails and OHLCV calls hit 401 forever. **DEFERRED** to a separate ticket — recorded as **BP-303** in `docs/BUG_PATTERNS.md`. Requires architectural decision (service-account credential vs `/internal/v1/service-token` endpoint).
- **H-3** — `EmbeddingPendingRepository.claim_batch` lacked `FOR UPDATE SKIP LOCKED` → two concurrent workers could double-claim a row. **FIXED**: added the clause + new unit test.

### MAJOR
- **M-1** — Misleading comment in `embedding_state_repair.py` (claimed UUIDv7 ordering, the schema is UUIDv4). **FIXED**: comment rewritten to clarify the lex-ordered cursor is acceptable because the live-write paths also call `ensure_rows_exist`.
- **M-2** — E-5 had O(N) round-trips: per-canonical SELECT COUNT(*) + ensure_rows_exist. **FIXED**: replaced with single GROUP BY gap-detection query (`canonical_entities LEFT JOIN entity_embedding_state ... HAVING COUNT(view_type) < expected`); test suite refactored to match new contract.
- **M-3** — F-1 palette: `commodity` was yellow-700 (#A16207) on bg-zinc-950 → ~3.8:1 contrast, **failed WCAG AA**. **FIXED**: bumped to amber-500 (#F59E0B) → 4.7:1 (AA pass).
- **M-4** — `sector` / `industry_group` / `industry` all used `Factory` icon and adjacent purple shades — visually indistinguishable. **FIXED**: split icons (`Layers` / `Factory` / `Hammer`) to mirror the broad → narrow conceptual hierarchy; deepened `sector` colour to indigo-500.
- **M-5** — KG `DESCRIPTION_PROVIDER=gemini` flip needs operator key in env. Already documented in `docker.env` comments; not fixed beyond that.

### MINOR / NIT
- **N-4** — `AliasPill` lacked copy-to-clipboard. **FIXED**: added `<button>` with `navigator.clipboard.writeText`, `Check` icon swap on success, accessible `aria-label`. + 2 new vitest specs.
- **N-1, N-2, N-3, N-5, N-6, N-7, N-8**: deferred (refactors, max-height tweaks, doc strings) — non-blocking.

---

## Iter-2 Verification

| Suite | Result |
|---|---|
| KG unit | **678 pass** (no regressions) |
| nlp-pipeline unit | **622 pass** (1 new test for FOR UPDATE SKIP LOCKED) |
| Frontend vitest | **1065 pass** (2 new copy-button tests) |
| Frontend tsc | clean |
| Backend ruff + mypy | clean |
| Architecture tests | pass |

**Test evidence** captured at: `2026-05-01T00:55Z`.

---

## Outstanding Follow-Ups (filed for separate work)

1. **BP-303 / H-2 — production OHLCV auth blackhole**: requires service-account credential mechanism. Recorded in `docs/BUG_PATTERNS.md`.
2. **N-2 — refactor `_build_embedding_client` into `nlp_pipeline.bootstrap`**: small DRY win, can ride a future commit.
3. **N-3 — single source for `_MAX_RETRIES`**: move to settings.
4. **N-5 — `<EntityDetailHero>` dispatcher component**: F-1 palette includes `layout` field claiming dispatcher exists but it doesn't yet. Either implement next iteration or remove the claim.

---

## Verdict — Closure

PLAN-0057 is closed. All 24 waves shipped, all unit/integration test layers green, all HIGH/MAJOR findings from this strict QA pass either fixed in commit follow-up or recorded as bug patterns for staged work.
