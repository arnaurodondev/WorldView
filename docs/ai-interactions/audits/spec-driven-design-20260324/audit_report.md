# Spec-Driven Design Audit Results

Date: 2026-03-24
Scope: worldview + eodhd-claude-skills (multi-root workspace)
Method: read-only repository audit (artifacts, CI/CD, tests, architecture docs, agent docs)

## Executive Summary

- Overall SDD Maturity: 3.6/5 (structured, partially auditable)
- Compliance Score: 74%
- Risk Level: Medium
- Top 3 Critical Gaps:
  1. Contract/spec compliance tests are uneven across services (heavy in portfolio, sparse elsewhere)
  2. Schema/model drift risk due to dual schema locations and mostly manual parity checks
  3. Agent plan/task specs exist as markdown prompts but lack machine-validated plan/task schemas

Topline assessment:
- worldview has strong enforcement foundations (CI fast-path gates, architecture tests, Avro validation, import guards).
- worldview is not yet fully spec-driven end-to-end because spec-to-code generation and continuous drift controls are limited.
- eodhd-claude-skills has rich documentation coverage but low enforcement automation (manual sync and manual verification).

## Current State Assessment

### 1. Project Topology

- worldview: Python + TypeScript monorepo, microservice/distributed architecture
- eodhd-claude-skills: documentation-first skill/plugin repo + stdlib Python client

Languages/frameworks discovered:
- Python 3.11+ (target 3.12), FastAPI, Pydantic, SQLAlchemy async, pytest, mypy, ruff
- TypeScript strict mode, React 18, Vite 5, Vitest, Playwright
- Kafka + Avro, Postgres/Timescale, MinIO, Valkey, Schema Registry

Service/agent boundary snapshot:
- worldview service dirs found: 11 (10 service components + intelligence-migrations)
- worldview architecture tests: 8 files
- worldview contract tests: 10 files
- worldview integration tests: 19 files
- worldview e2e tests: 5 files
- eodhd endpoint docs: 73 markdown files
- eodhd general guides: 29 markdown files

### 2. Specification Artifact Inventory

```json
{
  "specifications": [
    {
      "type": "OpenAPI/Swagger",
      "files": [
        "worldview/services/*/src/*/api/schemas.py (FastAPI-generated OpenAPI)",
        "worldview/docs/services/*.md"
      ],
      "versions": ["service API versions + /api/v2 required for breaking changes by RULES.md"],
      "coverage": "High for implemented FastAPI services; generated from route+model definitions"
    },
    {
      "type": "AsyncAPI",
      "files": [],
      "message_types": [],
      "note": "No AsyncAPI spec files found; Kafka contracts use Avro schemas"
    },
    {
      "type": "Protobuf/gRPC",
      "files": [],
      "services": [],
      "note": "No proto/gRPC artifacts found"
    },
    {
      "type": "Avro Event Schemas",
      "files": [
        "worldview/infra/kafka/schemas/*.avsc",
        "worldview/services/*/src/*/infrastructure/messaging/schemas/*.avsc"
      ],
      "versions": ["envelope schema_version policy documented in RULES.md + AGENTS.md"],
      "coverage": "Strong for Kafka events"
    },
    {
      "type": "JSON Schema / Structured Rule Specs",
      "files": [
        "worldview/scripts/import_guards/rules.yaml",
        "worldview/scripts/import_guards/baseline.json",
        "worldview/scripts/structure_checks/exceptions.yaml"
      ],
      "domains": ["import boundaries", "service structure conformance"]
    },
    {
      "type": "Internal DSL/Custom Format",
      "files": [
        "worldview/docs/ai-interactions/agent-prompts/*.md",
        "worldview/docs/ai-interactions/agent-planning/*.md",
        "eodhd-claude-skills/skills/eodhd-api/SKILL.md"
      ],
      "parser_location": "Human-readable markdown conventions; no formal parser/schema enforcement"
    }
  ]
}
```

### 3. Agent/Service Mapping

