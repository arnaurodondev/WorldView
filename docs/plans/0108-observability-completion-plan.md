# PLAN-0108: Observability Completion + Process Tooling Polish

**Status**: pending
**Created**: 2026-06-07
**Source**: PLAN-0107 follow-up findings + the deferred V2 layer of FU-OBS-LOKI-LABELS

---

## Overview

Five focused waves to close the remaining observability + tooling gaps surfaced during PLAN-0107 execution. All waves are independent.

```
A. Alloy → Loki label propagation (V2) — unblocks Workers Ready panel
B. Orphan-commit watchdog tuning — fewer false positives
C. Pre-commit framework integration — team-wide rollout of D-2 hook
D. Lockfile heartbeat orchestrator — long-running session protection
E. Cache invalidation admin endpoint — manual invalidate(dataset_type, symbol)
```

---

## Wave A — Alloy → Loki Label Propagation (FU-OBS-LOKI-LABELS-V2)

PLAN-0107 added a `service_name` target_label to `infra/alloy/config.alloy`, but Loki 3.5 auto-injects `service_name=unknown_service` because the OTLP push carries no `service.name` resource attribute. Disabling auto-discovery surfaced an upstream Alloy bug: `loki.source.docker` doesn't propagate relabel target_labels to the push, so Loki rejects streams with "at least one label pair required". Two-part fix:

1. **Attach external labels to `loki.write.default`** — gives Loki at least one static label so push never has zero pairs:
   ```alloy
   loki.write "default" {
     endpoint { url = "http://loki:3100/loki/api/v1/push" }
     external_labels = { stack = "worldview" }
   }
   ```

2. **Re-enable `discover_service_name: []` on Loki** so Alloy's relabel `service_name` is authoritative.

3. **Verify**: emit a fresh log from `content-ingestion-worker`, query Loki for distinct `service_name` values — expect ≥ 5 real container names (no `unknown_service`).

LOC: 5 lines Alloy + 1 line Loki + verification. Files: `infra/alloy/config.alloy`, `infra/loki/loki-config.yml`.

---

## Wave B — Orphan-Commit Watchdog Tuning

PLAN-0107 D-4 orphan triage found all 3 flagged commits were re-applied under different SHAs (path-rename or subject match). Tune the watchdog to auto-clear these:

1. **Subject-match**: for each orphan, check `git log --all --since=24h --format='%H %s' | grep -F "$(git log -1 --format=%s $orphan)"`. If a non-orphan match exists, mark **RE-APPLIED**.
2. **Rename detection**: use `git diff --find-renames=50` when comparing orphan content to current branch.
3. **Exit codes**:
   - 0 = no orphans OR all re-applied
   - 1 = genuine orphans need recovery
   - 2 = ambiguous (manual triage needed)

LOC: ~40 LOC bash + 1 negative test using a synthetic re-applied orphan. File: `scripts/orphan_commit_check.sh`.

---

## Wave C — Pre-Commit Framework Integration

`.git/hooks/pre-commit` is not tracked. PLAN-0107 added `scripts/install_hooks.sh` as a one-shot installer, but the project's existing `pre-commit` framework hook is the canonical path. Add a `local hook` entry to `.pre-commit-config.yaml`:

```yaml
- repo: local
  hooks:
    - id: worktree-lock-check
      name: PLAN-0107 D-2 worktree-lock check
      entry: bash scripts/worktree_lock.sh check_for_commit
      language: system
      pass_filenames: false
      stages: [pre-commit]
```

Add `check_for_commit` subcommand to `scripts/worktree_lock.sh` that returns nonzero (with message) when a foreign-pid lock is fresh.

LOC: 5 lines YAML + 15 lines bash subcommand. Files: `.pre-commit-config.yaml`, `scripts/worktree_lock.sh`.

---

## Wave D — Lockfile Heartbeat Orchestrator

Crashed sessions hold the lock for 30 min (TTL default) before clobber. Long-running orchestrators should heartbeat the lock to extend ownership. Add:

1. **`scripts/worktree_lock.sh` heartbeat** is already implemented per PLAN-0107 D-2 TTL fix. Verify.
2. **`scripts/worktree_lock.sh autonomous_heartbeat &`** — daemon mode that loops every `TTL/3` seconds calling `heartbeat`. Exits when lockfile disappears.
3. **Wire into `/loop` + `/implement` skill startup** — document in `.claude/skills/*/SKILL.md`: "On long-running operations, spawn `bash scripts/worktree_lock.sh autonomous_heartbeat &` and trap-kill it on exit."

LOC: ~30 LOC bash + skill doc edits. Files: `scripts/worktree_lock.sh`, optionally `.claude/skills/loop/SKILL.md`.

---

## Wave E — Cache Invalidation Admin Endpoint

PLAN-0107 A.5 flagged fundamentals staleness risk (24h TTL can serve pre-restatement data after an 8-K filing). Add a manual invalidation endpoint:

1. **API**: `DELETE /internal/v1/cache/{dataset_type}/{symbol}` on market-ingestion
2. **Use case**: `InvalidateCacheUseCase(cache).execute(dataset_type, symbol)` — calls `cache.invalidate(dataset_type, symbol)` which `DEL`s the Valkey key (or `DEL_PATTERN` for period_key wildcard).
3. **Auth**: internal JWT only (admin role) — reuse existing middleware.
4. **Tests**: 2 unit tests (cached → invalidated; non-existent → 404 or 204).
5. **Metric**: `s2_mi_provider_cache_invalidated_total{dataset_type}` Counter.

LOC: ~80 LOC + 30 LOC tests. Files: `services/market-ingestion/src/market_ingestion/{api,application/use_cases,infrastructure/cache}/*.py`.

---

## Acceptance per wave

- **A**: `curl http://localhost:3100/loki/api/v1/label/service_name/values` returns ≥ 5 distinct values (real container names).
- **B**: orphan watchdog with synthetic re-applied commit auto-clears it (exit 0).
- **C**: `pre-commit run --all-files` invokes the hook; foreign lock causes the hook to fail.
- **D**: heartbeat daemon refreshes lockfile every TTL/3; observable in `started_at` field.
- **E**: `DELETE /internal/v1/cache/ohlcv_eod/AAPL` returns 200; subsequent fetch is cache MISS.

---

## Acceptance gate for PLAN-0108

Plan reaches ✅ when:
- Workers Ready Grafana panel populates with ≥ 5 real container names (A)
- Watchdog false positive rate < 10% (B)
- Pre-commit framework hook blocks commits on foreign lock (C)
- Lockfile heartbeat keeps long-running session alive past TTL (D)
- Manual cache invalidation endpoint live + tested (E)
