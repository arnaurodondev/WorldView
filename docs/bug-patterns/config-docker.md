# Bug Patterns — Config & Docker

> **Category**: config-docker
> **Description**: pydantic-settings, Docker images, Docker Compose, env var loading, Makefile targets, Dockerfile patterns
> **Count**: 26 patterns
> **Back to index**: [BUG_PATTERNS.md](../BUG_PATTERNS.md)

---

## BP-002 — Env file loaded in wrong place (Makefile / Docker Compose)

**Date discovered**: 2026-03-10
**Services affected**: `portfolio`, `market-ingestion` (all services are susceptible)
**Prompts updated**: `0002-exec-portfolio-migration-wave-*.md`, `0003-exec-market-ingestion-migration-wave-*.md`

### Symptom

Three distinct but related failure modes, all caused by environment variables not
reaching the service process:

- **Local `make run`**: service starts but uses wrong defaults (wrong DB URL, missing
  API keys). Pydantic-settings silently uses field defaults when env vars are absent.
- **`make test-integration`**: tests fail with `connection refused` or `authentication
  failed` because infra env vars (DB URL, Kafka bootstrap servers) were never exported.
- **Docker Compose (`make test-e2e`)**: service starts with `DATABASE_URL=...` (no
  prefix) so pydantic-settings (env_prefix="SERVICE_") silently ignores the var and
  uses the wrong default host.

### Root causes (three independent bugs, all must be fixed together)

#### Bug A — Makefile `.env-check` verifies file existence but never sources it

```makefile
# WRONG — checks file exists, but variables are NEVER exported
.env-check:
    @test -f configs/dev.local.env || (echo "Missing configs/dev.local.env"; exit 1)

run: .env-check
    $(VENV)/bin/uvicorn service.app:create_app --factory --reload --port 8000
```

The `set -a && . ./configs/dev.local.env && set +a` idiom is missing from every
`run*`, `test-integration`, and `test-e2e` target. The `.env-check` guard is
useless without actual sourcing.

#### Bug B — `docker-compose.yml` uses inline `environment:` with wrong variable names

```yaml
# WRONG — vars without SERVICE_ prefix; pydantic-settings silently ignores them
services:
  my-service:
    environment:
      DATABASE_URL: postgresql+asyncpg://postgres:postgres@postgres:5432/my_db
      KAFKA_BOOTSTRAP_SERVERS: kafka:29092
```

Services use `Settings(env_prefix="MY_SERVICE_")`, so `DATABASE_URL` is never
read — `MY_SERVICE_DATABASE_URL` is required. The inline block also duplicates
what `configs/docker.env` already defines, creating two sources of truth that
inevitably drift.

#### Bug C — Postgres credentials mismatch between compose and service config

```yaml
# WRONG (old docker-compose.yml)
postgres:
  environment:
    POSTGRES_USER: worldview
    POSTGRES_PASSWORD: worldview
```

All service `docker.env` files connect as `postgres:postgres`. The container
creates a `worldview` superuser but no `postgres` user → all service connections
fail with `authentication failed for user "postgres"`.

Also: `infra/postgres/init/init-databases.sh` created `market_ingestion_db` but
`market-ingestion/docker.env` and `config.py` default to `ingestion_db` → service
fails to connect on first start.

### Correct implementation pattern

#### Makefile — source env for every target that talks to infra

```makefile
# CORRECT
run: .env-check
    set -a && . ./configs/dev.local.env && set +a && \
    $(VENV)/bin/uvicorn my_service.app:create_app --factory --reload --port 8000

run-worker: .env-check
    set -a && . ./configs/dev.local.env && set +a && \
    $(VENV)/bin/python -m my_service.worker.main

# Unit tests — no sourcing needed (all infra is mocked)
test:
    $(VENV)/bin/pytest tests/ -m unit -v

# Integration/e2e — DO source (hit real infra)
test-integration: .env-check
    set -a && . ./configs/dev.local.env && set +a && \
    $(VENV)/bin/pytest tests/ -m integration -v

test-e2e: .env-check
    @docker compose -f ../../infra/compose/docker-compose.test.yml \
        --profile my-service-test up --build --wait; \
    COMPOSE_EXIT=$$?; \
    if [ $$COMPOSE_EXIT -ne 0 ]; then \
        docker compose -f ../../infra/compose/docker-compose.test.yml \
            --profile my-service-test down -v; \
        exit $$COMPOSE_EXIT; \
    fi; \
    set -a && . ./configs/dev.local.env && set +a; \
    $(VENV)/bin/pytest tests/e2e/ -v; \
    EXIT=$$?; \
    docker compose -f ../../infra/compose/docker-compose.test.yml \
        --profile my-service-test down -v; \
    exit $$EXIT
```

#### `docker-compose.yml` — use `env_file:` pointing to the prefixed docker.env

```yaml
# CORRECT — env_file replaces ALL inline environment: blocks
services:
  my-service:
    env_file:
      - ../../services/my-service/configs/docker.env
    # NO inline environment: block
```

`configs/docker.env` must use the correct `SERVICE_` prefix:

```env
# configs/docker.env  (Docker-internal hostnames)
MY_SERVICE_DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/my_db
MY_SERVICE_KAFKA_BOOTSTRAP_SERVERS=kafka:29092
MY_SERVICE_STORAGE_ENDPOINT_HOST=minio
```

#### `docker-compose.yml` — postgres must match service credentials

```yaml
# CORRECT
postgres:
  environment:
    POSTGRES_USER: postgres
    POSTGRES_PASSWORD: postgres
```

#### `infra/postgres/init/init-databases.sh` — DB names must match service config

Always verify that each database name in the init script exactly matches the
database name used in the corresponding service's `docker.env` and `config.py`.

### Env loading responsibility table

| Context | Mechanism | File |
|---------|-----------|------|
| Local dev (`make run`) | `set -a && . ./configs/dev.local.env && set +a` | `configs/dev.local.env` |
| Docker Compose | `env_file:` in compose YAML | `configs/docker.env` |
| Unit tests | None — infra is fully mocked | N/A |
| Integration tests | Same as local dev (Makefile sources it) | `configs/dev.local.env` |
| CI/CD | Secret injection into process environment | CI secret store |
| Settings class | Reads **only** the process environment (no file knowledge) | `config.py` |

