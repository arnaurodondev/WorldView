# Contributing to Worldview

Thank you for contributing to the Worldview Market Intelligence Platform.

## Getting Started

1. Read `CLAUDE.md` — primary entry point, skill reference, and hard rules
2. Read `RULES.md` — the non-negotiable rules
3. Read `docs/MASTER_PLAN.md` — full system architecture
4. Run `./scripts/bootstrap.sh` to set up your environment

For AI contributors, also read:
- `AGENTS.md` — coding standards, architecture patterns, shared libraries
- `services/<service>/.claude-context.md` — per-service quick context

## Dev Environment Setup

### Prerequisites

- Python 3.12+ (`pyenv` recommended)
- Docker Desktop with Compose plugin
- `pnpm` for frontend (`npm install -g pnpm`)
- A clone of the private `worldview-gitops` repo next to this one (for env files and secrets)

### First-time setup

```bash
# 1. Install Python dependencies (creates .venv312/)
./scripts/bootstrap.sh

# 2. Copy dev env files from the private worldview-gitops repo
# (must have worldview-gitops cloned alongside this repo)
cd ../worldview-gitops && ./scripts/setup-dev.sh && cd ../worldview

# 3. Fetch external API keys (EODHD, Polymarket, OIDC credentials)
make fetch-secrets

# 4. Start the full dev stack
make dev

# 5. Seed sample data (instruments, entities, articles)
make seed
```

### Dev Login (no Zitadel required)

When the Zitadel OIDC service is not running locally, the frontend login page
automatically shows a **Dev Login** button. The API Gateway (`GET /v1/auth/dev-login`)
issues a test JWT valid for local development without any external auth service.

For full Zitadel auth development:
```bash
docker compose -f infra/compose/docker-compose.zitadel.yml up -d
# Then visit http://localhost:8080 to configure your OIDC client
```

### Environment Variables

All service configuration is in the private `worldview-gitops` repo under `env/dev/<service>.env`.
The `setup-dev.sh` script copies these to `services/<service>/configs/docker.env`.

**Tuning without rebuilding Docker images**: Almost all thresholds, model IDs, and processing
parameters are exposed as environment variables. Edit the relevant `env/dev/<service>.env` file
in worldview-gitops and restart the affected container:

```bash
# Example: change NLP pipeline GLiNER threshold
# Edit worldview-gitops/env/dev/nlp-pipeline.env: NLP_PIPELINE_GLINER_THRESHOLD=0.40
docker compose -f infra/compose/docker-compose.yml restart nlp-pipeline
```

No Docker image rebuild needed for configuration changes.

## AI-Assisted Workflow (Recommended)

Use the defined skills for all non-trivial work:

| Task | Skill | Description |
|------|-------|-------------|
| New feature | `/prd` → `/plan` → `/implement` | Full lifecycle: spec → plan → build |
| Bug fix | `/fix-bug` | Diagnose, fix, test, update patterns |
| Deep investigation | `/investigate` | Multi-hypothesis analysis |
| Code review | `/review` | Structured multi-layer analysis |
| Write tests | `/test-feature` | Comprehensive test design |
| Quality check | `/qa` | Full test layers + architecture check |
| Security review | `/security-audit` | OWASP + project-specific threats |
| Refactoring | `/refactor` | Safe behavior-preserving restructure |
| Documentation check | `/docs-audit` | Find gaps, staleness, inconsistencies |

Skills enforce validation gates, documentation updates, and compounding updates automatically.

## Manual Development Workflow

### 1. Branch from main
```bash
git checkout main && git pull
git checkout -b feat/my-feature
```

Branch naming: `feat/`, `fix/`, `docs/`, `refactor/` prefix.

### 2. Make changes
- Follow Clean Architecture (see `AGENTS.md` § Architecture Pattern)
- Write tests alongside code (R1 from `RULES.md`)
- Update docs if you changed APIs, events, or schemas (R3)

### 3. Validate locally
```bash
make qa                # lint + typecheck + unit tests (CI gate)
./scripts/lint.sh      # ruff + mypy only
./scripts/test.sh      # pytest all services + libs
```

See `docs/testing/TEST_GUIDE.md` for the full test reference (all layers, Docker Compose profiles, frontend).

Hooks enforce validation automatically:
- **Pre-commit**: ruff + mypy + unit tests on changed files
- **Post-edit**: targeted tests after `.py` and `.ts/.tsx` edits
- **Pre-PR**: full checklist (lint, tests, architecture, schemas, docs, security)

### 4. Create a Pull Request
- Reference related issues
- Fill in the PR template
- Ensure CI passes (R17)
- Request review if touching `libs/`, `infra/`, or Avro schemas

### 5. Merge
- Squash-merge to keep history clean
- Delete the feature branch after merge

## Architecture Decisions

Major changes require an ADR (Architecture Decision Record):
1. Copy `docs/architecture/decisions/ADR_TEMPLATE.md`
2. Name: `NNNN-<short-title>.md`
3. Get review before implementing

## Code Style

Enforced automatically by `ruff` and `mypy`. Key points:
- Line length: 120
- Type hints on all function signatures
- `structlog` for logging (never `print()`)
- `async`/`await` for all I/O
- Pydantic models for config and API schemas

## Test Categories

| Marker | Purpose | When Required |
|--------|---------|---------------|
| `@pytest.mark.unit` | Fast, isolated tests | Always |
| `@pytest.mark.integration` | Tests with real DB/Kafka/MinIO | For data layer changes |
| `@pytest.mark.contract` | Avro schema compatibility | For event changes |
| `@pytest.mark.e2e` | Full request path tests | For API/cross-service changes |

## Compounding Knowledge

Every contribution should leave the system smarter:
- Found a new bug pattern? → Add to `docs/BUG_PATTERNS.md`
- Established a new convention? → Add to `docs/STANDARDS.md`
- Found a security pattern? → Add to `.claude/review/heuristics/HIGH_RISK_PATTERNS.md`

## Questions?

Open an issue or check `docs/` for detailed guides.
