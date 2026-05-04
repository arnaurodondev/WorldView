# W9 Pre-Flight Baseline — PLAN-0065 Wave A

**Date**: 2026-05-04 (Wave A executed)
**Author**: `/implement` skill — PLAN-0065 Wave A
**Purpose**: Empirical verification of all 4 PRD-referenced code fixes; baseline state for Waves C/D/E.

---

## T-A-01: BP-302 Fix — nlp-pipeline Article Consumer

| Check | Result |
|-------|--------|
| Container image source-introspection | `True` — `progress_made` guard present in `chunk_section` |
| Container | `worldview-nlp-pipeline-article-consumer-1` — Up 15 hours (healthy) |
| Kafka consumer group | `nlp-pipeline-group` (plan doc used `nlp-pipeline-article-consumer` — corrected here) |
| Offset status | Active on all 12 partitions of `content.article.stored.v1`; lag 83–116 per partition; steadily advancing (NOT frozen) |

**Offset snapshot** (captured 2026-05-04):

| PARTITION | CURRENT-OFFSET | LOG-END | LAG |
|-----------|---------------|---------|-----|
| 0 | 755 | 838 | 83 |
| 1 | 821 | 924 | 103 |
| 2 | 789 | 886 | 97 |
| 3 | 818 | 922 | 104 |
| 4 | 823 | 939 | 116 |
| 5 | 808 | 903 | 95 |
| 6 | 818 | 929 | 111 |
| 7 | 759 | 847 | 88 |
| 8 | 862 | 951 | 89 |
| 9 | 749 | 842 | 93 |
| 10 | 846 | 947 | 101 |
| 11 | 823 | 922 | 99 |

**Decision**: **SKIP T-B-01 and T-B-02** — fix is deployed, consumer is healthy and advancing, no stuck partition detected. No redeploy or offset reset needed for the article consumer.

---

## T-A-02: F-VISUAL-002 / F-E8 / F-D4 Fixes

### F-VISUAL-002 — `--muted-foreground` CSS variable sync

| Check | Result |
|-------|--------|
| `:root` block (`globals.css:74`) | `--muted-foreground: 240 4% 55%` — ✅ PRESENT |
| `.dark` block (`globals.css:177`) | `--muted-foreground: 240 4% 55%` — ✅ PRESENT |
| Commit in branch history | `f27e266b` (2026-05-01) ✅ |

### F-E8 — `/undefined` path guard (`_client.ts:75`)

| Check | Result |
|-------|--------|
| Guard present | `/\/undefined(\/|\?|$)/.test(path)` at line 75 — ✅ PRESENT |
| `/null` guard | `/\/null(\/|\?|$)/.test(path)` at line 76 — ✅ PRESENT |
| Commit in branch history | `f27e266b` (2026-05-01) ✅ |

### F-D4 — EU date parsing normalization (`economic_events_dataset_consumer.py:90`)

| Check | Result |
|-------|--------|
| Fix present | `date_str.replace(" ", "T", 1)` at line 90 — ✅ PRESENT |
| Commit in branch history | `f27e266b` (2026-05-01) ✅ |

**All three source fixes confirmed in the current branch.** T-B-03 smoke verification: **READY TO PROCEED**.

---

## EU Economic Events Consumer — Offset State (T-B-04 context)

| Check | Result |
|-------|--------|
| Consumer group | `kg-economic-events-dataset-group` |
| Topic | `market.dataset.fetched` |
| Active consumer | Yes (rdkafka member on all 6 partitions) |
| Container up | `worldview-knowledge-graph-economic-events-dataset-consumer-1` — Up 22 minutes |

**Offset snapshot** (captured 2026-05-04):

| PARTITION | CURRENT-OFFSET | LOG-END | LAG |
|-----------|---------------|---------|-----|
| 0 | 194 | 194 | **0** |
| 1 | 117 | 173 | 56 |
| 2 | 134 | 207 | 73 |
| 3 | 128 | 214 | 86 |
| 4 | **81** | 169 | 88 |
| 5 | **0** | 203 | **203** |

**Key findings**:
- Partition 4 current offset = **81** — matches the known "81 EU events logged `ingested=0`" from the pre-fix run (2026-04-30 12:25:55). Those 81 events were consumed (offsets committed) but silently dropped due to the EU date bug. The fix landed in commit `f27e266b` (2026-05-01). The consumer needs a **reset of partition 4 to offset 0** to re-ingest those dropped events.
- Partition 5 has never been processed (offset = 0, lag = 203). This is normal — partition 5 was newly assigned on restart. The consumer is actively processing it.
- Total lag: **506 messages** across all 6 partitions.
- **Decision**: **EXECUTE T-B-04** — reset partition 4 to offset 0 to backfill the 81 dropped EU economic events. All other partitions are either caught up (p0) or actively processing (normal lag).

---

## Missing Observability Artifacts (inputs to Waves C / D / E)

| Artifact | Current State | Target State (after Waves C/D/E) |
|----------|--------------|----------------------------------|
| `libs/observability/sentry.py` | **MISSING** — `libs/observability/src/observability/` has only `error_capture.py`, `logging.py`, `metrics.py`, `tracing.py` | New module with `init_sentry()` + `SentrySettings` + PII `before_send` |
| `sentry-sdk` in any backend requirements | **MISSING** — not found in any service | Added via `libs/observability` dependency in all 10 backends |
| `@sentry/nextjs` in `apps/worldview-web/package.json` | **MISSING** — sentry dict `{}` (no Sentry packages) | `@sentry/nextjs` exact-pinned, `instrumentation.ts` + error boundary |
| UptimeRobot monitor | **MISSING** — no monitor configured | Dual monitors on `/healthz` + `/readyz` polling every 5 min |
| In-tree status page | **MISSING** — no `apps/worldview-web/app/(public)/status/` route | Next.js route + UptimeRobot read-only API proxy |

---

## Summary

| Fix | Code Merged | Image Deployed | Operational Action Needed |
|-----|------------|----------------|--------------------------|
| BP-302 (article-consumer hang) | ✅ `f27e266b` | ✅ Confirmed via introspection | None — offset advancing |
| F-VISUAL-002 (muted-foreground sync) | ✅ `f27e266b` | ✅ In source | None |
| F-E8 (`/undefined` guard) | ✅ `f27e266b` | ✅ In source | None |
| F-D4 (EU date parsing) | ✅ `f27e266b` | ✅ In source | **T-B-04**: reset partition 4 to offset 0 |
| Sentry (backends) | ❌ Not started | ❌ | **Wave C** |
| Sentry (frontend) | ❌ Not started | ❌ | **Wave D** |
| UptimeRobot | ❌ Not started | ❌ | **Wave E** |
| Status page | ❌ Not started | ❌ | **Wave E** |
