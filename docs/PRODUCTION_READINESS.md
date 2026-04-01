# Production Readiness Checklist

> **Purpose**: Track all changes required to migrate the worldview platform from local Docker Compose development to a production-ready deployment.
> **Status**: Draft — items are categorized by priority and effort.
> **Last updated**: 2026-03-30

---

## Legend

| Priority | Meaning |
|----------|---------|
| P0 | **Blocking** — must fix before any production deployment |
| P1 | **Critical** — must fix before serving real users |
| P2 | **Important** — should fix within first production sprint |
| P3 | **Nice-to-have** — improve as the platform matures |

---

## 1. Secrets & Credential Management

| # | Item | Priority | Status | Notes |
|---|------|----------|--------|-------|
| 1.1 | Replace all hardcoded dev credentials (postgres/postgres, minioadmin, admin/admin) with injected secrets | P0 | TODO | Docker Compose uses plaintext defaults; production must use external secret store (Vault, AWS SSM, K8s secrets) |
| 1.2 | Remove default values from sensitive config fields (`jwt_secret`, API keys) — make them required | P0 | TODO | `api-gateway` has `jwt_secret = "dev-secret-change-me"`; content-ingestion has empty API key defaults |
| 1.3 | Rotate all dev credentials that have been committed to git history | P0 | TODO | Even though `.env` is gitignored, `docker.env` examples contain real-ish defaults |
| 1.4 | Set up secret rotation policy for database passwords, API keys, JWT signing keys | P2 | TODO | |
| 1.5 | Implement startup validation: crash if required secrets are empty/default | P1 | TODO | Add pydantic validator that rejects known dev values in production mode |
| 1.6 | Replace all `minioadmin` defaults in `docker.env.example` files with `<CHANGE_ME>` — use Docker secrets or Vault for production injection | P0 | PARTIAL | Added "Dev default — replace with real credentials" comment to all 9 service docker.env.example files (PLAN-0008 Wave F-1). Full `<CHANGE_ME>` replacement tracked as follow-up. |
| 1.7 | Replace all `internal_service_token = ""` empty defaults with a mandatory non-empty secret injected at deploy time | P0 | TODO | Affects portfolio and market-ingestion. Empty token means the X-Internal-Token auth header accepts any request. |
| 1.8 | Switch `warnings.warn` for missing secrets to `structlog` WARNING | P1 | DONE | Replaced `warnings.warn` with `structlog.get_logger().warning()` in market-ingestion and portfolio configs. PLAN-0008 Wave F-1 (T-F-1-02). |

---

## 2. TLS / Encryption

| # | Item | Priority | Status | Notes |
|---|------|----------|--------|-------|
| 2.1 | Enable TLS on all service-to-service communication | P0 | TODO | Currently all HTTP. Kafka, Postgres, Valkey, MinIO all use plaintext |
| 2.2 | Enable TLS on Alloy → Tempo OTLP exporter (`insecure = true` → `false`) | P1 | TODO | Traces may contain PII (user IDs, query params) |
| 2.3 | Enable TLS on Alloy → Loki log push | P1 | TODO | Logs may contain sensitive data |
| 2.4 | Configure HTTPS termination at load balancer / reverse proxy for API Gateway | P0 | TODO | Frontend → Gateway must be HTTPS |
| 2.5 | Enable Kafka TLS (SASL_SSL) for broker connections | P1 | TODO | All 6 services connect to Kafka over plaintext |
| 2.6 | Enable PostgreSQL `sslmode=require` in all database URLs | P1 | TODO | |
| 2.7 | Enable MinIO TLS for object storage connections | P2 | TODO | |

---

## 3. Authentication & Authorization

| # | Item | Priority | Status | Notes |
|---|------|----------|--------|-------|
| 3.1 | Replace dev JWT secret with production-grade key (RS256 asymmetric recommended) | P0 | TODO | Currently HS256 with dev-secret default |
| 3.2 | Implement proper user registration / OAuth2 flow | P0 | TODO | Current JWT is manually issued; no user management |
| 3.3 | Add tenant isolation to all database queries (WHERE tenant_id = ...) | P0 | TODO | Multi-tenancy design exists but not enforced at query level everywhere |
| 3.4 | Protect `/metrics` endpoints — bind to internal interface only or add network-level access controls | P1 | TODO | Currently exposed on 0.0.0.0; metrics expose request rates, latencies, queue depths — operational intelligence. Ref: F-SEC-010, PLAN-0008. |
| 3.5 | Protect `/readyz` and admin endpoints from external access | P1 | TODO | Readyz leaks dependency health details |
| 3.6 | Add rate limiting to API Gateway (middleware exists but not wired) | P1 | TODO | `RateLimitMiddleware` defined but not applied |
| 3.7 | Restrict CORS origins to production frontend domain only | P1 | TODO | Currently `allow_methods=["*"]`, `allow_headers=["*"]` |
| 3.8 | Implement API key management for external data provider access | P2 | TODO | |

---

## 4. Database

