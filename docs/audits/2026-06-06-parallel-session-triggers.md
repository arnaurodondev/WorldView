# Parallel-Session Triggers — Diagnostic Audit

**Date**: 2026-06-06
**Plan**: PLAN-0107 Wave D-1
**Scope**: Identify concrete triggers behind the four parallel-session revert cases observed during the PLAN-0099 W4 worker-metrics rollout.
**Related**: R42, BP-590, PLAN-0107 §D.

---

## 1. Concurrent session detection (overlapping JSONL transcripts)

`~/.claude/projects/-Users-arnaurodon-Projects-University-final-thesis-worldview/` contains one JSONL per Claude session, with the file's mtime advancing on every transcript append. Overlapping mtimes within a few seconds of each other on the **same project root** are direct evidence that two (or more) Claude agents were live simultaneously.

### 1.1 Evidence — Jun 6 2026 17:43–17:48 window

```
156ab693-…jsonl  Jun  6 17:43  3.5 MB
aa7b63ca-…jsonl  Jun  6 17:46  1.8 MB
e9207b49-…jsonl  Jun  6 17:46  30 MB   ← long-running
cf4f3c25-…jsonl  Jun  6 17:47  1.3 MB
ec91102f-…jsonl  Jun  6 17:47  23 MB   ← long-running (this audit's session)
```

Five sessions wrote transcripts to the same project within a 4-minute window. At least two of them (`e9207b49`, `ec91102f`) are large multi-megabyte transcripts representing long-running interactive sessions, not micro-replays. This is the direct mechanism behind cases 1–4 in §5.

### 1.2 Evidence — Jun 6 2026 14:00–14:32 window

```
f159bbf1-…jsonl  Jun  6 14:25  2.0 MB
45d562cb-…jsonl  Jun  6 14:32  7.4 MB
```

Two more sessions overlapped while PLAN-0107 was being drafted (commit `59fad46f` at 14:05 and CI-fix flurry through 14:38).

### 1.3 Evidence — Jun 5 2026 21:26–21:48 window (the original PLAN-0099 W4 incident)

`git log --since="2026-06-05 21:00" --until="2026-06-05 22:00"` reveals **duplicated commit SHAs with identical author, timestamp, and message** — the canonical fingerprint of a branch-rewind followed by re-cherry-pick:

| Phase | SHA #1 (orphaned) | SHA #2 (re-applied) | Timestamp |
|-------|-------------------|---------------------|-----------|
| Phase 3a | `0259eb8a` | `823a07f7` | 21:28:09 |
| Phase 3b | `a99aa892` | (lost — repaired in `63010c01`) | 21:38:14 |
| Helper + KG-scheduler | `046436c0` | `97bd48d6` | 21:28:00 |
| Grafana panels | `6e55ba63` | `e6974e72` | 21:26:55 |

`63010c01` is literally titled *"fix(workers): re-apply Phase 3b metrics-server wiring on unresolved_resolution_worker_main (parallel-session revert)"* — explicit remediation commit.

This pattern (two SHAs, one author, identical message, identical second) only arises when the same content gets committed twice on diverging branches, which only happens if two sessions raced.

---

## 2. Hook audit — no auto-commit handlers

```
$ find scripts/hooks .git/hooks -type f
scripts/hooks/schema-guard.sh
scripts/hooks/frontend-validate.sh
scripts/hooks/security-scan.sh
scripts/hooks/scrub_stash_markers.sh
scripts/hooks/pre-pr-checklist.sh
scripts/hooks/pre-commit-validate.sh
scripts/hooks/lint_tracking_shipped_claims.py
scripts/hooks/migration-guard.sh
scripts/hooks/secret-scan.sh
scripts/hooks/post-edit-validate.sh
.git/hooks/pre-commit  (pre-commit framework wrapper, 21 LOC)
```