### Files changed in fix

| File | Change |
|------|--------|
| `services/portfolio/Makefile` | Added `set -a && . ./configs/dev.local.env && set +a` to `run`, `run-dispatcher`, `test-integration`, `test-all`; restructured `test-e2e` to use `docker-compose.test.yml` |
| `services/market-ingestion/Makefile` | Same pattern as portfolio |
| `services/portfolio/configs/docker.env` | Created (was missing — only `.example` existed); contains `PORTFOLIO_`-prefixed vars with Docker-internal hostnames |
| `infra/compose/docker-compose.yml` | Replaced ALL inline `environment:` blocks with `env_file:`; fixed postgres credentials (`postgres:postgres`); built postgres from Dockerfile (TimescaleDB) |
| `infra/postgres/init/init-databases.sh` | Fixed `market_ingestion_db` → `ingestion_db` |
| `infra/compose/docker-compose.test.yml` | New isolated test stack with `tmpfs`, `service_completed_successfully`, `--wait`-compatible healthchecks |
| `infra/postgres/init/init-test-databases.sh` | New file for test stack; creates only `portfolio_db` and `ingestion_db` |
| `infra/minio/init/init-test-buckets.sh` | New file for test stack; creates `market-ingestion`, `market-bronze`, `market-canonical` buckets |
| `services/portfolio/tests/e2e/conftest.py` | New; real HTTP client against `http://localhost:8001` |
| `services/portfolio/tests/e2e/test_full_flow.py` | Rewritten to use `e2e_client` (real HTTP, not ASGI transport) |
| `services/market-ingestion/tests/e2e/conftest.py` | New; real HTTP client against `http://localhost:8002` |
| `services/market-ingestion/tests/e2e/test_api_workflows.py` | New; 13 tests covering all API workflows |

---

---

---

## BP-005 — Docker multi-stage build: `exec /app/.venv/bin/alembic: no such file or directory`

**Date discovered**: 2026-03-10
**Services affected**: `portfolio`, `market-ingestion` (all services using `uv venv` in Dockerfile)
**Prompts updated**: none yet — catch this at implementation time

### Symptom

The migrate container (or any container that runs a venv entry-point directly)
exits with code 255:

```
portfolio-migrate-1  | exec /app/.venv/bin/alembic: no such file or directory
portfolio-migrate-1 exited with code 255
service "portfolio-migrate" didn't complete successfully: exit 255
```

The binary file physically exists. The file system path is correct. The container
still cannot execute it.

### Root cause

The Dockerfile builds the venv in the **builder** stage at `/build/.venv`:

```dockerfile
# Builder stage — WORKDIR /build
RUN uv venv /build/.venv && \
    uv pip install ...
```

`uv` writes entry-point scripts (e.g. `alembic`, `uvicorn`) with a hardcoded
shebang referencing the build-time Python path:

```
#!/build/.venv/bin/python3.11
```

The runtime stage copies the venv to `/app/.venv`:

```dockerfile
COPY --from=builder /build/.venv /app/.venv
```

Now `/app/.venv/bin/alembic` exists and is executable, but its shebang still
points to `/build/.venv/bin/python3.11` — a path that does not exist in the
runtime image. The kernel resolves the shebang first, finds nothing, and returns
`ENOENT` (no such file or directory).

This is silent in the builder stage (the scripts execute fine there) and only
fails at runtime when the entry-point is actually invoked.

### Correct implementation pattern

**Build the venv at the path it will occupy in the runtime stage.** Since the
runtime stage uses `WORKDIR /app`, build at `/app/.venv` even inside the builder:

```dockerfile
# CORRECT — venv built at the runtime path; shebangs are already right
RUN uv venv /app/.venv && \
    uv pip install --no-cache --python /app/.venv \
        -e /build/libs/common \
        ...

# Runtime stage — copy from the same path (no path change = no shebang corruption)
COPY --from=builder /app/.venv /app/.venv
```

The `--python /app/.venv` flag to `uv pip install` is required when the venv
path differs from `WORKDIR` — `uv` won't auto-detect the venv otherwise.

**`PATH` and `ENV` in the runtime stage are unaffected** — they still point to
`/app/.venv/bin`.

### Test to add (prevents regression)

Add a smoke test to `docker-compose.test.yml` that verifies the migrate container
exits 0. The `service_completed_successfully` condition on every API service
dependency already catches this — if migration exits non-zero, the API container
never starts, causing `--wait` to fail.

### Files changed in fix

| File | Change |
|------|--------|
| `services/portfolio/Dockerfile` | Changed `uv venv /build/.venv` → `uv venv /app/.venv`; added `--python /app/.venv` to `uv pip install`; updated `COPY` source path |
| `services/market-ingestion/Dockerfile` | Same as portfolio |

---

---

## BP-010 — Docker Compose `--wait` fails for long-running worker processes

**Date discovered**: 2026-03-10
**Services affected**: `market-ingestion`, `portfolio`
**Prompts updated**: `0004-exec-market-data-migration-wave-02.md`, `0004-exec-market-data-migration-wave-03.md`, `0004-exec-market-data-migration-wave-04.md`

### Symptom

- `docker compose ... up --wait` fails with:

```
container <service>-dispatcher-1 has no healthcheck configured
```

- Or background processes exit because they inherited API-only healthchecks
    (e.g., probing `/readyz` on processes that do not expose HTTP).

### Root cause

Compose `--wait` requires health status for started services. Long-running
workers/schedulers/dispatchers often run as non-HTTP commands and cannot reuse
the API container healthcheck. If no healthcheck is present (or API healthcheck
is inherited from Dockerfile), readiness and lifecycle behavior become unstable.

### Correct implementation pattern

For non-HTTP background services:

```yaml
worker:
    command: ["python", "-m", "service.worker.main"]
    healthcheck:
        test: ["CMD", "python", "-c", "import sys; sys.exit(0)"]
        interval: 15s
        timeout: 3s
        retries: 3
        start_period: 5s
```

