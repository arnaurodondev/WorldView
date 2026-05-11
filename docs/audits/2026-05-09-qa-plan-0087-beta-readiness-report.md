# QA Report: PLAN-0087 Beta-Deployment Readiness

**Date**: 2026-05-09
**Skill**: qa
**Scope**: PLAN-0087 (full session: 17+ commits since `974f4f1d`)
**Branch**: `feat/content-ingestion-wave-a1`
**Verdict**: **PASS_WITH_WARNINGS for demo (GO) — REQUEST_CHANGES for beta deployment (NO_GO without 3-4 engineer-weeks of integration)**
**Bar**: hedge-fund analyst/trader using the platform daily, not demo-survival.

---

## Executive Summary

10 specialist agents reviewed the platform end-to-end against beta-deployment quality bars (real users, not a friendly walkthrough). They returned **~95 distinct findings** across 8 dimensions. The platform is **demo-functional today** (Phase A walkthrough surfaces verified live), but **NOT beta-ready for deployment inside a regulated financial firm** without ~3-4 engineer-weeks of integration work.

**The biggest revelation of this QA pass**: my own commit `92915986` (cooperative-sticky assignor) introduced a `max.poll.records` config field that is JAVA-ONLY — librdkafka rejects it, crashing every BaseKafkaConsumer in the platform. The article-consumer was wedged in a Restarting(1) crash-loop for hours, which is why the entire NLP pipeline looked silently broken (KG empty, 0 organic relations, 0 events). **Fixed in this QA pass.**

The chat tool-call rate ("11/13") was a metric-definition artifact: P13/P14 are correct cold-start refusals. The honest rate is **12/12 routings + 2/2 refusals = 100%**. Routing work is DONE.

---

## Multi-Agent Review Summary

| Agent | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | Report |
|---|---|---|---|---|---|---|
| QA/Test Engineer | 19 | 4 | 4 | 5 | 4 | qa-beta-test-engineer.md |
| Security | 22 | 3 | 4 | 8 | 7 | qa-beta-security.md |
| Data Platform | 18 | 5 | 7 | 6 | — | qa-beta-data-platform.md |
| Distributed Systems | 7 | 0 | 2 | 3 | 2 | qa-beta-distributed-systems.md |
| Architecture | 27 | 1 | 7 | 10 | 9 | qa-beta-architecture.md |
| Frontend Bug-hunt | 7 | 4 (HF demo) | — | — | 3 | qa-beta-frontend.md |
| LLM Quality | 18 | 3 | 6 | 6 | 3 | qa-beta-llm-quality.md |
| Data-plane Health | 12 | 8 | 1 | 1 | 2 | qa-beta-data-plane-health.md |
| Tool-call RCA | — | — | — | — | — | qa-beta-tool-call-rca.md (100% rate confirmed) |
| Beta-deployment Blockers | 16 | 7 (regulated-firm) | 9 | — | — | qa-beta-blockers.md |

---

## Cross-Agent High-Confidence Signals

Issues flagged by 2+ agents independently — these are HIGH confidence and demand attention:

1. **GLiNER class mismatch silently dropping all relation extraction** (LLM-Quality F-LLM-001 + Data-Platform F-002 + Data-plane Health D-P3-007): LLM extracts relations correctly, but the resolver maps `organization`-tagged GLiNER mentions to canonicals tagged `financial_instrument` → 100% drop rate. **3-hour fix unlocks 3 downstream pipelines** (relation_evidence_raw, KG growth, A4 graph density).
2. **R3 doc gap** (Architecture F-021 + Standards-rules audit): zero `docs/services/*.md` updates in 17 commits despite multi-service changes.
3. **Outbox schema drift** (Data-Platform F-003 + Distributed-Systems implicit): 5 different outbox table shapes across services — R8 violations at scale.
4. **JSON-error narratives leak** (LLM-Quality F-LLM-007): 8 demo-critical entities literally rendered `{"error": ...}` strings as narrative_text. **FIXED in this pass** via demote+repoint + container rebuild.
5. **JWT-aud test gap** (Test-Engineer F-001 + Security): the audience-claim enforcement was added to 6 services but no negative test asserts wrong/missing aud → 401.

---

## Fixes Landed in This QA Pass (4 commits)

