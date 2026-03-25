# Worldview Testing Guide

Last updated: 2026-03-24

## Overview

Worldview testing is service-centric, with tests distributed across:

- `tests/architecture/` for repository-wide architecture rules
- `services/*/tests/` for service unit, integration, contract, e2e
- `libs/*/tests/` for shared library validation

This guide provides practical local commands that match current CI behavior.

## Prerequisites

1. Python 3.11+ (3.12 recommended)
2. Docker Desktop / Docker Engine with Compose plugin
3. Dependencies installed for target service/lib under test

## Quick Start

### Run fast checks

```bash
./scripts/test-quick.sh
```

### Run full layered suite

```bash
./scripts/test-full.sh
```

## Test Layers and Commands

### Architecture tests (root)

```bash
pytest tests/architecture -v --tb=short
```

### Library tests

```bash
./scripts/test-libs.sh
```

### Service unit-ish tests (exclude infra tiers)

```bash
pytest services/<service>/tests -m "not integration and not e2e and not live and not slow" -v --tb=short
```

### Portfolio contract tests

```bash
pytest services/portfolio/tests/contract -m contract -v --tb=short
```

### Service integration tests

Portfolio and market-data (often testcontainers-backed):

```bash
pytest services/portfolio/tests/integration -m integration -v --tb=short
pytest services/market-data/tests/integration -m integration -v --tb=short
```

Market-ingestion (compose-backed):

```bash
docker compose -f infra/compose/docker-compose.test.yml --profile market-ingestion-test up --build --wait
pytest services/market-ingestion/tests/integration -m integration -v --tb=short
docker compose -f infra/compose/docker-compose.test.yml --profile market-ingestion-test down -v
```

### E2E tests

```bash
docker compose -f infra/compose/docker-compose.test.yml --profile portfolio-test up --build --wait
pytest services/portfolio/tests/e2e -m e2e -v --tb=short
docker compose -f infra/compose/docker-compose.test.yml --profile portfolio-test down -v
```

Equivalent profiles:

- market-ingestion: `market-ingestion-test`
- market-data: `market-data-test`

## Marker Taxonomy

Configured markers:

- `unit`
- `integration`
- `contract`
- `e2e`
- `slow`

Examples:

```bash
pytest -m "not integration"
pytest -m "contract"
pytest -m "e2e"
```

## Compose Test Infrastructure

Compose file:

- `infra/compose/docker-compose.test.yml`

Important host ports:

- PostgreSQL: 55433
- TimescaleDB: 5433
- Kafka: 9092
- Schema Registry: 8081
- MinIO: 7480
- Valkey: 6379

See `docs/testing/DOCKER_COMPOSE_TEST_GUIDE.md` for full details.

## Debugging Failing Tests

### Increase output detail

```bash
pytest path/to/test_file.py::test_name -vv --tb=long -s
```

### Watch compose logs

```bash
docker compose -f infra/compose/docker-compose.test.yml --profile all logs -f
```

### Verify health quickly

```bash
./scripts/wait-for-services.sh
```

### Typical issue categories

1. Configuration mismatch between local env and compose host ports.
2. Migration not applied before API/worker starts.
3. Kafka/schema registry startup race.
4. Async eventual-consistency assertions without enough polling window.

## Coverage

Repository-level coverage config in `pyproject.toml`:

- branch coverage enabled
- source includes `services` and `libs`
- minimum threshold currently 60

Generate report:

```bash
pytest --cov=services --cov=libs --cov-report=term --cov-report=html
```

## Recommended Daily Workflow

1. `./scripts/test-quick.sh`
2. target service unit/integration tests
3. contract tests for changed event/API contracts
4. `./scripts/test-full.sh` before merge