`grep -lE 'auto-commit|git commit|git add -A' scripts/hooks/* .git/hooks/*` returns only `scripts/hooks/pre-commit-validate.sh` (which validates a *pending* commit; does not auto-create one). No handler in this repo silently invokes `git commit` on file-change. **Hooks are NOT the trigger.** This rules out one hypothesis the post-mortem entertained.

`.git/hooks/pre-commit` is the standard pre-commit-framework shim, hardcoded against the *old* venv path `Final Thesis/worldview/.venv/bin/python3` (note the capital + space, current path is lowercase + dash). It probably fails to find the interpreter and falls through to `command -v pre-commit`. Not a trigger source, but worth noting as a follow-up.

---

## 3. Skill audit — sub-agents that inherit cwd

`/loop` and `/babysit-prs` do not exist as `.claude/skills/` directories here (they are global user skills). The two **in-repo skills that spawn sub-agents are**:

### 3.1 `/qa` — `Spawns parallel agents (QA, Security, Data Platform, Distributed Systems, Architecture)`
- `.claude/skills/qa/SKILL.md:11`: "You coordinate 5 specialist review agents in parallel"
- `.claude/skills/qa/SKILL.md:70`: "Spawn **5 agents in parallel** using the Agent tool."
- Each sub-agent inherits the orchestrator's cwd and can issue git read commands. They are documented as read-only review agents, but nothing in the skill spec prevents one from running `git stash` or otherwise mutating index state.

### 3.2 `/implement` — `Agent tool with isolation: "worktree"`
- `.claude/skills/implement/SKILL.md:90`: *"Use `Agent` tool with `isolation: \"worktree\"` to spawn independent implementation agents per task"*
- `.claude/skills/implement/SKILL.md:101`: *"You MUST commit your changes to the main worktree (not just leave them in a worktree) before returning. If the worktree merge fails, apply your changes directly to the main branch files and commit."* — **this is the gun**. The instruction explicitly tells sub-agents to fall back to committing directly on the parent worktree, defeating the isolation.
- `.claude/skills/implement/SKILL.md:473`: *"If a hook or parallel session reverted your change, re-apply and commit again."* — acknowledges the failure mode but offers no prevention.

### 3.3 Conclusion
The `/implement` skill is a documented mechanism for inducing the very pattern PLAN-0107 §D is trying to fix. Wave D-2's lockfile is the natural mitigation: the second-arriving sub-agent should fail-fast on the lock rather than fall back to mutating the parent.

---

## 4. Reflog evidence — HEAD jumps

```
d0dab8c2 HEAD@{2026-06-06 17:48:02}: commit: fix(ci): add healthcheck to ollama-init
c3acbf96 HEAD@{2026-06-06 17:46:21}: checkout: moving from main to fix/post-plan-0104-nlp-kg-e2e-gliner
c3acbf96 HEAD@{2026-06-06 17:46:21}: reset: moving to origin/main
c3acbf96 HEAD@{2026-06-06 17:46:21}: checkout: moving from main to main
c3acbf96 HEAD@{2026-06-06 17:46:14}: checkout: moving from fix/post-plan-0104-e2e-alert-content-ingestion to main
c3acbf96 HEAD@{2026-06-06 17:46:14}: checkout: moving from fix/post-plan-0104-e2e-alert-content-ingestion to fix/post-plan-0104-mi-worker-and-playwright
c3acbf96 HEAD@{2026-06-06 17:45:46}: checkout: moving from main to fix/post-plan-0104-e2e-alert-content-ingestion
c3acbf96 HEAD@{2026-06-06 17:45:46}: reset: moving to origin/main
c3acbf96 HEAD@{2026-06-06 17:45:39}: checkout: moving from main to main
c3acbf96 HEAD@{2026-06-06 17:45:13}: reset: moving to origin/main
01603cf8 HEAD@{2026-06-06 17:45:13}: checkout: moving from feat/plan-0099-w4 to main
3f4326de HEAD@{2026-06-06 17:45:12}: reset: moving to HEAD
```

