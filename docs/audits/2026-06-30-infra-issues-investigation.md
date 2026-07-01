# Infra Issues Investigation — 2026-06-30

Backend-health QA sweep follow-up. Three flagged containers investigated. Read-only
diagnostics + one safe restart (#3). No code or git changes.

Host: 14 CPU / ~50 GB RAM (`docker info`). Ample free memory at investigation time.

---

## Issue 1 — `intelligence-migrations` exited(255): "Can't locate revision 0063"

**Status: ROOT-CAUSED. Fix = rebuild the migration image. Do NOT run any manual stamp/downgrade.**

### Finding — stale container image, NOT a broken migration chain

The on-disk migration chain is intact and linear:

| file | revision | down_revision |
|------|----------|---------------|
| `0061_add_relation_evidence_raw_promoted_at.py` | `0061` | `0060` |
| `0062_covering_index_relation_evidence_raw_density.py` | `0062` | `0061` |
| `0063_create_graph_edges.py` | `0063` | `0062` |

`0063` is the current disk head (no `0064` exists). Nothing was deleted or renamed.

The DB is correctly stamped and the migration genuinely applied:
- `intelligence_db` → `SELECT version_num FROM alembic_version` = **`0063`**
- `SELECT to_regclass('public.graph_edges')` = **`graph_edges`** (the table `0063` creates exists)

So `0063` was applied to the DB at some point by a **fresh** image. The problem is the
**currently-deployed migration image is stale** — it was built at head `0062` and does not
contain `0063` on disk. Confirmed by inspecting the image filesystem:

```
$ docker run --rm --entrypoint sh worldview-intelligence-migrations \
    -c "find / -name '006*.py' -path '*versions*'"
/app/alembic/versions/0060_index_relation_evidence_raw_density.py
/app/alembic/versions/0061_add_relation_evidence_raw_promoted_at.py
/app/alembic/versions/0062_covering_index_relation_evidence_raw_density.py
   # <-- no 0063 in the image
```

On startup Alembic reads the DB head (`0063`), tries to locate that revision in its own
(stale) `versions/` directory, cannot find it → `Can't locate revision identified by '0063'`
→ exit 255. This is the known "compose build ships stale files" pattern (memory:
`feedback_compose_build_stale_prompts`).

### Recommended fix

Rebuild the migration image so it includes `0063`, then re-run the one-shot container.
After rebuild the DB head (`0063`) == disk head (`0063`), so `alembic upgrade head` is a
**no-op** and the container exits 0.

```bash
cd infra/compose
docker compose -f docker-compose.yml -f docker-compose.dev.yml -p worldview --profile all \
  build intelligence-migrations
docker compose -f docker-compose.yml -f docker-compose.dev.yml -p worldview --profile all \
  up --no-deps intelligence-migrations
```

If a plain compose build ships stale files again (has happened before), fall back to a
direct build + retag from repo root:
`docker build -f services/intelligence-migrations/Dockerfile -t worldview-intelligence-migrations .`

**No chain repair, no manual stamp, no downgrade needed** — the chain and DB are already
consistent. Do NOT `alembic stamp` or `downgrade`; that would corrupt a correct state.

---

## Issue 2 — `alert-rule-poller` SIGKILL(137), never restarted

**Status: ROOT-CAUSED — most likely a manual/compose stop, NOT an OOM. NEEDS USER DECISION
before restart (intentional vs accidental).**

### Finding — not an OOM; consistent with an explicit stop

`docker inspect` State:
- `ExitCode = 137` (SIGKILL)
- `OOMKilled = false`
- `HostConfig.Memory = 0` (no container memory limit) / `MemorySwap = 0`
- `RestartPolicy = unless-stopped`
- FinishedAt `2026-06-29T12:48:40Z`

Because there is **no container memory limit** and **`OOMKilled=false`**, this was not a
cgroup OOM kill. The decisive signal is the restart behaviour: the policy is
`unless-stopped`, which auto-restarts on any exit **except** an explicit stop. The container
did **not** restart → Docker recorded it as manually stopped. A host-kernel OOM-kill would
still have triggered an auto-restart under `unless-stopped`, so that is effectively ruled
out. Conclusion: the poller was almost certainly stopped by a `docker stop` /
`docker compose stop`/`down` (targeting this service or a broader set), not by a crash.

Last log lines show clean 60s ticks, then two "Run time of job ... was missed by ~2–7s"
entries just before exit — i.e. brief host scheduling lag around the stop, consistent with
a busy host during a compose operation, but no crash/traceback/OOM trace.

### Is the poller required?

Yes. Per `services/alert/.claude-context.md`:
- "Rule Poller (PLAN-0113)" — `python -m alert.infrastructure.rules.poller_main`.
- Wakes every `ALERT_ALERT_RULE_POLL_TICK_SECONDS` (60s); evaluates user `AlertRule`s
  (per-type cadence via `AlertRule.is_due`), edge-triggered on `last_state`, and fires
  alerts (per-user cap `ALERT_ALERT_RULE_MAX_PER_USER`).
- Master switch `ALERT_ALERT_RULE_POLLER_ENABLED` (default true).
- Watchdog metric `s10_rule_poller_last_success_timestamp_seconds` +
  `infra/prometheus/rules/alert_rule_poller.yml`.

**While it is down, user-defined alert rules are NOT evaluated and no rule-based alerts
fire.** This is a real user-facing gap that has now been open ~40h.

### Recommended fix (needs user go-ahead)

- **FLAG FOR USER:** confirm the stop was accidental (e.g. a scoped compose op that also
  hit this container) vs. intentional. It is user-facing, so unless it was deliberately
  disabled it should be restarted.
- No memory-limit bump is required — there is no limit today and the kill was not an OOM.
  Restarting as-is will not re-trigger a 137 from memory. (If desired, a limit could be
  ADDED later for isolation, but that is orthogonal and would introduce OOM risk where none
  exists now — not recommended as part of this fix.)
- Restart command once approved:
  ```bash
  docker start worldview-alert-rule-poller-1
  # or, to re-assert desired state via compose:
  cd infra/compose && docker compose -f docker-compose.yml -f docker-compose.dev.yml \
    -p worldview --profile all up --no-deps alert-rule-poller
  ```
  Then confirm 60s ticks resume in logs and `s10_rule_poller_last_success_timestamp_seconds`
  advances.

---

## Issue 3 — `alert-intelligence-consumer` unhealthy (wedged rdkafka healthcheck) — FIXED

**Status: RESTARTED. Container is HEALTHY and rejoined its group. One caveat below.**

### Action taken

```bash
docker restart worldview-alert-intelligence-consumer-1
```

### Verification

- Health transitioned `starting → healthy` within ~40s of restart
  (`docker inspect ... .State.Health.Status = healthy`).
- Logs show a clean cold start: `intelligence_consumer_starting` → `metrics_server_started`
  → `alert-intelligence-consumer_ready` → `kafka_consumer_started` with
  `group_id=alert-service-group`, subscribed to
  `["nlp.signal.detected.v1", "graph.state.changed.v1", "intelligence.contradiction.v1"]`.
- The half-open/stuck rdkafka connection (continuous REQTMOUT/SESSTMOUT, FailingStreak
  ~2186) is cleared; the consumer re-established a fresh connection and rejoined the group.

### Caveat to flag

Shortly after the clean restart, one `kafka_connectivity_probe_failed`
(`_TIMED_OUT` getting metadata, `consecutive_failures: 1 / threshold: 3`) still appeared,
and the `kafka-consumer-groups --list/--describe` admin CLI **timed out (>2 min)** against
the broker. Both point at **broker-side sluggishness** (metadata requests slow), not just
the consumer's socket. This is consistent with the known broker 1 GB-heap / GC-freeze wedge
class (memory: `project_kafka_resilience_and_qa_2026_06_21`, BP-706). The consumer restart
resolved *this* container's symptom, but if metadata timeouts recur across consumers, the
**broker heap/GC** is the underlying issue to address separately. Recommend a quick check of
`worldview-kafka-1` heap/GC health if other consumers start flapping.

---

## Summary

| # | Container | Root cause | Fix | Needs user? |
|---|-----------|-----------|-----|-------------|
| 1 | intelligence-migrations | Stale image (built at 0062); DB & disk both at 0063; chain intact | Rebuild image + re-run (no-op upgrade). No stamp/downgrade. | No — safe rebuild |
| 2 | alert-rule-poller | SIGKILL 137, not OOM (no limit, OOMKilled=false); `unless-stopped` didn't restart ⇒ manual/compose stop. Required user-facing function, down ~40h. | `docker start` once confirmed accidental; no mem bump needed. | **Yes — confirm intentional vs accidental** |
| 3 | alert-intelligence-consumer | Half-open rdkafka connection (stuck healthcheck), consumer otherwise live | **Restarted — now healthy, rejoined `alert-service-group`, lag clear** | No — done. Watch broker-side metadata timeouts (BP-706 class). |
