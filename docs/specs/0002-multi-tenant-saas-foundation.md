# PRD-0002: Multi-Tenant SaaS Foundation

**Version**: 1.0
**Date**: 2026-03-26
**Status**: Draft — Pending Review
**Owner**: Arnau Rodon
**Depends on**: PRD-0001 (Intelligence Pipeline)

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Users & Personas](#2-users--personas)
3. [Functional Requirements](#3-functional-requirements)
4. [Non-Functional Requirements](#4-non-functional-requirements)
5. [Out of Scope](#5-out-of-scope)
6. [Technical Design](#6-technical-design)
7. [Architecture Decisions](#7-architecture-decisions)
8. [Security Design](#8-security-design)
9. [Failure Modes & Recovery](#9-failure-modes--recovery)
10. [Scalability & Performance](#10-scalability--performance)
11. [Test Strategy](#11-test-strategy)
12. [Migration Strategy](#12-migration-strategy)
13. [Observability](#13-observability)
14. [Open Questions](#14-open-questions)
15. [Future Work (PRD-0003+)](#15-future-work-prd-0003)

---

## 1. Problem Statement

Worldview's intelligence pipeline (PRD-0001) was designed as a thesis-grade system where all intelligence data — entities, relations, claims, contradictions — is shared and public. There is no concept of private data, no self-serve onboarding, and no usage-based cost attribution. This architecture cannot support a commercial SaaS product where:

1. **Enterprise clients need private intelligence** — proprietary entities, relations, and enrichments that must never leak to other tenants.
2. **Self-serve onboarding is required** — users must be able to sign up, verify their email, and start using the platform without manual intervention.
3. **Usage must be attributed and limited** — per-tenant rate limiting prevents abuse, and LLM cost tracking enables future billing.
4. **Identity must be robust** — the current HS256 JWT with a hardcoded dev secret is not production-grade.

PRD-0001 §10.6 designed the migration path for tenant-scoped intelligence (nullable `tenant_id` columns) but deferred implementation. This PRD implements that path along with the auth, provisioning, and rate-limiting infrastructure required for a commercial launch.

### 1.1 Relationship to PRD-0001

This PRD is **additive** — it builds on PRD-0001 without contradicting or replacing it. All changes are backward-compatible:
- Existing public intelligence data remains `tenant_id = NULL` and visible to all tenants.
- No existing tables are dropped or renamed.
- No existing Kafka topics or Avro schemas are broken.

---

## 2. Users & Personas

### 2.1 Free-Tier User
- Signs up via Keycloak self-serve flow
- Gets a personal tenant automatically (1 user = 1 tenant)
- Accesses shared/public intelligence data only
- Subject to standard rate limits (20 req/min default)
- No private intelligence capabilities

### 2.2 Pro-Tier User
- Upgraded by admin (manual tier assignment for now)
- All Free capabilities plus:
  - Can create **private entities** and **private relations** visible only to their tenant
  - Higher rate limits (200 req/min default)
  - LLM usage tracked and visible per tenant

### 2.3 Enterprise-Tier User
- Onboarded via admin/sales process
- All Pro capabilities plus:
  - Highest rate limits (1000 req/min default, or custom)
  - Future: data export, RBAC, document upload (PRD-0003)

### 2.4 Platform Admin
- Internal user with admin access
- Can list, inspect, suspend, and upgrade/downgrade tenants
- Can view aggregate LLM cost attribution across tenants

---

## 3. Functional Requirements

| ID | Requirement | Priority | Description |
|----|-------------|----------|-------------|
| FR-01 | Keycloak integration | MUST | Add Keycloak to infrastructure, configure `worldview` realm with two clients |
| FR-02 | Self-serve sign-up | MUST | Users register via Keycloak UI, email verified, tenant created automatically |
| FR-03 | JWT validation via JWKS | MUST | S9 validates RS256 JWTs using Keycloak's JWKS endpoint (cached) |
| FR-04 | Tenant auto-provisioning | MUST | Keycloak registration event triggers S1 tenant + user creation |
| FR-05 | Billing tiers | MUST | Free / Pro / Enterprise tiers stored on tenant, reflected in JWT claims |
| FR-06 | Tenant-scoped intelligence | MUST | Nullable `tenant_id` on `canonical_entities`, `relations`, `claims`, `events`, `entity_embedding_state`, `llm_usage_log` |
| FR-07 | Tenant-scoped queries | MUST | All intelligence queries filter: `WHERE tenant_id IS NULL OR tenant_id = :current_tenant_id` |
| FR-08 | Private entity creation | MUST | Pro/Enterprise tenants can create entities with `tenant_id` set |
| FR-09 | Private relation creation | MUST | Pro/Enterprise tenants can create relations with `tenant_id` set |
| FR-10 | Entity reuse | MUST | Entity resolution searches public + own private entities; reuses existing matches |
| FR-11 | Per-tenant rate limiting | MUST | Valkey-based sliding window keyed on `{tenant_id}:{endpoint_group}` |
| FR-12 | Tier-based rate limits | MUST | Different limits per tier and endpoint group, env-configurable |
| FR-13 | LLM cost attribution | MUST | `tenant_id` column on `llm_usage_log` for per-tenant cost queries |
| FR-14 | Tenant management API | MUST | Admin-only endpoints: list, get, update tier, suspend tenants |
| FR-15 | Tenant context propagation | MUST | S9 extracts `tenant_id`, `tier` from JWT, injects as headers to downstream services |

---

## 4. Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-01 | Rate limit defaults | Free: 20/min, Pro: 200/min, Enterprise: 1000/min (env-configurable per endpoint group) |
| NFR-02 | Tenant isolation guarantee | No tenant can ever read, write, or infer another tenant's private data |
| NFR-03 | Zero-downtime migration | Adding `tenant_id` columns uses `DEFAULT NULL`, no table locks on existing data |
| NFR-04 | JWKS cache TTL | 1 hour; S9 continues validating tokens during brief Keycloak outages |
| NFR-05 | Registration latency | Tenant creation completes within 2 seconds of Keycloak registration event |
| NFR-06 | Rate limit fail-open | If Valkey is unavailable, requests are allowed (existing behavior preserved) |
| NFR-07 | Backward compatibility | All existing public intelligence remains `tenant_id = NULL`, visible to all |
| NFR-08 | Auth algorithm | RS256 (asymmetric) via Keycloak JWKS, replacing HS256 with hardcoded secret |

---

## 5. Out of Scope

| Item | Deferred To | Rationale |
|------|-------------|-----------|
| API key management | PRD-0003 | Keycloak client credentials grant covers programmatic access for now |
| Data export (JSONL/Parquet) | PRD-0003 | Not needed for launch |
| Audit logging | PRD-0003 | Compliance feature, not launch-blocking |
| RBAC (roles within tenant) | PRD-0003 | 1 user = 1 tenant eliminates the need; required when invite flow lands |
| Tenant document upload | PRD-0003 | Major pipeline change (S4→S5→S6→S7 tenant-aware); separate PRD |
| Custom entity/relation specification | PRD-0003 | Depends on tenant upload pipeline |
| Self-serve billing (Stripe) | Future | Manual tier assignment sufficient for early customers |
| Data residency controls | Future | Single-region deployment for launch |
| Private-to-public entity merging | Future | Tracked in `docs/TECH_DEBT.md`; complex, deferred to admin tool |
| Tenant invite flow (multi-user tenants) | PRD-0003 | 1:1 user-tenant mapping sufficient for launch |
| Schema-per-tenant isolation | Never | Shared-DB with `tenant_id` columns is the chosen isolation model |

---

## 6. Technical Design

### 6.1 Affected Services

| Service | Change Type | Summary |
|---------|------------|---------|
| **infra** | NEW + MODIFIED | Add Keycloak to Docker Compose, realm config, env vars |
| **S9 (API Gateway)** | MODIFIED | Replace HS256 auth with Keycloak JWKS validation; per-tenant rate limiting; tenant context injection |
| **S1 (Portfolio)** | MODIFIED | Add `tier`, `keycloak_id` to tenants; `keycloak_user_id` to users; internal registration endpoint |
| **intelligence-migrations** | MODIFIED | New migration: add nullable `tenant_id` to 6 tables + indexes |
| **S6 (NLP Pipeline)** | MODIFIED | Tenant-aware entity resolution (search public + tenant-private) |
| **S7 (Knowledge Graph)** | MODIFIED | Tenant-scoped relation writes; tenant-aware confidence queries |
| **libs/common** | MODIFIED | Add `TenantTier` enum, rate limit config types |

### 6.2 API Changes

#### 6.2.1 S9 — API Gateway

##### Auth Middleware (Modified)

**Current**: `AuthMiddleware` decodes HS256 JWT with hardcoded secret, sets `request.state.user`.

**New**: `KeycloakAuthMiddleware` validates RS256 JWT via JWKS endpoint.

| Aspect | Current | New |
|--------|---------|-----|
| Algorithm | HS256 | RS256 |
| Secret source | `jwt_secret` env var (hardcoded default) | Keycloak JWKS endpoint (public keys) |
| Validation | `jwt.decode()` with secret | `jwt.decode()` with JWKS public key, issuer check, audience check |
| Claims extracted | Arbitrary dict | `sub`, `tenant_id`, `tier`, `email` |
| Header injection | None | `X-Tenant-ID`, `X-User-ID`, `X-Tenant-Tier` to downstream |

**JWKS Configuration:**
| Setting | Type | Default | Env Var | Description |
|---------|------|---------|---------|-------------|
| `keycloak_url` | str | `http://keycloak:8080` | `KEYCLOAK_URL` | Keycloak base URL |
| `keycloak_realm` | str | `worldview` | `KEYCLOAK_REALM` | Realm name |
| `jwks_cache_ttl_seconds` | int | `3600` | `JWKS_CACHE_TTL` | How long to cache JWKS keys |
| `jwt_audience` | str | `worldview-frontend` | `JWT_AUDIENCE` | Expected `aud` claim |

##### Rate Limiting Middleware (Modified)

**Current**: Single limit per IP. Key: `ratelimit:{client_ip}`.

**New**: Per-tenant, per-endpoint-group limits. Key: `ratelimit:{tenant_id}:{group}` or `ratelimit:anon:{client_ip}`.

**Endpoint groups:**
| Group | Endpoints | Description |
|-------|-----------|-------------|
| `default` | Most endpoints | Standard CRUD, reads |
| `market_data` | `/v1/ohlcv/*`, `/v1/quotes/*` | Market data queries |
| `intelligence` | `/v1/entities/*`, `/v1/relations/*`, `/v1/knowledge/*` | Intelligence graph queries |
| `chat` | `/v1/chat/*` | RAG/Chat (LLM cost) |
| `search` | `/v1/search/*` | Full-text and semantic search |

**Rate limit defaults (per minute, env-configurable):**

| Env Var | Group | Free | Pro | Enterprise |
|---------|-------|------|-----|------------|
| `RATE_LIMIT_FREE_DEFAULT` | `default` | 20 | — | — |
| `RATE_LIMIT_FREE_MARKET_DATA` | `market_data` | 30 | — | — |
| `RATE_LIMIT_FREE_INTELLIGENCE` | `intelligence` | 10 | — | — |
| `RATE_LIMIT_FREE_CHAT` | `chat` | 5 | — | — |
| `RATE_LIMIT_FREE_SEARCH` | `search` | 10 | — | — |
| `RATE_LIMIT_PRO_DEFAULT` | `default` | — | 200 | — |
| `RATE_LIMIT_PRO_MARKET_DATA` | `market_data` | — | 300 | — |
| `RATE_LIMIT_PRO_INTELLIGENCE` | `intelligence` | — | 100 | — |
| `RATE_LIMIT_PRO_CHAT` | `chat` | — | 50 | — |
| `RATE_LIMIT_PRO_SEARCH` | `search` | — | 100 | — |
| `RATE_LIMIT_ENTERPRISE_DEFAULT` | `default` | — | — | 1000 |
| `RATE_LIMIT_ENTERPRISE_MARKET_DATA` | `market_data` | — | — | 1500 |
| `RATE_LIMIT_ENTERPRISE_INTELLIGENCE` | `intelligence` | — | — | 500 |
| `RATE_LIMIT_ENTERPRISE_CHAT` | `chat` | — | — | 200 |
| `RATE_LIMIT_ENTERPRISE_SEARCH` | `search` | — | — | 500 |

**Rate limit response (429):**
```json
{
  "error": "rate_limit_exceeded",
  "detail": "Rate limit exceeded for endpoint group 'intelligence'",
  "retry_after_seconds": 12
}
```

Response includes `Retry-After` header (seconds until next window).

##### Tenant Management API (New, Admin-Only)

These endpoints are internal/admin-only, not exposed to regular users. Authentication: JWT with `role=admin` claim (Keycloak realm role).

###### GET /admin/v1/tenants
- **Purpose**: List all tenants with pagination
- **Auth**: Admin role required
- **Query params**:
  | Param | Type | Required | Default | Description |
  |-------|------|----------|---------|-------------|
  | page | int | no | 1 | Page number |
  | page_size | int | no | 50 | Items per page (max 200) |
  | tier | string | no | — | Filter by tier (free/pro/enterprise) |
  | status | string | no | — | Filter by status (active/suspended) |
- **Response** (200):
  | Field | Type | Description |
  |-------|------|-------------|
  | tenants | array | List of tenant objects |
  | total | int | Total matching tenants |
  | page | int | Current page |
  | page_size | int | Page size |
- **Tenant object**:
  | Field | Type | Description |
  |-------|------|-------------|
  | id | UUID | Tenant UUIDv7 |
  | name | string | Tenant name |
  | tier | string | free/pro/enterprise |
  | status | string | active/suspended |
  | keycloak_id | string | Keycloak user ID |
  | created_at | string | ISO-8601 UTC |
- **Error responses**: 401 (not authenticated), 403 (not admin)

###### GET /admin/v1/tenants/{tenant_id}
- **Purpose**: Get tenant details with usage summary
- **Auth**: Admin role required
- **Response** (200):
  | Field | Type | Description |
  |-------|------|-------------|
  | id | UUID | Tenant UUIDv7 |
  | name | string | Tenant name |
  | tier | string | Billing tier |
  | status | string | active/suspended |
  | keycloak_id | string | Keycloak user ID |
  | email | string | Primary user email |
  | created_at | string | ISO-8601 UTC |
  | usage | object | LLM usage summary (see below) |
- **Usage object**:
  | Field | Type | Description |
  |-------|------|-------------|
  | total_llm_calls | int | Total LLM calls this month |
  | total_tokens_in | int | Total input tokens this month |
  | total_tokens_out | int | Total output tokens this month |
  | estimated_cost_usd | float | Estimated cost this month |
- **Error responses**: 401, 403, 404

###### PATCH /admin/v1/tenants/{tenant_id}
- **Purpose**: Update tenant tier or status
- **Auth**: Admin role required
- **Request body**:
  | Field | Type | Required | Validation | Description |
  |-------|------|----------|------------|-------------|
  | tier | string | no | one of: free, pro, enterprise | New billing tier |
  | status | string | no | one of: active, suspended | New status |
- **Response** (200): Updated tenant object (same as GET)
- **Error responses**: 401, 403, 404, 422 (invalid tier/status value)
- **Side effects**: If tier changes, S1 updates the tenant record. Next JWT refresh reflects new tier.

###### GET /admin/v1/tenants/{tenant_id}/llm-usage
- **Purpose**: Detailed LLM usage for a tenant
- **Auth**: Admin role required
- **Query params**:
  | Param | Type | Required | Default | Description |
  |-------|------|----------|---------|-------------|
  | from | string | no | start of current month | ISO-8601 date |
  | to | string | no | now | ISO-8601 date |
- **Response** (200):
  | Field | Type | Description |
  |-------|------|-------------|
  | tenant_id | UUID | Tenant ID |
  | period_from | string | Start of period |
  | period_to | string | End of period |
  | by_provider | array | Breakdown by provider |
  | by_capability | array | Breakdown by capability |
  | total_estimated_cost_usd | float | Total cost in period |
- **by_provider item**:
  | Field | Type | Description |
  |-------|------|-------------|
  | provider | string | LLM provider name |
  | calls | int | Number of calls |
  | tokens_in | int | Input tokens |
  | tokens_out | int | Output tokens |
  | estimated_cost_usd | float | Cost |

#### 6.2.2 S1 — Portfolio Service

##### POST /internal/v1/auth/on-register (New)
- **Purpose**: Called by Keycloak event listener on user registration. Creates tenant + user atomically.
- **Auth**: Internal-only (not routed through S9 public API). Secured via network policy or shared internal secret.
- **Request body**:
  | Field | Type | Required | Default | Validation | Description |
  |-------|------|----------|---------|------------|-------------|
  | keycloak_user_id | string | yes | — | 1-100 chars | Keycloak subject ID |
  | email | string | yes | — | valid email | User's verified email |
  | name | string | no | email local part | 1-255 chars | Display name |
- **Response** (201):
  | Field | Type | Description |
  |-------|------|-------------|
  | tenant_id | UUID | Created tenant UUIDv7 |
  | user_id | UUID | Created user UUIDv7 |
  | tier | string | Always "free" on creation |
- **Error responses**:
  - 409: `keycloak_user_id` already exists (idempotent — returns existing tenant_id/user_id)
  - 422: Validation error
- **Idempotency**: If called twice with the same `keycloak_user_id`, returns the existing tenant/user without creating duplicates (UNIQUE constraint on `keycloak_user_id`).

##### PATCH /internal/v1/tenants/{tenant_id}/tier (New)
- **Purpose**: Update tenant tier. Called by admin API via S9.
- **Auth**: Internal-only
- **Request body**:
  | Field | Type | Required | Validation | Description |
  |-------|------|----------|------------|-------------|
  | tier | string | yes | free/pro/enterprise | New tier |
- **Response** (200): Updated tenant object
- **Error responses**: 404, 422

##### PATCH /internal/v1/tenants/{tenant_id}/status (New)
- **Purpose**: Suspend or reactivate tenant. Called by admin API via S9.
- **Auth**: Internal-only
- **Request body**:
  | Field | Type | Required | Validation | Description |
  |-------|------|----------|------------|-------------|
  | status | string | yes | active/suspended | New status |
- **Response** (200): Updated tenant object
- **Error responses**: 404, 422
- **Side effects**: Suspended tenants' JWTs are rejected by S9 (S9 checks `status` claim or calls S1 to verify).

### 6.3 Event Changes

#### 6.3.1 tenant.created.v1 (New)

- **Topic**: `tenant.lifecycle.v1`
- **Partition key**: `tenant_id`
- **Retention**: 30 days
- **Producers**: S1 (Portfolio)
- **Consumers**: S10 (Alert — to set up default alert preferences)
- **Avro schema**:
  | Field | Type | Default | Nullable | Description |
  |-------|------|---------|----------|-------------|
  | event_id | string | — | no | UUIDv7 |
  | event_type | string | — | no | Always `tenant.created.v1` |
  | tenant_id | string | — | no | UUIDv7 of the new tenant |
  | tier | string | `free` | no | Initial tier |
  | created_at | string | — | no | ISO-8601 UTC |
  | schema_version | int | 1 | no | Schema version |

#### 6.3.2 tenant.tier_changed.v1 (New)

- **Topic**: `tenant.lifecycle.v1`
- **Partition key**: `tenant_id`
- **Retention**: 30 days
- **Producers**: S1 (Portfolio)
- **Consumers**: S9 (to invalidate cached tier), S10 (to update alert quotas)
- **Avro schema**:
  | Field | Type | Default | Nullable | Description |
  |-------|------|---------|----------|-------------|
  | event_id | string | — | no | UUIDv7 |
  | event_type | string | — | no | Always `tenant.tier_changed.v1` |
  | tenant_id | string | — | no | Tenant UUIDv7 |
  | old_tier | string | — | no | Previous tier |
  | new_tier | string | — | no | New tier |
  | changed_at | string | — | no | ISO-8601 UTC |
  | schema_version | int | 1 | no | Schema version |

#### 6.3.3 tenant.suspended.v1 (New)

- **Topic**: `tenant.lifecycle.v1`
- **Partition key**: `tenant_id`
- **Retention**: 30 days
- **Producers**: S1 (Portfolio)
- **Consumers**: S9 (to reject requests from suspended tenants)
- **Avro schema**:
  | Field | Type | Default | Nullable | Description |
  |-------|------|---------|----------|-------------|
  | event_id | string | — | no | UUIDv7 |
  | event_type | string | — | no | `tenant.suspended.v1` or `tenant.reactivated.v1` |
  | tenant_id | string | — | no | Tenant UUIDv7 |
  | status | string | — | no | `suspended` or `active` |
  | changed_at | string | — | no | ISO-8601 UTC |
  | schema_version | int | 1 | no | Schema version |

#### 6.3.4 Avro Schema Files (New)

All three events share topic `tenant.lifecycle.v1`. New Avro schema files to create:

| File | Location |
|------|----------|
| `tenant.created.v1.avsc` | `infra/kafka/schemas/` |
| `tenant.tier_changed.v1.avsc` | `infra/kafka/schemas/` |
| `tenant.suspended.v1.avsc` | `infra/kafka/schemas/` |

### 6.4 Database Changes

#### 6.4.1 intelligence_db — Migration 0002_add_tenant_isolation.py

**Owner**: `intelligence-migrations` (exclusive DDL owner, as per PRD-0001)

##### Column additions:

| Table | Column | Type | Nullable | Default | Constraints | Notes |
|-------|--------|------|----------|---------|-------------|-------|
| `canonical_entities` | `tenant_id` | UUID | yes | NULL | — | NULL = public, non-NULL = tenant-private |
| `relations` | `tenant_id` | UUID | yes | NULL | — | NULL = public, non-NULL = tenant-private |
| `claims` | `tenant_id` | UUID | yes | NULL | — | NULL = public, non-NULL = tenant-private |
| `events` | `tenant_id` | UUID | yes | NULL | — | NULL = public, non-NULL = tenant-private |
| `entity_embedding_state` | `tenant_id` | UUID | yes | NULL | — | NULL = public, non-NULL = tenant-private |
| `llm_usage_log` | `tenant_id` | UUID | yes | NULL | — | For cost attribution; NULL = system/unattributed |

**Tables NOT modified** (transitive isolation via FK):
- `entity_aliases` — scoped through `entity_id` FK → `canonical_entities`
- `relation_evidence_raw` — scoped through `subject_entity_id` join → `relations`
- `relation_evidence` — scoped through `relation_id` FK → `relations`
- `relation_summaries` — scoped through `relation_id` FK → `relations`
- `relation_contradiction_links` — scoped through `relation_evidence_id`
- `event_entities` — scoped through `event_id` FK → `events`

**Tables NOT modified** (system/global):
- `decay_class_config`, `source_trust_weights`, `model_registry`, `prompt_templates`, `relation_type_registry` — system configuration
- `outbox_events`, `dead_letter_queue` — ops tables, tenant in payload
- `embedding_migration_state` — admin ops
- `provisional_entity_queue` — processing queue

##### New indexes:

| Table | Index Name | Columns | Condition | Purpose |
|-------|-----------|---------|-----------|---------|
| `canonical_entities` | `ix_entities_tenant` | `(tenant_id)` | `WHERE tenant_id IS NOT NULL` | Tenant's private entities |
| `canonical_entities` | `ix_entities_tenant_type` | `(tenant_id, entity_type)` | `WHERE tenant_id IS NOT NULL` | Filtered entity resolution |
| `relations` | `ix_relations_tenant` | `(tenant_id, subject_entity_id)` | `WHERE tenant_id IS NOT NULL` | Tenant's private relations |
| `claims` | `ix_claims_tenant` | `(tenant_id, subject_entity_id)` | `WHERE tenant_id IS NOT NULL` | Tenant's private claims |
| `events` | `ix_events_tenant` | `(tenant_id, subject_entity_id)` | `WHERE tenant_id IS NOT NULL` | Tenant's private events |
| `llm_usage_log` | `ix_llm_usage_tenant` | `(tenant_id, created_at DESC)` | `WHERE tenant_id IS NOT NULL` | Cost attribution queries |
| `entity_embedding_state` | `ix_embeddings_tenant` | `(tenant_id)` | `WHERE tenant_id IS NOT NULL` | Tenant embedding search scope |

##### Uniqueness constraint updates:

```sql
-- Tenant-scoped entity uniqueness (private entities unique per tenant)
CREATE UNIQUE INDEX CONCURRENTLY uq_entities_tenant_name_type
  ON canonical_entities(tenant_id, canonical_name, entity_type)
  WHERE tenant_id IS NOT NULL;
```

The existing UNIQUE on `relations(subject_entity_id, canonical_type, object_entity_id)` handles tenant scoping implicitly: since `tenant_id` is nullable and `NULL != NULL` in Postgres uniqueness, a public relation and a private relation with the same subject/type/object can coexist. Application-layer validation in S7 enforces uniqueness within a tenant's private relations.

**Note on partitioned tables**: `relations` is hash-partitioned on `subject_entity_id`. `ALTER TABLE ... ADD COLUMN` propagates to all 8 partitions. Partial indexes propagate automatically. No partition rebuild required.

##### Migration SQL:

```sql
-- All ADD COLUMN operations are non-blocking (DEFAULT NULL, no table rewrite)
ALTER TABLE canonical_entities ADD COLUMN tenant_id UUID DEFAULT NULL;
ALTER TABLE relations ADD COLUMN tenant_id UUID DEFAULT NULL;
ALTER TABLE claims ADD COLUMN tenant_id UUID DEFAULT NULL;
ALTER TABLE events ADD COLUMN tenant_id UUID DEFAULT NULL;
ALTER TABLE entity_embedding_state ADD COLUMN tenant_id UUID DEFAULT NULL;
ALTER TABLE llm_usage_log ADD COLUMN tenant_id UUID DEFAULT NULL;

-- Partial indexes (only index non-NULL rows, zero overhead on public data)
CREATE INDEX CONCURRENTLY ix_entities_tenant
  ON canonical_entities(tenant_id) WHERE tenant_id IS NOT NULL;
CREATE INDEX CONCURRENTLY ix_entities_tenant_type
  ON canonical_entities(tenant_id, entity_type) WHERE tenant_id IS NOT NULL;
CREATE INDEX CONCURRENTLY ix_relations_tenant
  ON relations(tenant_id, subject_entity_id) WHERE tenant_id IS NOT NULL;
CREATE INDEX CONCURRENTLY ix_claims_tenant
  ON claims(tenant_id, subject_entity_id) WHERE tenant_id IS NOT NULL;
CREATE INDEX CONCURRENTLY ix_events_tenant
  ON events(tenant_id, subject_entity_id) WHERE tenant_id IS NOT NULL;
CREATE INDEX CONCURRENTLY ix_llm_usage_tenant
  ON llm_usage_log(tenant_id, created_at DESC) WHERE tenant_id IS NOT NULL;
CREATE INDEX CONCURRENTLY ix_embeddings_tenant
  ON entity_embedding_state(tenant_id) WHERE tenant_id IS NOT NULL;
CREATE UNIQUE INDEX CONCURRENTLY uq_entities_tenant_name_type
  ON canonical_entities(tenant_id, canonical_name, entity_type)
  WHERE tenant_id IS NOT NULL;
```

**Estimated impact**: Zero rows to backfill. All existing rows stay `tenant_id = NULL`. Index creation on empty partial set is instant.

#### 6.4.2 portfolio_db — Migration 0005_add_saas_fields.py

**Owner**: S1 (Portfolio)

##### Column additions:

| Table | Column | Type | Nullable | Default | Constraints | Notes |
|-------|--------|------|----------|---------|-------------|-------|
| `tenants` | `tier` | VARCHAR(20) | no | `'free'` | CHECK (tier IN ('free', 'pro', 'enterprise')) | Billing tier |
| `tenants` | `keycloak_id` | VARCHAR(100) | yes | NULL | UNIQUE (partial, WHERE NOT NULL) | Keycloak subject ID |
| `tenants` | `max_users` | INT | no | 1 | CHECK (max_users > 0) | Max users per tenant |
| `users` | `keycloak_user_id` | VARCHAR(100) | yes | NULL | UNIQUE (partial, WHERE NOT NULL) | Keycloak user ID |

##### Migration SQL:

```sql
ALTER TABLE tenants ADD COLUMN tier VARCHAR(20) NOT NULL DEFAULT 'free';
ALTER TABLE tenants ADD CONSTRAINT ck_tenants_tier
  CHECK (tier IN ('free', 'pro', 'enterprise'));
ALTER TABLE tenants ADD COLUMN keycloak_id VARCHAR(100);
CREATE UNIQUE INDEX uq_tenants_keycloak ON tenants(keycloak_id)
  WHERE keycloak_id IS NOT NULL;
ALTER TABLE tenants ADD COLUMN max_users INT NOT NULL DEFAULT 1;
ALTER TABLE tenants ADD CONSTRAINT ck_tenants_max_users CHECK (max_users > 0);

ALTER TABLE users ADD COLUMN keycloak_user_id VARCHAR(100);
CREATE UNIQUE INDEX uq_users_keycloak ON users(keycloak_user_id)
  WHERE keycloak_user_id IS NOT NULL;
```

### 6.5 Domain Model Changes

#### 6.5.1 libs/common — New Types

##### Enum: TenantTier
- **Purpose**: Billing tier for tenant capabilities and rate limits
- **Location**: `libs/common/src/common/types.py`
- **Values**:
  | Value | Description |
  |-------|-------------|
  | `free` | Shared intelligence only, basic rate limits |
  | `pro` | Private intelligence, higher rate limits |
  | `enterprise` | All features, highest/custom rate limits |

```python
class TenantTier(StrEnum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"
```

##### Dataclass: RateLimitConfig
- **Purpose**: Rate limit configuration per tier and endpoint group
- **Location**: `libs/common/src/common/types.py`
- **Frozen**: yes

```python
@dataclass(frozen=True)
class RateLimitConfig:
    tier: TenantTier
    endpoint_group: str
    max_requests_per_minute: int
```

#### 6.5.2 S1 Portfolio — Entity Updates

##### Entity: Tenant (Modified)
- **Existing attributes preserved** (id, name, status, created_at)
- **New attributes**:
  | Attribute | Type | Required | Default | Validation | Description |
  |-----------|------|----------|---------|------------|-------------|
  | tier | TenantTier | yes | TenantTier.FREE | enum member | Billing tier |
  | keycloak_id | str \| None | no | None | 1-100 chars if set | Keycloak subject ID |
  | max_users | int | yes | 1 | > 0 | Max users allowed |
- **New methods**:
  | Method | Returns | Description |
  |--------|---------|-------------|
  | `upgrade_tier(new_tier: TenantTier)` | `TenantTierChanged` event | Changes tier, returns domain event |
  | `suspend()` | `TenantSuspended` event | Sets status to suspended |
  | `reactivate()` | `TenantReactivated` event | Sets status back to active |
  | `can_create_private_intelligence()` | bool | True if tier is PRO or ENTERPRISE |
- **Invariants**: tier is a valid TenantTier; max_users >= 1; suspended tenant cannot be upgraded (must reactivate first)

##### Entity: User (Modified)
- **Existing attributes preserved** (id, tenant_id, email, status, created_at)
- **New attributes**:
  | Attribute | Type | Required | Default | Validation | Description |
  |-----------|------|----------|---------|------------|-------------|
  | keycloak_user_id | str \| None | no | None | 1-100 chars if set | Keycloak user ID |
- **Factory**: `User.from_keycloak_registration(tenant_id, keycloak_user_id, email)`

##### New Domain Events (S1):

###### TenantTierChanged
- **Frozen**: yes
- **Attributes**:
  | Attribute | Type | Required | Description |
  |-----------|------|----------|-------------|
  | event_id | UUID | yes | UUIDv7 |
  | tenant_id | UUID | yes | Affected tenant |
  | old_tier | TenantTier | yes | Previous tier |
  | new_tier | TenantTier | yes | New tier |
  | changed_at | datetime | yes | UTC timestamp |
- **EVENT_TYPE**: `tenant.tier_changed.v1`
- **AGGREGATE_TYPE**: `tenant`

###### TenantSuspended
- **Frozen**: yes
- **Attributes**:
  | Attribute | Type | Required | Description |
  |-----------|------|----------|-------------|
  | event_id | UUID | yes | UUIDv7 |
  | tenant_id | UUID | yes | Affected tenant |
  | status | str | yes | `suspended` or `active` |
  | changed_at | datetime | yes | UTC timestamp |
- **EVENT_TYPE**: `tenant.suspended.v1`
- **AGGREGATE_TYPE**: `tenant`

#### 6.5.3 S9 API Gateway — New Domain Types

##### Dataclass: AuthenticatedUser
- **Purpose**: Represents the authenticated user context extracted from JWT
- **Frozen**: yes
- **Attributes**:
  | Attribute | Type | Required | Description |
  |-----------|------|----------|-------------|
  | user_id | UUID | yes | Keycloak subject as UUID |
  | tenant_id | UUID | yes | Tenant UUIDv7 |
  | tier | TenantTier | yes | Current billing tier |
  | email | str | yes | Verified email |
  | roles | list[str] | yes | Keycloak realm roles (e.g., `["user"]` or `["user", "admin"]`) |

##### Dataclass: TenantRateLimitPolicy
- **Purpose**: Resolved rate limit policy for a tenant based on tier
- **Frozen**: yes
- **Attributes**:
  | Attribute | Type | Required | Description |
  |-----------|------|----------|-------------|
  | tenant_id | UUID | yes | Tenant ID |
  | tier | TenantTier | yes | Billing tier |
  | limits | dict[str, int] | yes | Map of endpoint_group → max_requests_per_minute |

#### 6.5.4 S6 NLP Pipeline — Entity Resolution Changes

**Current behavior**: Searches all `canonical_entities` + `entity_aliases` without scoping.

**New behavior**: Accepts optional `tenant_id` context. When present:
1. Search `canonical_entities WHERE tenant_id IS NULL OR tenant_id = :tenant_id`
2. Search `entity_aliases` joined through `canonical_entities` with same filter
3. If no match found and `tenant_id` is not NULL → create new entity with `tenant_id = tenant_id`
4. If no match found and `tenant_id` is NULL (public processing) → create new entity with `tenant_id = NULL`

**Resolution priority**:
1. Exact alias match (public or own tenant)
2. Fuzzy alias match via trigram similarity (public or own tenant)
3. Create new entity (inherits tenant_id from processing context)

**Key invariant**: Entity resolution NEVER returns entities from other tenants. The filter `tenant_id IS NULL OR tenant_id = :current_tenant_id` is non-negotiable.

#### 6.5.5 S7 Knowledge Graph — Tenant-Scoped Writes

**Current behavior**: Creates relations with no tenant scoping.

**New behavior**: When materializing relations from tenant-scoped documents:
1. Relation inherits `tenant_id` from the source evidence/document context
2. Confidence computation for tenant-scoped relations only considers tenant-scoped + public evidence (never other tenants' evidence)
3. Contradiction detection scoped: a tenant's private claim only contradicts public claims or the same tenant's private claims

**Query filter for all S7 reads**:
```sql
WHERE (r.tenant_id IS NULL OR r.tenant_id = :tenant_id)
```

### 6.6 Infrastructure Changes

#### 6.6.1 Keycloak Service (New)

**Docker Compose addition** (`infra/compose/docker-compose.yml`):

```yaml
keycloak:
  image: quay.io/keycloak/keycloak:24.0
  command: start-dev --import-realm
  environment:
    KEYCLOAK_ADMIN: admin
    KEYCLOAK_ADMIN_PASSWORD: ${KEYCLOAK_ADMIN_PASSWORD:-admin}
    KC_DB: postgres
    KC_DB_URL: jdbc:postgresql://keycloak-db:5432/keycloak
    KC_DB_USERNAME: keycloak
    KC_DB_PASSWORD: ${KEYCLOAK_DB_PASSWORD:-keycloak}
    KC_HTTP_PORT: 8080
    KC_HOSTNAME_STRICT: false
    KC_HTTP_ENABLED: true
  ports:
    - "8080:8080"
  volumes:
    - ./keycloak/realm-export.json:/opt/keycloak/data/import/realm-export.json:ro
    - ./keycloak/event-listener.jar:/opt/keycloak/providers/event-listener.jar:ro
  depends_on:
    keycloak-db:
      condition: service_healthy
  profiles:
    - infra
  healthcheck:
    test: ["CMD-SHELL", "exec 3<>/dev/tcp/localhost/8080"]
    interval: 10s
    timeout: 5s
    retries: 10

keycloak-db:
  image: postgres:16-alpine
  environment:
    POSTGRES_DB: keycloak
    POSTGRES_USER: keycloak
    POSTGRES_PASSWORD: ${KEYCLOAK_DB_PASSWORD:-keycloak}
  volumes:
    - keycloak_data:/var/lib/postgresql/data
  profiles:
    - infra
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U keycloak"]
    interval: 5s
    timeout: 3s
    retries: 5
```

**New volume**: `keycloak_data`

#### 6.6.2 Keycloak Realm Configuration

**File**: `infra/compose/keycloak/realm-export.json`

Key configuration:
- **Realm**: `worldview`
- **Clients**:
  | Client ID | Type | Flow | Redirect URIs |
  |-----------|------|------|---------------|
  | `worldview-frontend` | public | Authorization Code + PKCE | `http://localhost:5173/*`, `http://localhost:3000/*` |
  | `worldview-api` | confidential | Client Credentials | N/A (service-to-service) |
- **Realm roles**: `user` (default), `admin`
- **User attributes**: `tenant_id` (stored after S1 creates tenant)
- **Token mapper**: Custom protocol mapper to include `tenant_id` and `tier` in access token claims
- **Email settings**: SMTP configured for verification (dev: Mailhog; prod: SES/SendGrid)
- **Registration**: Enabled with email verification required
- **Password policy**: Minimum 8 characters, at least 1 digit

#### 6.6.3 Keycloak Event Listener

**Purpose**: On user registration, calls S1 to create tenant + user, then updates Keycloak user attributes with `tenant_id` and `tier`.

**Implementation**: Custom SPI (Java EventListenerProvider)

The SPI:
1. Listens for `REGISTER` event
2. Calls `POST http://portfolio:8001/internal/v1/auth/on-register`
3. Gets back `{tenant_id, user_id, tier}`
4. Updates Keycloak user attributes via Admin API: `tenant_id`, `tier`
5. First token issued already contains correct claims

**Fallback**: If the S1 call fails, the SPI logs the error and does NOT block registration. A background reconciliation job (or lazy creation on first S9 request) handles the retry.

#### 6.6.4 Dev Email (Mailhog)

**Docker Compose addition**:

```yaml
mailhog:
  image: mailhog/mailhog:latest
  ports:
    - "1025:1025"   # SMTP
    - "8025:8025"   # Web UI
  profiles:
    - infra
```

Keycloak SMTP configured to point to `mailhog:1025` in dev.

#### 6.6.5 S9 Environment Variables (New/Modified)

| Env Var | Type | Default | Description |
|---------|------|---------|-------------|
| `KEYCLOAK_URL` | str | `http://keycloak:8080` | Keycloak base URL |
| `KEYCLOAK_REALM` | str | `worldview` | Realm name |
| `JWKS_CACHE_TTL` | int | `3600` | JWKS cache TTL in seconds |
| `JWT_AUDIENCE` | str | `worldview-frontend` | Expected JWT audience |
| `RATE_LIMIT_FREE_*` | int | (see §6.2.1) | Free tier limits per group |
| `RATE_LIMIT_PRO_*` | int | (see §6.2.1) | Pro tier limits per group |
| `RATE_LIMIT_ENTERPRISE_*` | int | (see §6.2.1) | Enterprise tier limits per group |

**Removed env vars**: `JWT_SECRET`, `JWT_ALGORITHM` (replaced by JWKS)

### 6.7 Data Flow Diagrams

#### 6.7.1 User Registration Flow

```
User → Keycloak (register + verify email)
  → Keycloak EventListenerSPI fires on REGISTER
  → SPI calls POST S1:/internal/v1/auth/on-register {keycloak_user_id, email}
  → S1 creates Tenant(tier=free) + User(keycloak_user_id=...)
  → S1 emits tenant.created.v1 via outbox
  → SPI receives {tenant_id, user_id, tier}
  → SPI updates Keycloak user attributes: tenant_id, tier
  → User logs in → JWT contains tenant_id + tier claims
```

#### 6.7.2 Authenticated Request Flow

```
Frontend sends: Authorization: Bearer <JWT>
  → S9 validates JWT via cached JWKS (RS256)
  → S9 extracts tenant_id, tier, user_id from claims
  → S9 resolves endpoint group from request path
  → S9 checks Valkey: INCR ratelimit:{tenant_id}:{group}, compare to tier limit
  → If rate limited: 429 + Retry-After header
  → If OK: proxy request with X-Tenant-ID, X-User-ID, X-Tenant-Tier headers
  → Downstream service uses X-Tenant-ID to scope all queries
```

#### 6.7.3 Tenant-Scoped Intelligence Query

```
S9 → S7 (GET /v1/relations?entity=Apple&type=acquired)
  → S7 extracts tenant_id from X-Tenant-ID header
  → SQL: SELECT ... FROM relations r
         JOIN canonical_entities ce_s ON r.subject_entity_id = ce_s.entity_id
         WHERE (r.tenant_id IS NULL OR r.tenant_id = :tenant_id)
           AND (ce_s.tenant_id IS NULL OR ce_s.tenant_id = :tenant_id)
           AND ce_s.canonical_name ILIKE '%Apple%'
         ORDER BY r.confidence DESC LIMIT 50
  → Returns: public + tenant's private relations (never other tenants')
```

#### 6.7.4 Admin Tier Change Flow

```
Admin → S9: PATCH /admin/v1/tenants/{tid} {tier: "pro"}
  → S9 validates admin role in JWT
  → S9 calls S1: PATCH /internal/v1/tenants/{tid}/tier {tier: "pro"}
  → S1 updates tenant.tier, emits tenant.tier_changed.v1 via outbox
  → S9 consumes tenant.tier_changed.v1, invalidates cached tier
  → Next JWT refresh: Keycloak reads updated tier from user attributes
  → Note: tier update in Keycloak user attributes requires either:
    (a) S1 calls Keycloak Admin API to update attribute, OR
    (b) Keycloak token mapper reads tier from external source
    Recommendation: (a) — S1 updates Keycloak via Admin API after DB commit
```

---

## 7. Architecture Decisions

### ADR-006: Shared-DB with Tenant Column Isolation

**Context**: Need multi-tenant data isolation for intelligence tables.

**Options considered**:
| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A: Shared DB + tenant_id column | Nullable column, NULL = public | Simple, no infra change, additive | Must audit every query |
| B: Schema-per-tenant | Postgres schema per tenant | Strongest isolation | DDL on every tenant creation, migration complexity |
| C: Database-per-tenant | Separate DB per tenant | Complete isolation | Massive infra overhead, no cross-tenant queries |

**Decision**: **Option A** — shared DB with nullable `tenant_id` column.

**Rationale**: The intelligence pipeline processes public data by default. Private data is the exception. Schema/DB-per-tenant introduces operational complexity disproportionate to the isolation benefit at this scale. Partial indexes on `WHERE tenant_id IS NOT NULL` ensure zero performance impact on existing public queries. Query-level isolation is enforced via mandatory `WHERE tenant_id IS NULL OR tenant_id = :tid` filters, validated by code review checklist.

### ADR-007: Keycloak for Identity Management

**Context**: Current auth is HS256 JWT with hardcoded dev secret. Need production-grade identity with self-serve registration, email verification, and token management.

**Options considered**:
| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A: Keycloak | Full-featured OIDC provider | Built-in flows, email, RBAC-ready | Java dependency, memory footprint (~512MB) |
| B: Auth0/Clerk (hosted) | Managed identity SaaS | Zero infra, quick | Vendor lock-in, cost at scale, latency |
| C: Custom auth service | Build JWT issuance, registration, email | Full control | Weeks of work, security risk, maintenance |

**Decision**: **Option A** — Keycloak.

**Rationale**: Self-hosted (data sovereignty), OIDC-compliant (standard JWT validation), built-in email verification, extensible via SPIs, free. Memory footprint acceptable for a startup. Avoids vendor lock-in. Custom auth is too risky for a small team.

### ADR-008: Transitive Tenant Isolation via FK

**Context**: Need to decide whether child tables (entity_aliases, relation_evidence, etc.) get their own `tenant_id` column or inherit scoping through foreign keys.

**Options considered**:
| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A: Transitive (via FK joins) | Only parent tables get `tenant_id` | Less denormalization, no sync bugs | Extra JOINs on queries |
| B: Denormalized | Every table gets `tenant_id` | Faster queries (no JOIN needed) | Must keep in sync, more columns |

**Decision**: **Option A** — transitive isolation.

**Rationale**: The risk of denormalization bugs (alias says tenant A, parent entity says tenant B) outweighs the JOIN cost. The JOINs already exist in most intelligence queries (e.g., evidence always joins to relation). Partial indexes keep JOIN performance acceptable. If query performance becomes an issue at scale, denormalization can be added as an optimization — but premature denormalization is a correctness risk.

### ADR-009: Event Listener SPI vs Webhook for Tenant Provisioning

**Context**: Need to create tenant records in S1 when users register in Keycloak.

**Decision**: Custom Java SPI (EventListenerProvider) that synchronously calls S1.

**Rationale**: Ensures tenant_id is available in the first JWT issued (no second login needed). Webhook approaches introduce async delay and require a webhook receiver service. The SPI is ~100 lines of Java, deployed as a JAR in Keycloak's providers directory.

---

## 8. Security Design

### 8.1 Threat Model

| Threat | Vector | Mitigation | Severity |
|--------|--------|------------|----------|
| Tenant data leakage | Missing WHERE filter | Mandatory filter in every intelligence query; code review checklist item | CRITICAL |
| JWT forgery | Weak algorithm | RS256 via JWKS (asymmetric); cannot forge without Keycloak's private key | HIGH |
| Tenant ID spoofing | Client sends fake X-Tenant-ID | S9 extracts tenant_id from validated JWT only; ignores client headers | HIGH |
| Rate limit bypass | IP rotation | Rate limits keyed on tenant_id (from JWT), not client IP | MEDIUM |
| Privilege escalation | Free user accesses Pro features | Tier checked in application layer before private intelligence operations | HIGH |
| Account takeover | Weak passwords | Keycloak password policy: min 8 chars, 1 digit. Future: MFA (PRD-0003) | MEDIUM |
| Suspended tenant access | Cached JWT | S9 maintains suspended tenant set (from Kafka events); rejects even valid JWTs | MEDIUM |

### 8.2 Tenant Isolation Enforcement

**Rule**: Every SQL query that touches a table with `tenant_id` MUST include the filter:
```sql
WHERE tenant_id IS NULL OR tenant_id = :current_tenant_id
```

**Enforcement layers**:
1. **Code review checklist** — new item: "All intelligence queries include tenant_id filter"
2. **Integration tests** — test that tenant A cannot see tenant B's private data
3. **Future**: SQL middleware/interceptor that auto-appends the filter (not in this PRD)

### 8.3 Authentication Flow Security

- **PKCE** required for frontend client (prevents authorization code interception)
- **Audience validation** — S9 rejects JWTs not intended for `worldview-frontend`
- **Issuer validation** — S9 rejects JWTs from unexpected issuers
- **Token expiry** — access tokens: 5 minutes; refresh tokens: 30 minutes (configurable in Keycloak)
- **JWKS key rotation** — Keycloak rotates signing keys; S9 JWKS cache TTL = 1 hour ensures new keys are picked up

### 8.4 Internal Endpoint Security

The `/internal/v1/` endpoints on S1 are NOT exposed through S9's public API. Security:
- **Network-level**: Only accessible within Docker network (not port-mapped to host for internal paths)
- **Optional shared secret**: `X-Internal-Secret` header validated by S1 (env-configurable, optional for dev)

---

## 9. Failure Modes & Recovery

| Failure | Impact | Detection | Recovery | RTO |
|---------|--------|-----------|----------|-----|
| **Keycloak down** | No new logins/registrations | Health check fails | S9 JWKS cache (1h) keeps existing sessions alive. New logins fail until Keycloak recovers. | Auto-recover |
| **S1 down during registration** | Keycloak creates user but no tenant | SPI logs error, user has no tenant_id in JWT | Lazy tenant creation on first S9 request (fallback path). SPI retries on next Keycloak restart. | Manual or auto-retry |
| **Valkey down** | Rate limits not enforced | Health check fails | Fail-open: requests allowed without rate limiting (existing behavior). Log warning. | Auto-recover |
| **Intelligence DB migration fails** | New `tenant_id` columns not created | Alembic exit code != 0 | Fix migration, re-run `intelligence-migrations` init container. No data loss (additive migration). | Manual |
| **Keycloak SPI JAR missing** | Events not fired, no tenant auto-creation | User registers but first JWT has no tenant_id | Lazy creation fallback in S9 (same as S1 down). | Manual deploy |
| **Kafka down** | Tenant lifecycle events not delivered | Consumer lag alerts | Events buffered in outbox. Dispatcher retries when Kafka recovers. S9 may have stale tier info until events flow. | Auto-recover |
| **JWT with missing tenant_id claim** | Request cannot be scoped | S9 rejects with 401 | User must re-login. If persistent, check Keycloak mapper config. | Config fix |
| **Tier change not reflected in JWT** | User has old tier limits | User reports wrong limits | Keycloak Admin API update failed. Manual fix via Keycloak admin UI. Token refresh picks up new claims. | Manual |

### 9.1 Lazy Tenant Creation Fallback

If the Keycloak SPI fails to create a tenant (S1 down, network issue), S9 implements a fallback:

```
1. S9 receives JWT with valid `sub` but no `tenant_id` claim
2. S9 calls S1: POST /internal/v1/auth/on-register {keycloak_user_id: sub, email: email_claim}
3. If S1 returns 201 or 409 (already exists): extract tenant_id
4. S9 caches the mapping: keycloak_sub → tenant_id (Valkey, 24h TTL)
5. Proceed with request using resolved tenant_id
6. Respond with header: X-Tenant-Provisioned: true (frontend can prompt re-login for clean JWT)
```

This ensures users are never permanently blocked by a transient failure.

---

## 10. Scalability & Performance

### 10.1 Bottleneck Analysis

| Component | Bottleneck | Mitigation |
|-----------|-----------|------------|
| JWKS validation | Network call to Keycloak on every request | JWKS cache (1h TTL), in-memory |
| Rate limit check | Valkey INCR on every request | Single O(1) operation, sub-ms |
| Tenant-scoped queries | Extra WHERE clause on intelligence tables | Partial indexes (only non-NULL tenant_id rows); zero cost on public queries |
| Keycloak registration | SPI makes HTTP call to S1 | Async fallback; registration not latency-critical |
| Entity resolution | Expanded search space (public + private) | Partial indexes; private entities are a small fraction of total |

### 10.2 Capacity Planning

| Metric | Expected at Launch | Expected at 1K Tenants |
|--------|-------------------|----------------------|
| Tenants | 10-50 | 1,000 |
| Private entities per tenant | 0-100 | 0-1,000 |
| Private relations per tenant | 0-500 | 0-5,000 |
| Total private entities | ~500 | ~100K |
| Total private relations | ~2,500 | ~500K |
| Rate limit Valkey keys | ~250 (50 tenants × 5 groups) | ~5,000 |
| Keycloak sessions | ~50 concurrent | ~500 concurrent |

All numbers are well within single-instance capacity for Postgres, Valkey, and Keycloak.

### 10.3 Index Impact

Partial indexes (`WHERE tenant_id IS NOT NULL`) have zero impact on existing public data queries:
- Postgres query planner ignores partial indexes when the filter doesn't match
- Index size is proportional only to private data volume
- No existing query performance regression

---

## 11. Test Strategy

### 11.1 Unit Tests

| Test | Service | What It Verifies | Priority |
|------|---------|-----------------|----------|
| `test_tenant_tier_upgrade` | S1 | `Tenant.upgrade_tier()` returns correct event, updates tier | HIGH |
| `test_tenant_tier_upgrade_while_suspended_raises` | S1 | Suspended tenant cannot upgrade tier | HIGH |
| `test_tenant_suspend_returns_event` | S1 | `Tenant.suspend()` returns TenantSuspended event | HIGH |
| `test_tenant_can_create_private_intelligence` | S1 | Returns True for PRO/ENTERPRISE, False for FREE | HIGH |
| `test_user_from_keycloak_registration` | S1 | Factory creates user with keycloak_user_id | MEDIUM |
| `test_tenant_tier_enum_values` | common | TenantTier has exactly free/pro/enterprise | HIGH |
| `test_rate_limit_config_frozen` | common | RateLimitConfig is immutable | LOW |
| `test_authenticated_user_from_jwt_claims` | S9 | Extracts correct fields from JWT payload | HIGH |
| `test_authenticated_user_missing_tenant_id_raises` | S9 | Rejects JWT without tenant_id claim | HIGH |
| `test_rate_limit_policy_resolution` | S9 | Correct limits resolved per tier × endpoint group | HIGH |
| `test_endpoint_group_mapping` | S9 | Request paths map to correct endpoint groups | HIGH |
| `test_rate_limit_defaults_from_env` | S9 | Env var overrides apply correctly | MEDIUM |

### 11.2 Integration Tests

| Test | Services | Infrastructure | What It Verifies |
|------|----------|---------------|-----------------|
| `test_registration_creates_tenant` | S1 | Postgres | POST /internal/v1/auth/on-register creates tenant + user |
| `test_registration_idempotent` | S1 | Postgres | Same keycloak_user_id twice → returns same tenant_id |
| `test_tier_change_emits_event` | S1 | Postgres + Kafka | PATCH tier → outbox event → Kafka message |
| `test_suspend_emits_event` | S1 | Postgres + Kafka | Suspend → outbox event → Kafka message |
| `test_jwks_validation` | S9 | Keycloak | RS256 JWT validated via JWKS endpoint |
| `test_jwks_cache_survives_keycloak_restart` | S9 | Keycloak | Cached JWKS keys work after Keycloak goes down |
| `test_rate_limit_per_tenant` | S9 | Valkey | Tenant A's rate limit doesn't affect Tenant B |
| `test_rate_limit_per_endpoint_group` | S9 | Valkey | Intelligence group limit independent of default group |
| `test_rate_limit_429_response` | S9 | Valkey | Exceeding limit returns 429 + Retry-After |
| `test_rate_limit_fail_open` | S9 | (Valkey down) | Requests allowed when Valkey unavailable |
| `test_suspended_tenant_rejected` | S9 | Valkey + Kafka | S9 rejects requests from suspended tenants |
| `test_tenant_isolation_migration` | intel-migrations | Postgres | Migration adds columns + indexes without errors |
| `test_existing_data_unaffected` | intel-migrations | Postgres | Existing rows have tenant_id = NULL after migration |

### 11.3 Tenant Isolation Tests (Critical)

| Test | Service | What It Verifies |
|------|---------|-----------------|
| `test_private_entity_invisible_to_other_tenant` | S6/S7 | Tenant A creates private entity → Tenant B cannot see it |
| `test_private_relation_invisible_to_other_tenant` | S7 | Tenant A creates private relation → Tenant B cannot see it |
| `test_public_data_visible_to_all_tenants` | S6/S7 | NULL tenant_id entities/relations visible to all |
| `test_tenant_sees_public_plus_own_private` | S7 | Query returns public + own private, never others' |
| `test_entity_resolution_scoped` | S6 | Entity resolution never matches other tenants' private entities |
| `test_private_entity_reuses_public_match` | S6 | If public entity matches, reuse it (don't create private copy) |
| `test_no_match_creates_private_entity` | S6 | No match + tenant context → new entity with tenant_id set |
| `test_free_tier_cannot_create_private` | S6/S7 | Free tier user rejected when attempting private intelligence |
| `test_confidence_scoped_to_tenant` | S7 | Confidence computation only uses public + own tenant evidence |
| `test_contradiction_scoped_to_tenant` | S7 | Contradictions only between public + own tenant claims |

### 11.4 End-to-End Tests

| Test | Flow | What It Verifies |
|------|------|-----------------|
| `test_full_registration_flow` | Keycloak → SPI → S1 → JWT | User registers, gets JWT with tenant_id + tier=free |
| `test_authenticated_request_e2e` | Frontend → S9 → downstream | JWT validated, rate limit checked, tenant context injected |
| `test_admin_tier_change_e2e` | Admin → S9 → S1 → Keycloak | Tier change reflected in next JWT |
| `test_tenant_lifecycle_e2e` | Register → use → upgrade → suspend | Full lifecycle from free signup to suspension |

### 11.5 Contract Tests

| Test | What It Verifies |
|------|-----------------|
| `test_tenant_created_avro_schema` | `tenant.created.v1.avsc` valid, forward-compatible |
| `test_tenant_tier_changed_avro_schema` | `tenant.tier_changed.v1.avsc` valid, forward-compatible |
| `test_tenant_suspended_avro_schema` | `tenant.suspended.v1.avsc` valid, forward-compatible |