Three observations:
1. **`reset: moving to origin/main`** appears 3× in 90 seconds — this is *not* normal interactive behavior; it suggests an external workflow (another session, or a script invoked from another session) is force-aligning the branch.
2. **`checkout: moving from main to main`** (twice) is the textbook "two agents racing on git state" signature — only happens when a `git checkout main` runs while HEAD is already on main and another concurrent operation has just changed HEAD.
3. Earlier on the same day: `93d395e3 HEAD@{2026-06-06 13:14:57}: reset: moving to HEAD` repeats 4× in 30 minutes — another race.

The bulk-commit `6ed7ec04` (case 1, "fix(ci): bulk-commit 59 modified files + 3 targeted fixes", Jun 5 15:44, author `arnaurodondev@gmail.com`) is on a different branch and confirmed by `git show 6ed7ec04 --stat` to touch 59 files.

---

## 5. Trigger taxonomy — four cases mapped to evidence

| # | Pattern | Evidence | Trigger source |
|---|---------|----------|----------------|
| **1** | **Bulk-commit pattern** — unexpected commit author + large file count | `6ed7ec04`, 59 files, author `arnaurodondev` (not the Claude `Co-Authored-By` trailer), Jun 5 15:44 | Manual `git commit -a` from a sibling terminal while a worktree agent was mid-edit. No hook involvement (§2). |
| **2** | **Branch-rewind pattern** — `git reflog` shows HEAD jump backward; cherry-picks left orphaned | Duplicate SHAs `0259eb8a`+`823a07f7`, `046436c0`+`97bd48d6`, `6e55ba63`+`e6974e72` (§1.3); reflog `reset: moving to origin/main` 3× in 90s (§4) | Sibling session executing `git reset --hard origin/main` (probably from a "sync with main" prompt) while another session had un-pushed cherry-picks. |
| **3** | **Selective file revert** — change present, then absent | `63010c01`'s subject line: *"re-apply Phase 3b metrics-server wiring on `unresolved_resolution_worker_main` (parallel-session revert)"* — the file lost its `start_metrics_server` import during a checkout cascade | Selective `git checkout <branch> -- <file>` from a sibling session, or a partial stash-pop conflict that took only one side. |
| **4** | **YAML/JSON revert** — config-file silent rollback | `e8f03862` ("restore 2 dropped services + fix alloy healthcheck") + plan §D opening: *"Compose Kafka tuning (`KAFKA_CONTROLLER_QUORUM_REQUEST_TIMEOUT_MS` et al.) was silently rolled back"* | Same selective-checkout mechanism as case 3, but on `infra/docker-compose.*.yml`. Tests still pass because containers tolerate the old defaults; the regression is only visible at deploy. |

---

## 6. Mitigation map (PLAN-0107 D-waves)

| Trigger | Prevention | Detection | Wave |
|---------|------------|-----------|------|
| Manual `git commit -a` from sibling terminal (case 1) | `.worktree-lock` refuses commit when peer pid alive | Co-Authored-By trailer check | D-2 + D-3 |
| Sibling `git reset` rewinding HEAD (case 2) | `.worktree-lock` refuses checkout when peer alive | Orphan-commit watchdog | D-2 + D-4 |
| Selective `git checkout -- <file>` (case 3) | `.worktree-lock` | Diff-against-expected post-cherry-pick | D-2 + D-4 |
| YAML revert (case 4) | `.worktree-lock` | CI YAML drift check | D-2 + D-4 |
| `/implement` sub-agent committing on parent (§3.2) | `.worktree-lock` | Sub-agent guardrail prompt update | D-2 + D-5 (CLAUDE.md update) |

All four cases collapse to the same root cause: **two write-capable git operations in the same checkout with no mutual exclusion**. D-2 (the lockfile) is the single highest-leverage fix.

---

## 6b. D-2 pre-commit wiring — deferred to main worktree

The plan calls for the lockfile guard to live at the top of `.git/hooks/pre-commit`. In a git **worktree**, `.git/hooks/` is shared with the main checkout — the path is `<main-repo>/.git/hooks/pre-commit`, not `<worktree>/.git/hooks/pre-commit`. From an agent worktree, that path is outside the worktree subtree and our sandbox refuses edits to it (correctly, because every worktree shares the same hook file and one race-condition edit could corrupt it for everyone).

