# Worldview Documentation Index

> Single entry point for all project documentation. Updated 2026-05-17.

---

## How to Navigate This Documentation

### Starting a new session?
Read in this order:
1. `CLAUDE.md` (root) — workflow router, skill reference, hard rules
2. `services/<service>/.claude-context.md` — quick context for the service you're working on
3. Invoke the appropriate skill (`/implement`, `/fix-bug`, `/review`, etc.)

### Need deeper understanding?
- System architecture → [MASTER_PLAN.md](MASTER_PLAN.md)
- Engineering standards → [STANDARDS.md](STANDARDS.md)
- Known bug patterns → [BUG_PATTERNS.md](BUG_PATTERNS.md)
- Service details → [services/](#services-s1s10)

### Planning new work?
1. `/prd` → creates spec in [specs/](specs/)
2. `/plan` → creates plan in [plans/](plans/)
3. `/implement` → executes waves from plan

---

## Architecture

| Document | Purpose |
|----------|---------|
| [MASTER_PLAN.md](MASTER_PLAN.md) | Single source of truth — services, data flows, infrastructure, roadmap |
| [STANDARDS.md](STANDARDS.md) | Engineering standards, DDD patterns, testing conventions |
| [Architecture Diagrams](architecture/diagrams.md) | Mermaid component, dataflow, and sequence diagrams |
| [ADR Index](architecture/decisions/) | Architecture Decision Records (ADR-0001 through ADR-0006, plus ADR-F-02, ADR-AUTH-002, ADR-TENANT-001, ADR-EODHD-FAILOVER) |

---

## Services (S1–S10)

| Service | Port | Doc | Context |
|---------|------|-----|---------|
| S1 · Portfolio | 8001 | [portfolio.md](services/portfolio.md) | [.claude-context.md](../services/portfolio/.claude-context.md) |
| S2 · Market Ingestion | 8002 | [market-ingestion.md](services/market-ingestion.md) | [.claude-context.md](../services/market-ingestion/.claude-context.md) |
| S3 · Market Data | 8003 | [market-data.md](services/market-data.md) | [.claude-context.md](../services/market-data/.claude-context.md) |
| S4 · Content Ingestion | 8004 | [content-ingestion.md](services/content-ingestion.md) | [.claude-context.md](../services/content-ingestion/.claude-context.md) |
| S5 · Content Store | 8005 | [content-store.md](services/content-store.md) | [.claude-context.md](../services/content-store/.claude-context.md) |
| S6 · NLP Pipeline | 8006 | [nlp-pipeline.md](services/nlp-pipeline.md) | [.claude-context.md](../services/nlp-pipeline/.claude-context.md) |
| S7 · Knowledge Graph | 8007 | [knowledge-graph.md](services/knowledge-graph.md) | [.claude-context.md](../services/knowledge-graph/.claude-context.md) |
| S8 · RAG / Chat | 8008 | [rag-chat.md](services/rag-chat.md) | [.claude-context.md](../services/rag-chat/.claude-context.md) |
| S9 · API Gateway | 8000 | [api-gateway.md](services/api-gateway.md) | [.claude-context.md](../services/api-gateway/.claude-context.md) |
| S10 · Alert | 8010 | [alert.md](services/alert.md) | [.claude-context.md](../services/alert/.claude-context.md) |
| Init · Intelligence Migrations | — | — | [.claude-context.md](../services/intelligence-migrations/.claude-context.md) |

---

## Applications

| App | Port | Doc |
|-----|------|-----|
| Worldview Web (Next.js 15) | 3001 | [worldview-web.md](apps/worldview-web.md) |

---

## Shared Libraries

| Library | Purpose | Doc |
|---------|---------|-----|
| common | IDs, time, constants | [common.md](libs/common.md) |
| contracts | Canonical Pydantic models, event envelopes | [contracts.md](libs/contracts.md) |
| messaging | Kafka, Avro, outbox, Valkey | [messaging.md](libs/messaging.md) |
| storage | S3/MinIO abstraction | [storage.md](libs/storage.md) |
| observability | structlog, metrics, tracing | [observability.md](libs/observability.md) |
| ml-clients | ML model abstraction | [ml-clients.md](libs/ml-clients.md) |
| prompts | LLM prompt templates | [prompts.md](libs/prompts.md) |
| tools | LLM tool manifest + capability registry (R29) | (doc pending) |

---

## Workflows & Operations

| Guide | Purpose |
|-------|---------|
| **[Infrastructure Guide](infrastructure.md)** | **Complete setup guide: prerequisites, quick start, ports, env vars, Makefile, runbooks** |
| [Local Development](workflows/local-dev.md) | Bootstrap, Docker profiles, port map, troubleshooting |
| [Testing Strategy](testing/testing-strategy.md) | Test pyramid, markers, coverage targets, infrastructure |
| [CI/CD Pipeline](workflows/ci-cd.md) | GitHub Actions, fast path, gated jobs |
| [Release Process](workflows/release-process.md) | Versioning, changelog, pre-release checklist |
| [Testing Guide](testing/TESTING_GUIDE.md) | Quick reference for running tests |
| [Docker Compose Testing](testing/DOCKER_COMPOSE_TEST_GUIDE.md) | Integration test infrastructure |
| [Test Infrastructure Map](testing/TEST_INFRASTRUCTURE_MAP.md) | 155+ test files inventory |
| [Test Report Guide](testing/TEST_REPORT_GUIDE.md) | How to read and generate test reports |

---

## Operations Runbooks

| Service | Runbook |
|---------|---------|
| Infrastructure | [infrastructure.md#runbooks](infrastructure.md#12-runbooks) |
| Market Data (S3) | [market-data-operations.md](runbooks/market-data-operations.md) |
| Market Ingestion (S2) | [market-ingestion-operations.md](runbooks/market-ingestion-operations.md) |
| General | [debugging-guide.md](runbooks/debugging-guide.md) |
| General | [hotfix-procedures.md](runbooks/hotfix-procedures.md) |

---

## Governance (Root-Level Files)

| File | Purpose |
|------|---------|
| [CLAUDE.md](../CLAUDE.md) | Primary entry point — skills, hooks, hard rules, context loading |
| [AGENTS.md](../AGENTS.md) | Coding standards, architecture patterns, shared libraries |
| [RULES.md](../RULES.md) | 34 hard rules (MUST/NEVER), R1–R34 |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Contribution workflow for humans and AI |
| [PRODUCT_CONTEXT.md](PRODUCT_CONTEXT.md) | Product vision, target users, journeys, constraints |
| [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) | P0-P3 production readiness checklist |
| [SECURITY_ISSUES.md](SECURITY_ISSUES.md) | Known security issues (SEC-001 through SEC-011) |

---

## AI-Assisted Development

| Resource | Purpose |
|----------|---------|
| [BUG_PATTERNS.md](BUG_PATTERNS.md) | Living knowledge base of 13+ failure patterns |
| [Eval Framework](../.claude/evals/EVAL_FRAMEWORK.md) | Session tracking, quality metrics, improvement loop |
| [PRD-0014 (Active)](specs/0014-PRD-v1-final.md) | Authoritative PRD for unstructured data pipeline |

---

## Specs & Plans

| Resource | Purpose |
|----------|---------|
| [PRD Template](specs/TEMPLATE.md) | Standardized format for product requirements |
| [Plan Template](plans/TEMPLATE.md) | Standardized format for implementation plans |
| [Plan Tracking](plans/TRACKING.md) | Active plans index |

---

## Audits

| Report | Scope |
|--------|-------|
| [Cross-Service QA Report](audits/2026-03-27-cross-service-qa-report.md) | Initial 3-service QA pass (16 findings) |
| [Deep Cross-Service QA Report](audits/2026-03-27-deep-cross-service-qa-report.md) | Comprehensive multi-agent QA (87 findings) |
| [Spec-Driven Design Audit](audits/spec-driven-design-20260324/audit_report.md) | Contract/schema parity audit with playbooks |

---

## Reference

| Resource | Purpose |
|----------|---------|
| [EODHD Endpoints Reference](references/eodhd-endpoints-reference.md) | 72 EODHD API endpoints with params and response shapes |
