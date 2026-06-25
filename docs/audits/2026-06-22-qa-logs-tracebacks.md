# QA Log & Traceback Sweep — 2026-06-22

**Mode:** READ-ONLY (docker logs / ps / inspect only — no edits, commits, or restarts).
**Scope:** All 88 running `worldview-*` containers (+ 4 `unit_*` containers, out of scope).
**Window:** `docker logs --since 15m` per container (~10:18–10:33 UTC). A full rebuild + redeploy completed at ~10:25 UTC, so the window straddles a cold boot — most "errors" are boot-transient connection races that self-healed by the next tick.
**Method:** Per-container grep for `traceback|error|exception|critical|fatal|failed|panic|exit|refused|timed out|unhandled`, tallied, classified by severity (HIGH = crash / data-loss / repeated steady-state traceback; MED = recurring handled error or high-volume noise; LOW = boot-transient or dev-config warning), and checked for recency (still firing at ~10:33 vs. boot-only).

No secrets, tokens, or keys appeared in any matched log line.

---

## Ranked Issue Table (HIGH → LOW)

| # | Container | Severity | Recurring? | NEW / pre-existing | Signature | Representative line (redacted) |
|---|-----------|----------|------------|--------------------|-----------|--------------------------------|
| 1 | `nlp-pipeline-article-consumer-1` | **HIGH** | **Yes — still firing at 10:33** | Pre-existing (known `statement_timeout` pattern) | `asyncpg.QueryCanceledError: canceling statement due to statement timeout` on `INSERT INTO provisional_entity_queue ... ON CONFLICT ... RETURNING queue_id`. Mention is then **`downgraded_to: "unresolved"`** → silent entity-resolution data loss. | `entity_resolution.provisional_insert_failed ... QueryCanceledError: canceling statement due to statement timeout ... downgraded_to: "unresolved"` |
| 2 | `portfolio-manual-holdings-worker-1` | **HIGH (health)** | Yes (healthcheck) | Pre-existing (known unhealthy) | Container `Up 4 min (unhealthy)`. Healthcheck probe traceback: `urllib.error.URLError: <urlopen error [Errno 111] Connection refused>`. App logs themselves are clean (no in-process errors) — the worker's HTTP health endpoint is not accepting connections. | `urllib.error.URLError: <urlopen error [Errno 111] Connection refused>` (from `docker inspect` health log) |
| 3 | `nlp-pipeline-price-impact-worker-1` | **MED** (was HIGH at boot) | No — last error 10:26:44, **silent since** | Pre-existing | Boot-time hot loop: 513 errors in window. Interleaved `market_data_client_token_mint_failed status_code=429` (dev-login rate-limited, `will_retry=false` → no backoff) **and** `market_data_resolve_request_error error="[Errno -2] Name or service not known"` (DNS to market-data failed during boot). Self-inflicted 429s from minting a fresh dev-login token per ticker. Recovered once market-data DNS resolved. | `market_data_client_token_mint_failed status_code=429 will_retry=false` / `market_data_resolve_request_error ticker="SCHD" error="[Errno -2] Name or service not known"` |
| 4 | `portfolio-snapshot-worker-1` | **MED** | No — one-time startup catch-up burst, now idle (`sleeping`) | Pre-existing | 540× `ohlcv_price_fetch_error` (`ConnectError` to market-data) during startup historical backfill. Degrades gracefully → falls back to `cost_basis` and writes snapshot. Consequence: seeded-instrument valuations for 2026-05-29→06-22 read at cost, not market. Burst ended (`startup_catchup_complete`). | `ohlcv_price_fetch_error ... error:"ConnectError" ... level:"warning"` |
| 5 | `schema-registry-1` | **MED** | Yes (low rate) | Pre-existing | 28× `javax.ws.rs.NotFoundException: HTTP 404 Not Found` — clients probing subjects not yet registered post-restart. No 409/incompatibility errors; `GET /subjects` returns 200 (registry healthy). | `ERROR Request Failed with exception (DebuggableExceptionMapper) javax.ws.rs.NotFoundException: HTTP 404 Not Found` |
| 6 | `postgres-intelligence-1` | **MED** | Yes (3× in ~18s, 10:31) | Pre-existing (KG/promoter long-query pattern) | `ERROR: canceling statement due to statement timeout` — steady-state, not boot. Same root cause family as issue #1 (statement_timeout guard firing on intelligence_db). | `ERROR: canceling statement due to statement timeout` |
| 7 | `alertmanager-1` | **MED (noise)** | Yes (140×) | Pre-existing (dev env) | Email notify failing — `lookup mailhog on 127.0.0.11:53: no such host`. MailHog not running (not started without `make dev`). Cosmetic, off data path. | `Notify for alerts failed ... lookup mailhog ... no such host` |
| 8 | `loki-1` | **MED (noise)** | Yes (164×) | Pre-existing | `negative structured metadata bytes received ... size=0` — Loki/Alloy version-skew warning on push. Logs still ingesting. Cosmetic. | `caller=push.go:202 msg="negative structured metadata bytes received" ... size=0` |
| 9 | `rag-chat-brief-scheduler-1` | **LOW** | No — boot-only, silent since 10:29 | Pre-existing | 2× boot-time upstream errors reaching S1/instruments before they were up: `[Errno -2] Name or service not known` + `ConnectError` on `/api/v1/instruments/lookup`. Handled (warning). Recovered. | `upstream_request_error ... error:"[Errno -2] Name or service not known"` |
| 10 | `content-ingestion-scheduler-1` | **LOW** | No — single boot event | Pre-existing | One `ticker_news_sync_market_data_error` (httpx ConnectError to `market-data:8003`) at 10:29; ~42 traceback render lines = 1 event. Healthy `scheduler_tick_complete` since. | `ticker_news_sync_market_data_error url=http://market-data:8003/internal/v1/instruments` |
| 11 | `market-ingestion-scheduler-1` | **LOW** | No — boot race | Pre-existing | 3× `httpx.ConnectError: All connection attempts failed` to `market-data:8003` (fundamentals refresh + instrument policy sync US/CC) at 10:30:08. Recovered next tick. | `fundamentals_refresh_endpoint_error url=.../top-by-market-cap` |
| 12 | `alert-rule-poller-1` | **LOW** | No — single boot event | Pre-existing | 1× `asyncpg.CannotConnectNowError: ... Consistent recovery state has not been yet reached` at 10:25:39 (Postgres still in recovery at boot). All subsequent ticks OK. | `rule_poll_cycle_failed ... the database system is not yet accepting connections` |
| 13 | `api-gateway-1` | **LOW** | No — boot | Pre-existing (by design) | 3× `oidc_discovery_attempt_failed` → `oidc_discovery_skipped` (`OIDC_DISCOVERY_OPTIONAL=true; starting with internal-JWT-only auth`). Expected when Zitadel not configured. | `oidc_discovery_skipped detail="OIDC_DISCOVERY_OPTIONAL=true; starting with internal-JWT-only auth"` |
| 14 | `kafka-1` | **LOW** | No — boot rebalance | Pre-existing | 5× GroupCoordinator `Member ... has failed, removing from group` — consumer rebalance churn after restart (nlp, market-data, kg groups). No broker/GC/ISR errors. | `Member rdkafka-... in group nlp-pipeline-group has failed, removing it from the group` |
| 15 | `postgres-1` | **LOW** | No — boot | Pre-existing | 1× `FATAL: the database system is not yet accepting connections` then `ready to accept connections` at 10:25:53. Pure startup race. | `FATAL: the database system is not yet accepting connections` |
| 16 | `synthetic-monitor-1` | **LOW** | No — boot | Pre-existing | 2× `probe_failed` at 10:25:29 during boot; steady `GET /healthz 200` after. (Recurring `401` on `/v1/quotes` is expected — probe lacks JWT — did not match grep.) | `ERROR probe_failed` |
| 17 | `postgres_exporter-1` | **LOW** | No | Pre-existing | 1× `Error loading config ... postgres_exporter.yml: no such file` — warn only, falls back to env DSN. | `level=warn msg="Error loading config"` |
| — | `knowledge-graph-1`, `nlp-pipeline-1`, `market-ingestion-1`, `content-ingestion-1`, `content-store-1`, `alert-1` | **LOW (info)** | n/a | n/a | `internal_jwt_skip_verification_enabled` logged at `critical` level — **dev-mode config notice**, NOT a runtime fault (JWT signature verification disabled because no Zitadel locally). Would matter only in production. | `InternalJWTMiddleware signature verification is DISABLED` |