```yaml
worldview-portfolio:
  type: microservice
  language: [python]
  entry_points: [services/portfolio/src/portfolio/api/main.py]
  specs_consumed: [Avro schemas, Pydantic API schemas, architecture rules]
  specs_produced: [portfolio event contracts]
  responsibilities: [portfolio domain + event emission]
  external_dependencies: [Postgres, Kafka, Schema Registry]
  internal_dependencies: [libs/common, libs/messaging, libs/contracts, libs/observability]

worldview-market-ingestion:
  type: microservice
  language: [python]
  entry_points: [services/market-ingestion/src/market_ingestion/api/main.py]
  specs_consumed: [EODHD source contract assumptions, Avro event schema]
  specs_produced: [market.dataset.fetched events]
  responsibilities: [provider ingestion, canonicalization, claim-check emission]
  external_dependencies: [EODHD API, MinIO, Kafka, Postgres]
  internal_dependencies: [shared libs]

worldview-market-data:
  type: microservice
  language: [python]
  entry_points: [services/market-data/src/market_data/main.py]
  specs_consumed: [market.dataset.fetched Avro schema]
  specs_produced: [instrument/materialization events]
  responsibilities: [materialization into timeseries DB + serving API]
  external_dependencies: [Timescale/Postgres, Kafka, MinIO, Valkey]
  internal_dependencies: [shared libs]

worldview-content-ingestion:
  type: microservice
  language: [python]
  entry_points: [services/content-ingestion/src/content_ingestion/api/main.py]
  specs_consumed: [source feed conventions]
  specs_produced: [content.article.raw.v1 events]
  responsibilities: [unstructured source polling]
  external_dependencies: [feeds/APIs, MinIO, Kafka, Postgres]
  internal_dependencies: [shared libs]

worldview-content-store:
  type: microservice
  language: [python]
  entry_points: [services/content-store/src/content_store/api/main.py]
  specs_consumed: [content.article.raw.v1]
  specs_produced: [content.article.stored.v1]
  responsibilities: [cleaning, dedup, canonical storage]
  external_dependencies: [Postgres, MinIO, Kafka]
  internal_dependencies: [shared libs]

worldview-nlp-pipeline:
  type: microservice
  language: [python]
  entry_points: [services/nlp-pipeline/src/nlp_pipeline/api/main.py]
  specs_consumed: [content.article.stored.v1]
  specs_produced: [nlp.article.enriched.v1, nlp.signal.detected.v1]
  responsibilities: [NLP extraction, enrichment, embeddings]
  external_dependencies: [ML models/providers, Postgres, Kafka]
  internal_dependencies: [shared libs, libs/ml-clients]

worldview-knowledge-graph:
  type: microservice
  language: [python]
  entry_points: [services/knowledge-graph/src/knowledge_graph/api/main.py]
  specs_consumed: [nlp.article.enriched.v1]
  specs_produced: [graph.state.changed.v1, intelligence.contradiction.v1]
  responsibilities: [graph materialization + reasoning]
  external_dependencies: [Postgres, Kafka]
  internal_dependencies: [shared libs]

worldview-rag-chat:
  type: microservice
  language: [python]
  entry_points: [services/rag-chat/src/rag_chat/api/main.py]
  specs_consumed: [gateway/request contracts, retrieval contracts]
  specs_produced: [chat API responses]
  responsibilities: [RAG orchestration/chat]
  external_dependencies: [LLM providers, vector/graph/sql backends]
  internal_dependencies: [shared libs]

worldview-api-gateway:
  type: microservice
  language: [python]
  entry_points: [services/api-gateway/src/api_gateway/main.py]
  specs_consumed: [downstream service API contracts]
  specs_produced: [frontend-facing REST contract]
  responsibilities: [composition and BFF logic]
  external_dependencies: [service APIs, Valkey]
  internal_dependencies: [shared libs]

worldview-alert:
  type: microservice
  language: [python]
  entry_points: [services/alert/src/alert/api/main.py]
  specs_consumed: [nlp.signal.detected.v1, graph.state.changed.v1, intelligence.contradiction.v1]
  specs_produced: [alert.delivered.v1]
  responsibilities: [alert fan-out and delivery]
  external_dependencies: [Kafka, Postgres, WebSocket clients]
  internal_dependencies: [shared libs]

worldview-frontend:
  type: app
  language: [typescript]
  entry_points: [apps/frontend/src/main.tsx]
  specs_consumed: [gateway REST contracts]
  specs_produced: [none]
  responsibilities: [UI]
  external_dependencies: [browser, gateway API]
  internal_dependencies: [frontend libs]

eodhd-api-skill:
  type: agent skill package
  language: [markdown, python]
  entry_points: [skills/eodhd-api/SKILL.md, skills/eodhd-api/scripts/eodhd_client.py]
  specs_consumed: [EODHD public API docs]
  specs_produced: [endpoint docs, workflow docs, plugin manifest]
  responsibilities: [agent guidance + endpoint reference + helper client]
  external_dependencies: [EODHD API]
  internal_dependencies: [none beyond stdlib for client]
```