And do **not** rely on Dockerfile API healthchecks for these process types.

### Test to add (prevents regression)

- In CI/local smoke script, run:

```bash
docker compose -f infra/compose/docker-compose.test.yml --profile <service>-test up --wait
docker compose -f infra/compose/docker-compose.test.yml ps
```

- Assert worker/scheduler/dispatcher are `Up (healthy)` and not restarting.

### Files changed in fix

| File | Change |
|------|--------|
| `infra/compose/docker-compose.test.yml` | Added explicit healthchecks for `market-ingestion-scheduler`, `market-ingestion-worker`, `market-ingestion-dispatcher`, and `portfolio-dispatcher` |

---

---

## BP-011 — Runtime schema files missing from container image

**Date discovered**: 2026-03-10
**Services affected**: `market-ingestion`
**Prompts updated**: `0004-exec-market-data-migration-wave-02.md`

### Symptom

Dispatcher crashes only in containers with:

```
FileNotFoundError: Could not locate market.dataset.fetched.avsc from module path or cwd
```

### Root cause

Schema files under `infra/kafka/schemas/` were available in the repo for local
execution but not copied into the Docker runtime image. Module path resolution
worked on host but failed in container filesystem.

### Correct implementation pattern

Copy required non-code assets into image at build time:

```dockerfile
COPY infra/kafka/schemas /build/infra/kafka/schemas
...
COPY --from=builder /build/infra/kafka/schemas /app/infra/kafka/schemas
```

Also prefer robust schema path resolution that scans parents/cwd and fails with
clear error text.

### Test to add (prevents regression)

- Container smoke command in CI:

```bash
docker compose -f infra/compose/docker-compose.test.yml --profile <service>-test up --build --wait
docker compose -f infra/compose/docker-compose.test.yml logs <dispatcher-service>
```

- Assert no `FileNotFoundError` and dispatcher remains running.

### Files changed in fix

| File | Change |
|------|--------|
| `services/market-ingestion/Dockerfile` | Copied `infra/kafka/schemas` into runtime image |
| `services/market-ingestion/src/market_ingestion/infrastructure/messaging/kafka/serialization.py` | Added resilient schema path resolver |

---

---

## BP-018 — Client constructor mismatch in wiring code

**Date discovered**: 2026-03-26
**Service affected**: `content-ingestion` (found during QA review)

### Symptom

`TypeError: __init__() got an unexpected keyword argument 'rate_limiter'` when constructing adapter clients. Or: `http_client` not passed because generic `adapter_cls(**kwargs)` was used.

### Root cause

Each client has a different constructor signature (EODHD/Finnhub need `api_key`, SEC EDGAR needs `user_agent`, NewsAPI needs `valkey`). Generic wiring code doesn't handle these differences.

### Correct implementation pattern

Use explicit per-source-type wiring with type-checked constructors:

```python
if source_type == "eodhd":
    client = EODHDClient(http_client=http_client, api_key=settings.eodhd_api_key)
elif source_type == "newsapi":
    client = NewsAPIClient(http_client=http_client, api_key=settings.newsapi_key, valkey=valkey)
```

### Test to add (prevents regression)

HTTP client tests using `httpx.MockTransport` that verify each client can be constructed and called.

---

---

## BP-085 — Config field reuse: `otlp_endpoint` used as ML model URL

**Context**: Process topology refactoring (PLAN-0011) — standalone `*_consumer_main.py` entry points

**Symptom**: Embedding client silently connects to OpenTelemetry collector instead of Ollama. All vector embeddings fail or return nonsense. Error message resembles Jaeger/Tempo connection refused rather than Ollama.

**Root cause**: `settings.otlp_endpoint` was copy-pasted as the Ollama `base_url` fallback: `base_url=settings.otlp_endpoint or "http://ollama:11434"`. When OTLP is configured (e.g., `http://tempo:4317`), this URL is sent to the Ollama adapter instead of the OTel exporter endpoint.

**Fix**: Add a dedicated `ollama_base_url: str = "http://ollama:11434"` field to `Settings` (and optionally `embedding_model_id: str = "nomic-embed-text"`), then use `settings.ollama_base_url` in the entry point.

**Prevention**: Never reuse config fields for unrelated purposes. When writing a new entry point, check that every settings field used actually corresponds to the purpose implied by its name.

---

---

## BP-098 — Config Re-Export Shim Breaks AST Architecture Tests

**Pattern**: A service's `config.py` uses a thin re-export shim (`Settings = OtherSettingsClass`) instead of defining the `Settings` class directly. AST-based architecture tests that visit `ClassDef` nodes (like R23 and config-pattern tests) cannot detect fields defined in the aliased class.

**Symptom**: Architecture tests fail for the service with violations like "Settings missing a write database URL field" even though the service IS compliant — the actual class is in a different file.

**Fix Options**:
1. **Preferred**: Define the `Settings` class directly in `config.py` (standard pattern for all services)
2. **Workaround**: Add the service to the test's `_BASELINE` dict with explanation
3. **Test improvement**: Enhance AST visitor to follow `Settings = X` assignments and scan `X`'s source file

**Applies to**: Any service using `infrastructure/config/settings.py` as the canonical settings location (non-standard — avoid this pattern).

---

---

## BP-110 — Settings Re-Export Shim Not Staged Causes Mypy Pre-Commit Failures

**Category**: Tooling / Pre-commit hooks
**Affected areas**: Any service that splits config into `config.py` (canonical) + `infrastructure/config/settings.py` (re-export shim)

**Symptom**: `mypy` passes when run directly (`mypy services/<service>/src --config-file mypy.ini`) but fails in the pre-commit hook with errors like `"RagChatSettings" has no attribute "database_url"` or `Argument 1 has incompatible type "RagChatSettings"; expected "Settings"`.

**Root cause**: The pre-commit hook stashes ALL unstaged working-tree changes before running `mypy`. If `infrastructure/config/settings.py` (the shim that re-exports `Settings as RagChatSettings`) has unstaged working-tree changes — because it was refactored in a prior wave but not committed — the hook stashes it back to the committed version (which was the full class, not the shim). Mypy then sees two different types: `Settings` (from `rag_chat.config`) and `RagChatSettings` (from the committed full class), and treats them as incompatible.

