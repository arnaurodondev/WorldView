# AI Brief Empty Universe-Wide — Investigation

**Date:** 2026-06-19
**Worktree:** `worldview-wt-md-reliability` (branch `feat/md-reliability-followups`)
**Mode:** Read-only (live DB / logs / code inspection)
**Question:** Why is `instrument_fundamentals_snapshot.has_ai_brief` = false for all 669 instruments? Is the "missing gitops env var" the cause, and is it fixed?

---

## TL;DR — Verdict

**The AI brief is NOT fixed, and the root cause is a CODE GAP, not a missing env var.**

`has_ai_brief` is materialised from S8's `GET /internal/v1/instruments/{id}/ai-brief-flag`, which reports `true` only when a row exists in `rag_db.user_briefs` with `brief_type = 'entity'` and `entity_id = <instrument_id>`.

**No code path in the entire repository ever writes an entity-scoped brief row.** The only writer of `user_briefs` hardcodes `brief_type="morning", entity_id=None` (`generate_briefing.py:644-645`). The on-demand instrument-brief route (`execute_public_instrument`) generates and returns a brief but never persists it. Therefore the `'entity'` query can never match → `has_ai_brief` is structurally always `false` → all 669 snapshot rows are `false`. The market-data sync side is working correctly; it is faithfully materialising the `false` the flag endpoint returns.

The user's "missing gitops env var" memory refers to an **older, already-fixed** failure (the service-JWT / DeepInfra key gap on the *morning* brief pre-gen path — PLAN-0094 W2 follow-up). Those env vars are now SET. That fix is unrelated to `has_ai_brief`.

There is **also a current live failure** on the morning-brief pregen path (separate from `has_ai_brief`): DeepInfra is returning **402 Payment Required** (billing/credit exhausted), so every brief generation fails right now. But fixing that would still not populate `has_ai_brief`.

---

## 1. Where briefs live + current counts

### `rag_db.user_briefs` (S8's own DB — note: DB is named `rag_db`, NOT `rag_chat_db`)

```
 brief_type | count | with_entity |            latest
------------+-------+-------------+-------------------------------
 morning    |    85 |           0 | 2026-06-19 05:28:58.111481+00
```

- 85 rows, ALL `brief_type='morning'`, ALL `entity_id IS NULL`.
- **Zero `brief_type='entity'` rows.** Distinct users = 1.
- There is **no** `instrument_intelligence_snapshot` table anywhere (rag_db, intelligence_db, kg_db). The doc-strings referencing that name are aspirational; the authoritative store is `user_briefs`.

### `market_data_db.instrument_fundamentals_snapshot`

```
 total | ai_true | ai_null
-------+---------+---------
   669 |       0 |       0
```

All 669 rows have `has_ai_brief = false` (none NULL — the sync worker has run and written explicit `false`). Note: the materialised column is just `has_ai_brief`; there is **no** `ai_brief_generated_at` column on this table (the L-5b migration only added the boolean).

---

## 2. The full brief chain (as built vs. as queried)

| Step | Component | What it does |
|------|-----------|--------------|
| Pre-gen worker | `MorningBriefPregenerationWorker` (`application/workers/...`) | Iterates **active users** (not instruments). Writes results to **Valkey only** (`briefing:morning:v2:{user_id}` + `:lastgood:`). Writes **nothing** to `user_briefs`. |
| Scheduler | `brief_scheduler_main.py` → container `worldview-rag-chat-brief-scheduler-1` | RUNNING. APScheduler `IntervalTrigger(hours=1)`, single job id `brief_pregeneration`. Only schedules the **morning** worker — no instrument-brief job exists. |
| `user_briefs` writer | `GenerateBriefingUseCase.execute()` `generate_briefing.py:640-660` | The ONLY `archive.save()` caller. Hardcodes `brief_type="morning", entity_id=None`. |
| Instrument brief generation | `GenerateBriefingUseCase.execute_public_instrument()` `generate_briefing.py:706` | Generates an instrument brief on demand, **returns** it to the route. **No persistence** — no `UserBriefRecord`, no `archive.save()`. |
| Instrument brief route | `GET /api/v1/briefings/instrument/{entity_id}` `public_briefings.py:456` | Calls `execute_public_instrument`, maps to response. **Never persists.** |
| Flag endpoint | `GET /internal/v1/instruments/{id}/ai-brief-flag` → `GetAiBriefFlagUseCase` `ai_brief_flag.py:57-64` | `SELECT MAX(generated_at) FROM user_briefs WHERE brief_type='entity' AND entity_id=:id`. Returns `false` because no such rows exist. |
| MD sync | `SyncIntelligenceRollupUseCase` `sync_intelligence_rollup.py:300-303` | Correctly calls S8 flag, upserts `has_ai_brief`. Working as designed → writes `false`. |

**The disconnect:** the producing side (Valkey morning keys + on-demand instrument generation) and the consuming side (`user_briefs WHERE brief_type='entity'`) never meet. The flag's data source is a table that nothing populates with entity rows.

---

## 3. Pregen worker run status + live errors

Scheduler container is alive and firing hourly. Recent runs (19:46 UTC):

- `eligible_users = 1` (only 1 active user in the 7-day window — the dev seed user `01900000-...-010`).
- Morning generation currently **FAILS for that user**:
  - `provider_failed deepinfra` → **402 Payment Required** (DeepInfra billing/credit exhausted).
  - `provider_failed ollama` → 404 (no model at `ollama:11434`).
  - → `ProviderUnavailableError`, `brief_pregeneration_user_failed`.