## Spec-Driven Implementation Audit

### 2.1 Specification Quality Assessment

Worldview:
- Coverage & Completeness: 80%
  - Public APIs documented through FastAPI model-driven OpenAPI for implemented services
  - Avro contracts cover key Kafka event streams
  - Error/status modeling exists but is not consistently contract-tested across every service
  - Auth/rate-limit/SLA details are documented in high-level docs, not uniformly embedded into machine-validated API specs
- Clarity & Correctness: 82%
  - Machine-readable for Avro and OpenAPI generation path
  - Versioning strategy documented in RULES.md and AGENTS.md
  - Backward compatibility guidance exists, enforcement partial
- Tooling maturity: intermediate
  - Strong lint/type/test gates, schema syntax validation, architecture conformance checks
  - Weak automated parity checks between Python models and Avro/OpenAPI contracts

EODHD skills repo:
- Coverage & Completeness: 68%
  - Endpoint breadth is high (73 endpoint docs) but machine readability is low (markdown-only)
  - Error handling and plan limits documented by prose
- Clarity & Correctness: 70%
  - Docs are structured, but consistency appears manually maintained
- Tooling maturity: basic
  - No CI schema validation, no contract test generation, no drift automation

### 2.2 Agent/Plan/Task Architecture Alignment

Plan architecture maturity: structured (not formal)
- Plans exist as markdown templates/prompts and runbooks
- No machine-readable plan schema, grammar, or static validator
- Versioning uses file naming and VCS history rather than schema-controlled plan versions

Task architecture maturity: structured (not formal)
- Task objectives and steps are explicit in prompt docs
- Preconditions/postconditions are partly defined by conventions and checklists
- Retries/recovery are described in runbooks, but not formalized in executable task schemas

### 2.3 Code-to-Spec Fidelity Audit

| Artifact | Binding Method | Coverage | Validation | Drift Risk |
|---|---|---:|---|---|
| REST endpoint contract (worldview) | Generated (FastAPI + Pydantic) | 85% | Runtime + tests | Medium |
| Kafka event schema (Avro) | Manual files + conventions | 78% | CI schema parse + some contract tests | Medium |
| Python event/domain models | Manual typed models | 72% | mypy + runtime paths | Medium-High |
| Architecture invariants | Rule-based scripts/tests | 88% | CI continuous | Low-Medium |
| Agent plan/task definitions | Convention markdown | 55% | Manual review | High |
| EODHD endpoint specs | Markdown docs | 65% | Manual/live checks | High |

Drift detection level:
- worldview: automated (partial)
  - Present: CI schema parse, architecture tests, import guards
  - Missing: continuous model-to-schema parity checks for all services and bidirectional contract diffs
- eodhd skills: manual review
  - Lacks CI docs lint + API compatibility probes

### 2.4 Standards, Rules, and Enforcement

Coding and governance standards:
- Strongly documented in AGENTS.md, RULES.md, CLAUDE.md, service docs, ADRs
- Enforced by layered controls:
  - Layer 1 (pre-commit): Avro syntax/parse checks
  - Layer 2 (CI): lint/type/schema/structure/import/architecture/unit/integration/e2e
  - Layer 3 (merge gating): required checks through CI
  - Layer 4 (runtime): request validation is present, response/event compliance metrics are limited

Enforcement maturity:
- worldview: comprehensive
- eodhd skills: partial

### 2.5 Code Review Process

Review maturity: structured
- Strong evidence of standardized prompts, runbooks, and remediation guides
- Architecture standards explicit; ADR process defined
- Missing automated review aids for spec diffs and compatibility impact reports

### 2.6 Testing and Validation Pyramid

Spec test coverage estimate: 71%
- Unit/architecture: strong on structural invariants
- Contract tests: concentrated in selected services (portfolio strongest)
- Integration/E2E: present but not full service matrix

Test generation automation: partial
- No broad generation of contract tests from OpenAPI/Avro
- Property-based testing called out in architecture goals, not uniformly evidenced

## Critical Gaps and Anti-Patterns

### Highest-Risk Gaps

1. Uneven contract coverage
- Impact: High
- Effort: Medium
- Priority: P0
- Why: contract tests are not symmetric across all services producing/consuming events

2. Schema/model parity drift risk
- Impact: High
- Effort: Medium
- Priority: P1
- Why: dual schema locations and manual parity checks create divergence risk

3. Plan/task specs not machine-validated
- Impact: High
- Effort: Medium-High
- Priority: P1
- Why: orchestration logic is documented but not statically verifiable

