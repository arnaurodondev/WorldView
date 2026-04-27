# ADR-TENANT-001: Article Scoping -- Platform-Global vs Tenant-Scoped

**Status**: Accepted
**Date**: 2026-04-24
**Context**: PRD-0025 (Auth Foundation) introduced `tenant_id` across all services. QA findings F-009 and F-010 exposed that the NLP pipeline's article-related tables had no tenant isolation, creating a cross-tenant data leakage risk once multi-tenancy is active.

---

## Decision

### Platform-global tables (no tenant_id column)

The following tables store **public-domain news** ingested globally. They are not tenant-specific and do not reveal any tenant's investment interests:

| Table | Database | Rationale |
|-------|----------|-----------|
| `document_source_metadata` | `content_store_db` | Raw article metadata from public news sources |
| `routing_decisions` | `nlp_db` | NLP processing tier assignment -- algorithmic, not tenant-specific |
| `article_impact_windows` | `nlp_db` | Price-impact labels derived from public OHLCV data |

### Tenant-scoped table (tenant_id column added)

| Table | Database | Rationale |
|-------|----------|-----------|
| `entity_mentions` | `nlp_db` | Reveals which entities appear in articles processed for a tenant's watchlist. Exposes watchlist composition indirectly. |

The `entity_mentions.tenant_id` column is **nullable** to support legacy rows ingested before multi-tenancy. Queries use `AND (em.tenant_id IS NULL OR em.tenant_id = :tenant_id)` to include both legacy and tenant-scoped rows.

---

## API Endpoint Scoping

| Endpoint | Scoping | Auth | Rationale |
|----------|---------|------|-----------|
| `GET /api/v1/news/top` | **Platform-global** | System JWT (nil-UUID tenant) | Public news feed -- all tenants see the same top stories |
| `GET /api/v1/entities/{id}/articles` | **Tenant-filtered** | User JWT | Requires watchlist ownership check (entity must be in the requesting tenant's watchlist). Query filters `entity_mentions` by `tenant_id`. |

### Watchlist ownership guard (F-010)

`GET /api/v1/entities/{id}/articles` performs a watchlist membership check before returning results:

```python
if tenant_id and not await watchlist_cache.is_watched(tenant_id, entity_id):
    raise HTTPException(status_code=404, detail="Entity not found")
```

- Uses the existing `WatchlistCache` (Valkey-backed, populated from `portfolio.watchlist.updated.v1` Kafka events)
- Returns 404 (not 403) to prevent entity ID enumeration
- Fail-open if Valkey is unavailable (logged for ops visibility) -- authoritative store is S1 (Portfolio)

---

## Consequences

1. **Articles remain globally queryable** via `GET /news/top` -- no per-tenant duplication of article storage.
2. **Entity-level intelligence is tenant-scoped** -- a tenant cannot enumerate another tenant's watched entities or see which articles are linked to entities outside their watchlist.
3. **Legacy data compatibility** -- the nullable `tenant_id` on `entity_mentions` means existing rows (ingested before multi-tenancy) are visible to all tenants. New rows stamped with `tenant_id` from the Kafka event envelope are visible only to the originating tenant.
4. **Future RLS option** -- if the platform scales beyond ~100 tenants, PostgreSQL Row-Level Security (RLS) policies on `entity_mentions` can replace the application-layer filter with zero API changes.
5. **No schema migration needed for article tables** -- `document_source_metadata`, `routing_decisions`, and `article_impact_windows` remain unchanged.

---

## Alternatives Considered

| Option | Description | Why rejected |
|--------|-------------|-------------|
| A: RLS on all tables | PostgreSQL Row-Level Security across all article/NLP tables | Over-engineered for current scale (single tenant / thesis). High effort, requires careful policy testing. Recommended for 100+ tenant scale. |
| B: tenant_id on all tables | Add `tenant_id` to `document_source_metadata`, `routing_decisions`, `article_impact_windows` | Articles are public-domain news. Adding tenant_id would require duplicating article ingestion per tenant or assigning articles to a "system" tenant -- both add complexity without security benefit. |
| C: Schema-per-tenant | Separate PostgreSQL schemas per tenant | Extreme operational overhead. Not viable for a thesis-stage platform. |

---

## References

- PRD-0025: Auth Foundation (introduced tenant_id)
- F-009: Missing tenant_id filter in nlp-pipeline news queries
- F-010: No entity ownership check in entity articles endpoint
- `docs/audits/2026-04-24-qa-findings-investigation-report.md`
