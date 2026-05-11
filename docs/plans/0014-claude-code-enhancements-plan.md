---
id: PLAN-0014
title: "Claude Code Source Adaptations — Tier 2 Enhancements"
status: pending
prd: investigation-report-2026-04-01
created: 2026-04-01
updated: 2026-04-01
author: /investigate + /implement skills
scope: ".claude/skills, services/rag-chat (S8), libs/messaging, scripts/hooks"
depends_on: ["PLAN-0013"]
---

# PLAN-0014 — Claude Code Source Adaptations: Tier 2 Enhancements

**Status**: pending
**Created**: 2026-04-01
**Depends on**: PLAN-0013 complete
**Source**: Investigation of open-sourced Claude Code source (`src/`) — 2026-04-01

---

## Background

On 2026-03-30 the Claude Code source was made public. An investigation (`/investigate`, 2026-04-01) identified four Tier 2 adaptations from Claude Code's architecture that directly benefit worldview. Tier 1 and Tier 3 items were implemented in the same session (see commit history).

This plan covers the four Tier 2 items that require more design work or depend on services not yet built.

---

## Tier 2 Items (ordered by dependency)

| ID | Title | Depends on | Effort |
|----|-------|-----------|--------|
| T2-D | Hook complexity guard | none | light |
| T2-B | Subagent permission isolation | none | medium |
| T2-C | Agent memory scopes (local/project split) | none | medium |
| T2-A | S8 RAG query pipeline — recovery paths | S8 service scaffold | heavy |

---

## Sub-Plan A: Hook & Skill Infrastructure (T2-D + T2-B)

### Wave A-1: Hook Complexity Guard (T2-D) — pending

**Motivation**: Claude Code caps bash security analysis at 50 subcommands before falling back to a safe `ask` default. Worldview's `security-scan.sh` has no such guard — on large commits it scans all files and can time out (30s limit).

**Tasks:**

| ID | Task | File |
|----|------|------|
| A1-001 | Add MAX_FILES guard to security-scan.sh: if staged Python files > 50, emit JSON `{"rejection": "Too many files (N) for automated scan — run manually: ..."}` and exit 2 with suggestion to run targeted scan | `scripts/hooks/security-scan.sh` |
| A1-002 | Add MAX_FILES guard to post-edit-validate.sh: if the service has > 50 Python files, run only the directly-edited file's tests rather than the full test suite | `scripts/hooks/post-edit-validate.sh` |
| A1-003 | Add structured JSON output to migration-guard.sh (same pattern as pre-commit): emit `{"rejection": "Migration needed for <table>: run /migrate-db"}` | `scripts/hooks/migration-guard.sh` |

**Acceptance criteria:**
- [ ] `bash -n` passes on all three hooks
- [ ] security-scan.sh exits 2 with valid JSON when >50 files staged
- [ ] migration-guard.sh outputs valid JSON rejection with fix command
- [ ] No regression on hooks with <50 files

---

### Wave A-2: Subagent Permission Isolation (T2-B) — pending

**Motivation**: Claude Code explicitly scopes tool permissions per subagent — parent-granted permissions (e.g., `Bash(git push:*)`) do NOT leak to child agents. Worldview's `/qa` skill spawns 5 parallel agents that currently inherit the parent's full permission set.

**Tasks:**

| ID | Task | File |
|----|------|------|
| A2-001 | Define `READ_ONLY_TOOLS` constant: tools the parallel QA agents are allowed to use (Read, Glob, Grep, Bash(read-only), no Write/Edit) | `.claude/skills/qa/SKILL.md` |
| A2-002 | Update `/qa` skill: document that Agent spawning for QA specialists must pass `isolation: "worktree"` and restrict tool access in the agent prompt | `.claude/skills/qa/SKILL.md` |
| A2-003 | Update `/implement` skill: when spawning parallel task agents (Wave 2.0), pass explicit tool allowlist scoped to the task's write_paths | `.claude/skills/implement/SKILL.md` |
| A2-004 | Document permission isolation pattern in `AGENTS.md` — add a "Subagent Tool Scoping" section | `AGENTS.md` |

**Acceptance criteria:**
- [ ] `/qa` skill documentation specifies worktree isolation for specialist agents
- [ ] `/implement` parallel execution documentation specifies write_paths-scoped tool access
- [ ] No breaking changes to existing skill workflows

---

## Sub-Plan B: Memory System Enhancements (T2-C)

### Wave B-1: Agent Memory Scopes — pending

**Motivation**: Claude Code supports three memory scopes: `user` (cross-project, `~/.claude/`), `project` (in-repo, `.claude/`), and `local` (gitignored). Worldview currently has only `project` scope. Investigation findings noted that local scope (gitignored) would be valuable for in-progress investigation notes.

**Tasks:**

| ID | Task | File |
|----|------|------|
| B1-001 | Create `memory/local/` directory (gitignored): for ephemeral investigation and debugging notes that should not be committed | `memory/local/.gitkeep`, update `.gitignore` |
| B1-002 | Update `MEMORY.md` References section: add entry for `memory/local/` explaining its purpose | `memory/MEMORY.md` |
| B1-003 | Update `/investigate` skill: add a "Memory Scope" section — findings go to `memory/local/` during investigation, promoted to `project` scope only on explicit user request | `.claude/skills/investigate/SKILL.md` |
| B1-004 | Update `scripts/memory_staleness_scan.py`: skip `memory/local/` from staleness scan (ephemeral by design) | `scripts/memory_staleness_scan.py` |
| B1-005 | Add `memory/local/` to `.gitignore` | `.gitignore` |

