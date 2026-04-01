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
./scripts/lint.sh      # ruff + mypy
./scripts/test.sh      # pytest all services + libs
```

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
