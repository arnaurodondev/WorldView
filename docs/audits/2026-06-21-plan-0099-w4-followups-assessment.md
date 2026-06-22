# PLAN-0099 W4 Follow-ups — Integration Assessment

**Date:** 2026-06-21
**Branch under review:** `feat/plan-0099-w4-followups`
**Target branch (HEAD):** `feat/md-reliability-followups` @ `e8123dc73`
**Merge-base:** `ff32d6195` (`fix(rag-chat): synthesis-turn quality …`)
**Mode:** READ-ONLY investigation (git read/log/diff/show + trial cherry-picks, all aborted/reset). No mutations.

---

## TL;DR / VERDICT

**Do NOT rebase the whole branch. Cherry-pick a curated subset; drop the rest as superseded or moot.**

The branch is linear from the merge-base (`ff32d6195`), which HEAD also contains, so a rebase is mechanically possible — but HEAD has independently evolved the two hot areas this branch targets, taking **different, already-shipped solutions** to the same problems:

- **Intelligence bundle (`routes/intelligence.py`)**: HEAD has 8 commits since merge-base (1090→1418 LOC: PLAN-0112 pathfinding, edge passthrough, BP-486 timeout, Valkey cache). The branch has 2 (1090→1274). HEAD solved the graph_d2 cold-latency problem **differently** than this branch's R1 — so R1 is a *conflicting alternative*, not a complement.
- **Instrument-brief pregeneration (rag-chat)**: HEAD already ships a complete `InstrumentBriefPregenerationWorker` (PLAN-0113, commit `281586e47`) with an `active_instruments` Valkey port. The branch's R4 implements the *same feature* via a different eligibility source (watchlist-union). **Functionally superseded.**

Net worth-taking: **3 commits** (W4-I OHLCV strip, status-page build fix, optionally the R3 prewarmer worker). One commit (recharts) would be a regression. Two are moot/superseded. R1/R2/R4 are conflicting-alternative or superseded.

---

## Per-commit assessment