| # | Item | Priority | Status | Notes |
|---|------|----------|--------|-------|
| 4.1 | Run all Alembic migrations on production database(s) | P0 | TODO | Services: portfolio, market-ingestion, market-data, content-ingestion, content-store, intelligence-migrations |
| 4.2 | Set up read replicas for market-data (TimescaleDB) and portfolio | P2 | TODO | `read_replica_url` config field exists in market-data |
| 4.3 | Configure connection pooling (PgBouncer or similar) | P1 | TODO | Direct asyncpg connections may exhaust pool under load |
| 4.4 | Set up automated backups with point-in-time recovery | P0 | TODO | |
| 4.5 | Review and tune PostgreSQL configuration (shared_buffers, work_mem, etc.) | P2 | TODO | |
| 4.6 | Enable query logging / slow query detection | P2 | TODO | |
| 4.7 | Set up TimescaleDB continuous aggregates for OHLCV rollups | P3 | TODO | Improves chart query performance |

---

## 5. Kafka & Event Streaming

| # | Item | Priority | Status | Notes |
|---|------|----------|--------|-------|
| 5.1 | Deploy multi-broker Kafka cluster (minimum 3 brokers) | P1 | TODO | Currently single broker in Docker |
| 5.2 | Configure topic replication factor ≥ 2 | P1 | TODO | Single broker = no replication |
| 5.3 | Set up Schema Registry with authentication | P1 | TODO | Currently unauthenticated |
| 5.4 | Configure Kafka SASL_SSL authentication | P1 | TODO | See §2.5 |
| 5.5 | Tune consumer group rebalance settings for production load | P2 | TODO | |
| 5.6 | Set up dead letter topic monitoring and alerting | P1 | TODO | DLQ tables exist per service but no alerting |
| 5.7 | Configure topic retention policies per topic | P2 | TODO | |
| 5.8 | Before any non-fresh deployment, drain `market.events.v1` topic to zero consumer lag before deploying topic-alignment wave — or add a one-time bridge consumer | P1 | TODO | Ref: F-DS-014 PLAN-0001-E-R1 Wave 5. Existing consumers may be reading from old topic name; abrupt switch drops in-flight events. |

---

## 6. Object Storage (MinIO → S3)

| # | Item | Priority | Status | Notes |
|---|------|----------|--------|-------|
| 6.1 | Migrate from MinIO to AWS S3 (or production-grade MinIO cluster) | P1 | TODO | `libs/storage` abstracts this; config change only |
| 6.2 | Configure bucket policies and IAM roles per service | P1 | TODO | Currently all services use same minioadmin credentials |
| 6.3 | Enable server-side encryption (SSE-S3 or SSE-KMS) | P2 | TODO | |
| 6.4 | Set up lifecycle rules for bronze/silver tier data retention | P2 | TODO | |
| 6.5 | Enable bucket versioning for critical buckets | P3 | TODO | |

---

## 7. Observability & Monitoring

| # | Item | Priority | Status | Notes |
|---|------|----------|--------|-------|
| 7.1 | Deploy production monitoring stack (Prometheus, Grafana, Tempo, Loki) | P1 | TODO | Docker Compose stack exists (`--profile monitoring`); needs cloud-native deployment |
| 7.2 | Create Grafana dashboards: per-service health, Kafka lag, DB connections | P1 | TODO | Datasources provisioned; dashboards not yet created |
| 7.3 | Set up alerting rules: error rate > threshold, consumer lag, DB pool exhaustion | P1 | TODO | |
| 7.4 | Configure log retention and rotation in Loki | P2 | TODO | |
| 7.5 | Add structured log sanitization processor to strip PII/secrets | P1 | TODO | structlog processors exist but no PII filter |
| 7.6 | Enable distributed tracing sampling (not 100% in production) | P2 | TODO | Currently all spans exported |
| 7.7 | Set up uptime monitoring for external endpoints | P2 | TODO | |

---

## 8. Deployment & Infrastructure

| # | Item | Priority | Status | Notes |
|---|------|----------|--------|-------|
| 8.1 | Create production Dockerfiles (multi-stage, non-root user, minimal base) | P0 | TODO | Current Dockerfiles exist but need hardening |
| 8.2 | Set up Kubernetes manifests or Docker Swarm stack | P0 | TODO | Currently Docker Compose only |
| 8.3 | Configure resource limits (CPU, memory) per service | P1 | TODO | |
| 8.4 | Set up horizontal pod autoscaling for stateless services (S9, S1, S3) | P2 | TODO | |
| 8.5 | Configure health check probes (liveness, readiness, startup) in K8s | P1 | TODO | `/healthz` and `/readyz` endpoints ready |
| 8.6 | Set up a reverse proxy / load balancer (nginx, Traefik, or cloud LB) | P0 | TODO | |
| 8.7 | Configure graceful shutdown timeouts matching Kafka consumer commit intervals | P1 | TODO | |
| 8.8 | Add `portfolio-instrument-consumer` as an independent container in production manifests | P1 | DONE | Extracted from API process in PLAN-0008 Wave C-3; added to docker-compose.yml as `portfolio-instrument-consumer`. K8s manifests pending. |
| 8.9 | Add `max_length=200` to `BatchQuoteRequest.instrument_ids` and all unbounded list query parameters in market-data | P1 | DONE | Added `max_length=200` to `BatchQuoteRequest.instrument_ids`, `/quotes/latest` Query, and `/ohlcv/bulk` Query. PLAN-0008 Wave F-1 (T-F-1-03). |

