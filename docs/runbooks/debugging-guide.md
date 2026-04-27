# Debugging Guide

A repeatable process for diagnosing and fixing failures in tests, runtime workflows, and production issues.

---

## Diagnosis Loop

1. **Reproduce** reliably — get a failing test, curl command, or log trace.
2. **Isolate** the failing boundary (domain, adapter, contract, infra, timing).
3. **Classify** root cause (code / spec / test / environment / timing).
4. **Implement** the smallest fix.
5. **Add** or update regression test.
6. **Re-run** targeted test suite, then adjacent suites.
7. **Record** in `docs/BUG_PATTERNS.md` if a new failure pattern is discovered.

---

## Debugging Tools

### Python / Backend

```bash
# Run a single test with full output
cd services/<service>
python -m pytest tests/path/to/test.py::test_case -vv --tb=long -s

# Run tests matching a keyword
python -m pytest tests/ -k "test_create_portfolio" -vv

# Run by marker
python -m pytest tests/ -m "unit" -v --tb=short
python -m pytest tests/ -m "integration" -v --tb=short
python -m pytest tests/ -m "contract" -v --tb=short

# Run with coverage
python -m pytest tests/ --cov=src/<service> --cov-report=term-missing

# Lint a single file
uvx ruff check src/<service>/path/to/file.py --diff
uvx ruff format src/<service>/path/to/file.py --diff

# Type check a single service
mypy src/<service>/ --config-file=../../mypy.ini
```

### Frontend

```bash
cd apps/worldview-web

# Run a single test
pnpm test -- __tests__/specific-test.test.tsx

# Run tests matching a pattern
pnpm test -- -t "should render dashboard"

# Debug in browser (Playwright)
pnpm test:e2e -- --debug

# Check TypeScript errors
pnpm typecheck
```

### Infrastructure

```bash
# Check all infrastructure health
docker compose --profile infra ps

# Tail logs for a specific service
docker compose logs -f svc-portfolio
docker compose logs -f kafka
docker compose logs -f postgres

# Check Kafka topics and consumers
docker compose --profile tools up -d
# Open http://localhost:8090 (Kafka UI)

# Check database state
docker compose --profile tools up -d
# Open http://localhost:8091 (pgweb)

# Or connect directly
docker exec -it worldview-postgres-1 psql -U postgres -d portfolio_db

# Check MinIO buckets
# Open http://localhost:7481 (minioadmin/minioadmin)

# Check Valkey state
docker exec -it worldview-valkey-1 valkey-cli
> KEYS *
> GET auth:user:<sub>
> TTL rl:v1:user:<user_id>

# Check Ollama models
docker exec -it worldview-ollama-1 ollama list
```

### Docker Compose Test Stack

For integration/E2E tests that need isolated infrastructure:

```bash
# Start test stack
docker compose -f infra/compose/docker-compose.test.yml --profile all up -d --wait

# Check health
docker compose -f infra/compose/docker-compose.test.yml --profile all ps

# Tail logs
docker compose -f infra/compose/docker-compose.test.yml --profile all logs -f

# Tear down
docker compose -f infra/compose/docker-compose.test.yml --profile all down -v
```

---

## Common Failure Categories

### 1. Schema Mismatch (Avro / OpenAPI)

**Symptoms**: `SerializationError`, `DeserializationError`, Kafka consumer crashes, Schema Registry rejection.

**Debug**:
```bash
# Validate Avro schemas
./scripts/gen-contracts.sh

# Check Schema Registry
curl http://localhost:8081/subjects | jq
curl http://localhost:8081/subjects/<topic>-value/versions/latest | jq

# Compare schema in code vs registry
cat infra/kafka/schemas/<topic>.avsc | jq
```

**Common fix**: Schema field added without `"default"` value — add one for forward compatibility.

### 2. Config / Environment Drift

**Symptoms**: Service fails to start, `ValidationError` from pydantic-settings, wrong database/URL.

**Debug**:
```bash
# Check what env vars the service sees
cd services/<service>
python -c "from <service>.config import Settings; s = Settings(); print(s.model_dump())"

# Diff example vs actual
diff configs/dev.local.env.example configs/.env
```

**Common fix**: New config var added to Settings but not to `.env` — copy from `dev.local.env.example`.

### 3. Async Timing / Eventual Consistency

**Symptoms**: Test passes in isolation, fails in suite. Race condition between Kafka publish and consume.

**Debug**:
```bash
# Run test in isolation
python -m pytest tests/path/to/test.py::test_case -vv -s

# Run full suite to reproduce
python -m pytest tests/ -v

# Check for event loop issues
# Use asyncio.run() not get_event_loop().run_until_complete() (BP-133)
```

**Common fix**: Add polling/retry in test (`poll_until` helper), or fix event loop isolation.

### 4. Migration Drift

**Symptoms**: `alembic.util.exc.CommandError: Target database is not up to date`, column does not exist.

**Debug**:
```bash
cd services/<service>
alembic current        # What revision is the DB at?
alembic history -v     # Full migration history
alembic heads          # What's the latest?
```

**Common fix**: `make migrate` (run `alembic upgrade head`).

### 5. Container Readiness / Healthcheck Sequencing

**Symptoms**: Service starts before Postgres/Kafka is ready, connection refused errors.

**Debug**:
```bash
docker compose --profile infra ps    # Check health status
docker compose logs kafka | tail -20  # Check if Kafka is "started"
docker compose logs postgres | tail -20
```