**Fix**: Before committing any wave that touches the settings type, stage `infrastructure/config/settings.py` explicitly, even if the wave didn't formally change it:
```bash
git add services/<service>/src/<service>/infrastructure/config/settings.py
```
Also ensure all files in the module that reference `RagChatSettings` use the same canonical import path (`from rag_chat.infrastructure.config.settings import RagChatSettings`) so mypy resolves both sides to the same type.

**Prevention**: When introducing a `config.py` → `infrastructure/config/settings.py` shim in a wave, commit the shim in the same wave — do not leave it as an unstaged working-tree change.

**First seen**: PLAN-0016 Wave B-2 (2026-04-07), rag-chat S8.

---

---

## BP-137 — Helm values.yaml Key Mismatch Causes Silent Misconfiguration

**Symptom**: A service is deployed via Helm but starts without a required env var (e.g., `DEEPINFRA_API_KEY` is empty). Kubernetes shows the pod as `Running`/`Ready` because `/health` does not validate all config. The misconfiguration surfaces only at runtime when the first request exercises the missing config path.

**Root cause**: The key name in `infra/helm/values/<service>.yaml` under `env:` does not match what the Deployment template injects, or the key was renamed in the values file but the template variable reference was not updated. `helm install` succeeds silently; the env var is simply absent.

**Fix**: After any change to `infra/helm/values/*.yaml` or the Deployment template:
1. Run `helm template <svc> infra/helm/worldview-service -f infra/helm/values/<svc>.yaml` and inspect the rendered `env:` block
2. Run `kubectl -n worldview exec <pod> -- env | grep <KEY>` after deploy to verify presence
3. Run `./scripts/ci-local.sh --job validate-helm` to catch render failures in CI

**Prevention**:
- `validate-helm` is now part of `ci-local.sh --job all` and runs on every push
- For each new env var added to a values file, manually verify the Deployment template propagates it
- `helm test` hooks with env-var assertions are the most reliable guard (deferred)

**First seen**: Investigation 2026-04-10 — identified as deployment risk for PLAN-0024 Wave A-2.

---

## BP-140 — Settings Fields Defined But Never Read (Dead Config)

**Symptom**: Operators set an env var expecting to tune behavior (e.g., `ALERT_ALERT_SEVERITY_CRITICAL_THRESHOLD=0.9`), but the service ignores it because the Settings field is defined but never passed to the domain object that uses it. Behavior is silently hardcoded.

**Root cause**: Settings field added in `config.py`, but the consumer/service entry-point that constructs the domain object (e.g., `SeverityThresholds`) passes `None` or uses the default, never reading `settings.<field>`.

**Fix**: In the entry-point (`*_main.py` or `app.py`), explicitly pass all threshold/config fields when constructing domain objects:
```python
SeverityThresholds(
    critical=settings.alert_severity_critical_threshold,
    high=settings.alert_severity_high_threshold,
    medium=settings.alert_severity_medium_threshold,
)
```

**Prevention**: When adding a `Settings` field that controls domain behavior, grep for all constructors of the affected domain object and verify each reads from `settings`. Add the mock value to `_mock_settings()` in entrypoint tests.

**First seen**: PLAN-0021 QA pass, 2026-04-10 (F-202 Architecture finding).

---

---

## BP-167 — Floating Docker Image Tags Create Non-Reproducible Builds

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-19 |
| **Severity** | MAJOR |
| **Affected areas** | `infra/compose/docker-compose.yml`, `infra/compose/docker-compose.test.yml` |
| **Root cause** | `minio/mc:latest`, `timescale/timescaledb:latest-pg16`, `provectuslabs/kafka-ui:latest` used in compose files. Floating tags are updated by image publishers and can change behaviour silently between runs. Test and production compose used divergent TimescaleDB versions. |
| **Fix** | Pinned all three images to specific version tags (`2.17.2-pg16`, `RELEASE.2024-01-16T16-07-38Z`, `v0.7.2`). |

### Prevention

NEVER use `:latest` tags in any Docker Compose file (dev, test, or production). Always use an explicit version tag. The test compose file MUST use the same database image versions as the production compose file to prevent "passes in test, breaks in prod" failures.

---

---

## BP-179 — pydantic-settings Parses Empty Env Var as `SecretStr("")` Not `None`

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (rag-chat local bring-up) |
| **Severity** | HIGH — service crashes at startup; all traffic fails |
| **Affected areas** | Any service with `Optional[SecretStr]` settings checked with `is not None` |
| **Root cause** | pydantic-settings parses `KEY=` (env var set to empty string) as `SecretStr("")` not `None`. An `is not None` guard evaluates True for `SecretStr("")`, so empty-string values are not treated as "absent". If downstream code passes the empty string to a URL parser (e.g., `create_async_engine("")`), it crashes with a parse error. |
| **Symptom** | `sqlalchemy.exc.ArgumentError: Could not parse SQLAlchemy URL from string ''` at startup. Only happens when the env var is present but empty (`KEY=`), not when it's absent. |
| **Fix** | Replace `if value is not None` guards on `SecretStr` settings with `if value` or `if value and value.get_secret_value()`. For URL-like settings, use: `url = settings.db_url_read.get_secret_value() if settings.db_url_read is not None else None` + `if not url or ...` (truthy check handles both `None` and `""`). |

### Prevention

Add to `.claude/review/checklists/REVIEW_CHECKLIST.md`: "Settings: `Optional[SecretStr]` guarded by `is not None` is broken for empty-string env vars. Use `if value` or `if not url` instead."

---

---