4. Optional schema registry compatibility checks
- Impact: Medium-High
- Effort: Medium
- Priority: P1

5. EODHD docs not CI-validated against API behavior
- Impact: Medium
- Effort: Medium
- Priority: P2

### Anti-Patterns Identified

- Spec cargo-culting risk (low-medium): some specs are present but not always executable/validated end-to-end
- Dual maintenance (medium): model/schema/doc copies can drift
- Spec opacity in agent execution (high): markdown plans without formal grammar/schema
- Test decoupling (medium): architecture checks strong, contract checks uneven
- Silent failures risk (medium): schema parse passes can still hide semantic incompatibilities

## Tool Integration Analysis

### Tool Readiness

spec-kitty
- Current integration: none found
- Fit: high for spec linting + compatibility checks + generated checks in CI
- Recommended adoption: Scenario B (gradual)

OpenSpec
- Current integration: none found
- Fit: moderate-high for formal plan/task schemas and spec governance
- Migration effort: high due to existing markdown-driven workflows
- Recommended adoption: selective pilot first

Other tools
- AsyncAPI tooling: recommended if event architecture docs should become machine-readable
- OpenAPI generators/spectral: recommended for stronger REST governance and drift checks
- Buf/protobuf: not applicable today (no proto)

### Ranked Tool Priorities

1. Spectral + OpenAPI diff tooling (immediate CI value)
2. Avro compatibility checker against registry history (prevent breaking changes)
3. spec-kitty pilot for spec lint + drift control
4. AsyncAPI documentation generator for Kafka topic landscape
5. OpenSpec pilot for agent plan/task formalization

## Recommendations

### Quick Wins (Week 1-2)

1. Add mandatory contract tests for each event-producing service (P0)
2. Add schema parity check job between central and mirrored `.avsc` files (P0)
3. Add OpenAPI lint + breaking-change diff check in PR CI (P1)
4. Add spec review checklist template to PR process (P1)

### Medium-Term (Month 1-2)

1. Introduce generated contract test harness from Avro/OpenAPI (P1)
2. Formalize agent plan/task schema (YAML/JSON schema + validator) (P1)
3. Add schema registry compatibility gate (P1)
4. Add docs drift bot for eodhd endpoint references (P2)

### Long-Term (Quarter)

1. End-to-end contract testing framework across all services (P2)
2. Runtime compliance telemetry (request/response/event validation metrics) (P2)
3. Evaluate OpenSpec full migration after pilot and ROI review (P3)

## 30/60/90 Day Roadmap

30 days:
- Enforce minimum contract test presence per service
- Add OpenAPI lint/diff and Avro mirror parity checks
- Add review checklist and ownership model for spec updates

60 days:
- Introduce generated spec compliance tests
- Add schema registry compatibility checks to merge gate
- Implement first machine-readable plan/task schema pilot

90 days:
- Expand formal plan/task schemas to all agent workflows
- Add runtime spec compliance dashboards and SLOs
- Decide on spec-kitty broad adoption and OpenSpec migration scope

## Success Criteria Coverage

1. Current maturity: 3.6/5
2. Highest-risk gaps: uneven contract coverage, parity drift, non-formal plan/task specs
3. Implementation/spec compliance: about 74% overall across audited scope
4. Root causes: historical incremental growth, mixed manual/generated contracts, partial automation focus
5. Best tools: spectral/openapi-diff, avro-compat checks, spec-kitty pilot
6. Timing: phased 30/60/90 day roadmap
7. Stakeholders: platform lead, service owners, QA/contract testing owner, architecture reviewer
8. Effort: about 10-16 engineer-weeks across one quarter for comprehensive uplift

## Evidence Base (Key Files)

- worldview/docs/MASTER_PLAN.md
- worldview/docs/ai-interactions/BUG_PATTERNS.md
- worldview/RULES.md
- worldview/.github/workflows/ci.yml
- worldview/tests/architecture/
- worldview/scripts/gen-contracts.sh
- worldview/scripts/import_guards/
- worldview/scripts/structure_checks/
- eodhd-claude-skills/skills/eodhd-api/SKILL.md
- eodhd-claude-skills/.claude-plugin/marketplace.json
- eodhd-claude-skills/skills/eodhd-api/references/endpoints/

## Assumptions and Constraints

- Analysis-only: no production runtime verification performed
- CI evidence interpreted from repository state at audit time
- Coverage percentages are evidence-based estimates, not instrumented measurements
- Recommendations are designed to preserve current architecture and team velocity
