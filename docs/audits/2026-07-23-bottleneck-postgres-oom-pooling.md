# Bottleneck Deep-Dive — "Postgres OOM / connection pooling / index planning" cluster

- **Date:** 2026-07-23
- **Scope:** Read-only investigation of current source (`services/knowledge-graph`, `services/nlp-pipeline`,
  `services/market-data`, `infra/gliner`) + review-framework artifacts
  (`docs/BUG_PATTERNS.md`, `.claude/review/heuristics/HIGH_RISK_PATTERNS.md`,
  `.claude/review/checklists/REVIEW_CHECKLIST.md`) against the mined root-cause summary and evidence
  patterns supplied. This file is the only artifact written by this investigation.
- **Headline correction to the mined summary:** the summary's premise — that BP-717's prevention text
  was "never lifted into HIGH_RISK_PATTERNS.md/REVIEW_CHECKLIST.md" and that the GLiNER OOM and DB-session
  duplication gaps are "undocumented" — is **stale**. All three are already documented in the current
  working tree (BP-730 through BP-733, HR entry + checklist line at `HIGH_RISK_PATTERNS.md:1013-1049` /
  `REVIEW_CHECKLIST.md:114`). **However, those additions are uncommitted local changes** (`git status`
  shows `M` on all three files, zero commits touching them since `9f3cab378`) — so as of `HEAD`
  (`19d5fbf3c`), a fresh clone would NOT have any of this compounding. See Finding 0.

---

## Finding 0 (new, highest priority) — the compounding fixes exist but are not committed

`git diff --stat HEAD -- docs/BUG_PATTERNS.md .claude/review/heuristics/HIGH_RISK_PATTERNS.md .claude/review/checklists/REVIEW_CHECKLIST.md`
shows 354 uncommitted insertion lines: BP-731 through BP-739 in `BUG_PATTERNS.md`, a full HR entry
(partial-index/literal-predicate) in `HIGH_RISK_PATTERNS.md`, and the matching checklist line in
`REVIEW_CHECKLIST.md:114`. These are exactly the artifacts the mined summary says are missing — they
were evidently drafted (likely by a prior `/docs-audit` pass in this same session tree) but never
`git add`+`git commit`+pushed. Until committed, they exist only in this one working tree: a sibling
agent, a fresh worktree (`git worktree add`), or CI checking out `HEAD` would see none of this
knowledge. **Recommendation: commit these three files as their own change (they are pure documentation,
no code) before anything else in this cluster is considered "closed."** This is not something this
investigation should do unprompted (task scope is audit-only, single new file), but it is the single
highest-leverage, lowest-risk action available.

---

## Recurrence 1 — Partial-index predicate bound as a parameter (BP-717 → BP-730)

**Current code state (verified by reading source, not docs):**
- `services/knowledge-graph/src/knowledge_graph/infrastructure/intelligence_db/repositories/entity_embedding_ann.py`
  — `find_nearest()` validates `view_type` against `_VALID_VIEW_TYPES = frozenset({"definition", "narrative", "fundamentals_ohlcv"})`
  and inlines it as a SQL literal (`WHERE ees.view_type = '{view_type}'`), with `exclude_entity_id` /
  `entity_types` staying parameterized. **Fix is real, present, and correctly scoped** (not a blanket
  f-string change — only the allow-listed enum column is inlined).
- `services/nlp-pipeline/src/nlp_pipeline/infrastructure/intelligence_db/repositories/entity_profile_embedding.py`
  — same pattern, same allow-list, mirrored fix. Confirmed present.
- Regression tests exist for both: `test_entity_embedding_ann_partial_index.py` (knowledge-graph),
  `test_entity_profile_embedding_partial_index.py` (nlp-pipeline), plus the original
  `test_chunk_search_accel_partial_index.py` (BP-717, nlp-pipeline).

**Classification: BOTH (TEST_GAP dominant across all three fixes; the first occurrence was also an
IMPLEMENTATION_GAP that got closed and then re-opened elsewhere).**