## BP-181 — Missing Shared Library in Service Dockerfile (ml-clients Not Installed)

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-23 (rag-chat local bring-up, `ModuleNotFoundError: No module named 'ml_clients'`) |
| **Severity** | HIGH — service crashes at startup |
| **Affected areas** | Any service whose Dockerfile omits a lib it imports |
| **Root cause** | `libs/ml-clients` was added as an import in `rag_chat/infrastructure/llm/provider_chain.py` but was never added to `services/rag-chat/Dockerfile`. The build stage only copies `libs/common`, `libs/messaging`, `libs/observability`. The `PYTHONPATH` also lacks `ml-clients/src`. |
| **Symptom** | `ModuleNotFoundError: No module named 'ml_clients'` at import time during lifespan startup. |
| **Fix** | Add `COPY libs/ml-clients /build/libs/ml-clients` and `-e /build/libs/ml-clients` to the build stage; add `/app/libs/ml-clients/src` to `PYTHONPATH` in the runtime stage. |

### Prevention

When adding a new lib import to a service, check the service Dockerfile immediately and add the lib. Add to service scaffold checklist: "New lib dependency → update Dockerfile COPY + install + PYTHONPATH."

---

---

## BP-202 — New Shared Lib Not Added to All Consuming Service Dockerfiles

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-24 (rag-chat container exit on startup: ModuleNotFoundError: No module named 'prompts') |
| **Severity** | CRITICAL — container crash on startup |
| **Affected areas** | `services/rag-chat/Dockerfile` (missing `libs/prompts`), similar for knowledge-graph and nlp-pipeline local venvs |
| **Root cause** | `libs/prompts` was added as a dependency to multiple services (commit 3f1cba6), but the Dockerfiles for those services were not updated to COPY + install + add to PYTHONPATH. The lib works locally (via .pth files) but fails in Docker. |
| **Symptom** | Container exits immediately with `ModuleNotFoundError: No module named 'prompts'` |
| **Fix** | Added `COPY libs/prompts`, `uv pip install -e /build/libs/prompts`, and `/app/libs/prompts/src` to PYTHONPATH in rag-chat Dockerfile. Created `.pth` files for knowledge-graph and nlp-pipeline local venvs. |

### Prevention

- **Checklist when adding a lib dep**: grep for all Dockerfiles that build services importing the lib (`grep -r "lib_name" services/*/src`). For each Dockerfile, add: COPY, uv pip install -e, PYTHONPATH entry.
- Consider a CI step that runs `python -c "import <lib>"` inside each Docker image as a startup smoke test.

---

---

## BP-217 — Standalone Consumer Entry Point Not Added to docker-compose

| Field | Value |
|-------|-------|
| **Discovered** | 2026-04-24 QA of commit f0a031f (D-W3 consumers) |
| **Severity** | BLOCKING — consumers never run in any deployed environment |
| **Root cause** | New `_main.py` entry points committed + legacy workers tombstoned (D-W5), but docker-compose.yml not updated. Complete data gap for 3 dataset types. |
| **Symptom** | Kafka topic has messages; no consumer lag; no DB rows written |
| **Fix** | Add service definition to docker-compose.yml in the same commit that creates the entry point. |

### Prevention

Add a check in the pre-commit hook or CI: for every `*_main.py` under `consumers/`, assert there is a matching `command:` entry in docker-compose.yml. Or add to the `/implement` skill checklist: "For each new entrypoint, add docker-compose service."

---

---

## BP-222 — Worker Registry Divergence: `_build_registry()` Bypasses Shared Builder

| Field | Value |
|-------|-------|
| **Service** | market-ingestion (S2) |
| **Severity** | CRITICAL |
| **Discovered** | 2026-04-26 QA PLAN-0038 |
| **Root cause** | `WorkerProcess._build_registry()` manually constructed a `ProviderRegistry` and only registered `EODHDProviderAdapter`. The canonical `build_provider_registry()` in `__init__.py` registered EODHD + Yahoo + Finnhub, but the worker never called it. |
| **Symptom** | Provider routing (`_preferred_provider()`) and zero-bar failover were dead code in the production worker — all data always fetched via EODHD. |
| **Fix** | Replace `_build_registry()` body with `build_provider_registry(self._settings, http_timeout=...)`. |

### Prevention

When adding a new adapter/provider to a shared registry builder function, **grep for ALL callers** of the registry — not just the API path. Workers, schedulers, and test helpers that construct their own registries bypass the shared builder and must be updated independently. Add a test asserting the worker's registry contains all expected providers.

---

---

## BP-223 — API Keys as `str` Instead of `SecretStr` in pydantic-settings

| Field | Value |
|-------|-------|
| **Service** | market-ingestion (S2), potentially others |
| **Severity** | CRITICAL |
| **Discovered** | 2026-04-26 QA PLAN-0038 |
| **Root cause** | `eodhd_api_key`, `finnhub_api_key`, `storage_secret_key` etc. were typed as plain `str` in `config.py`. `SecretStr` was only used for `database_url`. |
| **Symptom** | API keys appear in full in `repr(settings)`, `settings.model_dump()`, pydantic validation error tracebacks, and any diagnostic logging that serialises the settings object. |
| **Fix** | Change all secret fields to `SecretStr`. Update all call sites to use `.get_secret_value()`. Update test mocks to assign `SecretStr("...")` values. |

### Prevention

Any field in a pydantic-settings `BaseSettings` class whose value is a credential, API key, token, or password MUST use `SecretStr` — never plain `str`. This is enforced by reviewing `config.py` changes in code review. Match the established pattern of `database_url: SecretStr`.

---

---

## BP-224 — Hardcoded `Path(__file__).parents[N]` Schema Path Fails in Docker

| Field | Value |
|-------|-------|
| **Service** | market-data (S3), portfolio (S1), knowledge-graph (S7) |
| **Severity** | BLOCKING |
| **Discovered** | 2026-04-26 live-infra QA |
| **Root cause** | `_SCHEMA_DIR = Path(__file__).parents[N] / "infra/kafka/schemas"` assumes a fixed directory depth. In the source tree the depth is correct; in the Docker container the installed package lives at `/app/<pkg>/…` — a different number of parent levels — so the path resolves to `/infra/kafka/schemas` (root-relative) which doesn't exist. |
| **Symptom** | `FileNotFoundError` or silent fallback to JSON parsing of Confluent Avro binary → `'utf-32-be' codec can't decode bytes` → all Kafka events dead-lettered. |
| **Fix** | Replace hardcoded parent chains with the walk-up algorithm: `for base in Path(__file__).resolve().parents: candidate = base / relative; if candidate.is_dir(): return candidate`. This is portable across source tree and Docker container depths. |

