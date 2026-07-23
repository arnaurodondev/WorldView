# Docs/Pain-Point Audit — Synthesis Report — 2026-07-23

Cross-cutting synthesis of a 3-vertical audit run: (1) failure-pattern mining across git history,
(2) compounding doc updates (`BUG_PATTERNS.md`, `HIGH_RISK_PATTERNS.md`, `REVIEW_CHECKLIST.md`,
service `.claude-context.md` files), (3) per-cluster bottleneck deep-dives with source verification.

## Summary — the #1 recurring pain point

**`services/rag-chat`'s prompt/grounding/citation machinery (`libs/prompts/chat/tool_use.py`,
`chat_orchestrator.py`, `numeric_grounding.py`) is the single largest recurring pain point**, at
**19 mined recurrences** — more than 2x the next cluster (content-ingestion pagination, 6) and more
than 3x messaging self-heal (9) or postgres pooling (2). It also has the most severe *shape* of
recurrence: unlike the other four clusters, where a fix in one file needs to be copy-propagated to
sibling files, rag-chat's fixes are landing **in the same file, sometimes the same commit chain**,
and still regressing — e.g. `24f71c0d2` patched v1.23's own `BATCH WIDTH` directive because it had
caused the LLM to silently drop a *different* tool call (`traverse_graph`), one commit after that
directive was introduced. That is a fix inducing a same-class regression in the file it just edited,
which no amount of "copy the fix to siblings" discipline (the fix applied to every other cluster)
would have prevented — it needs a structural fix (a real citation contract, not another regex gate)
or a CI-gated live A/B eval before merge, and today has neither.

The second-most systemic issue is **messaging self-heal** (BaseKafkaConsumer): not the highest
recurrence count, but the only cluster where the *deep-dive* confirmed the latest bug (`19d5fbf3c`)
was a pure, cheaply-preventable test gap — a unit test over the pause-state cross-product would have
caught it before a human reviewer did, and the fix commit that closed it added zero such tests, so
the gap is still open today.

## Clusters