| # | Commit | What it delivers | Type | Superseded by HEAD? | Conflict cost | Recommendation |
|---|--------|------------------|------|---------------------|---------------|----------------|
| 1 | `d1ae804c9` recharts@2.15.0 | Adds recharts dep + lockfile churn | chore | **YES — HEAD has recharts `3.8.1`** (newer) | Would *downgrade* + lockfile fight | **SKIP (regression)** |
| 2 | `3f1febf75` 6 ESLint unused-var fixes | Removes unused imports/vars to unblock docker build | chore | **Largely MOOT** — the 4 target files diverged on HEAD; the referenced symbols (`useState`, `formatDateTime`, `userEvent`, `qk`) no longer exist as live code in HEAD (now only in comments) | n/a | **SKIP (already different on HEAD; re-verify `pnpm lint` on HEAD instead)** |
| 3 | `bf2071059` R1 — drop graph_d2 from bundle | Removes the depth-2 AGE leg from the server composite (4.1s→~1.1s cold), sets `graph_d2=None`; frontend hook stops hydrating from null leg | perf | **NO, but CONFLICTING ALTERNATIVE.** HEAD *keeps* graph_d2 and instead parallelised the depth-1 merge as a 6th gather leg + added `asyncio.wait_for(timeout=20.0)` + Valkey 5-min cache (commits `8282f005c`, `e9239f4e6`, `2c451898f`, BP-486) | **HARD CONFLICT** on `routes/intelligence.py` **and** `tests/test_intelligence_bundle.py` (confirmed by trial cherry-pick) | **SKIP (HEAD already solved cold-latency differently; do not regress its cache+timeout design)** |
| 4 | `02c6b297b` R3 — bundle pre-warmer worker (opt-in) | New `bundle_prewarmer_main.py` worker + 7 `prewarm_*` config knobs + compose service; loops hot entity IDs hitting the bundle over HTTP every 240s to keep the Valkey cache warm | feature | **NO** — HEAD has no prewarmer worker or `prewarm_*` config | Clean-ish: `config.py` + new files add cleanly; `docker-compose.yml` **auto-merges** (no conflict in trial) | **TAKE (optional, opt-in, low risk)** — but see Dependencies note: its *value* depends on HEAD's bundle Valkey cache, which HEAD already has, so it's actually *more* compatible with HEAD than with its own R1 base |
| 5 | `a6c05b545` R2 — SSE streaming bundle endpoint + FE hook | New additive `GET /entities/{id}/intelligence-bundle/stream` (StreamingResponse, per-leg `event: leg` SSE, restores graph_d2 as opt-in streamed leg) + `useEntityIntelligenceBundleStream.ts` + tests | feature | **NO** — HEAD has no SSE/streaming bundle and only `useEntityIntelligenceBundle.ts` (non-stream) | **Auto-merges** on `intelligence.py` (purely additive insert, no edit to existing gather). References R1 only in comments, not code | **OPTIONAL TAKE** — works without R1; but it's 1025 LOC of new surface (endpoint + hook + 2 test files) for a feature the frontend doesn't yet consume on HEAD. Defer unless the UX is wanted now |
| 6 | `474e3fcb8` prewarmer compose env fix | JSON-list syntax fix for empty `entity_ids` in compose | bug fix | Only relevant if #5/#3 taken | n/a (folds into R3) | **TAKE *with* R3** (squash into it) |
| 7 | `3046d84af` R4 — instrument-brief pregeneration | Extends `MorningBriefPregenerationWorker` with an instrument phase fed by a **watchlist-union** source: new portfolio `GET /internal/v1/watchlists/all-entity-ids`, new `IWatchlistEntitiesPort`, rag-chat client, config knobs | feature | **YES (functionally).** HEAD ships `InstrumentBriefPregenerationWorker` (`281586e47`) doing the same pre-gen via an **active-instruments Valkey sorted-set** + BP-624 `summary_paragraph` wiring (`210790a3f`) | Would conflict on `morning_brief_pregeneration_worker.py` (HEAD's class has no instrument phase) + `brief_scheduler_main.py` + portfolio `internal.py` (HEAD has 1 commit there too) | **SKIP (superseded).** Only revisit if the *watchlist-union* eligibility model is preferred over HEAD's *recently-viewed* model — a product decision, not a merge |
| 8 | `d9c0bb64b` status page force-dynamic | `export const dynamic = "force-dynamic"` on `/status` to stop build-time prerender fetch hanging on `localhost:3000` | build fix | **NO** — HEAD's status page still does the localhost fetch in a Server Component and lacks force-dynamic | **CLEAN** (trial cherry-pick: zero conflicts) | **TAKE (high value, tiny, safe)** — real docker-build hang fix |
| 9 | `b3fccbcc8` W4-I — strip OHLCV from dashboard batch + paginated OHLCV endpoint | Adds `include_ohlcv` to `CompanyOverviewUseCase` (batch passes `False`, saving 1-3s/instrument); new `GET /v1/instruments/{id}/ohlcv` cursor-paginated (300 default, max 500) | perf + feature | **NO** — HEAD's `CompanyOverviewUseCase` has no `include_ohlcv` (always fetches OHLCV); batch always includes it; HEAD has no paginated OHLCV endpoint | **CLEAN** (trial cherry-pick auto-merged all 3 files, zero conflicts) | **TAKE (high value, clean, real dashboard perf win)** |

---

## 2. Superseded check — how HEAD diverged vs the branch's assumptions

**`routes/intelligence.py` (the conflict file).** The branch was cut when this file was 1090 LOC. HEAD is now 1418 LOC after 8 commits the branch never saw:
- `e9239f4e6` parallelise bundle (5 serial → 6 concurrent legs)
- `8282f005c` Valkey 5-min bundle cache + rel_volume daily fallback
- `2c451898f` / `9e0297d94` BP-486 per-request httpx timeout + 4 hang root-causes (added the `asyncio.wait_for(timeout=20.0)` outer deadline)
- `d805d465a`, `b95dd544a`, `62f8f5699`, `a0f529fe9` PLAN-0089/0112 edge-field passthrough, relation/node detail, pairwise pathfinding, weird-connections feed

Crucially, **HEAD still fetches graph_d2** inside the gather (now as `graph_t` + a concurrent `graph_d1_t` merge leg, lines ~1142-1234) and guards it with a 20s `wait_for` → 504. The branch's R1 deletes that whole block and returns `graph_d2=None`. These are two **mutually exclusive** solutions to the same cold-latency problem; R1 is older and less defensive (no outer timeout, no cache). HEAD's is the keeper.

**rag-chat instrument-brief pregen.** HEAD has the full feature already: `application/workers/instrument_brief_pregeneration_worker.py` (`InstrumentBriefPregenerationWorker`), `application/ports/active_instruments.py`, wired into `infrastructure/scheduling/brief_scheduler_main.py`, gated by `RAG_CHAT_BRIEF_INSTRUMENT_PREGEN_ENABLED`, plus the BP-624 `summary_paragraph` fix. The branch's R4 is the *same intent* (pre-gen instrument briefs to collapse the bundle's brief leg to a cache hit) but uses watchlist-union eligibility and *extends the morning-brief worker* rather than adding a dedicated one. HEAD's design is cleaner (separate worker, separate port). **R4 superseded.**

**recharts.** HEAD `3.8.1` > branch `2.15.0`. Taking the branch commit would downgrade a major version and fight the lockfile. Pure regression.

**ESLint fixes.** The 4 files diverged on HEAD; the specific unused symbols the commit removed are no longer present as live code on HEAD. The build-unblock intent is moot — re-run `pnpm lint` on HEAD to confirm rather than cherry-picking.

---

## 3. Conflict scope + integration cost (trial cherry-picks against HEAD)