### Prevention

Never use `Path(__file__).parents[N]` to locate repo-relative resources. Always use the walk-up pattern. Search for `.parents[` in any new file to catch this before it ships.

---

---

## BP-245 — Docker Compose Per-Role Images Not Rebuilt by Base Service Build

| Field | Value |
|-------|-------|
| **Service** | market-ingestion (S2) — Docker Compose build configuration |
| **Severity** | MEDIUM (stale code deployed despite rebuild, hard to diagnose) |
| **Discovered** | 2026-04-27 ingestion pipeline investigation |
| **Root cause** | Services with multiple roles (scheduler, worker, dispatcher) each have their own `build:` block in `docker-compose.yml`, producing separate image tags: `worldview-market-ingestion-scheduler`, `worldview-market-ingestion-worker`, `worldview-market-ingestion`. Running `docker compose build market-ingestion` only rebuilds the base service image — the scheduler and worker images are NOT rebuilt. Code changes are not deployed to those containers until their specific image is rebuilt. |
| **Symptom** | `docker compose build market-ingestion && docker compose up -d --force-recreate market-ingestion-scheduler` runs old code. `python -c "import inspect; print(inspect.getsource(...))"` inside the container confirms old code. |
| **Fix** | When code changes affect market-ingestion, rebuild all three: `docker compose build --no-cache market-ingestion market-ingestion-scheduler market-ingestion-worker`. The `--no-cache` flag is required to bypass BuildKit layer caching. |

### Prevention

- Always rebuild all role-specific images when changing shared service code.
- Consider merging scheduler/worker into a single image with a CMD arg, or using Docker Compose `image:` inheritance to share the same build output.
- When verifying deployed code, always inspect the running container's source directly, not just the tagged image.

---

---

## BP-256 — `AliasChoices` First-Match Wins: Empty Env Var Shadows Non-Empty Prefixed Var

**Date discovered**: 2026-04-28
**Affected areas**: Portfolio service SnapTrade config, any pydantic-settings with `AliasChoices`

**Pattern**:
`docker-compose.yml` `environment:` section sets bare `SNAPTRADE_CLIENT_ID=` (empty via `${SNAPTRADE_CLIENT_ID:-}` when host var is unset). The `env_file:` provides `PORTFOLIO_SNAPTRADE_CLIENT_ID=actual-value`. `AliasChoices("SNAPTRADE_CLIENT_ID", "PORTFOLIO_SNAPTRADE_CLIENT_ID")` tries the first alias first — finds the empty string — and uses it, ignoring the non-empty prefixed var.

**Root cause**:
pydantic-settings `AliasChoices` uses first-match semantics. When docker-compose `environment:` explicitly sets a bare var to empty string (not unset — empty), it shadows the non-empty prefixed var from `env_file:` regardless of declaration order.

**Fix**:
Reverse `AliasChoices` order so the prefixed var (`PORTFOLIO_SNAPTRADE_*`) is tried first. The prefixed var in `env_file:` will always be non-empty and will win over the potentially-empty bare var from `environment:`.

**Prevention**:
- Put the most-specific (prefixed) alias FIRST in `AliasChoices` so it wins over shorter/bare aliases that might be set to empty by `environment:` shell expansion.
- In docker-compose, be aware that `SOME_VAR=${SOME_VAR:-}` explicitly injects an empty string — it does NOT omit the variable. An injected empty string WILL override `env_file:` values that use the same alias.

---

---

## BP-257 — `docker compose restart` Does Not Swap Image; Use `up -d --no-deps`

**Date discovered**: 2026-04-28
**Affected areas**: All Docker Compose managed services

**Pattern**:
After `docker compose build <service>`, running `docker compose restart <service>` restarts the existing container but keeps the OLD image. The new image is only used when the container is RECREATED (not just restarted). This causes stale code in the running container even after a successful build.

**Root cause**:
`docker compose restart` sends `SIGTERM`/`SIGKILL` to the running container and restarts it in-place — it does not create a new container from the new image. Only `docker compose up -d` (which detects image changes and recreates) uses the new image.

**Fix**:
Always use `docker compose up -d --no-deps <service>` after building. Or `docker stop + docker rm + docker compose up -d`.
Note: even `up -d` may not recreate if the service has multiple variants (e.g. `portfolio`, `portfolio-brokerage-sync`) — each variant has its own image that must be built and recreated independently.

**Prevention**:
- After `docker compose build`, always use `docker compose up -d` (not `restart`) to apply the new image.
- When multiple services share a Dockerfile (e.g. portfolio variants), build and recreate ALL of them: `docker compose build --no-cache portfolio portfolio-brokerage-sync`.

---

---

## BP-261 — GitOps Env Drift: Local `docker.env` Changes Not Propagated to worldview-gitops

**Category**: Config
**Severity**: HIGH
**First seen**: 2026-04-28
**Services**: All services

**Symptoms**:
- Env var changes made during a debugging session only apply to the local `services/<svc>/configs/docker.env` copy
- After running `scripts/setup-dev.sh` the changes are overwritten from `worldview-gitops/env/dev/<svc>.env`
- Another developer (or a fresh checkout) never gets the change

**Root cause**:
`services/<svc>/configs/docker.env` files are generated copies of `worldview-gitops/env/dev/<svc>.env`.
The gitops repo is the authoritative source of truth. Any env var change made only to the local copy is ephemeral.

**Fix**:
After any env var change in a `docker.env` file, **always** mirror the change to the corresponding file in `worldview-gitops/env/dev/<svc>.env` and commit it.

**Prevention**:
- Treat `services/*/configs/docker.env` as read-only artifacts — never the canonical source.
- When a debugging session adds or changes an env var, immediately update `worldview-gitops/env/dev/` before closing the session.
- Add a reminder comment to the top of each `docker.env`: "Copy to ../worldview/... via setup-dev.sh — edit worldview-gitops, not this file."

**Regression test**: N/A (process rule, not a code bug)


---

---

## BP-319 — Stale Docker Image Blocks Alembic Upgrade After New Migration Added

