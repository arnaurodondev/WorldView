# Debugging Guide

## Goal

Provide a repeatable process for diagnosing and fixing failures in tests and runtime workflows.

## Loop

1. Reproduce reliably.
2. Isolate failing boundary (domain, adapter, contract, infra).
3. Classify root cause (code/spec/test/environment/timing).
4. Implement smallest fix.
5. Add or update regression test.
6. Re-run targeted then adjacent suites.
7. Record in `docs/ai-interactions/DEBUGGING_LOG.md`.

## Commands

```bash
pytest path/to/test.py::test_case -vv --tb=long -s
pytest -m "contract" -v --tb=short
pytest -m "integration" -v --tb=short
```

For infrastructure-backed debugging:

```bash
docker compose -f infra/compose/docker-compose.test.yml --profile all ps
docker compose -f infra/compose/docker-compose.test.yml --profile all logs -f
```

## Common Categories

- schema mismatch (Avro/OpenAPI)
- config/env drift
- async timing and eventual consistency
- migration drift
- container readiness/healthcheck sequencing
