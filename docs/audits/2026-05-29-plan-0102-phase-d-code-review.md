# PLAN-0102 Phase D — Adversarial Code Review (2026-05-29)

**Scope:** W1 `a8604277` (Brief Wave A), W6 `2ef0fee0` (DLQ timeout), W7 `4a3a1b50` (doc gaps).
W4 + W5 had **not landed** at review time (branch HEAD `325b228a`, working tree clean modulo
unrelated F-LIVE-NEW-002 in-flight files).

## Verdict: **CONDITIONAL PASS**

W1 ships materially correct wiring, but contains a **semantic contradiction inside the
v4.0 prompt** (P1) that will degrade live brief output: the top-of-prompt advertises a
6-section spec while the lower output-format block still hard-caps the LLM to **4
sections / 4 bullets**, plus the `## LEAD + ---` divider contract. The model is being
asked to obey two incompatible rubrics in the same prompt. W6 + W7 are clean.

---

## 1. Test sweep

| Suite | Result | Notes |
|---|---|---|
| `services/rag-chat tests/unit` (full) | **9 collection errors** | Pre-existing: `tools.types` import (PLAN-0067 W11-1) + 2 `test_tool_registry_*` modules. NOT introduced by W1. |
| `services/rag-chat tests/unit` (excluding pre-existing breakers) | **6 fails** | All in `tests/unit/use_cases/test_chat_orchestrator_tool_use.py` — last touched by PLAN-0095 W2, NOT introduced by W1. |
| Targeted W1 tests (`test_briefing_context_gatherer.py` + `test_brief_context_formatter.py`) | **46 passed** | Clean. |
| `services/market-data tests/unit` | **895 passed, 1 failed** | Failure: `test_app_lifespan.py::test_lifespan_starts_cleanly` (module-import-time) — needs verification it pre-dates W6. |
| `libs/prompts tests` | **91 passed** | Includes the bumped `assert MORNING_BRIEFING.version == "4.0"`. |
| `chat-eval tests/validation/chat_eval` (live skipped) | **passed** | All `RAG_CHAT_BASE_URL` rows correctly SKIPPED. |

**P1 finding:** the rag-chat test base has 9 collection breakers and 6 pre-existing
failures the W1 commit message does not acknowledge. The commit message claims "1421
rag-chat unit tests pass" — this is true only when the broken modules are silently
ignored by pytest's default collection-error behaviour. The hooks let this through.
Recommend a `pytest --strict-markers --ignore-glob=...` policy in CI to prevent
green-on-broken-collection masquerade.

## 2. W1 Brief — semantic correctness

- `MarketOverview` model (`services/rag-chat/src/rag_chat/application/models/briefing_context.py:94-116`) — additive change, default-empty lists, no caller-break risk. **Single producer call site** (`_build_market_overview` at `briefing_context.py:743-792`) + **single consumer** (`brief_context_formatter.py:240-280`). Grep across `services/rag-chat/src` confirms zero other reads of `market_overview.sector_performance|top_gainers|top_losers`, so the legacy fields are dead weight. **P2:** legacy fields could be dropped in PLAN-0103 once retention is no longer needed.
- SPY/QQQ/VIX path: tickers are resolved via `_resolve_ticker_map` (same path as holdings) and then JOINED with holding instrument ids into ONE `instrument_ids` list before the single S3 batch quote call (`briefing_context.py:167`). Tape symbols ARE treated as instruments (correct — S3 quote endpoint is instrument-id keyed). Tape resolution is wrapped in its own try/except so a single missing ticker does NOT zero the tape. **OK.**
- Overlap multiplier `1.5×` is a class constant `_NEWS_OVERLAP_MULTIPLIER` at `briefing_context.py:103`. **NOT env-configurable.** **P2:** expose via `RAG_CHAT_BRIEF_NEWS_OVERLAP_MULTIPLIER` for live tuning.
- Macro 2nd call — event_types disjoint (`portfolio: earnings/analyst_action/corporate` vs `macro: macro/economic`), so no double-count provided S7 honours the filter. **P2:** add an assertion test that S7's `search_events` actually applies `event_types` (currently the test only verifies the call SHAPE — not the filter outcome).
- **P1:** in `_fetch_events` (`briefing_context.py:586`) macro rows get `subject_entity_id=UUID(int=0)` sentinel because `e.subject_entity_id` is `None` for macro. This zero-UUID can leak into any downstream code that joins/filters on the field. Currently the formatter doesn't, but the sentinel is fragile. Suggest making `subject_entity_id: UUID | None` on `EventSummary` and migrating the field — non-blocking but flag for PLAN-0103.

## 3. W1 Prompt v4.0 (`libs/prompts/src/prompts/briefing/morning.py`)