**Service**: `intelligence-migrations` (also applies to any service with Alembic)
**Symptom**: `alembic upgrade head` exits with `Can't locate revision identified by 'NNNN'`; `intelligence-migrations` container exits 255; 15+ downstream services stay in `Created` state.

### Mechanism

`make dev` runs `docker compose up -d` without rebuilding images. If a new migration file is committed after the last `make dev-rebuild`, the Docker image lacks that script. The database was already migrated to that revision in a previous session, so Alembic finds the DB at version `NNNN` but cannot locate it in the image's version tree.

### Fix

Rebuild only the affected migration image (fast, uses layer cache):

```bash
docker compose -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.dev.yml \
    build intelligence-migrations
docker compose -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.dev.yml \
    --profile infra up -d --force-recreate intelligence-migrations
```

Or run `make dev` (which now uses `--build` and will rebuild changed images automatically).

### Prevention

- `make dev` now uses `--build` flag, which rebuilds images when source files change (uses Docker layer cache — fast for unchanged layers).
- The `--build` flag is the key difference from plain `up -d`. Never use bare `up -d` for a dev restart.

---

---

## BP-320 — Docker Compose v5 `up -d` Leaves Services in `Created` State

**Service**: All services (platform-wide)
**Symptom**: After `docker compose up -d --force-recreate`, many containers are in `Created` state and never progress to `Up`. Running `up -d` again doesn't help.

### Mechanism

Docker Compose v5.1.1 in detached (`-d`) mode exits before all dependency health checks resolve for the full 60+ container stack. Containers created by `--force-recreate` land in `Created` state (container object exists, process not started). A subsequent `up -d` does not start `Created`-state containers the same way it starts `Exited`-state containers.

`docker start <container>` or `docker ps -aq --filter status=created | xargs docker start` bypasses the dependency wait and starts them directly.

### Fix

```bash
# After any up -d run that leaves containers in Created state:
docker ps -aq --filter status=created | xargs -r docker start
```

`make dev` now includes this as a cleanup step after `up -d --build`.

### Prevention

- `make dev` appends `docker ps -aq --filter status=created | xargs -r docker start` to catch any remaining `Created`-state containers.
- Avoid `up -d --force-recreate` directly; prefer `make dev` (which handles both the build and the Created-state fix).

---

---

## BP-326 — Lazy Imports in Kafka Consumer Hot-Path Hide `ModuleNotFoundError` from Container Health Checks

**Date discovered**: 2026-05-03
**Service affected**: `nlp-pipeline` (S6), `knowledge-graph` (S7)

### Symptom

Container starts cleanly, reports healthy, but every Kafka message is dead-lettered with:
```
ModuleNotFoundError: No module named 'contracts.events'
```
The module exists in source but the installed package in `.venv` was cached from an older image layer before the subpackage was added.

### Root cause

Imports inside function bodies (`process_message`, `_enqueue_enriched`) defer the `ModuleNotFoundError` until message processing begins. Container startup only imports top-level symbols; the missing subpackage never raises at health-check time. `uv pip install --mount=type=cache` uses the cached wheel even when the source subpackage was added.

### Example

```python
# Bad — import inside hot-path function body hides the error at startup
async def process_message(self, key, value, headers):
    from contracts.events.nlp.article_enriched import decode_raw_array  # CRASHES HERE
    ...

# Good — top-level import surfaces the error at container startup
from contracts.events.nlp.article_enriched import decode_raw_array
```

### Fix

Move all imports to module-level. Bump `pyproject.toml` version to force uv cache invalidation. If a rebuild is not possible immediately, `docker cp <module_dir> <container>:/app/.venv/lib/python3.11/site-packages/` as a hotfix.

### Prevention

- Never place critical imports inside `process_message()`, `handle_event()`, or similar hot-path functions
- `docker cp` hotfixes are ephemeral — always follow with a proper rebuild
- Review checklist: scan consumer files for `from X import Y` inside `async def process_message`

---

## BP-331 — Embedding Model Name Mismatch Between Seeder and Runtime Consumer

**Date discovered**: 2026-05-03
**Services affected**: `intelligence-migrations` (seed), `knowledge-graph` (S7 enriched consumer)

### Symptom

`relation_type_registry.embedding` column stays NULL after every fresh deploy even though the `populate_embeddings.py` entrypoint step reports no errors. S7 Block 11 Step 2 (ANN soft-map) is permanently bypassed; all relation types fall through to Step 3 (proposed). The `relations` table stays empty or only accumulates seed data.

### Root cause

The `intelligence-migrations` Docker Compose service set `EMBEDDING_MODEL: "bge-large-en-v1.5"` (HuggingFace model ID), while the Ollama container only has the model registered as `bge-large:latest` (Ollama tag). Ollama returned an HTTP 4xx for the unknown model name; `populate_embeddings.py` caught `urllib.error.HTTPError` (a `URLError` subclass), logged a warning, and continued with `embeddings = None` for every row. The ANN step was silently disabled on every fresh deploy.

### Example

```yaml
# Bad — docker-compose.yml uses HuggingFace model ID, not Ollama tag
intelligence-migrations:
  environment:
    EMBEDDING_MODEL: "bge-large-en-v1.5"   # wrong — Ollama doesn't know this name

# Good — use the Ollama registry tag that matches the pulled model
intelligence-migrations:
  environment:
    EMBEDDING_MODEL: "bge-large:latest"    # matches `ollama pull bge-large`
```

```python
# Also: explicit ::vector cast required in UPDATE — psycopg2 won't implicitly
# coerce a Python str to the pgvector vector type
# Bad:
conn.execute(text("UPDATE ... SET embedding = :emb ..."), {"emb": str(vec)})
# Good:
conn.execute(text("UPDATE ... SET embedding = :emb::vector ..."), {"emb": str(vec)})
```

### Fix

1. Change `EMBEDDING_MODEL: "bge-large-en-v1.5"` → `"bge-large:latest"` in `infra/compose/docker-compose.yml`.
2. Update the default in `services/intelligence-migrations/scripts/populate_embeddings.py` to match.
3. Add `::vector` cast to the SQLAlchemy `UPDATE` statement.
4. Add Alembic migration 0013 as belt-and-suspenders embedding seeding with the correct model name.

