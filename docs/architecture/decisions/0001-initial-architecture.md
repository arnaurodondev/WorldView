# ADR-0001: Initial Architecture — Monorepo with Hatch, Clean Architecture, Event-Driven

**Date**: 2026-02-28
**Status**: Accepted
**Deciders**: Arnau Rodon

## Context

We are rebuilding the thesis market intelligence platform from scratch ("Worldview").
The original platform (`platform_repo`) used Poetry per-service, Clean/Hexagonal
architecture, Kafka with Avro schemas, transactional outbox, and claim-check patterns.

Key decisions needed:
1. **Packaging**: Poetry (per-project) vs Hatch (monorepo workspaces) vs uv
2. **Monorepo structure**: flat vs nested, service naming
3. **Architecture pattern**: continuation of Clean Architecture vs simpler alternatives
4. **New services**: how to integrate Content, Intelligence, RAG/Chat, API Gateway

## Decision

### 1. Packaging: Hatch

We adopt **Hatch** (`hatchling` build backend) for the monorepo.

**Why Hatch over Poetry**:
- Hatch supports monorepo workspaces natively (each service/lib has its own `pyproject.toml`)
- Hatch is PEP 621 compliant (standard `[project]` table) — future-proof
- Poetry requires non-standard `[tool.poetry]` tables and has slower dependency resolution
- Hatch integrates with `uv` for fast installs when desired

**Why not uv alone**:
- `uv` as a build backend is experimental; as a package installer it's excellent
- We use `uv pip install -e .` for development installs but `hatchling` as build backend

### 2. Monorepo Structure

```
worldview/
├── services/   # 7 microservices (each: pyproject.toml + src/ + tests/ + alembic/)
├── libs/       # 5 shared libraries (each: pyproject.toml + src/ + tests/)
├── infra/      # Docker Compose, Kafka schemas, DB init
├── scripts/    # Bootstrap, lint, test, gen-contracts
├── docs/       # All documentation
```

Services reference libs via relative path dependencies:
```toml
[project]
dependencies = [
    "messaging @ {root:uri}/../../../libs/messaging",
]
```

### 3. Clean/Hexagonal Architecture (Continued)

We preserve the Clean Architecture pattern from the original platform:
- `domain/` = pure business logic, no framework dependencies
- `application/` = use cases and port interfaces
- `infrastructure/` = adapters (DB, Kafka, S3, external APIs)
- `api/` = FastAPI routers and Pydantic schemas

This pattern proved effective in the original platform and provides clear
boundaries for testing and dependency management.

### 4. New Services

Following the Architectural Rebuild Plan, we implement 7 deployable units:

| Service | Origin | Notes |
|---------|--------|-------|
| Portfolio | Existing (reuse) | Minimal changes needed |
| Market Ingestion | Existing (reuse) | Refine scheduling and backfill |
| Market Data | Existing (reuse) | Add TimescaleDB, expand fundamentals API |
| Content | New (S4+S5 merged) | Ingestion + Store modules in one process |
| Intelligence | New (S6+S7 merged) | NLP + KG modules in one process |
| RAG/Chat | New (stateless) | Orchestrates retrieval + LLM completion |
| API Gateway | New (stateless) | BFF pattern with caching and composition |

### 5. Tooling Standardization

| Concern | Tool | Config |
|---------|------|--------|
| Linting | ruff | `ruff.toml` (repo root) |
| Type checking | mypy | `mypy.ini` (repo root) |
| Testing | pytest | `pytest.ini` (repo root) + per-service |
| Pre-commit | pre-commit | `pre-commit-config.yaml` |
| CI | GitHub Actions | `.github/workflows/ci.yml` |

## Consequences

### Positive
- Single repo = single CI pipeline, atomic cross-service changes, shared tooling
- Clean Architecture = testable domain logic, swappable infrastructure
- Hatch = standards-compliant, fast, monorepo-friendly
- Reuse of proven patterns from original platform reduces risk

### Negative
- Monorepo CI must test all services on every push (mitigated by path-based filtering)
- Hatch is less widely known than Poetry (documentation may be harder to find)
- 7 services in local Docker may strain resources (mitigated by profile-based compose)

### Neutral
- Migration from Poetry to Hatch is mechanical (rewrite pyproject.toml headers)
- Clean Architecture file count is higher than a flat structure, but self-documenting

## Alternatives Considered

| Alternative | Pros | Cons | Why Rejected |
|-------------|------|------|--------------|
| Poetry per-service | Already used in legacy | Non-standard pyproject.toml; slow resolver | Hatch is more future-proof |
| uv-only | Fastest installs | Build backend still experimental | Use uv as installer, hatch as builder |
| Poly-repo | Independent deployments | Cross-cutting changes need coordinated PRs | Thesis scope = single developer |
| Django-style (fat services) | Less boilerplate | Tight coupling, hard to test domain logic | Contradicts data-ownership principle |

## References

- `docs/MASTER_PLAN.md` — full system architecture
- `docs/ARCHITECTURAL_REBUILD_PLAN.md` — detailed rebuild rationale
- PEP 621: https://peps.python.org/pep-0621/
- Hatch docs: https://hatch.pypa.io/