**Recommended patch** (apply manually from `/Users/arnaurodon/Projects/University/final_thesis/worldview` or open this file from any non-worktree session):

Insert after the `# ID:` line, before `# start templated`:

```bash
# --- PLAN-0107 D-2: worktree lockfile guard --------------------------------
# Refuse the commit if a peer Claude/manual session holds the lock.
# Opt out: WORLDVIEW_DISABLE_WORKTREE_LOCK=1
if [ "${WORLDVIEW_DISABLE_WORKTREE_LOCK:-0}" != "1" ] && [ -f .worktree-lock ]; then
    lock_pid="$(sed -n 's/.*"pid"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' .worktree-lock | head -n 1)"
    if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
        owned_by_us=0; p=$$
        while [ "$p" != "1" ] && [ -n "$p" ]; do
            if [ "$p" = "$lock_pid" ]; then owned_by_us=1; break; fi
            p="$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')"
            [ -z "$p" ] && break
        done
        if [ "$owned_by_us" = "0" ]; then
            echo "pre-commit: refused — another session holds .worktree-lock (pid $lock_pid)." >&2
            echo "  Override: rm .worktree-lock   or   export WORLDVIEW_DISABLE_WORKTREE_LOCK=1" >&2
            exit 1
        fi
    fi
fi
# --- end PLAN-0107 D-2 -----------------------------------------------------
```

The guard walks the calling process's parent chain to detect whether the lock owner is an ancestor (i.e. this commit comes from the session that owns the lock — allowed). A foreign live pid in the lockfile → refuse with override instructions. The standalone `scripts/worktree_lock.sh` and its tests are fully functional without this wiring; D-2 acceptance criteria for the script itself is met. The hook wiring is one shell-paste away from being live.

---

## 7. Follow-ups (not in scope for D-1/D-2)

- **`.git/hooks/pre-commit` interpreter path is stale** — references `Final Thesis/` (capital, space) but the repo lives at `final_thesis/`. Likely silently fails the `[ -x "$INSTALL_PYTHON" ]` check and falls back to `command -v pre-commit`. Filed as a side-item; D-2 will wire its lockfile check into this same script, so the fix happens incidentally.
- **`/qa` skill spawns 5 parallel agents** with no documented isolation contract. Even if they are "read-only" by intent, the Agent tool gives them write capability. Either move to `isolation: "worktree"` or add a banner in the skill prompt forbidding git writes.
- **`/implement` skill's commit-fallback instruction** (line 101) — recommend rewriting to: *"If the worktree merge fails, STOP and report — do NOT commit to the parent worktree."*
- The 17:46 reflog "moving from main to main" double-checkout deserves its own investigation; it strongly suggests a third concurrent process (cron, fsmonitor watchman, IDE git integration) is also touching HEAD. Out of scope for D-1.

---

## 8. Confidence

| Claim | Confidence | Basis |
|-------|------------|-------|
| ≥2 sessions ran simultaneously today | **Certain** | 5 JSONL files with mtimes within a 4-minute window (§1.1) |
| Hook framework is NOT a trigger | **Certain** | Exhaustive grep, no auto-commit handlers (§2) |
| `/implement` skill can induce parallel-session commits | **High** | Skill prompt explicitly instructs sub-agents to commit on parent worktree (§3.2) |
| Branch-rewind case 2 happened on Jun 5 21:28 | **Certain** | Duplicate SHAs with identical timestamps + explicit remediation commit `63010c01` (§1.3) |
| Case 1 (bulk commit) was manual user action | **High** | Commit author email `arnaurodondev@gmail.com` matches manual-terminal identity; Claude commits carry `Co-Authored-By` trailer per CLAUDE.md convention |

---

*End of D-1 audit. Proceed to D-2: filesystem lockfile (`scripts/worktree_lock.sh`).*