### Prevention

- The Ollama model tag and the embedding model env var must come from the same source. Add a comment in docker-compose.yml next to the `ollama pull` command.
- Test: after `make dev` on a fresh volume, assert `SELECT COUNT(*) FROM relation_type_registry WHERE embedding IS NULL` returns 0.
- Review checklist: when adding an Ollama pull command, grep for every `EMBEDDING_MODEL` env var and verify they all use the Ollama tag form (`name:tag`), not the HuggingFace form (`org/name`).

---

### BP-344: AGE SyncWorker Disabled by Feature Flag — Fully Implemented Worker Never Executes

**Category**: Config & Docker
**Severity**: MEDIUM
**First seen**: 2026-05-03
**Services**: knowledge-graph (S7)

**Symptoms**:
- AGE (Apache AGE) property graph is never populated despite 500+ entities and relations existing
- Worker 13F logs `age_sync_worker_disabled` every run with `return` immediately
- Apache AGE graph `worldview_graph` exists but has stale/empty data

**Root cause**:
`KNOWLEDGE_GRAPH_CYPHER_ENABLED=false` in `services/knowledge-graph/configs/docker.env`. The worker code at `age_sync_worker.py:179` checks `if not self._settings.cypher_enabled: return`. The worker itself is fully implemented with injection-protected Cypher queries, watermark-based sync, and proper `LOAD 'age'` session setup — it was intentionally gated during development and the flag was never flipped.

**Example**:
```python
# Bad (docker.env)
KNOWLEDGE_GRAPH_CYPHER_ENABLED=false  # worker never runs

# Good
KNOWLEDGE_GRAPH_CYPHER_ENABLED=true
```

**Fix**:
Set `KNOWLEDGE_GRAPH_CYPHER_ENABLED=true` in `services/knowledge-graph/configs/docker.env` and rebuild the knowledge-graph-scheduler container.

**Prevention**:
- Feature flags that disable entire workers should be tracked in TRACKING.md with an explicit "re-enable by [date]" note
- Review checklist: grep for `=false` in docker.env files and verify each disabled feature has a documented rationale
- Add a startup log message when `cypher_enabled=false` at WARNING level (not DEBUG) so the disabled state is visible without hunting

**Regression test**: manual validation — `docker logs knowledge-graph-scheduler | grep age_sync` should show `age_sync_worker_complete` not `age_sync_worker_disabled`

---

### BP-346: Stale Container Missing Module Added After Last Build

**Category**: Config & Docker
**Severity**: CRITICAL
**First seen**: 2026-05-03
**Services**: knowledge-graph

**Symptoms**:
- Consumer container appears healthy (`Up X hours (healthy)`) but emits `ModuleNotFoundError` for every Kafka message
- Zero records being created in downstream tables despite active Kafka topic traffic
- Container logs show `kafka_message_failed_retryable` + `kafka_unexpected_error` with `attempt: 1` in a loop

**Root cause**:
A Python module (`contracts.events.nlp.article_enriched`) was added to a shared library after the Docker image was last built. The container image's `.venv` was built from the old library code and does not include the new subpackage. Because Docker caches the build and the image tag (`latest`) is reused, the running container is silently out of date.

**Example**:
```
ModuleNotFoundError: No module named 'contracts.events'
```
in `enriched_consumer.py` line 27:
```python
from contracts.events.nlp.article_enriched import decode_raw_array
```
even though `libs/contracts/src/contracts/events/nlp/article_enriched.py` exists in the source tree.

**Fix**:
```bash
docker compose build <service-name>
docker compose up -d --no-deps <service-name>
```

**Prevention**:
- After adding a new Python module to a shared library, rebuild ALL containers that import that library
- Add a CI step that checks the installed package version in the running container against the source version on startup
- Log the installed `contracts` package version at consumer startup: `importlib.metadata.version("contracts")` — this makes version drift immediately visible in logs

**Regression test**: observe `kafka_consumer_started` log + successful `enriched_article_processed` after rebuild

---

## BP-456 — Parallel fix + QA agents: Docker rebuild races with uncommitted fix-agent edits

**Date discovered**: 2026-05-11

**Symptom**: Docker rebuild completes. Container is healthy. Bugs that fix agents were supposed to fix are still visible — the old compiled code is running. `git status` shows the fix files modified locally (fixes ARE on disk) but the container has old behaviour.

**Root cause**: In a multi-agent parallel workflow, a QA/rebuild agent starts `docker compose build` at the same time as fix agents begin editing files. The `COPY` instruction in the Dockerfile captures the source tree at the moment it executes, not at build-end. If fix agents finish writing files AFTER the `COPY` layer has already run, the compiled bundle contains pre-fix source code.

**Timeline example**:
```
T+00s  Fix Agent A starts editing OHLCVChart.tsx
T+00s  QA Agent: docker compose build starts
T+15s  Docker COPY apps/worldview-web executes (captures pre-fix source)
T+30s  Next.js compilation starts from stale copy
T+45s  Fix Agent A writes fix to disk (too late — already copied)
T+2m   Build complete — healthy container with OLD code
```

**Detection**: Run `grep -n "fix_signature" local/source/file.tsx`. If present locally but the container behaviour is wrong, the build raced. For Next.js standalone containers (no source files inside), the compiled JS bundles cannot be grepped — rely on HTTP smoke tests against the running container.

**Fix**:
```bash
docker compose build <service>        # rebuild AFTER all fixes confirmed on disk
docker compose up -d worldview-web    # restart with new image
```

**Prevention**:
- In multi-agent workflows, QA/rebuild agents must be launched SEQUENTIALLY after fix agents confirm their edits (not in parallel).
- Never start a Docker build step as part of a parallel agent batch that also includes edit agents.
- Validate the rebuild actually captured the fix: for frontend bundles, run a lightweight HTTP test that exercises the fixed component, not just a health check.

**Reference**: 2026-05-11 portfolio/instrument frontend bug fix batch — QA agent built image 87s before fix agents finished writing OHLCVChart.tsx.

---