- Upstream context also degraded: S1 portfolio `403`, S5 alerts client error, S7 events empty.

These failures explain why even the morning-brief Valkey cache is stale right now, but they are **orthogonal** to `has_ai_brief`. Even a fully successful morning run writes `brief_type='morning'`, which the flag query explicitly excludes.

---

## 4. The "worldview-gitops missing env var" angle

Checked the running containers (`docker exec ... env`):

| Var | rag-chat-1 | brief-scheduler-1 |
|-----|-----------|-------------------|
| `RAG_CHAT_BRIEF_PREGEN_ENABLED` | `true` | `true` |
| `RAG_CHAT_DEEPINFRA_API_KEY` | SET | SET |
| `RAG_CHAT_SERVICE_ACCOUNT_TOKEN` | SET | SET |
| `RAG_CHAT_BRIEF_PREGEN_INTERVAL_HOURS` | — | `1` |
| `RAG_CHAT_BRIEF_PREGEN_ACTIVE_WINDOW_DAYS` | — | `7` |
| `RAG_CHAT_BRIEF_PREGEN_BATCH_SIZE` / `CONCURRENCY` | — | `50` / `4` |

**All brief-pipeline env vars are present.** The historical gitops gap (missing `RAG_CHAT_SERVICE_ACCOUNT_TOKEN` → worker minted no service JWT → S1/S5/S6/S7 returned 401 → empty *morning* briefs, the PLAN-0094 W2 / BP-303-variant failure documented in the worker docstring) is **now closed** — the token is set and the scheduler logs `brief_scheduler_token_minted {mint_path: "service-token"}`.

**No env var is the current cause of `has_ai_brief=false`.** There is no env var that, if set, would make entity briefs appear, because nothing writes them.

---

## 5. Root cause + remediation

### Root cause (definitive)
`has_ai_brief` depends on `user_briefs` rows with `brief_type='entity'`, but the system has **no producer** of such rows. The instrument-brief feature is purely read-through (generate-and-return), never persisted. The flag and the screener column are therefore dead-on-arrival universe-wide. This is a missing-implementation gap, not config and not data.

### Fix (code change required — outside this read-only investigation)
Persist instrument briefs when generated. Concretely, in `GenerateBriefingUseCase.execute_public_instrument()` (`generate_briefing.py:706`), after building the result, fire the same best-effort `archive.save()` pattern used by `execute()`, but with:

```python
UserBriefRecord(
    id=new_uuid7(),
    user_id=<requesting user or system uuid>,
    tenant_id=<tenant or system uuid>,
    brief_type="entity",            # <-- the missing piece
    entity_id=UUID(entity_id),      # <-- the missing piece
    generated_at=utc_now(),
    headline=(lead or content or "")[:500],
    lead=lead,
    sections_json=_sections_json,
    citations_json=_citations_json,
    confidence=confidence,
    source_version="v2",
)
```

Caveat: `execute_public_instrument` currently takes no `user_id`/`tenant_id`, and the scheduler's `briefing_uc` is wired with `brief_archive=None` (Valkey-only). To populate `has_ai_brief` proactively (so the nightly rollup sees coverage) you would also need a **scheduled instrument-brief pregen job** that iterates instruments and persists entity briefs — that job does not exist today. The simplest first step is to persist on the on-demand route (then any instrument a user views gets a flag); a fuller fix adds an instrument pregen worker analogous to the morning one.

Important `entity_id` semantics: the flag matches `entity_id == instrument_id`. The instrument-brief route comment (`public_briefings.py:461-464`) notes a market-data `instrument_id` is NOT a KG `entity_id`; ensure whatever ID is persisted is the same `instrument_id` the screener uses, or the join will silently miss.

### Secondary (independent) fix — live morning briefs
DeepInfra returns **402 Payment Required**. Top up / rotate the DeepInfra account (the key itself is valid and set; this is a billing/credit exhaustion, like the 2026-06-17 key-revocation episode). Until then ALL brief generation (morning and instrument) fails at the LLM step, so even after the persistence fix above no entity brief could be generated.

### To generate a test brief once code is fixed
- Ensure DeepInfra has credit (resolve the 402).
- Hit `GET /api/v1/briefings/instrument/{entity_id}` for a known KG entity; with the persistence patch it writes a `brief_type='entity'` row.
- Run the market-data intelligence rollup (or wait for the nightly loop); `has_ai_brief` flips to `true` for that instrument.

---

## Evidence index
- Flag query: `services/rag-chat/src/rag_chat/application/use_cases/ai_brief_flag.py:57-71`
- Only `user_briefs` writer (hardcoded morning): `services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py:640-660`
- Instrument brief, no persist: `services/rag-chat/src/rag_chat/application/use_cases/generate_briefing.py:706-813`
- Instrument route, no persist: `services/rag-chat/src/rag_chat/api/routes/public_briefings.py:456`
- Morning pregen → Valkey only: `services/rag-chat/src/rag_chat/application/workers/morning_brief_pregeneration_worker.py:314-328`
- Scheduler (only morning job): `services/rag-chat/src/rag_chat/infrastructure/scheduling/brief_scheduler_main.py:253-269`
- MD sync (correct consumer): `services/market-data/src/market_data/application/use_cases/sync_intelligence_rollup.py:300-303`
- Live DB: `rag_db.user_briefs` (85 morning / 0 entity); `market_data_db.instrument_fundamentals_snapshot` (669 / 0 true)
- Live logs: `worldview-rag-chat-brief-scheduler-1` — DeepInfra 402, ProviderUnavailableError