| Cluster | Recurrence count | Root-cause classification | Doc fixes applied this run |
|---|---|---|---|
| **rag-chat-grounding** — prompt/citation/fabrication heuristic accretion | **19** | Both (structural: no enforced citation contract; test: no cross-guard/cross-prompt-version interaction tests) | BUG_PATTERNS BP-734, BP-735; HIGH_RISK_PATTERNS HR-065, HR-066; REVIEW_CHECKLIST §6b (2 lines, merged); `services/rag-chat/.claude-context.md` (+1 bullet naming the meta-pattern) |
| **content-ingestion-pagination** — Polymarket short-page heuristic + duplicated clients | 6 | Both (structural: no shared pagination helper across client family; test: pagination tested against assumed, not live, provider contract) | BUG_PATTERNS BP-739 (flags `polymarket_data_trades/client.py` as still-unfixed); HIGH_RISK_PATTERNS HR-067; REVIEW_CHECKLIST §7 + §8 (2 lines); `services/content-ingestion/.claude-context.md` (+1 bullet) |
| **messaging-selfheal** — BaseKafkaConsumer self-heal gate accretion | 9 | Both (structural: 5-signal boolean pile, no unified liveness-state enum; test: each fix tests its own gate in isolation, never the full cross-product) | BUG_PATTERNS BP-731 (folds in sibling-collection sub-pattern); HIGH_RISK_PATTERNS HR-060; REVIEW_CHECKLIST §4 (2 lines); `services/nlp-pipeline/.claude-context.md` (+1 bullet, no BP-NNN existed for the specific `_resume_all_paused_partitions` bug before this run) |
| **kg-entity-worker-quality** — dedup + worker crashloop resilience | 3 | Structural/abstraction gap (no shared BaseWorker/resilient-deserialize mixin; APScheduler jobs get exception-swallowing for free, standalone loops and consumers don't) | BUG_PATTERNS BP-736, BP-737, BP-738; HIGH_RISK_PATTERNS HR-062, HR-063, HR-064; REVIEW_CHECKLIST §1, §2, §6b (3 lines); `services/knowledge-graph/.claude-context.md` (+1 bullet naming all 7 still-unfixed sibling consumers) |
| **postgres-oom-pooling** — partial-index defeat + duplicated DB session hardening | 2 | Weighted toward structural (no shared `libs/db` engine-factory across 9 services); partial-index sub-pattern was a review-signal gap, already resolved by prior BP-717/BP-730 + HIGH_RISK_PATTERNS/REVIEW_CHECKLIST entries | BUG_PATTERNS BP-732 (DB hardening duplication only — partial-index sub-pattern explicitly skipped as already covered by BP-717/BP-730); HIGH_RISK_PATTERNS HR-061; REVIEW_CHECKLIST §6b (1 line: DB session.py connect_args parity check); `services/knowledge-graph/.claude-context.md` + `services/nlp-pipeline/.claude-context.md` (+1 bullet each, cross-referencing BP-730 as the sibling-repo recurrence of BP-717) |

Also captured, not part of the ranked table: **GLiNER native-process OOM** (two independent
mechanisms — activation-size scaling and glibc arena fragmentation) was folded into BUG_PATTERNS
BP-733 and HIGH_RISK_PATTERNS flagged it as *not* code-shape reviewable (pure ops/infra incident),
so it has no REVIEW_CHECKLIST line by design.

## Remaining items needing a follow-up session

Each bottleneck deep-dive below contains source-verified findings, a test-gap/implementation-gap
split, and a concrete top recommendation. None are deploy-blocking; ordered by severity/urgency.

- **`docs/audits/2026-07-23-bottleneck-rag-chat-grounding.md`** — Highest priority. Confirms BP-734/
  BP-735/HR-065 already exist as **uncommitted working-tree edits** from a prior run — commit those
  first (zero-risk). Top action: convert the checklist's live-A/B-run requirement from advisory text
  into a CI-blocking pre-PR hook; that is the only mechanism that has ever actually caught this bug
  class, and it is not currently enforced.
- **`docs/audits/2026-07-23-bottleneck-kg-entity-worker-quality.md`** — High severity/likelihood
  (R11 guarantees more backward-compatible Avro field appends). Verified 7 of 9 comparable KG
  consumers still lack the resilient-deserialize override two siblings already received. Top
  recommendation: move the catch into `BaseKafkaConsumer._handle_message` itself (or a
  `ResilientDeserializeMixin`, mirroring the existing `ValkeyDedupMixin` precedent) so protection is
  on by default, then backfill 7 missing regression tests + one architecture test.
- **`docs/audits/2026-07-23-bottleneck-postgres-oom-pooling.md`** — Verified `command_timeout` exists
  only in nlp-pipeline; rag-chat, content-store, alert, and market-ingestion (all PgBouncer-pooled)
  still lack it. Pure implementation gap (no test can catch missing hardening). Fix: extract a shared
  `build_async_engine()` factory, or short of that, a CI parity-check script across the 9 services.
- **`docs/audits/2026-07-23-bottleneck-content-ingestion-pagination.md`** — Confirmed
  `polymarket_data_trades/client.py:94` still contains the disproven `has_more = len(trades) >= limit`
  heuristic, unfixed and unpropagated from the Gamma-client fix. Medium-high severity: under-fetched
  trades would silently bias OI/volume-derived prediction-market signals. Top action: one read-only
  live-contract smoke test + extract a shared `next_offset_cursor` helper across the Polymarket client
  family.
- **`docs/audits/2026-07-23-bottleneck-messaging-selfheal.md`** — Lowest urgency (current code is
  correct); the `19d5fbf3c` fix itself added zero tests. Top action: add
  `TestResumeAllPausedPartitions` to `libs/messaging/tests/unit/test_connectivity_probe.py` covering
  barrier-only, backpressure-only, and combined pause states, plus one combinatorial fire/suppress
  test. Structural follow-up (unifying the 5-signal pile into one liveness-state enum) is a
  non-urgent `/refactor` candidate.

## Compounding check

Confirms what was actually written to each compounding artifact this run (per the vertical-2 updater
reports) — use this to sanity-check `git diff` before committing.

- **`docs/BUG_PATTERNS.md`** — 9 new entries added, **BP-731 through BP-739**, continuing sequential
  numbering from the prior tail. One candidate pattern (parameterized predicate on a partial index)
  was deliberately **skipped** as already fully covered by existing BP-717 and BP-730.
- **`.claude/review/heuristics/HIGH_RISK_PATTERNS.md`** — 8 new entries added, **HR-060 through
  HR-067**, continuing from HR-059. Two related mined candidates were merged into HR-060 (same
  code-shape signal). Three candidates were **deliberately skipped** as not diff-shape reviewable
  (DB hardening duplication, GLiNER native OOM, unverified provider-contract testing) — flagged for
  `docs/BUG_PATTERNS.md`/QA-checklist coverage instead. Pre-existing duplicate IDs (HR-029, HR-046
  each appear twice, from earlier sessions) were left untouched — out of scope, flagged as a
  follow-up cleanup.
- **`.claude/review/checklists/REVIEW_CHECKLIST.md`** — 12 new lines added across Sections 1, 2, 4,
  6, 6b, 7, and 8. No new top-level section was created; every mined pattern fit an existing section.
  Two rag-chat-grounding candidates were merged into a single checklist line (same underlying gap: no
  live A/B validation on prompt changes).
- **Service `.claude-context.md` files** — 5 services edited, one bullet each, all under existing
  "Key Pitfalls"/"Pitfalls" sections (no restructuring):
  - `services/nlp-pipeline/.claude-context.md` — messaging self-heal accretion pattern (no BP-NNN
    existed for the specific bug before this run) **and** the BP-730 partial-index sibling-recurrence
    pointer.
  - `services/knowledge-graph/.claude-context.md` — BP-730 partial-index cross-reference to BP-717,
    **and** the missing-shared-abstraction structural pointer for the 7 still-unfixed consumers /
    `path_insight_worker.py` / 3 independently-invented attempt-capping mechanisms.
  - `services/rag-chat/.claude-context.md` — the citation/grounding whack-a-mole meta-pattern
    (previously only ~15 individual instance-level pitfalls were documented, never the class).
  - `services/content-ingestion/.claude-context.md` — the disproven short-page pagination heuristic,
    naming `polymarket_data_trades/client.py` as the still-unfixed instance.
  - Note: the repo-wide "DB session/engine bootstrap duplicated per-service, no shared `libs/db`
    factory" structural gap (postgres-oom-pooling, part a) was **explicitly not** added to any single
    service's context file, since it spans ~9 services and doesn't fit as one service's pitfall bullet
    — it is captured only in `docs/BUG_PATTERNS.md` (BP-732) and the bottleneck deep-dive.