---

## 9. CI/CD Pipeline

| # | Item | Priority | Status | Notes |
|---|------|----------|--------|-------|
| 9.1 | Set up GitHub Actions CI: lint, type-check, unit tests, contract tests | P0 | TODO | Pre-commit hooks exist locally; need CI equivalent |
| 9.2 | Add integration test stage with testcontainers in CI | P1 | TODO | |
| 9.3 | Set up container image build and push to registry | P0 | TODO | |
| 9.4 | Implement deployment pipeline (staging → production) | P1 | TODO | |
| 9.5 | Add Avro schema compatibility check in CI | P1 | TODO | `scripts/gen-contracts.sh` exists |
| 9.6 | Set up dependency vulnerability scanning (Dependabot, Snyk) | P2 | TODO | |
| 9.7 | Implement database migration CI step (dry-run, then apply) | P1 | TODO | |

---

## 10. Scaling & Performance

| # | Item | Priority | Status | Notes |
|---|------|----------|--------|-------|
| 10.1 | Load test critical paths: OHLCV queries, news feed, chatbot | P1 | TODO | Non-functional target: <200ms p95 charts, <500ms news |
| 10.2 | Configure Valkey (Redis) cluster mode for caching layer | P2 | TODO | Currently single-node Valkey |
| 10.3 | Implement query result caching for frequently accessed instruments | P2 | TODO | QuoteCache exists for market-data |
| 10.4 | Configure Kafka consumer parallelism (partition count vs consumer count) | P2 | TODO | |
| 10.5 | Set up connection pooling for external API calls (httpx limits) | P2 | TODO | httpx.AsyncClient has default pool limits |

---

## 11. Data Providers & External APIs

| # | Item | Priority | Status | Notes |
|---|------|----------|--------|-------|
| 11.1 | Secure production API keys for EODHD, Finnhub, NewsAPI, SEC EDGAR | P0 | TODO | Currently using demo/empty keys |
| 11.2 | Implement API key rotation without downtime | P2 | TODO | |
| 11.3 | Set up rate limit monitoring per provider | P1 | TODO | TokenBucket exists in S4 but no monitoring |
| 11.4 | Configure fallback/degradation when a provider is unavailable | P2 | TODO | |

---

## 12. ML / LLM Infrastructure

| # | Item | Priority | Status | Notes |
|---|------|----------|--------|-------|
| 12.1 | Deploy Ollama (or alternative LLM) with GPU support | P1 | TODO | S6 NLP pipeline and S8 RAG need embedding + generation models |
| 12.2 | Configure model caching and warm-up | P2 | TODO | First request to Ollama is slow (model loading) |
| 12.3 | Implement LLM request queuing with backpressure | P1 | TODO | Semaphore-based concurrency limiting needed |
| 12.4 | Set up model versioning and A/B testing capability | P3 | TODO | |

---

## 13. Frontend

| # | Item | Priority | Status | Notes |
|---|------|----------|--------|-------|
| 13.1 | Build production frontend bundle (Vite build, minified) | P0 | TODO | |
| 13.2 | Configure CDN for static asset delivery | P2 | TODO | |
| 13.3 | Set up CSP (Content Security Policy) headers | P1 | TODO | |
| 13.4 | Configure frontend error reporting (Sentry or equivalent) | P2 | TODO | |
| 13.5 | Implement frontend feature flags for gradual rollout | P3 | TODO | |

---

## 14. Compliance & Documentation

| # | Item | Priority | Status | Notes |
|---|------|----------|--------|-------|
| 14.1 | Document data flow for GDPR compliance (what PII is stored, where, retention) | P1 | TODO | Platform stores email only; but external content may contain PII |
| 14.2 | Implement data retention policies and automated cleanup | P2 | TODO | |
| 14.3 | Create runbook for common operational tasks (restart, scale, debug) | P1 | TODO | |
| 14.4 | Document disaster recovery procedure | P2 | TODO | |
| 14.5 | Create architecture decision records (ADRs) for production choices | P2 | TODO | ADR template exists at `docs/architecture/decisions/ADR_TEMPLATE.md` |

---

## Summary by Priority

| Priority | Count | Description |
|----------|-------|-------------|
| P0 | 16 | Must fix before any production deployment |
| P1 | 34 | Must fix before serving real users |
| P2 | 22 | Should fix within first production sprint |
| P3 | 5 | Nice-to-have improvements |
| **Total** | **77** | |

---

## Quick Wins (low effort, high impact)

These can be done immediately with minimal code changes:

1. **Remove default JWT secret** — make `jwt_secret` required (no default)
2. **Restrict CORS origins** — change `allow_methods/headers` to explicit whitelist
3. **Wire rate limiting middleware** in API Gateway
4. **Add startup secret validation** — pydantic validators that reject dev defaults
5. **Set `sslmode=require`** in database URL config defaults
6. **Sanitize `/readyz` responses** — return generic status, not exception details
