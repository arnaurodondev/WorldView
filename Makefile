.PHONY: help lint typecheck test-unit test-e2e test-all test-arch infra-up infra-down schema-set-compat qa qa-exhaustive qa-exhaustive-backend qa-exhaustive-frontend qa-live-stack qa-contract dev dev-down dev-reset dev-logs dev-ps dev-rebuild rebuild dev-clean seed prod prod-down prod-rebuild test test-down test-rebuild seed-eval eval python-base build-bases dev-lean dev-full dev-lean-status

# ── Docker base images ────────────────────────────────────────────────────────
# `python-base` must be built before any service image that derives from it.
# This bakes the 8 shared libs into /wheels/ inside worldview-python-base:latest.
# Service Dockerfiles then `FROM worldview-python-base:latest` and `uv pip
# install --find-links /wheels` only what they need.

python-base:
	DOCKER_BUILDKIT=1 docker build \
	  -f infra/docker/python-base/Dockerfile \
	  -t worldview-python-base:latest \
	  .

build-bases: python-base

# ── Default target ────────────────────────────────────────────────────────────

help:
	@echo "Worldview Platform — Test Targets"
	@echo ""
	@echo "  make lint            Ruff check + format check (no infra)"
	@echo "  make typecheck       mypy for all services and libs"
	@echo "  make test-unit       All unit + contract tests (no infra)"
	@echo "  make test-arch       Architecture/standards compliance tests"
	@echo "  make test-all        Full platform: lint + unit + integration + e2e"
	@echo "  make infra-up        Start test Docker Compose stack (--profile all)"
	@echo "  make infra-down      Stop test Docker Compose stack"
	@echo "  make qa              lint + typecheck + test-unit (CI gate)"
	@echo "  make qa-exhaustive   Exhaustive QA vs live dev stack (make dev + make seed first)"
	@echo "  make qa-live-stack   Frontend vs real API, no mocks (exposes broken backends)"
	@echo "  make qa-contract     Verify mock fixtures match real API shapes"
	@echo ""
	@echo "  make test-unit SERVICE=<svc>   Unit tests for a single service"
	@echo "  make test-e2e  SERVICE=<svc>   E2E tests for a single service"
	@echo "  make infra-up  PROFILE=<p>     Start a specific Compose profile"
	@echo ""
	@echo "Dev environment setup:"
	@echo "  (worldview-gitops)/scripts/setup-dev.sh   Copy dev env files from private repo"
	@echo "  make dev                                   Start full Docker Compose dev stack"
	@echo "  make dev-clean                             Remove local docker.env files"
	@echo "  make seed                                  Load sample data (SQL + Python)"
	@echo ""
	@echo "Retrieval eval (isolated — no live data ingestion):"
	@echo "  (worldview-gitops)/scripts/setup-eval.sh  Copy eval env files (run once)"
	@echo "  make test                                  Boot minimal eval stack"
	@echo "  make test-rebuild                          Rebuild images + boot eval stack"
	@echo "  make test-down                             Stop eval stack"
	@echo "  make seed-eval                             Seed SQL + demo data + eval corpus"
	@echo "  make eval                                  Run eval_retrieval.py vs live stack"
	@echo ""
	@echo "Production (Hetzner single-server, Traefik TLS):"
	@echo "  DOMAIN=worldview.example.com ACME_EMAIL=ops@example.com make prod"
	@echo "  make prod-down"
	@echo "  make prod-rebuild"

# ── Lint ──────────────────────────────────────────────────────────────────────

lint:
	uvx ruff@0.4.0 check libs/ services/ tests/
	uvx ruff@0.4.0 format --check libs/ services/ tests/

# ── Type check ────────────────────────────────────────────────────────────────

