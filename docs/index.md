# Worldview Documentation Index

> Single entry point for all project documentation.

---

## Architecture

| Document | Description |
|----------|-------------|
| [MASTER_PLAN.md](MASTER_PLAN.md) | System architecture, service catalog, data lifecycle, contracts |
| [Architecture Diagrams](architecture/diagrams.md) | Mermaid component, dataflow, and sequence diagrams |
| [ADR-0001 — Initial Architecture](architecture/decisions/0001-initial-architecture.md) | Backend architecture decisions |
| [ADR-0002 — Frontend Tooling](architecture/decisions/0002-frontend-tooling.md) | Vite + React + pnpm rationale |

---

## Services (S1–S9)

| Service | Port | Doc |
|---------|------|-----|
| S1 · Portfolio | 8001 | [portfolio.md](services/portfolio.md) |
| S2 · Market Ingestion | 8002 | [market-ingestion.md](services/market-ingestion.md) |
| S3 · Market Data | 8003 | [market-data.md](services/market-data.md) |
| S4 · Content Ingestion | 8004 | [content-ingestion.md](services/content-ingestion.md) |
| S5 · Content Store | 8005 | [content-store.md](services/content-store.md) |
| S6 · NLP Pipeline | 8006 | [nlp-pipeline.md](services/nlp-pipeline.md) |
| S7 · Knowledge Graph | 8007 | [knowledge-graph.md](services/knowledge-graph.md) |
| S8 · RAG / Chat | 8008 | [rag-chat.md](services/rag-chat.md) |
| S9 · API Gateway | 8000 | [api-gateway.md](services/api-gateway.md) |

---

## Applications

| App | Port | Doc |
|-----|------|-----|
| Frontend (React + Vite) | 5173 | [frontend.md](apps/frontend.md) |

---

## Shared Libraries

| Library | Doc |
|---------|-----|
| common | [common.md](libs/common.md) |
| contracts | [contracts.md](libs/contracts.md) |
| messaging | [messaging.md](libs/messaging.md) |
| storage | [storage.md](libs/storage.md) |
| observability | [observability.md](libs/observability.md) |

---

## Workflows

| Guide | Doc |
|-------|-----|
| Local Development | [local-dev.md](workflows/local-dev.md) |
| CI / CD Pipeline | [ci-cd.md](workflows/ci-cd.md) |
| Testing Strategy | [testing-strategy.md](workflows/testing-strategy.md) |
| Release Process | [release-process.md](workflows/release-process.md) |

---

## Governance

| File | Purpose |
|------|---------|
| [AGENTS.md](../AGENTS.md) | AI agent operating guide |
| [CLAUDE.md](../CLAUDE.md) | Claude-specific instructions |
| [RULES.md](../RULES.md) | Hard rules for all contributors |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Contribution workflow |

---

## Migration

| Doc | Description |
|-----|-------------|
| [REUSE_FROM_ORIGINAL_THESIS.md](migration/REUSE_FROM_ORIGINAL_THESIS.md) | Legacy repo reuse mapping |

---

## AI Interactions

| Item | Description |
|------|-------------|
| [AI Interactions README](ai-interactions/README.md) | Canonical workflow for prompts and response reports |
| [Orchestrator Runbook](ai-interactions/ORCHESTRATOR_RUNBOOK.md) | Operating procedure for 1 orchestrator + N worker agents |
| [Interactions Registry](ai-interactions/INTERACTIONS_REGISTRY.md) | Audit log of prompt and response executions |
| [Planning Prompt Index](ai-interactions/agent-planning/0000-prompt-library-index-and-conventions.md) | Naming conventions and planning prompt catalog |
| [0005 Generic planning template](ai-interactions/agent-planning/0005-generic-implementation-plan-and-task-breakdown-template.md) | Reusable planning prompt template for non-migration work |
| [Execution Prompt Index](ai-interactions/agent-prompts/0000-execution-prompt-index-and-conventions.md) | Naming conventions and implementation prompt catalog |
| [0001 Exec shared libs wave 01](ai-interactions/agent-prompts/0001-exec-shared-libs-wave-01.md) | First implementation wave for shared libs |
| [0002 Exec portfolio wave 01](ai-interactions/agent-prompts/0002-exec-portfolio-wave-01.md) | First implementation wave for portfolio |
| [0003 Exec market-ingestion wave 01](ai-interactions/agent-prompts/0003-exec-market-ingestion-wave-01.md) | First implementation wave for market-ingestion |
| [0004 Exec market-data wave 01](ai-interactions/agent-prompts/0004-exec-market-data-wave-01.md) | First implementation wave for market-data |
| [Response Template](ai-interactions/agent-responses/0000-response-template.md) | Required implementation report format |
| [Response Review Checklist](ai-interactions/agent-responses/0001-review-checklist.md) | Validation checklist for response quality and compliance |
| [Response Evidence Add-on](ai-interactions/agent-responses/0002-response-evidence-addon-template.md) | Optional per-task evidence section for responses |
| [0001 Shared libs migration](ai-interactions/agent-planning/0001-shared-libs-migration-detailed-plan-and-atomic-tasks.md) | Generate shared libs migration plan and atomic tasks |
| [0002 Portfolio migration](ai-interactions/agent-planning/0002-portfolio-migration-detailed-plan-and-atomic-tasks.md) | Generate portfolio migration plan and atomic tasks |
| [0003 Market Ingestion migration](ai-interactions/agent-planning/0003-market-ingestion-migration-detailed-plan-and-atomic-tasks.md) | Generate ingestion migration plan and atomic tasks |
| [0004 Market Data migration](ai-interactions/agent-planning/0004-market-data-migration-detailed-plan-and-atomic-tasks.md) | Generate market data migration plan and atomic tasks |