**Common fix**: Kafka needs ~15s to start. Use `depends_on: condition: service_healthy` in docker-compose.

### 6. Auth / JWT Failures

**Symptoms**: 401 Unauthorized, "invalid token", "JWKS fetch failed", "no X-Internal-JWT".

**Debug**:
```bash
# Check S9 can start with OIDC
docker compose logs svc-api-gateway | grep -i "oidc\|jwks\|error"

# Test JWKS endpoint
curl http://localhost:8000/internal/jwks | jq

# Decode a JWT (install: brew install mike-engber/jwt-cli/jwt-cli)
echo "<token>" | jwt decode -

# Check if service has X-Internal-JWT in test fixtures
grep -r "X-Internal-JWT\|_INTERNAL_HEADERS\|_make_system_jwt" services/<service>/tests/
```

**Common fixes**:
- Missing `X-Internal-JWT` in test fixtures (BP-134)
- S9 `OIDC_DISCOVERY_OPTIONAL=true` for dev without Zitadel
- Generate keypair: `./scripts/generate-internal-keypair.sh`

### 7. Kafka Consumer Issues

**Symptoms**: Consumer hangs, duplicate processing, messages in dead-letter topic.

**Debug**:
```bash
# Check consumer group lag
docker exec -it worldview-kafka-1 /opt/kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --describe --all-groups

# Check dead-letter topics
# Open Kafka UI at http://localhost:8090 — look for *.dead-letter.* topics

# Check consumer logs
docker compose logs svc-nlp-pipeline | grep -i "error\|exception\|dead-letter"
```

**Common fixes**:
- Missing idempotency check (every consumer must handle re-delivery)
- `is_duplicate` called before `get_unit_of_work` (BP feedback)
- Missing serializer for new topic in OutboxDispatcher (BP-147)

### 8. Frontend API Errors

**Symptoms**: Blank page, network errors in browser console, CORS errors.

**Debug**:
1. Open browser DevTools → Network tab
2. Check if `/api/v1/*` requests reach S9
3. Check S9 logs: `docker compose logs svc-api-gateway | tail -50`
4. Test directly: `curl http://localhost:8000/healthz`
5. Check CORS: `curl -H "Origin: http://localhost:3001" -v http://localhost:8000/v1/news/relevant`

**Common fixes**:
- S9 not running — start it first
- CORS origin not in allowlist — add to `API_GATEWAY_CORS_ORIGINS`
- Next.js rewrite not working — check `next.config.ts` rewrites + `API_GATEWAY_URL` in `.env.local`

---

## Debugging Specific Service Types

### Debugging S9 API Gateway

S9 is stateless — most issues are configuration or downstream service failures.

```bash
# Health check
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz

# Test auth flow (dev mode)
curl http://localhost:8000/v1/auth/me -H "Authorization: Bearer <token>"

# Test proxy to downstream
curl http://localhost:8000/v1/news/relevant | jq

# Check rate limiting
for i in $(seq 1 25); do curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/v1/news/relevant; done
# Should get 429 after 20 requests (unauthenticated limit)
```

### Debugging Kafka Pipeline (S2→S4→S5→S6→S7)

```bash
# 1. Check if events are being produced
# Open Kafka UI (http://localhost:8090) → Topics → select topic → Messages

# 2. Check consumer groups
docker exec -it worldview-kafka-1 /opt/kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --describe --all-groups

# 3. Trace a specific event through the pipeline
# Search logs for a document/article ID across services
docker compose logs | grep "<document_id>"
```

### Debugging NLP / ML (S6, S8)

```bash
# Check Ollama is running and has models
docker exec -it worldview-ollama-1 ollama list
# Should show: qwen3:0.6b, bge-large (nomic-embed-text optional)

# Pull missing model
docker exec -it worldview-ollama-1 ollama pull nomic-embed-text

# Test embedding directly
curl http://localhost:11434/api/embeddings -d '{"model":"nomic-embed-text","prompt":"test"}'

# Check for token overflow (BP-121: BGE-large 512 token limit)
# Truncate input to ≤1500 chars
```

---

## Useful One-Liners

```bash
# Find which service owns a Kafka topic
grep -r "topic_name\|TOPIC" services/*/src/*/config.py | grep "<topic>"

# Find which service has an endpoint
grep -r "@router\.(get\|post\|put\|delete)" services/*/src/*/api/ | grep "<path>"

# Check all service health endpoints
for port in 8001 8002 8003 8004 8005 8006 8007 8008 8000 8010; do
  echo -n "Port $port: "; curl -s -o /dev/null -w "%{http_code}" http://localhost:$port/healthz; echo
done

# Kill a process on a port
lsof -ti :8001 | xargs kill -9

# Reset a database (destructive!)
docker exec -it worldview-postgres-1 psql -U postgres -c "DROP DATABASE portfolio_db; CREATE DATABASE portfolio_db;"
cd services/portfolio && make migrate

# Restart all containers
docker compose --profile infra --profile runtime restart

# Clean Docker (nuclear option)
docker compose down -v    # removes volumes too!
docker compose --profile infra up -d
docker compose --profile init up
```

---

## Reference

- **Bug patterns**: `docs/BUG_PATTERNS.md` — known failure patterns and fixes
- **Testing guide**: `docs/testing/TESTING_GUIDE.md` — test layers and execution
- **Service docs**: `docs/services/<service>.md` — per-service API and architecture
- **Service context**: `services/<service>/.claude-context.md` — quick reference for each service