typecheck:
	@for svc_src in services/*/src; do \
	  svc_dir=$$(dirname "$$svc_src"); \
	  if [ -f "$$svc_dir/mypy.ini" ]; then \
	    echo "mypy: $$svc_dir"; \
	    mypy "$$svc_src" --config-file "$$svc_dir/mypy.ini" || exit 1; \
	  fi; \
	done
	@for lib_src in libs/*/src; do \
	  lib_dir=$$(dirname "$$lib_src"); \
	  if [ -f "$$lib_dir/mypy.ini" ]; then \
	    echo "mypy: $$lib_dir"; \
	    mypy "$$lib_src" --config-file "$$lib_dir/mypy.ini" || exit 1; \
	  fi; \
	done

# ── Unit tests ────────────────────────────────────────────────────────────────

test-unit:
	@./scripts/test-libs.sh
ifdef SERVICE
	@./scripts/run-unit-tests.sh services/$(SERVICE)
else
	@./scripts/run-unit-tests.sh
endif

# ── E2E tests ─────────────────────────────────────────────────────────────────

test-e2e:
ifdef SERVICE
	./scripts/run-service-e2e.sh $(SERVICE)
else
	./scripts/test-full.sh --no-cleanup
endif

# ── Full suite (all layers) ───────────────────────────────────────────────────

test-all:
	./scripts/test-full.sh

# ── Infrastructure ────────────────────────────────────────────────────────────

infra-up:
	docker compose -f infra/compose/docker-compose.test.yml \
	  --profile $${PROFILE:-all} up --build --wait

infra-down:
	docker compose -f infra/compose/docker-compose.test.yml down -v

