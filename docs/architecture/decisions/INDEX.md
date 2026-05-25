# Architecture Decision Records — Index

> All ADRs for the Worldview platform. Listed in chronological order.
> To create a new ADR: copy `ADR_TEMPLATE.md`, name it `NNNN-<short-title>.md`.

---

## Core ADRs (`docs/architecture/decisions/`)

| ADR | Title | Status | Date |
|-----|-------|--------|------|
| [ADR-0001](0001-initial-architecture.md) | Monorepo with Hatch, Clean Architecture, Event-Driven | Accepted | 2026-02-28 |
| [ADR-0002](0002-frontend-tooling.md) | Frontend Tooling — Vite + React + pnpm | **Superseded** (Next.js 15 migration 2026-04-17) | 2026-02-28 |
| [ADR-0003](0003-observability-stack.md) | Observability Stack — structlog + Prometheus + OpenTelemetry | Accepted | 2026-03-07 |
| [ADR-0004](0004-valkey-key-taxonomy.md) | Valkey Key Taxonomy and TTL Conventions | Accepted | 2026-03-08 |
| [ADR-0005](0005-messaging-error-classification.md) | Messaging Error Classification — Retryable vs Fatal | Accepted | 2026-03-08 |
| [ADR-0006](0006-timescaledb-hypertable-vs-list-partitioning.md) | TimescaleDB Hypertable for OHLCV Storage | Accepted | 2026-03-10 |
| [ADR-EODHD-FAILOVER](ADR_EODHD_FAILOVER.md) | EODHD API Failover Strategy (Circuit Breaker + 7-step chain) | Accepted | 2026-04-24 |
| [ADR-F-02](ADR-F-02-websocket-direct-connection.md) | WebSocket Direct Connection to S10 (only exception to "frontend → S9" rule) | Accepted | 2026-04-18 |
| ADR-F-12 | `entity_id` ≠ `instrument_id` (PRD-0027 §1367, inline) | **Superseded by ADR-F-16** | 2026-04-08 |
| [ADR-F-16](ADR-F-16-instrument-entity-id-unification.md) | Instrument / Entity ID Unification (single UUID per tradable security) | Accepted | 2026-05-20 |

## Service/Cross-Cutting ADRs (`docs/adrs/`)

| ADR | Title | Status | Date |
|-----|-------|--------|------|
| [ADR-AUTH-002](../../adrs/ADR-AUTH-002-jwt-middleware-consolidation.md) | InternalJWTMiddleware Shared Library Extraction | **Proposed** (not yet implemented) | 2026-04-24 |
| [ADR-TENANT-001](../../adrs/ADR-TENANT-001-article-scoping.md) | Article Scoping — Platform-Global vs Tenant-Scoped | Accepted | 2026-04-24 |

---

## Decision Principles

1. Write an ADR **before** implementing a major architectural change (R4/R16).
2. ADRs are immutable once accepted — create a new ADR to supersede, don't edit the old one.
3. "Superseded" ADRs are kept for historical context.
4. Reference ADRs in PR descriptions and related code comments.

## Next ADR number

Check `git log --oneline docs/architecture/decisions/` for the latest to avoid collisions (R32).
The last numbered ADR in `docs/architecture/decisions/` is **ADR-0006**.