**Acceptance criteria:**
- [ ] `memory/local/` exists and is gitignored
- [ ] `/investigate` skill documents when to use local vs project scope
- [ ] `memory_staleness_scan.py` skips `memory/local/`
- [ ] `python3 scripts/memory_staleness_scan.py` passes

---

## Sub-Plan C: S8 RAG Query Pipeline Recovery (T2-A)

**Depends on**: S8 service scaffolded (via `/scaffold-service`) and PLAN-0001-D PRD written.

### Wave C-1: RAG Context Budget Design — pending

**Motivation**: Claude Code's `queryLoop()` has a 4-stage compaction cascade when the context budget runs low: snip-oldest → microcompact-middle → context-collapse → autocompact. S8's LLM completion handler needs an equivalent cascade for chunk selection when retrieved context exceeds the LLM's context window.

**Design target** (to be elaborated in PLAN-0001-D PRD):

```
S8 RAG context management:

Retrieved chunks (N) → ranked by relevance score
  ↓
Stage 1 (snip): drop chunks with score < threshold until tokens ≤ budget
  ↓ (if still over budget)
Stage 2 (microcompact): summarize mid-ranked chunks (keep intro + conclusion sentences)
  ↓ (if still over budget)
Stage 3 (context-collapse): extract key sentences from all chunks
  ↓ (if LLM returns max_tokens error)
Stage 4 (retry): halve chunk count, retry with same question

Carry CompletionBudgetState across multi-turn chat (don't re-summarize same chunk twice)
```

**Tasks:**

| ID | Task | File |
|----|------|------|
| C1-001 | Define `ChunkBudgetState` domain entity in S8: tracks which chunks have been summarized (prevents re-summarization across turns) | `services/rag-chat/src/rag_chat/domain/entities/chunk_budget_state.py` |
| C1-002 | Implement `ChunkSelector` application service: takes N retrieved chunks + token budget, returns ranked selection applying 4-stage cascade | `services/rag-chat/src/rag_chat/application/use_cases/select_chunks.py` |
| C1-003 | Implement `ChunkSummarizer` using `libs/ml-clients` LLM adapter: summarizes a list of chunks to fit a token budget | `services/rag-chat/src/rag_chat/application/use_cases/summarize_chunks.py` |
| C1-004 | Wire `ChunkSelector` into the RAG completion route: inject before LLM call, retry on `max_tokens` response | `services/rag-chat/src/rag_chat/api/v1/chat.py` |
| C1-005 | Unit tests for `ChunkSelector`: all 4 cascade stages, multi-turn budget state persistence | `services/rag-chat/tests/unit/test_chunk_selector.py` |

**Acceptance criteria:**
- [ ] `ChunkSelector` handles 0, 1, N chunks without error
- [ ] All 4 cascade stages trigger correctly at budget thresholds
- [ ] `ChunkBudgetState` prevents double-summarization
- [ ] Unit tests pass (no LLM required — mock summarizer)
- [ ] S8 `/chat` endpoint returns 200 even when context overflows

---

### Wave C-2: S9 Memoized Query Caching — pending

**Motivation**: Claude Code's `getUserContext` and `getSystemContext` are memoized by CWD to avoid expensive re-computation. S9 makes repeated queries for portfolio state, entity metadata, and watchlist config — these should use Valkey caching with TTLs aligned to data change frequency.

**Tasks:**

| ID | Task | File |
|----|------|------|
| C2-001 | Define cache key taxonomy for S9 in `docs/services/api-gateway.md`: `portfolio:{user_id}:state`, `entity:{entity_id}:metadata`, `watchlist:{user_id}:list` | `docs/services/api-gateway.md` |
| C2-002 | Implement `S9CacheManager`: wraps `ValkeyClient`, provides typed get/set/invalidate with TTLs | `services/api-gateway/src/api_gateway/infrastructure/cache/cache_manager.py` |
| C2-003 | Wire cache invalidation: subscribe to `portfolio.changed.v1`, `graph.state.changed.v1` Kafka topics → invalidate affected keys | `services/api-gateway/src/api_gateway/infrastructure/kafka/cache_invalidation_consumer.py` |
| C2-004 | Unit tests: TTL expiry, cache-miss fallback, invalidation on event | `services/api-gateway/tests/unit/test_cache_manager.py` |

**Acceptance criteria:**
- [ ] S9 cache hit rate measurable via Prometheus metrics
- [ ] Cache invalidation fires within 1 Kafka message of portfolio/graph change
- [ ] Tests pass with fakeredis

---

## Validation Gates

| Wave | Gate |
|------|------|
| A-1 | `bash -n` on all hooks; manual smoke test with >50 and <50 files |
| A-2 | No regression on `/qa` and `/implement` workflows |
| B-1 | `memory_staleness_scan.py` passes; `memory/local/` in .gitignore |
| C-1 | All `test_chunk_selector.py` unit tests pass; no LLM required |
| C-2 | All `test_cache_manager.py` unit tests pass with fakeredis |

---

## Notes

- **C-1 and C-2 are blocked** until S8 and S9 are scaffolded. Use `/scaffold-service` first.
- **A-1 and B-1 are unblocked** — can be done independently after PLAN-0013 completes.
- This plan should be revisited when PLAN-0001-D (S9 API Gateway PRD) is written — C-2 tasks may move there.