```
<latest>   fix(kg): JSON-error narrative demote+repoint (in-DB only — 8 demo entities cleaned) ✅ LIVE
b6f23a92   fix(security+messaging): F-001 cross-tenant chunk-search leak + max.poll.records regression ✅ LIVE (consumers no longer crash)
81171b2e   feat(observability): default-startup Prometheus/Grafana/Tempo/Loki/Alertmanager ✅ LIVE (16 scrape targets up)
```

Plus runtime ops:
- KG scheduler force-rebuilt (`--no-cache`) so the JSON-error guard from commit `e6deebd6` is now in the running container.
- 8 JSON-error narrative_versions demoted (is_current=false); 5 demo entities (OpenAI, Anthropic, Coinbase, Netflix, Intel) now have NULL `current_narrative_version_id` so the frontend renders an empty state instead of error JSON.
- alertmanager.yml `${SLACK_WEBHOOK_URL}` substitution fix (Alertmanager doesn't expand env vars).
- tempo.yml updated to Tempo 2.7+ schema (`processor:` singular with sub-keys).
- Article-consumer brought back online with new max.poll.records-free config; consuming all 12 partitions.

---

## Beta-Readiness Verdict per Surface

| Surface | Demo (today) | Beta (1 firm) | Gap to close |
|---|---|---|---|
| **Login / Auth** | OK (dev-login) | NO-GO | Zitadel integration, MFA, password reset, email verify |
| **Dashboard A2** | OK | OK | Brief regen for 5 demo entities pending; otherwise functional |
| **Instrument page A4** | OK | WARN | Header populated; News tab functional; KG tab will be empty until GLiNER fix lands |
| **Chat A6/A7/A8** | OK | OK (with caveats) | Tool routing 100%; some downstream tools 503 (instruments/symbol 404) |
| **Screener A9** | OK | OK | screen_field_metadata=0 — populate from market-data |
| **Alerts A10** | OK | OK | — |
| **Portfolio Phase B** | OK | WARN | All routes 200; brokerage flow tested; but no settings UI for managing connections |
| **Brokerage connect** | OK (sandbox) | NO-GO | Production OAuth flow not certified |
| **Multi-tenant isolation** | unverified | NO-GO | DB filters in place, MinIO keys NOT tenant-prefixed (cross-tenant blob enumeration risk) |
| **Backups + DR** | n/a | NO-GO | No PITR, no restore drill, ephemeral docker volumes |
| **Encryption at rest** | n/a | NO-GO | Postgres TDE, MinIO SSE-S3 not configured |
| **Encryption in transit** | n/a | NO-GO | Plaintext intra-cluster (mTLS pending) |
| **GDPR right-to-delete** | n/a | NO-GO | No endpoint, no UI |
| **Observability** | OK (default-on this pass) | OK | 16 scrape targets up; Grafana dashboards + alerts wired |

---

## Top 10 Pre-Beta Action Items (Priority Order)

| # | Action | Severity | Effort | Owner |
|---|---|---|---|---|
| 1 | **GLiNER class-mismatch resolver** (LLM F-LLM-001) — single resolver patch unlocks relation_evidence_raw, KG depth, A4 graph density | BLOCKING | 3h | KG/NLP |
| 2 | **Zitadel deployment + Auth productionisation** | BLOCKING (beta) | 1-2 weeks | Auth/Platform |
| 3 | **Settings UI substance** (4/7 sub-pages currently placeholder) | BLOCKING (beta) | 1 week | Frontend |
| 4 | **Production backups + tested PITR drill** | BLOCKING (beta) | 3-5d | Platform |
| 5 | **Encryption at rest (Postgres TDE, MinIO SSE)** | BLOCKING (beta) | 2-3d | Platform |
| 6 | **Encryption in transit (mTLS)** | BLOCKING (beta) | 1 week | Platform |
| 7 | **GDPR right-to-delete endpoint + UI** | BLOCKING (beta) | 2-3d | Backend+Frontend |
| 8 | **MinIO tenant-keyspace prefixing** (cross-tenant blob enumeration risk) | CRITICAL | 1d | Storage |
| 9 | **Outbox schema unification** across 5 services | MAJOR | 2-3d | Platform |
| 10 | **Test coverage for the 4 BLOCKING test gaps** (JWT-aud negative, BriefArchiveWriteAdapter, IntelligenceAggregatesRepository, migration 0038) | MAJOR | 1d | QA |

**Aggregate effort: ~3-4 engineer-weeks** for minimum-beta in a single regulated firm (per qa-beta-blockers).

---

## Demo-Readiness Verdict (Today)

**GO with mitigations** — the platform is demo-functional with caveats:

✅ **What works today**:
- All 8 S9 endpoints return 200 (p95 <400ms)
- Chat tool-call rate 100% (was 0% pre-D-R1-001 fix)
- Real Llama 3.1 8B narratives flowing (5 demo entities currently NULL — frontend shows clean empty state instead of JSON-error leak; will repopulate on next 6h cron)
- Intelligence tab (`/v1/entities/{id}/intelligence`) returns real data with mean_support, relation_count, latest_evidence_at
- Instrument page-bundle resolves entity_id → ticker → instrument_id correctly
- Brief generation: Jinja-leak-stripped, citations enforced via prompt
- KG narrative cadence: fires 60s post-boot + every 6h
- 16 Prometheus scrape targets all "up"
- Grafana, Tempo, Loki, Alertmanager all healthy

⚠️ **Known demo-day caveats**:
- KG depth is thin — only 18 relations (cascade from D-P3-007 / GLiNER class mismatch). Demo flow that probes "show me the entity graph for OpenAI" will return a sparse graph.
- Some entity tools 503 due to downstream issues (instruments/symbol 404, search/chunks 500 on certain queries) — OK for scripted walkthrough but director's free-form prompts may hit them.
- Settings page tabs partially placeholder — director should not click Security/Integrations/Data tabs.

---

## Compounding Updates Needed (R3 / Architecture audit)

- `docs/BUG_PATTERNS.md` — add BP-442 (max.poll.records librdkafka incompatibility), BP-443 (Alertmanager env-var non-expansion), BP-444 (Tempo 2.7+ schema migration), BP-445 (JSON-error envelope masquerading as LLM output)
- `docs/services/knowledge-graph.md` — narrative cadence change (weekly → 6h + startup), JSON-error guard
- `docs/services/nlp-pipeline.md` — search/chunks tenant_id JWT-derived (security F-001 fix)
- `libs/messaging/.claude-context.md` — DOES NOT EXIST; create with cooperative-sticky default + max.poll.records anti-pattern
- ADR for cooperative-sticky default platform-wide
- `docs/MASTER_PLAN.md` — multi-tenant story (PLAN-0086)

---

## Verification Steps Post-Fix

```bash
# 1. Confirm no JSON-error narratives current
docker exec worldview-postgres-1 psql -U postgres -d intelligence_db -tAc "
SELECT COUNT(*) FROM entity_narrative_versions
WHERE is_current = true AND narrative_text ~ '^\\s*\\{' AND narrative_text ~ '\"error\"';"
# Expected: 0

# 2. Confirm article-consumer is consuming
docker exec worldview-kafka-1 kafka-consumer-groups --bootstrap-server localhost:9092 \
  --describe --group nlp-pipeline-group | head -15
# Expected: 12 partitions assigned, lag draining

# 3. Confirm tenant_id leak fixed
TOKEN=$(curl -fsS -X POST http://localhost:8000/v1/auth/dev-login \
  -H 'content-type: application/json' \
  -d '{"email":"demo@worldview.local"}' | jq -r .access_token)
curl -sS -X POST http://localhost:8000/v1/search/chunks \
  -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"query_text":"x","tenant_id":"00000000-0000-0000-0000-000000000099"}'
# Expected: tenant_id in body IGNORED; route uses request.state.tenant_id

# 4. Confirm observability stack
curl -sS http://localhost:9090/api/v1/targets | jq '[.data.activeTargets[] | .health] | group_by(.) | map({h: .[0], n: length})'
# Expected: [{h:"up", n:16}]
```

---

**End of QA report.**

> Compounding check: BP-442/443/444/445 ready to add to BUG_PATTERNS.md; libs/messaging/.claude-context.md to be created; ADR for cooperative-sticky pending. R3 doc updates queued in qa-beta-architecture.md §F-021.
