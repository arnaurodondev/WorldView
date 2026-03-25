# Docker Compose Test Infrastructure Guide

Last updated: 2026-03-24

## Compose Files

- Main dev stack: `infra/compose/docker-compose.yml`
- Test stack: `infra/compose/docker-compose.test.yml`

This guide focuses on `infra/compose/docker-compose.test.yml`.

## Design Summary

The test stack is profile-driven and optimized for deterministic E2E/integration:

- tmpfs-backed stateful services (clean state per run)
- one-shot migration/init containers with `service_completed_successfully`
- healthcheck-gated startup and `--wait` compatibility
- per-profile service selection for faster runs

## Available Profiles

- `portfolio-test`
- `market-ingestion-test`
- `market-data-test`
- `dev-tools`
- `all`

## Core Infrastructure Services

Service | Purpose | Host Port(s) | Health Check
--------|---------|--------------|-------------
postgres | shared test Postgres | 55433 | `pg_isready -U postgres`
timescaledb | market-data DB | 5433 | `pg_isready -U postgres`
valkey | cache/redis layer | 6379 | `valkey-cli ping`
minio | object storage | 7480, 7481 | `mc ready local`
kafka | event broker | 9092 | `kafka-broker-api-versions`
schema-registry | Avro registry | 8081 | `curl /subjects`

One-shot init containers:

- `minio-init-test`
- `kafka-init`
- `schema-registry-init`
- `<service>-migrate` jobs

Long-running background processes:

- `portfolio-dispatcher`
- `market-ingestion-scheduler`
- `market-ingestion-worker`
- `market-ingestion-dispatcher`
- `market-data-dispatcher`

## Startup and Teardown

### Start a specific profile

```bash
cd worldview

docker compose -f infra/compose/docker-compose.test.yml \
  --profile portfolio-test up --build --wait
```

### Stop and cleanup

```bash
docker compose -f infra/compose/docker-compose.test.yml \
  --profile portfolio-test down -v
```

### Start all test services

```bash
docker compose -f infra/compose/docker-compose.test.yml \
  --profile all up --build --wait
```

## Typical Execution Sequences

### Portfolio E2E

1. Start `portfolio-test` profile.
2. Run `pytest services/portfolio/tests/e2e -m e2e -v --tb=short`.
3. Tear down with `down -v`.

### Market-ingestion integration + E2E

1. Start `market-ingestion-test` profile.
2. Export env vars to host-mapped ports (same model as CI).
3. Run integration tests then e2e tests.
4. Tear down profile.

### Market-data E2E

1. Start `market-data-test` profile.
2. Run `pytest services/market-data/tests/e2e -m e2e -v --tb=short`.
3. Tear down profile.

## Environment Variable Guidance

Use service-local docker env examples as the source of truth:

- `services/portfolio/configs/docker.env.example`
- `services/market-ingestion/configs/docker.env.example`
- `services/market-data/configs/docker.env.example`

For host-run tests against compose services, map to localhost ports:

- Postgres: `localhost:55433`
- TimescaleDB: `localhost:5433`
- Kafka: `localhost:9092`
- Schema Registry: `http://localhost:8081`
- MinIO API: `http://localhost:7480`
- Valkey: `redis://localhost:6379/0`

## Health and Readiness Debugging

### Check status

```bash
docker compose -f infra/compose/docker-compose.test.yml --profile all ps
```

### Tail logs

```bash
docker compose -f infra/compose/docker-compose.test.yml --profile all logs -f
```

### Check a single service

```bash
docker compose -f infra/compose/docker-compose.test.yml --profile all logs -f market-ingestion
```

### Common failure modes

1. Migration container exits: inspect `<service>-migrate` logs.
2. Schema Registry not ready: verify kafka health first; schema registry depends on kafka.
3. Worker/dispatcher unhealthy in `--wait`: ensure dedicated process healthchecks are present.
4. Connection refused from local pytest: verify host-mapped ports, not container internal DNS names.

## Recommended Local Pattern

Use scripts added in this wave:

- `scripts/wait-for-services.sh`
- `scripts/test-quick.sh`
- `scripts/test-full.sh`

These scripts intentionally align with the existing compose file location and service profile model.