- **IMPLEMENTATION_GAP (closed after 2 recurrences, but by documentation only, not by a code invariant):**
  the true structural fix is not "inline this one literal" repeated three times — it is that nothing in
  the codebase *enforces* the invariant "a query against a partial-indexed column must bind that column
  as a literal, not a parameter." There is no static check, no repository base-class helper, no CI gate.
  Every one of BP-717/BP-730's two follow-on sites had to be independently discovered by a human/agent
  reading `EXPLAIN` output during a live OOM incident. A genuine implementation-level fix — not just a
  third documented instance — would be one of:
  1. A tiny shared helper in `libs/storage` (or a new `libs/db`), e.g.
     `literal_enum_predicate(column: str, value: str, allowed: frozenset[str]) -> str`, that every
     partial-indexed-enum query calls, so the allow-list-then-inline pattern lives in ONE place instead
     of being hand-copied (currently `_VALID_VIEW_TYPES` is defined independently in both
     `entity_embedding_ann.py` and `entity_profile_embedding.py` — a fourth site would very likely
     copy-paste-drift a third `_VALID_VIEW_TYPES` set that goes stale relative to
     `intelligence-migrations 0001` if that migration ever adds a fourth `view_type`).
  2. A migration-linter (pre-commit or CI step) that greps `CREATE INDEX ... USING (hnsw|btree) ... WHERE`
     in any new/changed Alembic migration and cross-references every repository method that filters on
     that same column, failing if the WHERE clause is built with `bindparam`/`:name` instead of a
     validated literal. This converts the HIGH_RISK_PATTERNS.md entry from an advisory (only fires if a
     human/agent reviewer remembers to check it) into an enforced gate.
- **TEST_GAP (still open in all three sites, including the "fixed" ones):** every regression test added
  so far — `test_chunk_search_accel_partial_index.py`, `test_entity_embedding_ann_partial_index.py`,
  `test_entity_profile_embedding_partial_index.py` — is a **mock-based SQL-shape assertion**
  (`assert "WHERE view_type = 'definition'" in sql`). None of them execute against a real Postgres and
  assert on `EXPLAIN` output. This is exactly option (b) that both the HIGH_RISK_PATTERNS.md entry and
  the REVIEW_CHECKLIST.md line explicitly offer as an alternative to literal-inlining ("ship an
  EXPLAIN-backed regression test asserting Index Scan"), and it has never actually been built for any of
  the three sites. Consequence: if a future refactor accidentally reverts the literal back to a bind
  param (e.g. someone "cleans up" the f-string into `text(...).bindparams(view_type=view_type)` for
  SQL-injection hygiene, not realizing the allow-list already makes it safe), **all three existing test
  suites would still pass** — they only check that today's code emits the literal, not that Postgres can
  actually use the index for that literal. A grep-only lint (SQL contains `= 'definition'` as a string)
  is a much weaker guarantee than a live `EXPLAIN` check.
  - **Test to add:** `services/nlp-pipeline/tests/integration/test_entity_profile_embedding_index_scan.py`
    (and a knowledge-graph twin) — spin up against the existing test Postgres fixture (same one
    `test_chunk_tenant_filter.py`/`test_chunk_lexical_search.py` already use), seed a handful of
    `entity_embedding_state` rows per `view_type`, run `EXPLAIN (FORMAT JSON) <the real repository
    query>` for each of `{"definition", "narrative", "fundamentals_ohlcv"}`, and assert the plan's
    top node type is `Index Scan` (or `Index Only Scan`) on `idx_entity_emb_<view_type>_hnsw` — **not**
    `Seq Scan` and **not** a `Sort` node above a Seq Scan. This is the only test shape that would have
    caught BP-717/BP-730 pre-merge instead of during a live OOM, and the only one immune to a future
    literal→bindparam regression.

**Severity/likelihood of recurring again as-is:** **MEDIUM, declining.** The allow-list-and-inline
pattern is now documented in three places (BUG_PATTERNS.md, HIGH_RISK_PATTERNS.md, REVIEW_CHECKLIST.md —
though uncommitted, see Finding 0) and correctly implemented in the two known repositories. The residual
risk is narrow but real: a **fourth** partial-indexed ANN/lookup site (the mined summary's own example —
"a future prediction-market embedding view_type, or a new tenant-scoped embedding table") would only be
caught by a reviewer remembering the checklist line, since there is no automated gate and no live-EXPLAIN
test anywhere in the codebase yet.

---

## Recurrence 2 — DB engine/connect_args hardening duplicated per-service (BP-732)

**Current code state (verified):** confirmed via direct inspection of all 9 services named in the
evidence pattern — no shared `libs/storage`/`libs/db` async-engine factory exists (`grep -rn
"build_async_engine|def build_engine" libs/` returns nothing). Concretely, as of this investigation:

| Service | `statement_cache_size=0` (PgBouncer) | `command_timeout` | `statement_timeout` |
|---|---|---|---|
| rag-chat | present | absent | absent |
| content-store | present | absent | absent |
| alert | present | absent | absent |
| market-ingestion | present | absent | absent |
| market-data | present | absent | present (server-side, ~8s) |
| nlp-pipeline | n/a (direct conn) | present | present |
| knowledge-graph | n/a (direct conn) | absent | present |
| content-ingestion | no `infrastructure/db/session.py` matched at all | — | — |
| portfolio | no `infrastructure/db/session.py` matched at all | — | — |

This confirms the mined summary's core claim precisely: `command_timeout` (added in `0d0f27119` to fix a
real dead-connection-hang incident) landed **only** in nlp-pipeline; the four PgBouncer-pooled services
that most need it (rag-chat, content-store, alert, market-ingestion — all of which already needed the
`statement_cache_size=0` PgBouncer fix, so they clearly share a connection topology with nlp-pipeline)
still have no client-side ceiling on a half-open socket. `content-ingestion` and `portfolio` didn't even
match the `infrastructure/db/session.py` path glob used by the other 7 services, which is itself a signal
that DB bootstrap code organization is not even consistently *located* across services, let alone shared.

