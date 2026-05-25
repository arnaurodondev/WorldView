---
id: INV-LIVE-JKLM
title: PLAN-0093 Phase 5c+1 — Investigation of 4 Live-Only Findings (J/K/L/M)
date: 2026-05-24
predecessor: docs/audits/2026-05-24-qa-plan-0093-phase-5c-reqa-results.md
branch: feat/plan-0093-remediation
investigators: 4 parallel Explore agents
status: ready_for_fix_orchestration
---

# Phase 5c+1 — Investigation Report (F-LIVE-J/K/L/M)

## TL;DR

| Finding | Severity | Root cause | Fix size | Same-fix as |
|---|---|---|---|---|
| **F-LIVE-J** | BLOCKING | `chat_orchestrator.py:914-923` injects tool results with `role: "user"` (single concatenated message) instead of per-call `role: "tool"` + `tool_call_id`. DeepInfra rejects per OpenAI spec. | ~10 lines | — |
| **F-LIVE-K** | CRITICAL | `chat()` and `chat_stream()` routes never call `set_current_jwt()` — JWT ContextVar empty when tool handlers execute → `BaseUpstreamClient._get()` sends no `X-Internal-JWT` → S7 returns 401. | ~6 lines | — |
| **F-LIVE-L** | CRITICAL | Same as K (`traverse_graph` and `get_entity_paths` go through the same `BaseUpstreamClient` / `S7IntelligencePort` chain). The "missing required tool" string comes from the grader after the orchestrator emits HTTP_ERROR. | 0 lines (resolved by FIX-K) | FIX-K |
| **F-LIVE-M** | MAJOR | `screen_universe` tool advertises `sector` only; NVDA/AMD/AVGO are GICS-tagged `sector=Technology, industry=Semiconductors`. No `industry` filter exists end-to-end (handler → tool registry → API schema → repo → query). | ~20 lines across 5 files | — |

3 distinct fix agents needed (J, K+L, M). Re-QA expected to push verdict from FAIL → PASS_WITH_NOTES.

---

## F-LIVE-J — DeepInfra tool-result follow-up (BLOCKING)

### Root cause (precise)

`services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py:914-923`:

```python
messages.append(
    {
        "role": "user",  # ← WRONG: should be "tool"
        "content": (
            "Here is the data retrieved by the tools:\n\n"
            + _context_block[:_TOOL_RESULT_MAX_CHARS]
            + "\n\nPlease answer the original question using this data."
        ),
    }
)
```

The OpenAI / DeepInfra Chat Completions spec requires that after an `assistant` message containing `tool_calls`, each tool result MUST be sent as a separate message with `role: "tool"` AND `tool_call_id: <matching id from tool_calls>`. The current code collapses N tool results into one `role: "user"` blob with no `tool_call_id`, so DeepInfra responds: `missing required tool from ['get_fundamentals_history']; got []`.

### Why Q3 worked, Q4 failed

Q3 (Tim Cook narrative) calls a single tool whose result is the final answer (often no second LLM turn). Q4 calls TWO tools (`get_fundamentals_history(NVDA, 4)` + `get_fundamentals_history(AMD, 4)`) and ALWAYS needs a second turn to synthesise the comparison — which is exactly the codepath that violates the spec.

### Patch

Replace lines 914-923 with one `role: "tool"` message per tool call, each carrying the matching `tool_call_id`. Per-call content should be the tool's individual stringified result (so the orchestrator must also stop pre-concatenating into `_context_block` and instead keep per-tool results separately). Tool-use blocks are obtained via `getattr(tc, "tool_use_id", tc.name)` from the `tool_calls: list[ToolUseBlock]` already in scope at line 559.

### Validation
- Re-fire Q4 v1: expect 2 tool calls + successful second-turn LLM + grounded numeric answer (no `$15B` fabrication).
- Q4 v2 / v6 / weak-point survey: should all unblock.
- Zero-HARMFUL gate: should pass.

---

## F-LIVE-K — Q7 401 contradictions (CRITICAL)

### Root cause (precise)

`services/rag-chat/src/rag_chat/infrastructure/middleware/internal_jwt.py:168-172` sets the JWT into a ContextVar via `set_current_jwt(token)` inside the middleware's `_post_validate()` hook. `services/rag-chat/src/rag_chat/infrastructure/clients/base.py` (`BaseUpstreamClient._get()`, lines 62-96) reads `get_current_jwt()` and forwards it as `X-Internal-JWT` to downstream services (S6/S7/S3/S1).

**BUT**: the `chat()` (line 54-96) and `chat_stream()` (line 99-154) routes in `services/rag-chat/src/rag_chat/api/routes/chat.py` never call `set_current_jwt()` explicitly. They rely on the middleware to do it. In contrast, `entity_context_chat()` (line 185) and `public_briefings.py:177-186` DO call it explicitly — and they work. The middleware path appears to lose the ContextVar across the async boundary into the tool executor.

When tool handlers (e.g., `get_contradictions` via `S7Client`) hit `BaseUpstreamClient`, `get_current_jwt()` returns empty → no `X-Internal-JWT` header → KG endpoint returns 401.

### Patch

In `services/rag-chat/src/rag_chat/api/routes/chat.py`, add after the auth-tuple unpack in BOTH `chat()` and `chat_stream()`:

```python
from rag_chat.infrastructure.clients.auth_context import set_current_jwt
set_current_jwt(request.headers.get("X-Internal-JWT"))
```

