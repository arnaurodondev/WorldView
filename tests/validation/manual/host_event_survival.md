# Host-event survival runbook (T-G-2-02)

**PLAN-0093 Wave G-2 / audit ref F-LOG-INFRA-001**

This runbook manually simulates the 21:40 Docker daemon event that originally
exposed the missing `restart: unless-stopped` policies on `ollama`,
`schema-registry`, `market-data`, and `minio`. After the Sub-Plan A
remediation, every critical container should come back up cleanly without
operator intervention.

Run this checklist after any change to:
- `infra/compose/docker-compose.yml` (especially `restart:` or `depends_on:`)
- Critical healthcheck configurations
- The Docker daemon version / configuration on the dev host

---

## Prerequisites

- Full platform up: `make dev` (all profiles)
- All containers healthy: `docker ps --format '{{.Status}}' | grep -v healthy | wc -l` should equal the number of one-shot init/migrate containers (Exited 0)
- Note the **expected total container count** for your profile mix (run `docker ps -a | grep worldview | wc -l` and record the number — call this `EXPECTED_TOTAL`)

---

## Procedure

### 1. Stop the six critical infra containers

```bash
docker stop \
  worldview-postgres-1 \
  worldview-kafka-1 \
  worldview-valkey-1 \
  worldview-ollama-1 \
  worldview-schema-registry-1 \
  worldview-market-data-1
```

> **Note:** Replace `worldview-` with your compose project prefix if you
> launched the stack with a non-default `COMPOSE_PROJECT_NAME`.

### 2. Wait 60 seconds

This simulates the gap between a host docker bounce and the dependent
services' health-check expiration windows. Many consumers will log
disconnect errors in this window — that is expected.

### 3. Verify all 6 are stopped

```bash
docker ps -a \
  --format '{{.Names}}\t{{.Status}}' \
  | grep -E 'postgres|kafka|valkey|ollama|schema-registry|market-data'
```

Every line should show `Exited (...)`.

### 4. Restart all 6

```bash
docker start \
  worldview-postgres-1 \
  worldview-kafka-1 \
  worldview-valkey-1 \
  worldview-ollama-1 \
  worldview-schema-registry-1 \
  worldview-market-data-1
```

### 5. Wait 120 seconds for healthchecks

Healthcheck `start_period` values range from 15s (MinIO) to 45s (knowledge-graph
API). 120 seconds gives every dependent worker time to reconnect.

### 6. Verify container count

```bash
docker ps -a \
  --format '{{.Status}}\t{{.Names}}' \
  | grep worldview \
  | grep -v Exited \
  | wc -l
```

This count must equal `EXPECTED_TOTAL` minus the number of `Exited (0)` one-shot
init/migrate containers. If any container is missing or restart-looping,
fail the check and inspect logs:

```bash
docker logs --tail 100 <container-name>
```

### 7. Run the rdkafka probe test (T-G-2-03)

```bash
WORLDVIEW_DOCKER_TEST_ALLOWED=1 \
KAFKA_BOOTSTRAP_TEST=localhost:9092 \
pytest tests/validation/test_kafka_dns_recovery.py -v
```

Consumers must reconnect within 60 seconds. The test asserts metric
`kafka_consumer_messages_consumed_total` advances post-restart.

---

## Expected outcome — green

- Every critical infra container shows `Up (healthy)` in `docker ps`
- Every consumer container shows `Up` (not `Restarting`)
- `tests/validation/test_kafka_dns_recovery.py` passes
- No container appears in `docker ps -a | grep -i restart`
- API endpoints respond:
  - `curl -fsS http://localhost:8003/healthz` → 200 (market-data)
  - `curl -fsS http://localhost:8081/subjects` → 200 (schema-registry)
  - `curl -fsS http://localhost:11434/api/tags` → 200 (ollama)

## Expected outcome — red (what to investigate)

| Symptom | Likely cause |
|---|---|
| Critical container shows `Exited` after step 5 | Missing `restart: unless-stopped` — re-run `pytest tests/validation/test_restart_policy.py` |
| Consumer container shows `Restarting` | Missing `depends_on` health gate — see retry-worker contract in `test_restart_policy.py::_RETRY_WORKER_HEALTH_DEPS` |
| Kafka consumers stuck after step 5 | rdkafka DNS-cache bug regressed — see F-LOG-003 |
| rag-chat container exited with code != 0 | `APP_ENV` enforcement triggered — run `tests/validation/test_app_env_enforcement.py` |

---

## Compounding the result

After running this runbook, append the outcome to
`docs/audits/2026-05-23-qa-intelligence-pipelines-report.md` under the
F-LOG-INFRA-001 section with date + git SHA + pass/fail.