## Pin per-subject Schema Registry compatibility level (PLAN-0057 D-004).
## Idempotent: re-runs the set-schema-compatibility.sh script against the
## running registry. Use this if you bring the registry up manually OR want
## to force-reset the policy without a full ``make dev`` cycle.
schema-set-compat:
	SCHEMA_REGISTRY_URL=$${SCHEMA_REGISTRY_URL:-http://localhost:8081} \
	COMPAT_LEVEL=$${COMPAT_LEVEL:-BACKWARD} \
	  bash infra/kafka/init/set-schema-compatibility.sh

# ── CI gate ───────────────────────────────────────────────────────────────────

qa: lint typecheck test-unit

# ── Exhaustive QA (requires dev stack running: make dev + make seed) ──────

.PHONY: qa-exhaustive qa-exhaustive-backend qa-exhaustive-frontend

## Run the full exhaustive QA layer (backend + frontend) against the live dev stack
qa-exhaustive: qa-exhaustive-backend qa-exhaustive-frontend

## Backend exhaustive QA: endpoint coverage, auth, security, schema validation
qa-exhaustive-backend:
	@echo "=== Running backend exhaustive QA ==="
	python3 scripts/qa_exhaustive.py

## Frontend exhaustive QA: all routes, states, screenshots, a11y, security headers
qa-exhaustive-frontend:
	@echo "=== Running frontend exhaustive QA ==="
	cd apps/worldview-web && npx playwright test e2e/qa-exhaustive.spec.ts --reporter=list

## Frontend live-stack QA: real API calls, no mocks — exposes broken backends
qa-live-stack:
	@echo "=== Running frontend live-stack QA (no mocks) ==="
	cd apps/worldview-web && npx playwright test e2e/qa-live-stack.spec.ts --project=chromium --reporter=list

## Contract alignment: verify frontend mock fixtures match real API response shapes
qa-contract:
	@echo "=== Running contract alignment check ==="
	python3 scripts/qa_contract_alignment.py

# ── Architecture tests ─────────────────────────────────────────────────────

test-arch:
	python -m pytest tests/architecture/ -v --tb=short

# ── Development Environment ──────────────────────────────────────────────────

# ── Development Environment ──────────────────────────────────────────────────
# Dev env files (docker.env) are NOT generated here — they live in the private
# worldview-gitops repo. Run scripts/setup-dev.sh from worldview-gitops first.
# See: https://github.com/your-org/worldview-gitops/blob/main/scripts/setup-dev.sh

## Start the full development stack (all services + dev tools + MailHog)
## Kills any local process holding port 3001 first so worldview-web always wins.
dev:
	@lsof -ti :3001 | xargs -r kill -9 2>/dev/null || true
	-$(COMPOSE_DEV) up -d --build
	@docker ps -aq --filter status=created | xargs -r docker start 2>/dev/null || true
	@echo ""
	@echo "🚀 Worldview dev stack is running!"
	@echo ""
	@echo "  Frontend:        http://localhost:3001"
	@echo "  API Gateway:     http://localhost:8000"
	@echo "  MailHog:         http://localhost:8025"
	@echo "  pgweb:           http://localhost:8091"
	@echo "  Kafka UI:        http://localhost:8092"
	@echo "  MinIO Console:   http://localhost:7481"
	@echo ""

COMPOSE_DEV := docker compose -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.dev.yml --profile infra

## Stop the development stack (--timeout 5 avoids 30s hang on workers without SIGTERM handlers)
dev-down:
	$(COMPOSE_DEV) down --timeout 5

## Stop and remove all data (clean reset)
dev-reset:
	$(COMPOSE_DEV) down -v --remove-orphans --timeout 5

## Show logs for all services (follow mode)
dev-logs:
	$(COMPOSE_DEV) logs -f --tail=50

## Show container health status
dev-ps:
	$(COMPOSE_DEV) ps

# ── Lean dev mode (CPU-bottleneck relief — 2026-06-21 cpu-bottleneck audit) ───
# The full dev stack runs the entire production topology (~78 containers) on one
# Docker VM. On a CPU-constrained host the idle/low-frequency consumers add base
# poll + Kafka-rebalance overhead that starves the hot paths (GLiNER NER, KG
# queries). ``dev-lean`` STOPS the Tier-1 idle consumers and collapses the
# article-consumer fleet 2->1; ``dev-full`` brings everything back. Both are
# REVERSIBLE and NON-destructive — containers are stopped/started (not removed),
# no rebuild, no data loss. NOT touched: the active market-data / KG / extraction
# consumers (stop those individually with ``$(COMPOSE_DEV) stop <svc>`` if needed).
#
# Tier-1 = low-frequency dataset loaders + niche consumers nothing produces to in
# idle local dev. Edit this list to taste.
SLIM_SERVICES := \
  knowledge-graph-insider-transactions-dataset-consumer \
  knowledge-graph-macro-indicator-dataset-consumer \
  knowledge-graph-economic-events-dataset-consumer \
  knowledge-graph-earnings-calendar-dataset-consumer \
  knowledge-graph-instrument-discovered-consumer \
  knowledge-graph-provisional-queued-consumer \
  market-data-insider-transactions-consumer \
  market-data-prediction-market-consumer

# The article-consumer fleet uses KIP-345 static membership: each replica is its
# OWN compose service (…-consumer-0, …-consumer-1) with a distinct instance id,
# NOT a scalable single service. `--scale nlp-pipeline-article-consumer=N` fails
# with "no such service". To collapse the fleet 2->1 we STOP replica -1 (keeping
# -0 hot); dev-full starts it back. Add future replicas here to keep them lean.
ARTICLE_CONSUMER_LEAN_STOP := nlp-pipeline-article-consumer-1
ARTICLE_CONSUMER_ALL := nlp-pipeline-article-consumer-0 nlp-pipeline-article-consumer-1

## Slim the running dev stack: stop Tier-1 idle consumers + collapse article-consumer 2->1 (reversible, no data loss)
dev-lean:
	$(COMPOSE_DEV) stop $(SLIM_SERVICES) $(ARTICLE_CONSUMER_LEAN_STOP)
	@echo ""
	@echo "🍃 Lean mode ON — Tier-1 consumers stopped + article-consumer collapsed to 1 (replica -1 stopped)."
	@echo "   Restore the full platform with:  make dev-full"

## Restore the full dev stack: start Tier-1 consumers + article-consumer back to both replicas
dev-full:
	$(COMPOSE_DEV) start $(SLIM_SERVICES) $(ARTICLE_CONSUMER_ALL)
	@echo ""
	@echo "🚀 Full mode — all Tier-1 consumers started + article-consumer back to 2 replicas."

## Show running/stopped status of just the Tier-1 (slimmable) services
dev-lean-status:
	$(COMPOSE_DEV) ps --all $(SLIM_SERVICES) $(ARTICLE_CONSUMER_ALL)

## Rebuild all images without cache and restart
dev-rebuild:
	@lsof -ti :3001 | xargs -r kill -9 2>/dev/null || true
	$(COMPOSE_DEV) build --no-cache
	$(COMPOSE_DEV) up -d --force-recreate
	@docker ps -aq --filter status=created | xargs -r docker start 2>/dev/null || true

## Rebuild + recreate EVERY variant of ONE service family (app + migrate +
## consumers + workers). Each variant has its own build:/image in compose, so
## `docker compose build <svc>` alone ships STALE code to the siblings — this
## target rebuilds them all. Usage: make rebuild SVC=market-data [CACHE=1]
rebuild:
	@test -n "$(SVC)" || { echo "Usage: make rebuild SVC=<family> [CACHE=1] (e.g. SVC=market-data)"; exit 2; }
	./scripts/rebuild_service.sh $(SVC) $(if $(CACHE),--cache,)

## Remove local docker.env files (re-run setup-dev.sh from worldview-gitops to restore)
dev-clean:
	@find services/*/configs -name "docker.env" -delete
	@echo "docker.env files removed. Run scripts/setup-dev.sh from worldview-gitops to restore."

## Seed development data (SQL fixtures + Python demo data).
## Runs both seed-dev-data.sh (portfolio/market instruments) AND seed_demo_data.py
## (canonical entities, OHLCV bars, company profiles, content_ingestion sources).
## WS3 audit finding: seed_demo_data.py was previously not called by make seed,
## leaving entity_embedding_state, ohlcv_bars, company_profiles and content_ingestion
## sources empty on a fresh stack.
seed:
	@./scripts/seed-dev-data.sh
	@.venv312/bin/python scripts/seed_demo_data.py

# ── Retrieval eval stack (isolated — no ingestion workers) ──────────────────
#
# The eval stack boots a controlled subset of services (API servers only) so
# that the intelligence_db corpus is never overwritten by live data ingestion
# during a test run.  Use make test + make seed-eval, then make eval.
#
# Prerequisites: run worldview-gitops/scripts/setup-eval.sh once to copy eval
# env files into services/*/configs/docker.env.  The eval env is identical to
# dev except rag-chat has INTERNAL_JWT_SKIP_VERIFICATION=true so eval_retrieval.py
# can call /v1/internal/retrieve without generating a signed JWT.

COMPOSE_EVAL := docker compose \
  -f infra/compose/docker-compose.yml \
  -f infra/compose/docker-compose.eval.yml \
  --profile eval

## Boot the minimal eval stack (infra + API servers; no workers or ingestion).
## Run worldview-gitops/scripts/setup-eval.sh first.
test:
	$(COMPOSE_EVAL) up -d --wait
	@echo ""
	@echo "Eval stack is running. Next: make seed-eval"
	@echo "  RAG Chat:      http://localhost:8008"
	@echo "  API Gateway:   http://localhost:8000"
	@echo "  Postgres:      localhost:5432"
	@echo "  Ollama:        http://localhost:11434"
	@echo ""

## Rebuild all eval images from scratch, then boot the eval stack.
test-rebuild:
	$(COMPOSE_EVAL) build --no-cache
	$(COMPOSE_EVAL) up -d --wait

## Stop the eval stack (graceful 5s timeout).
test-down:
	$(COMPOSE_EVAL) down --timeout 5

## Seed the eval corpus (SQL fixtures + Python demo data + synthetic eval chunks).
## Requires: make test (stack must be running), Ollama healthy with bge-large loaded.
## Order:
##   1. seed-dev-data.sh    — portfolio_db + market_data_db instruments
##   2. seed_demo_data.py   — canonical entities, OHLCV bars, company profiles
##   3. seed-eval-corpus.py — 225 synthetic financial chunks with bge-large embeddings
seed-eval:
	@echo "[seed-eval] Step 1/3: SQL fixtures (portfolio_db, market_data_db)..."
	@./scripts/seed-dev-data.sh
	@echo "[seed-eval] Step 2/3: Python demo data (entities, OHLCV, profiles)..."
	@.venv312/bin/python scripts/seed_demo_data.py
	@echo "[seed-eval] Step 3/3: Eval corpus (225 chunks + bge-large embeddings)..."
	@OLLAMA_URL=http://localhost:11434 \
	  EVAL_DB_URL=postgresql://postgres:postgres@localhost:5432/nlp_db \
	  .venv312/bin/python scripts/seed-eval-corpus.py
	@echo "[seed-eval] Done. Run: make eval"

## Run the retrieval evaluation harness vs the live eval stack.
## Uses queries_eval_stack.jsonl (synthetic-only corpus, 64 labelled queries).
## Full production eval uses queries.jsonl (120 queries, requires live ingestion).
## Reports NDCG@10, MRR, P@5, Recall@20 overall and per query_class.
## Gate: NDCG@10 must not drop >0.03 from results/baseline_pre_hybrid.json.
## Requires: make test + make seed-eval already run.
## Dev-only RS256 token (eval harness; signed with api-gateway dev keypair; no jti → replay check skipped).
## This token is intentionally committed — it uses a dev-only key stored in worldview-gitops (private repo),
## is only valid when RAG_CHAT_INTERNAL_JWT_SKIP_VERIFICATION=false with the matching public key,
## and expires 2027-04-21. Rotate by re-running scripts/gen-eval-jwt.py.
EVAL_JWT := eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwMDAwMDAwMC0wMDAwLTAwMDAtMDAwMC0wMDAwMDAwMDAwOTkiLCJ0ZW5hbnRfaWQiOiIwMDAwMDAwMC0wMDAwLTAwMDAtMDAwMC0wMDAwMDAwMDAwMDEiLCJyb2xlIjoic3lzdGVtIiwiZXhwIjoxODA5NzMxNjA1LCJpc3MiOiJ3b3JsZHZpZXctZ2F0ZXdheSIsImF1ZCI6Indvcmxkdmlldy1pbnRlcm5hbCJ9.HlVtdMTE1e1psgv-7F2KvD7QU6ITl6mq4jQ89RKUnxj_R7Ub0vbL1iFIapkOo_npb_BrIYHZ2SAKnVAc52JutoAJ734ke3TavHLj6qRE5X34TYLNrJfCo_JRBKx0dbl4jMwGTgNCMQv4hxYpRzjyokh3mPBjdKmknupTiLcLic8sFKwvLdgrItQcu0fhDToLCzMXQXhO8ZS1ivoGMjnmzAsPaQnLDJ1vcuEOW16jtNifQrMcZvKw8F9z-PRmiqQ5H84n6WdfkSm9VpWr7eac20neou6OnTxiMM2opW-EnQB6meKmt6---p-vjoxkkEjXn17_3l-Sp8cO1ow73lnvCA

eval:
	EVAL_INTERNAL_JWT=$(EVAL_JWT) \
	  .venv312/bin/python scripts/eval_retrieval.py \
	  --rag-url http://localhost:8008 \
	  --golden tests/eval/golden/queries_eval_stack.jsonl \
	  --query-embeddings tests/eval/golden/query_embeddings.parquet \
	  --mode hybrid \
	  --fail-on-regression 0.03 \
	  --output-dir results/

.PHONY: test test-down test-rebuild seed-eval eval

# ── Observability stack ─────────────────────────────────────────────────────

COMPOSE_MONITORING := docker compose -f infra/compose/docker-compose.yml --profile monitoring

## Start the monitoring stack (Prometheus, Grafana, Alertmanager, Alloy, Loki, Tempo).
## Run AFTER `make dev` — monitoring targets the running dev services.
## Grafana: http://localhost:3000  Prometheus: http://localhost:9090
## Alertmanager: http://localhost:9093
monitoring:
	$(COMPOSE_MONITORING) up -d
	@echo ""
	@echo "Observability stack is running:"
	@echo "  Grafana:        http://localhost:3000  (admin/admin)"
	@echo "  Prometheus:     http://localhost:9090"
	@echo "  Alertmanager:   http://localhost:9093"
	@echo ""
	@echo "Use 'make monitoring-down' to stop."

## Stop the monitoring stack
monitoring-down:
	$(COMPOSE_MONITORING) down

.PHONY: monitoring monitoring-down

## Validate every Grafana dashboard panel against live Prometheus/Loki
## (writes build/grafana_validation_results.tsv, exit 1 on BROKEN rows)
grafana-validate:
	@bash scripts/grafana_validation.sh

.PHONY: grafana-validate

# ── Production stack (Hetzner single-server with Traefik TLS) ───────────────
#
# Required env vars: DOMAIN, ACME_EMAIL
# Optional: ZITADEL_URL, ZITADEL_CLIENT_ID, NEXT_PUBLIC_WS_BASE_URL
#
# Example:
#   export DOMAIN=worldview.example.com
#   export ACME_EMAIL=ops@example.com
#   export ZITADEL_URL=https://auth.example.com
#   make prod
#
# For Vercel + Hetzner split: comment out worldview-web in docker-compose.prod.yml
# and deploy the Next.js app to Vercel with the corresponding env vars.

COMPOSE_PROD := docker compose \
  -f infra/compose/docker-compose.yml \
  -f infra/compose/docker-compose.prod.yml \
  --profile infra

## Start the full production stack with Traefik TLS (requires DOMAIN + ACME_EMAIL).
## Builds images and starts all services. First run pulls Let's Encrypt certificates.
prod:
	@if [ -z "$(DOMAIN)" ]; then echo "ERROR: DOMAIN is not set. Example: DOMAIN=worldview.example.com make prod"; exit 1; fi
	@if [ -z "$(ACME_EMAIL)" ]; then echo "ERROR: ACME_EMAIL is not set. Example: ACME_EMAIL=ops@example.com make prod"; exit 1; fi
	$(COMPOSE_PROD) up -d --build
	@docker ps -aq --filter status=created | xargs -r docker start 2>/dev/null || true
	@echo ""
	@echo "Worldview production stack is running!"
	@echo ""
	@echo "  App:        https://$(DOMAIN)"
	@echo "  API:        https://api.$(DOMAIN)"
	@echo "  WebSocket:  wss://ws.$(DOMAIN)"
	@echo "  Grafana:    https://grafana.$(DOMAIN)  (admin/admin — change immediately)"
	@echo ""
	@echo "Traefik is obtaining Let's Encrypt certificates. Allow 30-60s on first start."
	@echo "Check certificate status: docker logs worldview-traefik-1 2>&1 | grep acme"

## Stop the production stack (graceful 10s timeout)
prod-down:
	$(COMPOSE_PROD) down --timeout 10

## Rebuild all images and restart the production stack (zero-downtime not guaranteed)
prod-rebuild:
	@if [ -z "$(DOMAIN)" ]; then echo "ERROR: DOMAIN is not set."; exit 1; fi
	@if [ -z "$(ACME_EMAIL)" ]; then echo "ERROR: ACME_EMAIL is not set."; exit 1; fi
	$(COMPOSE_PROD) build --no-cache
	$(COMPOSE_PROD) up -d --force-recreate
	@docker ps -aq --filter status=created | xargs -r docker start 2>/dev/null || true