- **P1 — internal contradiction:** the prompt opens with a 6-section spec (Tape /
  Portfolio / Macro / News / Risks / Bonus) and a 250-word cap, then under "Output
  Format (STRICT — DO NOT DEVIATE)" requires a `## LEAD\n---\n## DETAILS` two-block
  structure with `Maximum 4 sections, maximum 4 bullets per section`. Six > four. The
  LLM will either truncate to 4 (dropping Risks + Bonus, the differentiators) or
  ignore the cap. Either way the v4.0 promise is broken.
- **P2 — version-bump fan-out incomplete:** 5 in-tree docstring/comment references
  still say "v3.0" (`brief_parser.py:42,149,154`, `api/schemas.py:252`,
  `api/routes/public_briefings.py:438`, `contract/test_brief_contract.py:81`,
  `unit/application/test_generate_briefing_public.py:582`,
  `libs/prompts/tests/test_briefing_citations.py:5,18`). None affect behaviour but
  obscure the bump.
- **P2 — 250-word cap is prompt-instruction only.** No tokenizer / post-process gate.
  DeepSeek-R1-Distill-32B regularly over-runs soft prompt caps. Add a post-process
  word-count truncation in `brief_parser.py` for any brief >300 words.
- **P2 — "NEVER include news that doesn't connect" floor.** The rule appears in the
  prompt; the floor is partly expressed (`On quiet days, surface 1 sector-relevant
  macro signal rather than padding`) but the "3 high-impact items minimum" floor
  mentioned in the audit is NOT in the prompt text. Add it explicitly.

## 4. W6 DLQ timeout

- Env wiring trace: `MARKET_DATA_FUNDAMENTALS_TIMEOUT_S` → pydantic-settings
  `env_prefix="MARKET_DATA_"` → `Settings.fundamentals_timeout_s: int = 90` → consumed
  in `fundamentals_consumer_main.py:81` and forwarded as
  `ConsumerConfig.message_processing_timeout_s`. **OK.**
- Session/heartbeat co-scaling: `session_timeout_ms = max(60_000, (timeout_s + 30) * 1_000)`
  = 120 s; heartbeat 40 s. Watchdog (90 s) < session (120 s). **OK.**
  **P2:** the librdkafka recommendation is heartbeat ≤ session/3; 40_000 ≤ 40_000 is at
  the boundary, not under. Consider `session // 3 - 1` for safety.
- **P0 — type-ignore patches mask incomplete WIP.** `insider_transactions_consumer.py:337`
  now reads `uow.insider_transactions.insert_batch(...)  # type: ignore[attr-defined]`
  — meaning `UnitOfWork` does NOT expose `insider_transactions`. This is silently
  shipping a `AttributeError`-at-runtime path. A separate session is wiring this up,
  but **filing it inside a PLAN-0102 commit with a "doesn't change behaviour"
  justification is wrong** — it changes behaviour from "mypy fails loudly" to "mypy
  passes, runtime fails silently". **Action:** open BP-618 follow-up to track the
  missing UoW attribute, and remove the type-ignore once the attribute lands.
- Histogram buckets `[1, 5, 10, 30, 45, 60, 90, 120]s` capture both the old (45) and
  new (90) thresholds and a head-room bucket. **OK.**

## 5. W7 doc gaps

- BP-612 + BP-613 entries present in `docs/BUG_PATTERNS.md:630-631`, both cite
  `commit 91a363a0`. **OK.**
- BP-610 entry at line 634 references `docs/audits/2026-05-28-plan-0101-bp-610-touch-at.md`;
  file exists. **OK.**
- Retroactive plan `docs/plans/0101-iter-10-tps-redesign-and-graders.md` exists,
  cites `91a363a0`/`096ebc5d`/`ca9e4dc7`, and matches TRACKING.md W3 status. **OK.**

## 6. Cross-commit interactions

- W1 tests coexist with existing `test_briefing_context_gatherer.py` content — 46
  pass. **OK.**
- W6 `MARKET_DATA_FUNDAMENTALS_TIMEOUT_S` is a NEW env var; default 90 covers prod;
  grep across `infra/` shows no orchestration explicitly sets the old 45 s. **OK.**

## 7. Security / data exposure

- `held_entity_ids` derives from `await self._s1.get_portfolio_context(UUID(user_id), UUID(tenant_id), …)`
  — user-scoped at S1 side. News re-ranking only re-orders **publicly fetched** news;
  it does NOT inject holdings into the news payload. No A→B leak possible.
- SPY/QQQ/VIX public; no PII. **OK.**

## 8. Migrations

`git log --diff-filter=A --name-only -10 | grep alembic` returns empty. **OK.**

## 9. Working-tree contamination

`git status` reports 3 modified rag-chat files and 3 new files, all belonging to the
in-flight F-LIVE-NEW-002 work declared in `git log` (`325b228a fix(rag-chat): F-LIVE-NEW-002 …`).
None overlap PLAN-0102 W1/W6/W7 scope. **OK.**

## 10. PLAN-0102 acceptance gate

