# PLAN-0087 — Standards / Rules Compliance Review

**Date**: 2026-05-09
**Auditor**: rules-compliance subagent (read-only)
**Scope**: 11 commits (plus 3 contemporaneous follow-ups discovered) since
`974f4f1d` on branch `feat/content-ingestion-wave-a1`.
**Sources read**: `RULES.md` (R1–R34), `docs/STANDARDS.md`, `AGENTS.md`,
`CLAUDE.md`, PRD-0087, PLAN-0087, defect register, BUG_PATTERNS.md (last 12
entries).

> Note on rule numbering: `RULES.md` is the canonical numbering source. The
> prompt's per-commit checklist used CLAUDE.md's older mapping for some
> labels (e.g. CLAUDE.md "R7" = no cross-service DB → RULES.md R7 same;
> "R10" = structlog → in RULES.md that is R12; etc.). This report aligns to
> `RULES.md` numbering, with a translation note where the prompt's label
> diverges.

---

## 1. Per-Commit Rule Pass/Fail Matrix

Legend: ✅ pass · ⚠ partial / weak · ❌ violation · — N/A · ? not assessable.
Columns map to the prompt's checklist (canonical RULES.md rule shown in
parentheses).

| Commit | R1/R4 (tests) | R5 (Avro fwd-compat) | R7/R9 (cross-DB) | R10 (UUIDv7) | R11 (UTC) | R12 (structlog) | R19 (no test deletion) | R25/R27 (API/UoW) | R29 (manifest) | R32 (alembic head) | R3 (docs) | BP / context update |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `493dcb4e` D-INIT-6 source_name + R7 removal | ✅ | ✅ default null, doc string explicit | ✅ removes one violation, none introduced | — | — | — | ✅ tests rewritten not deleted | — | — | — | ❌ no `docs/services/{nlp-pipeline,knowledge-graph}.md` update; no Avro doc page update | ❌ no BP, no `.claude-context.md` |
| `8d8e6519` chat-tools (D-R1-001/002/005) | ✅ comprehensive (libs/tools +153, executor +243, orchestrator +210) | — | — | — | — | — | ✅ MagicMock(to_tool_definitions) replaced not deleted | ✅ R30 factory pattern preserved | ⚠ test_tool_manifest_sync only checks names not param schemas (pre-existing gap, not introduced) | — | ❌ no `docs/services/rag-chat.md` or `docs/libs/tools.md` update | ❌ no BP, no context note |
| `92915986` cooperative-sticky | ✅ new test_consumer_config.py (143 lines) | — | — | — | — | — | ✅ | — | — | — | ❌ no `docs/libs/messaging.md` update; runtime default change is platform-wide and not surfaced anywhere durable | ⚠ BP-442 added LATER in `97153b36` (delayed compounding); no `libs/messaging/.claude-context.md` update; no ADR (arguably ADR-worthy: changes consumer-protocol default for every service) |
| `a630d62f` frontend polish (D-F3-001..011) | ✅ status-page tests updated; new architecture test `no-off-palette-colors.test.ts` (157 lines) | — | — | — | — | — | ✅ | — | — | — | ✅ `docs/ui/DESIGN_SYSTEM.md` whitelisted AG Grid (1 line — minimal) | ❌ no BP for `Loading…` ellipsis or off-palette guard; no `.claude-context.md` |
| `8bbd7480` intelligence aggregates SQL drift | ⚠ commit msg says "24 passing" but **no new test added** for the new SQL shape | — | ✅ stays inside intelligence_db | — | — | — | ✅ | ✅ R25 untouched (read-side repo) | — | — | ❌ no `docs/services/knowledge-graph.md` note that `confidence_components` is unshipped | ❌ no BP for "JSONB-column-referenced-but-never-migrated" pattern (this is exactly the kind of pattern BUG_PATTERNS catches) |
| `0f96c81c` confidence_trend follow-up | ⚠ same as `8bbd7480` — second broken query in same repo, **no new test** added | — | ✅ | — | — | — | ✅ | ✅ | — | — | ❌ same gap | ❌ same gap; the fact that this needed a follow-up commit is itself a missed-coverage signal that BP would document |
| `97153b36` 8-defect bundle | ⚠ partial: D-R4-002, D-F1-007, D-F1-009 have new tests (citation_pipeline, test_routes, test_news_url_normaliser); migration 0037 has new test_migration.py (128 lines); **D-R3-003, D-R3-005, D-R4-003, D-R4-004, D-F2-001 have NO new tests** | — | ✅ | — | ✅ `datetime.now(tz=UTC)` used in scheduler.py | ✅ | ⚠ legacy_sections fallback removed (function `_parse_sections_from_markdown` retained, its tests retained — R19 OK); but no positive test asserts new behaviour `legacy_sections == []` | ✅ | — | ✅ migration 0037 reviews 0036 head (chain valid) | ❌ no `docs/services/{rag-chat,knowledge-graph,api-gateway,portfolio,intelligence-migrations}.md` updates for behavioural changes | ⚠ BP-442 added (kafka, prior commit's debt); no BP for the new patterns (echoed Jinja vars; entity_id→ticker fallback chain; Finnhub URL normalisation; brief-archive-write null wiring) |
| `5e1b18f5` migration 0038 demo seeds | ❌ no test file for the new migration (compare 0037 which got a 128-line test_migration.py) | — | ✅ same DB | ✅ deterministic v7-shaped IDs (mirrors 0009 pattern; prompt explicitly accepts this) | — | — | ✅ | — | — | ✅ `Revises: 0037` matches actual head | ❌ no `docs/services/knowledge-graph.md` or `docs/services/intelligence-migrations.md` update naming the seeded entities | ❌ no BP, no `.claude-context.md` |

### Out-of-prompt-scope contemporaneous commits

| Commit | Rule check |
|---|---|
| `1ef95ee9` D-R3-NARR (post-bundle follow-up) | ❌ R1/R4: 7-line src change, **zero new tests**; the bug "every narrative was a 40-word template" is precisely the kind of regression a unit test on `generate_narrative.py:455` would have prevented. Also no BP for "ExtractionOutput.output vs raw_response field name drift". |
| `60b3f713` doc-only QA checkpoint | ✅ docs only; not subject to behavioural rules |
| `ad617194`, `720ae6b9` | merge commits; rule checks roll up to merged children |

---

## 2. Open Violations (must / should fix before demo)

Severity scale: **HF** = blocks demo, **SF** = degrades demo quality, **INFO**
= post-demo cleanup.

### HF — none
No commit shipped a runtime regression that would by itself fail the demo.
The R7 violation in D-INIT-6 was *removed* (good); no new HF-class
introductions found.

### SF-1 (R3 docs, repository-wide) — _multiple commits_
**No `docs/services/*.md`, `docs/libs/*.md`, or `docs/MASTER_PLAN.md` was
touched in any of the 14 non-merge commits.** This session changed:

- a forward-compat Avro schema field (`source_name` on `nlp.article.enriched.v1`)
- a platform-wide Kafka consumer default (assignor: range → cooperative-sticky)
- a public S9 endpoint behaviour (`/v1/instruments/{id}/page-bundle` now does
  entity_id → ticker → instrument_id resolution)
- a public S6 endpoint behaviour (`url` field on news items normalised)
- a use-case wiring change (BriefArchive null adapter → real write adapter)
- 8 demo-critical seeded entities (visible to chat A7 prompt and B5 page)

R3 is unambiguous: "every API/event/schema/config change must update docs".
Fix path: at minimum
- `docs/services/nlp-pipeline.md` § Events → add `source_name` to enriched.v1
- `docs/services/knowledge-graph.md` § Consumers → note R7 fallback removed
- `docs/libs/messaging.md` § Defaults → cooperative-sticky default + KIP-429 link
- `docs/services/api-gateway.md` § Composition routes → page-bundle fallback chain
- `docs/services/rag-chat.md` § Brief archival → BriefArchiveWriteAdapter
- `docs/services/intelligence-migrations.md` § Seed data → migration 0038 entity list

### SF-2 (R1/R4 missing tests) — `97153b36` + `1ef95ee9` + `8bbd7480` + `0f96c81c` + `5e1b18f5`
Behavioural changes shipped without a corresponding new test:

| Defect | Behaviour change | Missing test |
|---|---|---|
| D-R3-003 | scheduler interval cron→6h + 60s startup fire | no test that scheduler registers `worker_13d3_narrative_generation` with `next_run_time` ≤60s in future |
| D-R3-005 | `_HUB_MIN_RELATIONS` 10→2 env-overridable | no test of new default and env override |
| D-R4-003 | `legacy_sections=[]` always | no test asserting the new path returns empty `legacy_sections` |
| D-R4-004 | `briefing_uc.brief_archive` is now real adapter not Null | no test verifying `app.state.briefing_uc.brief_archive` is `BriefArchiveWriteAdapter` after `_wire_briefing_uc` |
| D-F2-001 | log level DEBUG→WARNING + exception class included | no test |
| D-R3-001 | repointed two SQL methods | repository tests not updated; existing test suite happens to still pass because the queries are mocked at a level above the repo |
| D-R3-001 follow-up | `confidence_trend` rewrite as CTE | same — no repo-level integration test added |
| D-R3-NARR | `result.output` → `result.raw_response` | no unit test on `generate_narrative.py` covering the LLM-success path |
| Migration 0038 | new seeds | no migration apply/rollback test (compare migration 0037 in the same session, which DID get a 128-line test) |

R1 says "every behavior change". The 9 above ship behaviour without a guard.

### SF-3 (R29 architecture test under-implemented) — pre-existing, exposed by `8d8e6519`
`tests/architecture/test_tool_manifest_sync.py` only checks **name presence**,
not parameter schemas. R29 explicitly requires "checks that every function
registered in `ToolRegistry` has a corresponding YAML entry **with a matching
parameter schema**". The 18-tool `parameters=[]` placeholder gap that
`8d8e6519` fixed should have been caught by this test years ago.

Fix path: extend `test_tool_manifest_sync.py` with a third test asserting
that every YAML tool's parameter list (name + type + required) matches the
registered `ToolSpec.parameters`.

### INFO-1 (compounding debt) — every behavioural commit
Eight new patterns were not added to BUG_PATTERNS.md or to any
`.claude-context.md`:

1. **Avro schema field absent → R7-violating fallback query** (D-INIT-6)
2. **Kafka assignor default change platform-wide** (D-P3-006/009; BP-442 *was* added but in the wrong commit — the message-bundle commit, not the change commit)
3. **JSONB column referenced before its migration ships** (D-R3-001 root cause)
4. **scheduler interval-vs-cron defaults for demo windows** (D-R3-003/005)
5. **LLM echoes Jinja template variable names as bracketed tokens** (D-R4-002)
6. **legacy list[dict] vs typed BriefSection drift** (D-R4-003)
7. **NullAdapter wiring left in production due to missing factory shape** (D-R4-004)
8. **API gateway entity_id ≠ instrument_id resolution chain** (D-F1-007 — variant of BP-342, deserves a cross-link or a new BP for the page-bundle compound case)
9. **ExtractionOutput field-name drift** (D-R3-NARR)

---

## 3. Missing Compounding Updates

Per CLAUDE.md "Evaluation & Improvement": after a session, bug patterns,
checklists, skill definitions, and hooks should be compounded.

| Commit | Expected compounding update | Actual |
|---|---|---|
| `493dcb4e` D-INIT-6 | BP for "Avro field missing → cross-DB fallback hides the bug"; update `services/knowledge-graph/.claude-context.md` (R7 trap removed) and `services/nlp-pipeline/.claude-context.md` (always emit `source_name`); update `docs/services/{nlp-pipeline,knowledge-graph}.md` § Events | None |
| `8d8e6519` chat-tools | BP for "tool registry to_tool_definitions silently absent → tools never invoked"; tighten `tests/architecture/test_tool_manifest_sync.py` to compare param schemas; update `docs/services/rag-chat.md` § Tool execution | None |
| `92915986` cooperative-sticky | BP-442 (added but in `97153b36`); `libs/messaging/.claude-context.md` should note new platform default; `docs/libs/messaging.md` § Defaults section needs the change; arguably an ADR for the platform-wide default change | BP-442 added but in *wrong commit*; no context, no docs, no ADR |
| `a630d62f` frontend polish | BP for "off-palette colours leak past code review without architecture test"; update `docs/ui/DESIGN_SYSTEM.md` deeper than the AG Grid line | Architecture test added (good); BP missing |
| `8bbd7480` + `0f96c81c` SQL drift | BP for "ORM/query references column whose migration was never shipped"; note in `services/knowledge-graph/.claude-context.md` that `confidence_components` is **NOT** a real column despite PLAN-0074 design; update `docs/services/knowledge-graph.md` | None |
| `97153b36` 8-defect bundle | BP-442 (kafka, retroactive); BPs for D-R4-002, D-R4-003, D-R4-004, D-F1-007, D-F1-009 patterns; update at least 4 service docs and 2 `.claude-context.md` files | Only BP-442 (and that was for the prior commit). Five new patterns un-recorded |
| `5e1b18f5` migration 0038 | Test (`tests/test_migration.py`-style) for migration 0038 apply + idempotency + rollback; update `docs/services/intelligence-migrations.md` with seeded-entities table; update `services/intelligence-migrations/.claude-context.md` | None |
| `1ef95ee9` D-R3-NARR | BP for "ExtractionOutput field-name drift"; update `services/knowledge-graph/.claude-context.md` with the canonical attribute name; add a unit test on `generate_narrative.py` | None |

**Score**: of the 8 behavioural commits, 1 BP entry was added (BP-442) and 1
architecture test was added (`no-off-palette-colors.test.ts`). Across an
8-commit fix burst that closed 27 demo defects, this is far below the
"compound after every commit" bar set in CLAUDE.md.

---

## 4. Recommendations (ordered by severity / cost-of-delay)

### Before demo (must)
1. **R3 doc updates — minimum viable set** (≈45 min):
   - `docs/services/nlp-pipeline.md`: add `source_name` to enriched.v1 § Events.
   - `docs/services/knowledge-graph.md`: add a "R7 trap removed" callout near the enriched-consumer section; note `confidence_components` column is not yet shipped.
   - `docs/libs/messaging.md`: cooperative-sticky default callout + KIP-429 link.
   - `docs/services/api-gateway.md`: page-bundle entity_id→ticker fallback chain.
   - `docs/services/rag-chat.md`: BriefArchiveWriteAdapter wiring.
2. **Migration 0038 test** (≈30 min): mirror the 128-line `test_migration.py`
   that 0037 received — apply, idempotency, rollback, row-count assertions on
   `canonical_entities` and `entity_aliases`.
3. **D-R3-NARR regression test** (≈20 min): add a unit test on
   `GenerateNarrativeUseCase.run` asserting that when `ExtractionOutput`
   carries a non-empty `raw_response`, the worker stores `model_id =
   <real-model>` and not `template-v1`. This bug erased every narrative for
   weeks; it is the highest-value missing test.

### Before demo (should)
4. **`.claude-context.md` updates for the three services with biggest
   surface change** (≈30 min): nlp-pipeline (always emit source_name),
   knowledge-graph (R7 trap pitfall, `confidence_components` not-real
   column), messaging (cooperative-sticky default).
5. **Tighten `test_tool_manifest_sync.py`** (≈45 min): add a third test that
   compares parameter names + types + required-flags between the YAML and
   the registered `ToolSpec`. This closes the gap that let 18 tools ship
   with `parameters=[]` for half a year.

### Post-demo
6. **Add BP entries** for the 8 unrecorded patterns listed in §3 INFO-1.
   Each is a future-trap. Estimated 90 min total.
7. **ADR for cooperative-sticky default** (≈30 min): the change affects
   every consumer group, every service. RULES.md R4 reading is borderline
   ADR-worthy; STANDARDS.md §3 (libs/messaging) deserves the formal record.
8. **Backfill missing tests for D-R3-003/005, D-R4-003/004, D-F2-001**
   (≈90 min). These changes shipped without guards; if the demo branches
   off here, regressions are silent.

---

## 5. Auditor's Summary

The session closed a large defect burst (27+ defects across 14 commits) and
the *runtime correctness* of those fixes is high — no new R7/R8/R10/R11/R12
violations were introduced, R5 forward-compatibility was preserved, R32
alembic chain is clean, R19 was not breached (D-R4-003 retained the orphan
function and its existing tests).

The **compounding hygiene is the standout weakness**. R3 (docs) and R1/R4
(tests) were skipped in 9 places, and only 1 BP entry / 1 architecture test
landed despite 8 distinct new failure modes being uncovered. The pattern
matches the user-feedback memory entry "tracking + docs mandatory" — this
is the same trap being rediscovered, mid-session, under demo pressure.

The single highest-leverage post-audit fix is **§4 item 3** (D-R3-NARR
regression test): the worst defect of the session — every narrative across
the platform reduced to 40-word templates — could regress overnight without
a guard.