---

## Clean containers (0 real matches)

`rag-chat-1`, `portfolio-1`, `portfolio-manual-holdings-worker-1` (app logs only — see #2 for health), `worldview-web-1` (see note below), all `market-data-*` consumers, `market-ingestion-{dispatcher,worker}`, `content-{ingestion,store}` dispatchers/consumers, all `knowledge-graph-*` consumers/dispatcher/workers (entity, enriched, fundamentals, instrument(-discovered), temporal-event, path-insight, provisional-queued, datasets), `nlp-pipeline` consumers 2/3, dispatcher, deletion/embedding-retry/entity-refresh/relevance-scoring/unresolved-resolution/watchlist workers, `ollama-1`, `gliner-server-1`, all `alert-*` (dispatcher, email-scheduler, intelligence/watchlist consumers), all remaining `portfolio-*` (brokerage-sync, dispatcher, instrument-consumer, manual-holdings-consumer), `minio-1`, `valkey-1`, `prometheus-1`, `grafana-1`, `tempo-1`, `alloy-1`, `pushgateway-1`, `redis_exporter-1`, `kafka-ui-1`, `pgweb-1`.

Counts surfacing the literal substring `failed` inside healthy `*_cycle_complete` logs (`"failed": 0`), Prometheus metric-family names (`fundamentals_refresh_failed`), or `"skipped": N` info lines were verified as false positives.

---

## Notes on the two "known-already" items

- **`worldview-web-1`**: the **running container is healthy** (`Up 7 hours (healthy)`), actively serving `GET /api/version` every ~15s with no errors. The known `pnpm build` failure is a separate build-artifact concern that does not affect this running instance. Out of scope for this sweep beyond confirming the live container is clean.
- **`portfolio-manual-holdings-worker-1`**: confirmed `unhealthy` (#2). The container's own application logs are clean — the unhealthy state comes from the Docker healthcheck probe getting `Connection refused [Errno 111]`, i.e. the worker's HTTP health endpoint is not listening. Health/pipeline ownership belongs to another agent; characterized only.

---

## Recommended priority

1. **Issue #1 (`article-consumer-1` statement timeout → unresolved downgrade)** — the only HIGH that is **actively recurring and causing data loss**. `INSERT INTO provisional_entity_queue` on consumer-1 is hitting `statement_timeout` (consumers 2 & 3 clean → lock/contention on `provisional_entity_queue`, not a global DB outage). Each failure silently downgrades a mention to `unresolved`. This is the same `statement_timeout` family flagged in prior CPU-bottleneck work and overlaps issue #6 (`postgres-intelligence` timeouts). **Top fix candidate.**
2. **Issue #2** — manual-holdings-worker health endpoint refusing connections (route to health-owning agent).
3. **Issues #3/#4** — boot-only market-data DNS/connect races; verify market-data ordering/readiness gating but no live impact now. Note #3's design smell: dev-login token minted per-request with `will_retry=false` self-inflicts 429s — worth caching the token.
4. Issues #5–#8 are recurring-but-benign (registry 404 probes, intelligence statement_timeout to watch, MailHog/Loki noise). #9–#17 are boot-transient and self-healed.