- W4 + W5 NOT shipped — `tps_streaming` NaN regression + grader policy + `record_once`
  guard still open. **Deferred verification.**
- No live brief A/B yet — would need a synthetic 5-holding user + a deterministic
  prompt seed. **Deferred verification.**
- Chat-eval rerun for the new gates is gated on W4 + W5 landing. **Deferred.**

---

## Prioritised PLAN-0103 punch-list

| # | Sev | Item | File / Anchor |
|---|---|---|---|
| 1 | **P1** | Resolve the v4.0 prompt's 6-section vs `Maximum 4 sections` contradiction (either lift the cap or restate the 6-section spec as "up to 6 — drop sections without content"). | `libs/prompts/src/prompts/briefing/morning.py:48-82` |
| 2 | **P0/P1** | Remove the `# type: ignore[attr-defined]` from `insider_transactions_consumer.py:337` + `insider_universe_loader.py:53` and file **BP-618** to track the missing `UnitOfWork.insider_transactions` attribute. The current state is "silent runtime failure". | `services/market-data/src/market_data/infrastructure/messaging/consumers/insider_transactions_consumer.py:337` + `infrastructure/workers/insider_universe_loader.py:53` |
| 3 | P1 | Fix the rag-chat pytest collection — 9 modules broken at import time (`tools.types`) means CI runs on a partial suite. Either restore the `tools` module path or `pytest --ignore` them explicitly with a tracking issue. | `services/rag-chat/tests/unit/infrastructure/llm/*.py`, `tests/unit/application/pipeline/test_tool_registry_*.py` |
| 4 | P1 | Investigate the 6 pre-existing fails in `test_chat_orchestrator_tool_use.py` (last touched PLAN-0095) — they're masking signal. | `services/rag-chat/tests/unit/use_cases/test_chat_orchestrator_tool_use.py` |
| 5 | P1 | Add a post-process word-count truncation for briefs > ~300 words; the 250-word cap is currently prompt-instruction only. | `services/rag-chat/src/rag_chat/application/use_cases/brief_parser.py` |
| 6 | P1 | Replace `subject_entity_id=UUID(int=0)` sentinel with `subject_entity_id: UUID | None` on `EventSummary` (macro events legitimately have no subject). | `services/rag-chat/src/rag_chat/application/models/briefing_context.py:127` + `briefing_context.py:586` |
| 7 | P2 | Expose `_NEWS_OVERLAP_MULTIPLIER` as an env var for live tuning. | `briefing_context.py:103` |
| 8 | P2 | Add an integration assertion that S7 `search_events(event_types=…)` actually filters on the server side (current tests only check call SHAPE). | `services/rag-chat/tests/unit/application/test_briefing_context_gatherer.py` |
| 9 | P2 | Sweep 8 stale "v3.0" docstring/comment references after the v4.0 bump. | `brief_parser.py:42,149,154`, `api/schemas.py:252`, `api/routes/public_briefings.py:438`, `tests/contract/test_brief_contract.py:81`, `tests/unit/application/test_generate_briefing_public.py:582`, `libs/prompts/tests/test_briefing_citations.py:5,18` |
| 10 | P2 | State the "3 high-impact items minimum" floor explicitly in the prompt — currently only the audit doc carries it. | `libs/prompts/src/prompts/briefing/morning.py:60-62` |
| 11 | P2 | Verify `test_lifespan_starts_cleanly` failure in market-data pre-dates W6 (or fix it). | `services/market-data/tests/unit/test_app_lifespan.py:20` |
| 12 | P2 | Drop the back-compat `sector_performance / top_gainers / top_losers` fields on `MarketOverview` — zero non-test reads remain. | `services/rag-chat/src/rag_chat/application/models/briefing_context.py:106-108` |
| 13 | P2 | Tighten heartbeat to `session // 3 - 1` (currently exactly at the boundary). | `services/market-data/src/market_data/infrastructure/messaging/consumers/fundamentals_consumer_main.py:84` |

### Proposed new BPs

- **BP-618** — "Type-ignore-on-missing-attr in shipped consumer creates silent
  AttributeError-at-runtime path." Trigger: any new `# type: ignore[attr-defined]`
  on a `uow.<repo>` call where `<repo>` is not declared on `UnitOfWork`. Found in
  PLAN-0102 W6 commit (insider transactions/loader).
- **BP-619** — "Prompt template advertises N sections in the spec but hard-caps the
  output-format block to M<N sections." Trigger: any prompt with two prescriptive
  rubrics whose section counts disagree. Found in PLAN-0102 W1 morning v4.0.
- **BP-620** — "pytest collection errors silently reduce the effective test suite
  surface; commit message reports the reduced PASS count as full." Trigger: any
  commit where `pytest tests/unit` reports collection errors alongside the green
  count.

---

**End of review.** Branch `feat/plan-0099-w4` at `325b228a`; W4 + W5 still pending.