**Classification: IMPLEMENTATION_GAP (pure).** No test would catch this class of bug — the missing
`command_timeout` on rag-chat/content-store/alert/market-ingestion does not fail any existing unit or
integration test; it only manifests as an unbounded hang under a specific network-partition/broker-drop
condition that none of those services' test suites simulate, and simulating it 7 times per service would
itself just be the duplication problem restated as tests. The only fix that closes the WHOLE class is
structural:

- Extract `libs/storage/src/storage/db/engine_factory.py` (or a new `libs/db` package, matching
  CLAUDE.md's existing shared-lib list which currently has no DB-session entry) exposing something like:
  ```python
  def build_async_engine(
      dsn: str,
      *,
      pooled: bool,                      # True = behind PgBouncer transaction pooling
      command_timeout_s: float = 600.0,  # client-side dead-socket ceiling (0d0f27119's proven default)
      statement_timeout_ms: int = 8_000, # server-side per-query ceiling (f1d04b8e5's default)
      application_name: str,
  ) -> AsyncEngine: ...
  ```
  and have every service's `infrastructure/db/session.py` call it instead of hand-building
  `connect_args`. A new hardening lesson then becomes a **one-file change** with N services picking it up
  on their next dependency bump, instead of N hand-edits that lag arbitrarily (as `command_timeout`
  currently does for 4+ services).
- Until that refactor happens, the next-best mitigating control is a **CI/lint invariant**, not a test:
  a small script (e.g. `scripts/check_db_session_parity.py`, run in the pre-PR checklist hook) that greps
  every `infrastructure/db/session.py`-equivalent file for the presence of `command_timeout` and
  `statement_timeout` connect_args keys and fails (or at least warns with a service list) if any pooled
  service is missing one that another pooled service has. This converts "someone has to remember to check
  the other 8 services" into an automated diff-against-parity check, without requiring the full
  refactor up front.

**Severity/likelihood of recurring again as-is: HIGH.** This is not a "might recur" risk — it has
**already** recurred three times (`bea446831`, `0d0f27119`, `f1d04b8e5`), it is currently in an
inconsistent state across the 9 services in the table above, and there is zero structural or automated
barrier preventing a 4th hardening lesson from landing in only 1-2 services again. This is the one
finding in this cluster where "as-is" genuinely means "still broken," not "fixed but under-tested."

---

## Recurrence 3 — GLiNER native-process OOM (BP-733)

**Current code state (verified):** GLiNER lives at `infra/gliner/` (not `services/gliner/` — the mined
summary's evidence-pattern path was slightly off, worth correcting for anyone searching by that path).
Confirmed present and real, not just documented:
- `infra/gliner/Dockerfile:29` — `ENV MALLOC_ARENA_MAX=2` with an explanatory comment block, correctly
  baked into the image (glibc reads `MALLOC_ARENA_MAX` pre-init, so this could not have been done from
  Python — the fix is in the right layer).
- `infra/gliner/server.py` — `GLINER_MAX_BATCH_CHARS` adaptive activation-budget guard (`_would_exceed_char_budget`),
  a pinned single-thread executor comment ("one glibc arena instead of one-per-executor-thread"), and
  `_malloc_trim()` called after every batch flush via a `ctypes` libc handle with a documented
  best-effort no-op fallback for non-glibc platforms.
- `infra/gliner/test_memory_bounds.py` — unit tests for `_malloc_trim` never raising, the char-budget
  guard bounding batch composition, and the single-executor-thread config. These are real, targeted
  regression tests (not just docstrings).

**Classification: BOTH, already substantially closed.**
- **IMPLEMENTATION_GAP: closed correctly.** The two-mechanism fix (activation-size budget + arena
  pinning/`malloc_trim`) is the right shape for the two failure modes described (spiky peak vs. flat
  ratchet), and it lives at the correct layer (Docker `ENV` for the glibc-level setting, application code
  for the batch-composition guard) rather than being a config value that could be lost on a redeploy.
- **TEST_GAP: narrow residual.** `test_memory_bounds.py` unit-tests the guard logic and confirms
  `_malloc_trim` doesn't raise, but (reasonably, since this is a native-process memory characteristic) it
  does not — and likely cannot, cheaply — assert an actual bounded RSS ceiling under a real sustained-load
  replay. That is an acceptable trade-off for this class of fix (a live-load soak test would belong in a
  staging/perf-test harness, not the unit suite), so this is not flagged as an action item — noting it
  only for completeness per the investigation's request to classify every recurrence.

**Severity/likelihood of recurring again as-is: LOW.** This mechanism is correctly fixed at the layer
that caused it (image env + inference-loop code) with targeted regression tests; the main residual risk
is generic ("a future GLiNER dependency bump or batching change could reintroduce a per-thread-per-call
allocation pattern"), which the existing REVIEW_CHECKLIST.md/HIGH_RISK_PATTERNS.md additions (once
committed — see Finding 0) already flag for reviewer attention on any inference-loop change.

---

## Summary table

| Recurrence | Classification | Structural fix status | Test-gap status | Severity as-is |
|---|---|---|---|---|
| Partial-index bound-param (BP-717/BP-730) | BOTH | Fixed at 2 sites; no shared helper/lint gate yet — a 3rd site relies on reviewer memory | Open at all 3 sites: only mock SQL-shape tests exist, no live-EXPLAIN Index Scan test | MEDIUM, declining |
| DB session/connect_args duplication (BP-732) | IMPLEMENTATION_GAP (pure) | **Not fixed** — no shared `libs/db`/`libs/storage` engine factory exists; 4+ services still missing `command_timeout` | N/A (a test-gap framing doesn't apply — nothing to test until centralized) | **HIGH — still actively broken** |
| GLiNER native OOM (BP-733) | BOTH, mostly closed | Fixed correctly at the right layer (image env + inference code) | Narrow, acceptable residual (no live-load soak test) | LOW |
| Compounding docs not committed (Finding 0) | N/A (process gap) | Draft exists, uncommitted | N/A | Blocks all of the above from taking effect outside this working tree |

## Top recommendation

Commit the already-drafted `docs/BUG_PATTERNS.md` / `.claude/review/heuristics/HIGH_RISK_PATTERNS.md` /
`.claude/review/checklists/REVIEW_CHECKLIST.md` changes (currently uncommitted `M` in this working tree)
first — they cost nothing and are the only thing making the partial-index fix visible outside this one
checkout. Then prioritize **Recurrence 2 (DB session bootstrap duplication)** over the other two: it is
the only finding here that is not actually fixed, has already caused 3 independent hardening passes to
under-propagate, and has zero automated barrier (test or lint) to stop a 4th. Extract a shared
`libs/storage`/`libs/db` `build_async_engine()` factory (or at minimum add a CI parity-check script) so
`command_timeout`/`statement_timeout`/PgBouncer settings stop needing manual re-application to 9 services
every time one of them gets paged.