| Commit | Trial result |
|--------|--------------|
| `b3fccbcc8` (W4-I) | **CLEAN** — auto-merged 3 files, 0 conflicts |
| `d9c0bb64b` (status) | **CLEAN** — 0 conflicts |
| `02c6b297b` (R3 prewarmer) | **CLEAN-ish** — new files add cleanly, `docker-compose.yml` auto-merges |
| `a6c05b545` (R2 SSE) | **CLEAN** — purely additive endpoint, auto-merges into intelligence.py |
| `bf2071059` (R1 graph_d2 drop) | **HARD CONFLICT** — `routes/intelligence.py` + `tests/test_intelligence_bundle.py` both conflict |

A full rebase would stall on R1's conflict and require manually reconciling R1 against HEAD's cache+timeout+6-leg design (net: throwing R1 away). Per-commit cherry-pick of the curated subset is the correct path — and 4 of the 5 useful commits cherry-pick with **zero conflicts**.

---

## 4. Dependencies & ordering

The R1→R2→R3→R4 narrative builds conceptually, but the **code coupling is loose**:
- **R2 (SSE) does NOT structurally depend on R1.** It only *adds* a new endpoint (no edit to the existing gather) and the new SSE endpoint *restores graph_d2* as an opt-in streamed leg. It references R1 only in comments. Takeable standalone.
- **R3 (prewarmer) does NOT depend on R1.** It calls `/intelligence-bundle` over HTTP, not via import. It actually pairs *better* with HEAD (whose bundle already has a Valkey cache for the prewarmer to populate) than with its own R1 base.
- **`474e3fcb8`** is a fix to R3's compose env — only take it *with* R3 (squash).
- **R4 (instrument-brief)** adds a portfolio internal endpoint + rag-chat port; independent of R1/R2/R3 but superseded by HEAD.

So later commits can be taken without earlier ones. No ordering constraint forces R1.

---

## 5. Risk / blast radius

- **W4-I (`b3fccbcc8`)** — touches the dashboard batch hot path. Low risk: `include_ohlcv` defaults to `True` (single-overview unchanged); only the batch caller opts out. New OHLCV endpoint is additive. **Recommend a quick check that the frontend chart actually calls the new `/instruments/{id}/ohlcv` endpoint** — if nothing consumes it yet on HEAD, the batch OHLCV strip removes data the dashboard may still expect. Verify the FE consumer before/with the take.
- **Status fix (`d9c0bb64b`)** — single line on a public, non-critical page. Negligible risk; clear build benefit.
- **R3 prewarmer** — *new process*. Blast radius gated to **off by default** (`prewarm_enabled=False`); a misbehaving prewarmer can only add load to the bundle endpoint (capped by `prewarm_concurrency=3`). Acceptable as opt-in. Note the original R1 commit message flagged that the *untracked* prewarmer broke mypy by referencing unstaged Settings fields — those fields ship in R3 itself, so taking R3 resolves that.
- **R2 SSE** — additive endpoint + unused FE hook; zero blast radius until something consumes it, but adds 1025 LOC of maintenance surface and a second code path for the same data.
- **R1** — would *reduce* HEAD's resilience (removes the 20s timeout + cache-friendly graph leg). Highest risk if taken; recommend against.

---

## Recommended integration sequence

Cherry-pick, in order, onto `feat/md-reliability-followups`:

1. **`d9c0bb64b`** (status force-dynamic) — clean, tiny, real docker-build fix. Take first.
2. **`b3fccbcc8`** (W4-I OHLCV strip + paginated endpoint) — clean, real dashboard perf win. *Before merging, grep the frontend for a consumer of `/instruments/{id}/ohlcv`; if none exists yet, either also port the FE chart change or keep `include_ohlcv=True` until the FE lazy-loader lands.*
3. **(Optional) `02c6b297b` + `474e3fcb8`** (prewarmer worker, squashed) — only if you want proactive bundle-cache warming; opt-in, low risk, pairs with HEAD's existing Valkey cache. Default-off, so safe to land dark.
4. **(Optional, defer) `a6c05b545`** (SSE bundle) — only if the streaming Intelligence-tab UX is wanted now; otherwise skip to avoid dead FE surface.

**Drop / do not take:**
- `d1ae804c9` recharts (regression — HEAD has 3.8.1)
- `3f1febf75` ESLint (moot — files diverged; re-run `pnpm lint` on HEAD instead)
- `bf2071059` R1 graph_d2 drop (conflicting alternative — HEAD's cache+timeout+merge design supersedes)
- `3046d84af` R4 instrument-brief pregen (superseded by HEAD's `InstrumentBriefPregenerationWorker`, PLAN-0113)

After cherry-picks: run api-gateway tests (`tests/test_instruments*.py`, `tests/test_bundle_prewarmer.py` if R3 taken) + `pnpm build` to confirm the status fix; verify the OHLCV FE consumer.
