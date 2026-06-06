# PLAN-0096 Revision Report — 2026-05-26

Two parallel investigations landed; W3/W4 placeholders folded in.

## Changes made

- **Frontmatter**: status `draft` → `ready`; investigations marked LANDED; report added to `source_audits`.
- **§0**: placeholders replaced with concrete root causes (AGE plpgsql `cypher()` schema-cache survives commit; `entity_mentions.tenant_id NOT NULL` blocks pre-PLAN-0086 payloads).
- **§2/§3**: W3/W4 boxes rewritten; 2 placeholder rows replaced with 5 file-and-line rows.
- **W3 rewrite**: T-W3-01 patches `age_sync_worker.py:447-479` with `await session.connection().invalidate()` after commit; T-W3-02 integration test asserts Cypher count; T-W3-03 idempotent `scripts/reconcile_age_temporal_events.py`. Gate: SQL count == AGE count. BP-547.
- **W4 rewrite**: T-W4-01 adds `PUBLIC_TENANT_ID` to `libs/common/ids.py` + substitutes at `article_consumer.py:454-458` with WARN log; T-W4-02 `scripts/replay_stuck_articles.py` (Confluent-Avro per BP-122); T-W4-03 Grafana **retry-storm** alert (NOT DLQ-lag); T-W4-04 legacy-payload regression test. Gate: `entity_mentions` climbs within 5 min. BP-548.
- **§5/§6/§7**: `libs/common` added; rollback steps written for W3/W4; BP wording concretised.
- **TRACKING.md**: `draft` → `ready`; prereqs trimmed; report linked.

## Inconsistencies corrected

- **AGE path drift**: audit said `infrastructure/scheduler/`; actual is `infrastructure/workers/`. Corrected.
- **"DLQ stall" misnomer**: DLQ is empty; stall is on the main-topic offset (`IntegrityError` is retryable). Wave renamed; alert is a retry-storm rule, not DLQ-lag.
- **Sentinel home**: audit used an inline literal UUID; promoted to shared `PUBLIC_TENANT_ID` in `libs/common/ids.py` (verified absent today).
- **Alert dir**: placeholder said `infra/observability/prometheus/rules/`; canonical home is `infra/grafana/alerts/` (mirrors `path_insight_stalled.yml`).
- **Scripts dir**: both new scripts placed at repo-root `scripts/`.

## Audit claims downgraded / upgraded

- **Downgraded**: AGE Hypotheses 1 + 3 — W3 commits to Hypothesis 2 / Option A only.
- **Downgraded**: DLQ replay → in-flight replay (peek offset, re-publish, then commit) because DLQ stays empty.
- **Upgraded**: multi-tenant pollution risk — not flagged in audits; revision verifies the sentinel UUID never matches a real JWT tenant_id.
- **Confirmed**: no Alembic-order changes; no overlap with PLAN-0095 (grep); `libs/common/ids.py` touched additively.