### Blast radius
ALL upstream-calling tools are affected, not just `get_contradictions`. Why other Q's appeared to work: many returned cached responses (FIX-LIVE-A invalidated those), or used Valkey-cached data, or returned empty silently (`[]` on exception). Once cache was invalidated and FIX-LIVE-D restored gateway routing, the latent 401s surfaced.

### Validation
- Q7 returns 200 with contradictions data.
- Q8 (traverse_graph) — see F-LIVE-L below — also unblocked by the same fix.

---

## F-LIVE-L — Q8 traverse_graph regression (CRITICAL)

### Root cause

`traverse_graph` is implemented in `handlers/intelligence.py:288-380` and calls `S7Port.cypher_traverse()` via `BaseUpstreamClient`. `get_entity_paths` is in `handlers/narrative.py:142-193` and calls `S7IntelligencePort.get_entity_paths()` via the same chain. Both swallow exceptions and return `[]` on failure (silent degradation).

When the JWT ContextVar is empty (root cause of F-LIVE-K), both tools' HTTP calls 401 silently — the handlers return `[]`, the orchestrator emits HTTP_ERROR, and the grader produces the "missing required tool from ['traverse_graph', 'get_entity_paths']; got []" message. **This is the same root cause as F-LIVE-K.**

### Patch
None separate — resolved by FIX-LIVE-K. Validation re-fires Q8 specifically to confirm.

### Note
The investigation agent ranked HTTP-error vs LLM-no-tool as ambiguous, but the most parsimonious explanation given (a) FIX-LIVE-K is fixing the same auth pattern, (b) cache invalidation surfaced this, and (c) handlers silent-degrade on auth exceptions — is that K and L share a root cause.

---

## F-LIVE-M — Q6 screener 0 tickers (MAJOR)

### Root cause (precise)

The `screen_universe` tool only advertises a `sector` parameter to the LLM. NVDA, AMD, AVGO, TSM in the live DB are GICS-tagged `sector="Technology", industry="Semiconductors"`. So `sector="Semiconductors"` returns 0 rows; `sector="Technology"` returns the entire tech sector (thousands) which the LLM/screener can't usefully narrow without `industry`.

The `industry` column exists in the `instruments` table but no filter path uses it: not the repo's `ScreenFilter` dataclass, not `query_screen()`, not the API's `ScreenFilterRequest`, not the rag-chat handler `_handle_screen_universe`, not the tool registry's `ParameterSpec`.

### Patch (5 files)

1. `services/market-data/src/market_data/application/ports/repositories.py` — add `industry: str | None = None` to `ScreenFilter` (line ~58).
2. `services/market-data/src/market_data/infrastructure/db/repositories/fundamental_metrics_query.py` — after line 269 (sector filter), add the parallel `industry` WHERE clause.
3. `services/market-data/src/market_data/api/schemas/fundamental_metrics.py` — add `industry: str | None = None` to `ScreenFilterRequest` (line ~35).
4. `services/market-data/src/market_data/api/routers/fundamental_metrics.py` — pass `industry=f.industry` into `ScreenFilter` (line ~172).
5. `services/rag-chat/src/rag_chat/application/pipeline/tool_registry_builder.py` — add `ParameterSpec(name="industry", ...)` after line 673.
6. `services/rag-chat/src/rag_chat/application/pipeline/handlers/market.py` — add `industry: str | None = None` to `_handle_screen_universe` signature (line ~264) and propagate into `filters` dict (line ~287).

Optional prompt hint in `libs/prompts/src/prompts/chat/tool_use.py`: "Use `sector='Technology'` + `industry='Semiconductors'` for AI chip queries (GICS taxonomy)."

### Validation
Q6 expected to surface NVDA/AMD/AVGO/INTC/QCOM/TSM/MU.

---

## Sequencing

All three fix agents have non-overlapping file scopes and can run in parallel:

- **FIX-LIVE-J**: `chat_orchestrator.py` only
- **FIX-LIVE-K+L**: `api/routes/chat.py` only
- **FIX-LIVE-M**: market-data backend + rag-chat tool layer (no orchestrator overlap)

After all three land, re-QA expectation:
- Q4 v1 / v2 / v6: PASS (FIX-J)
- Q7: PASS (FIX-K)
- Q8: PASS (FIX-K resolves L)
- Q6: PASS or MARGINAL (FIX-M)
- Zero-HARMFUL gate: PASS

Estimated total work: ~3 hours fix + ~1 hour re-QA.

---

## Compounding candidates (to be added in a follow-up commit)

- **BP-NEW**: Provider-spec compliance for tool-result follow-up — every LLM client adapter must inject results as `role: "tool"` with matching `tool_call_id`. Add an integration test that asserts the second-turn message shape.
- **BP-NEW**: ContextVar lifecycle across middleware → route handler — middleware-set ContextVars may not survive into nested async tasks; routes that spawn background tool execution should re-set them explicitly. Existing pattern (`entity_context_chat` + `public_briefings`) should be enforced repo-wide.
- **BP-NEW**: Silent-degrade handlers (return `[]` on any exception) hide auth failures — classify exceptions in handlers (auth vs upstream-down vs not-found) and surface auth as a distinct `tool_unauthorised` error.
- **BP-NEW**: GICS-style sector/industry taxonomy — tool definitions exposing only `sector` to LLMs cannot satisfy narrow-industry queries; always expose both with a doc hint.
- **HR-NEW**: Cached responses can hide upstream auth/wiring regressions for weeks. Invalidating cache (FIX-LIVE-A) was correct AND necessary AND surfaced 3 latent prod-grade bugs.
