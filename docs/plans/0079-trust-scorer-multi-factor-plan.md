# PLAN-0079 — TrustScorer Multi-Factor Replacement of `DEFAULT_TRUST_WEIGHTS`

> **PRD**: derived from `/investigate` 2026-05-07 — long-term consistency review (issue A-2)
> **Status**: in-progress (Wave A ✅ done 2026-05-07)
> **Created**: 2026-05-07
> **Owner**: TBD
> **Estimated effort**: ~2 dev-days (3 waves, ~9 tasks)
> **Critical path**: Wave A → Wave B → Wave C
> **Hard dependencies**: PLAN-0063 W5-3 ≥0.03 NDCG@10 regression gate (120-query golden set) — Wave B merge blocked until eval passes (see §3)
> **Blocks**: PLAN-0067 W11-2 (manifest no longer carries `trust_weight`); PLAN-0075 W7-3 (L2 tool-selection eval consumes `TrustScorer.score()` output)

## Wave Status

| Wave | Title | Status | Committed |
|------|-------|--------|-----------|
| A | Domain: `TrustScorer` + `SOURCE_AUTHORITY` + `extraction_confidence` field + unit tests | ✅ done | 2026-05-07 |
| B | Replace `DEFAULT_TRUST_WEIGHTS` call sites in `ParallelRetrievalOrchestrator` | ✅ done | 2026-05-07 |
| C | Tunable weights via env vars + eval sweep harness | pending | — |

---

## §0 Why this plan exists

Today's ranking trust weights live in a flat dict in `services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py` (line 46):

```python
DEFAULT_TRUST_WEIGHTS: dict[str, float] = {
    "sec_10k": 0.95, "sec_10q": 0.95, "sec_8k": 0.90,
    "earnings_data": 0.95, "corporate_action": 0.90,
    "eodhd_news": 0.70, "finnhub_news": 0.65,
    "relation": 0.85, "claim": 0.80, "financial": 0.90,
    "default": 0.60,
}
```

PLAN-0067's per-tool `trust_weight` (in `capability_manifest.yaml`) is a *second*, drift-prone table for the same concept. For Bloomberg-grade ranking the static lookup is too coarse — a 5-year-old 10-K should not be trusted equally with yesterday's, and corroboration across N independent sources should reinforce trust.

This plan replaces the flat lookup with `TrustScorer`: a per-item composite of source authority × recency decay × corroboration × extraction confidence.

> **BP-405 Name Verification** (run before implementing each wave):
> - `DEFAULT_TRUST_WEIGHTS` — confirmed exists at `services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py:46`. This is the authoritative single location to replace.
> - `SOURCE_AUTHORITY` — does NOT yet exist anywhere in the codebase (`git grep` returns no results in `libs/` or `services/`). Wave A creates it fresh in `libs/contracts/src/contracts/trust/__init__.py` (new module — see §1 Wave A note).
> - `TrustScorer` — does NOT yet exist in the codebase. Wave A creates it in `services/rag-chat/src/rag_chat/application/pipeline/trust_scorer.py`.
> - `recency_score` — `RetrievedItem.recency_score` is a **pre-computed field** set by `RetrievedItem.create()` (W5-4 of PLAN-0063 added source-specific recency decay via `compute_recency_score`). `TrustScorer` MUST read `item.recency_score` directly rather than re-computing decay — duplicating the decay formula would create a split source of truth and undo PLAN-0063 W5-4. The `recency_decay` factor in the formula below maps to `item.recency_score`.
> - `corroboration_factor` — no `evidence_count` field exists on `RetrievedItem`. For `relation`-sourced items, `evidence_count` is available on `RelationResult` but is NOT carried into `RetrievedItem` today. For all other item types, `corroboration_factor` defaults to 0.5. Wave A must decide: (a) add `evidence_count: int = 0` to `RetrievedItem`; or (b) accept default 0.5 for MVP. Recommended: option (b) for MVP, with a TODO comment pointing at this plan item — avoids a `RetrievedItem` schema change that would cascade into many tests.
> - `extraction_confidence` — exists as a field on `ClaimResult` (`libs/contracts/src/contracts/events/nlp/signal_detected.py:35`) and `EventResult`. It does NOT exist on `RetrievedItem`. For chunk/relation/financial items, `item.score` (the retrieval relevance score) is the best proxy; for claim items, `ClaimResult.extraction_confidence` is available. Wave A should add `extraction_confidence: float | None = None` to `RetrievedItem` so callers can forward the value when available, falling back to `item.score` when `None`.

---

## 1. The Scoring Model

```
trust(item) = w_source       · source_authority(item.source_type)
            ·                  item.recency_score          ← already computed (PLAN-0063 W5-4)
            · w_corroboration · corroboration_factor(item)
            · w_extraction   · extraction_confidence(item)
```

All factors in [0, 1]. Initial weights `(w_source, w_corroboration, w_extraction) = (0.4, 0.1, 0.1)` plus implicit recency (recency is multiplicative, not weighted, via the existing `item.recency_score`). Tuned via PLAN-0063 W5-7 sweep.

