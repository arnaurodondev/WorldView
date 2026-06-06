# PLAN-0098 Revision Report — 2026-05-27 (round 2)

Revised `docs/plans/0098-iter-9-pipeline-and-cleanup-plan.md` in place to fold in the data-pipelines investigation, the unblock chat-eval audit, and the already-shipped chunk_search R40 fix (commit `7e8ec9a8`).

## (a) Sections changed
- **Header**: title expanded; `revision_note` rewritten; `source_audits` upgraded from IN FLIGHT → LANDED.
- **§0 Inline PRD**: 5 failure classes (was 4); all `<TBD-investigation>` markers resolved.
- **§1 Overview**: bumped to 5 waves; coordination note now references commit `7e8ec9a8`.
- **§2 Dependency Graph**: added W5; W2+W5 joint critical path.
- **§3 Codebase State**: every `<TBD>` row replaced with concrete file:line per §A1-§A5 + §B; 2 new rows for W5.
- **§4 Sub-Plans**: W1 T-W1-01 marked SHIPPED, T-W1-03 deferred. W2 tasks given concrete root causes + paths. W3 rewritten around Option 1 coercion (no migration). W4 unchanged. **W5 added** (T-W5-01 row-mix; T-W5-02 parallelize section reads + EXPLAIN ANALYZE).
- **§5 Acceptance gate**: criteria expanded — Q4 real table ✓ (baseline), NVDA $10.3B check, p99<60s; command uses foreground+`disown` per unblock §6.
- **§6 Risk Register**: stale risks dropped; 2 W5 risks added.
- **§8 Next round**: rewritten — prior `<TBD>` items DONE.
- **TRACKING.md**: NEW PLAN-0098 row inserted at `draft 1/5`.

## (b) Inconsistencies found
- The audit promised BP-584 for chunk_search but commit `7e8ec9a8` filed it as **BP-583** (collision). Renumbered downstream: W2-T01=BP-584, W3=BP-585, W2-T04=BP-586, W5-T01=BP-587, W5-T02=BP-588.
- Original W3 had Option A (constraint extension) preferred; investigation §B prefers Option 1 (write-time coercion, no migration). Plan now reflects that.

## (c) Deferred to PLAN-0099
- T-W1-03 shared R40 helper (re-evaluate after T-W1-02 sweep).
- Additional Avro field mapping bugs in balance_sheet/cash_flow if surfaced by W2-T04.
- Retroactive backfill of dropped entity_mentions rows (forward-only fix in W2-T01).