| Factor | Source | Computation |
|---|---|---|
| `source_authority` | static `SOURCE_AUTHORITY` table (the rebadged `DEFAULT_TRUST_WEIGHTS`, single source of truth) | SEC primary 1.00 / SEC amendments 0.92 / earnings transcripts 0.92 / vetted wires (Reuters, Bloomberg, FT, WSJ) 0.85 / sell-side research 0.80 / general news (Yahoo, etc.) 0.65 / social/forum 0.30 / user-generated 0.20 / fallback 0.50 |
| `recency_decay` | `item.recency_score` (pre-computed by `RetrievedItem.create()` — PLAN-0063 W5-4, source-specific) | Use `item.recency_score` directly; do NOT re-compute. τ already varies by source via `_RECENCY_DECAY_RATES` in `fusion.py`. |
| `corroboration_factor` | `item.evidence_count` (MVP: not yet on `RetrievedItem` — default 0.5) | `1 - exp(-evidence_count / 3)`; saturates ~0.95 at 10+; default 0.5 when field absent. Wave A decision: add `RetrievedItem.evidence_count: int = 0` or accept 0.5 default for MVP (recommended for MVP). |
| `extraction_confidence` | `item.extraction_confidence` (new nullable field on `RetrievedItem`) | Direct field when set; `item.score` as proxy when `None`. |

## 2. Scope

| Wave | Title | Layer | Effort |
|------|-------|-------|--------|
| A | Domain: `TrustScorer` class + `SOURCE_AUTHORITY` constant in `libs/contracts`; extend `RetrievedItem` with `extraction_confidence: float \| None = None`; unit tests for each factor independently and composed | application + contracts | 6 hours |
| B | Replace `DEFAULT_TRUST_WEIGHTS.get(...)` call sites in `ParallelRetrievalOrchestrator` with `self._trust_scorer.score(item)`; assert PLAN-0063 120-query golden eval scores within 0.03 NDCG@10 of post-hybrid baseline before merge | application | 6 hours |
| C | Tunable weights (`w_source`, `w_corroboration`, `w_extraction`) via env vars; add `--mode trust_sweep` to PLAN-0063's `scripts/eval_retrieval.py` harness; remove per-tool `trust_weight` entries from `capability_manifest.yaml` | tooling | 4 hours |

## 3. Hard Constraints

- **Single source of truth** (R11 forward-compat): `SOURCE_AUTHORITY` lives in `libs/contracts/src/contracts/trust/__init__.py` as a module-level `dict[str, float]` constant — the same name and location referenced from `TrustScorer` and any future tool plan. PLAN-0067 manifest entries reference `source_type` only — no `trust_weight` in YAML (per R29 note added in RULES.md).
- **Eval gate** (PLAN-0063 dependency): replacing the flat lookup must not regress the **120-query** golden eval (PLAN-0063 v2 revised the set from 60 → 120 queries; the gate threshold is ≥0.03 NDCG@10 regression from the `results/baseline_pre_hybrid.json` anchor). The phrase "60-query parity" in earlier documentation is stale — the canonical gate is the 120-query set captured in `tests/eval/golden/`. If regression occurs, tune weights in Wave C before merge; do not lower the gate (R19 equivalent for eval).
- **Backwards-compatible at the call site** (R11): `RetrievedItem.trust_weight` field remains (no removal). `TrustScorer.score(item)` populates it in-place on the fusion path. No callers further down the pipeline (context assembler, prompt builder, persistence) change.
- **No cross-layer imports** (R25): `TrustScorer` is a domain/application class with no infrastructure imports. `SOURCE_AUTHORITY` is a pure constant in `libs/contracts` (no DB, no Kafka, no HTTP). Wave B wires `TrustScorer` into `ParallelRetrievalOrchestrator` (application layer) — this is permitted.
- **structlog only**: `TrustScorer` and any scoring helpers must use `observability.get_logger(__name__)` for debug-level score logging — never stdlib `logging`.
- **R10 — no new IDs**: `TrustScorer` is a stateless value object; it generates no entity IDs. No UUIDs needed.
- **R11 — UTC timestamps**: any `published_at` comparison inside `TrustScorer` must treat naive datetimes as UTC (match PLAN-0063 W5-4's `compute_recency_score` convention).

## 4. Cross-cutting

- New env vars: `RAG_CHAT_TRUST_W_SOURCE` (default `"0.4"`), `RAG_CHAT_TRUST_W_CORROBORATION` (default `"0.1"`), `RAG_CHAT_TRUST_W_EXTRACTION` (default `"0.1"`). Add to `RagChatSettings` and `docker-compose*.yml`. Note: τ per source is owned by `_RECENCY_DECAY_RATES` in `fusion.py` (PLAN-0063 W5-4) — do NOT duplicate τ in `TrustScorer` env vars.
- Documentation: `docs/services/rag-chat.md` adds a Trust Model section explaining the formula, factors, and env vars.
- Test: assert that for a synthetic SEC 10-K from yesterday vs. 5 years ago, the recent doc scores higher (recency factor dominant). Assert that a claim with `extraction_confidence=0.9` beats one with `extraction_confidence=0.3` at same recency/source.
- **`libs/contracts` module structure**: create `libs/contracts/src/contracts/trust/__init__.py` containing `SOURCE_AUTHORITY: dict[str, float]`. Add to `libs/contracts/src/contracts/__init__.py` exports. The contracts package already has `pyproject.toml` and test structure — follow the existing pattern.

## 5. Out of scope

- Per-source-name overrides (Bloomberg-specific tuning) — defer.
- Time-of-day decay correction — defer.
- User feedback signal incorporation (would feed `corroboration` over time) — captured in PLAN-0075 (eval framework) instead.
- `RetrievedItem.evidence_count` field addition — deferred to a follow-up wave or PLAN-0067 (recommended MVP: use default 0.5 for corroboration factor).

---

*Stub generated 2026-05-07 by `/investigate`. Architecture compliance pass applied 2026-05-07 (BP-405 name verification; 60-query → 120-query eval gate corrected; recency_decay/corroboration/extraction_confidence field gaps documented; SOURCE_AUTHORITY module path specified; R25/R10/R11/R29/structlog guardrails added).*
