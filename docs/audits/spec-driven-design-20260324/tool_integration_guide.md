# Tool Integration Guide for Spec-Driven Design

Date: 2026-03-24
Scope: worldview + eodhd-claude-skills

## Objective

Select and integrate tooling that improves:
- Spec linting and validity
- Spec/code drift detection
- Contract test automation
- Plan/task formalization for agent workflows

## Current Baseline

worldview currently has strong CI quality gates but partial spec fidelity automation:
- Strong: Avro syntax checks, architecture tests, import guards, service structure checks
- Partial: contract test coverage, schema parity and compatibility automation
- Missing: formal plan/task schema validation, comprehensive spec diff tooling

eodhd-claude-skills is documentation-rich but automation-light:
- Strong: endpoint and guide coverage
- Missing: CI validation against live API behavior, machine-validated spec artifacts

## Tool Evaluation Matrix

| Tool | Primary Use | Fit for worldview | Fit for eodhd | Effort | Risk | Recommendation |
|---|---|---|---|---|---|---|
| spectral (OpenAPI lint) | Lint style/rules for OpenAPI | High | Medium | Low | Low | Adopt immediately |
| openapi-diff | Breaking-change detection | High | Medium | Low-Med | Low | Adopt immediately |
| spec-kitty | Unified spec lint/validate/generation | Medium-High | Medium | Med | Med | Pilot in one domain |
| AsyncAPI tooling | Event contract docs and validation | Medium | Low | Med | Med | Pilot for Kafka map |
| Schema Registry compatibility checks | Avro compatibility gating | High | N/A | Med | Low | Adopt in CI |
| OpenSpec | Formal specification framework | Medium | Medium | High | Med-High | Evaluate via pilot |
| Buf/protobuf tooling | Protobuf governance | Low (not in use) | Low | High | N/A | Not recommended now |

## Tool-by-Tool Integration Recommendations

### 1) spectral + openapi-diff

why_needed: worldview REST contracts are generated and tested, but breaking changes are not consistently surfaced as explicit PR blockers.

integration_points:
- CI/CD stage: pull_request checks for OpenAPI lint + diff against base branch
- Local development: pre-commit or make target for quick checks
- IDE: optional spectral ruleset integration
- Runtime: none

effort_estimate: 3-5 days
risk_level: low

success_metrics:
- Spec lint pass rate >= 95%
- Breaking API change detection pre-merge >= 99%
- Reduction in downstream contract regressions

### 2) Avro compatibility gate (Schema Registry aware)

why_needed: current validation confirms Avro parseability, not compatibility against historical versions.

integration_points:
- CI/CD stage: compatibility check job against previous schema versions
- Local development: make target to run compatibility locally
- IDE: none required
- Runtime: optional consumer telemetry for incompatible payload reject rates

effort_estimate: 1-2 weeks
risk_level: low

success_metrics:
- Zero incompatible schema merges to main
- Compatibility check pass rate >= 95%
- Mean time to detect contract breaking change < 1 PR cycle

### 3) spec-kitty pilot

why_needed: unify linting, generation, and compliance checks for mixed spec types and reduce custom script burden.

integration_points:
- CI/CD stage: pilot on one service contract domain
- Local development: CLI for lint/generation
- IDE: plugin support where available
- Runtime: optional report export

effort_estimate: 2-4 weeks (pilot)
risk_level: medium

success_metrics:
- Generated code/test coverage >= 70% in pilot domain
- Drift incidents reduced by >= 50% in pilot domain
- Developer time to add a new contract reduced by >= 30%

### 4) OpenSpec pilot for plan/task definitions

why_needed: plan/task orchestration is currently markdown-driven and difficult to statically validate.

integration_points:
- CI/CD stage: validate plan/task artifacts against schema
- Local development: authoring templates + schema validation CLI
- IDE: JSON/YAML schema hints
- Runtime: orchestrator can reject invalid plans before execution

effort_estimate: 4-8 weeks (pilot + migration prep)
risk_level: medium-high

success_metrics:
- Plan validation pass rate >= 95%
- Invalid plan detection before execution >= 99%
- Retry/recovery behavior consistency improvement (incident rate reduction)

## Integration Scenarios

### Scenario A: Minimal Change (Internal Evolution)

Approach:
- Keep existing formats
- Add: OpenAPI lint/diff, Avro compatibility checks, schema parity checks, spec review checklists

Effort: 2-3 weeks
Risk: low
Expected outcome: large reliability gain with minimal workflow disruption

Best for: immediate hardening without major migration cost

### Scenario B: Gradual Adoption (spec-kitty)

Approach:
- Phase 1: linting and validation on selected contracts
- Phase 2: code/test generation in one service family
- Phase 3: broader contract testing integration

Effort: 4-6 weeks
Risk: medium
Expected outcome: higher automation and lower drift, moderate change management

Best for: teams ready for incremental tooling modernization

### Scenario C: Full Migration (OpenSpec-centric)

Approach:
- Formalize REST/event/plan/task specs under unified framework
- Migrate existing markdown plan/task definitions and contract policies
- Build new validation and generation pipeline

Effort: 8-12 weeks
Risk: medium-high
Expected outcome: strongest long-term formalism and auditable orchestration

Best for: long-horizon platform governance investment

## Recommended Path

Recommended sequence:
1. Execute Scenario A now (fast risk reduction)
2. Run a bounded spec-kitty pilot (Scenario B) in one service/event domain
3. Decide on OpenSpec adoption using an ADR after measured pilot outcomes

Decision gate criteria:
- If pilot reduces drift and effort materially, continue Scenario B rollout
- If plan/task failures remain costly, prioritize OpenSpec pilot for orchestration schemas
- If team bandwidth is constrained, remain on Scenario A plus targeted automation

## Team and Ownership Model

Core roles:
- Tech lead: governance and acceptance criteria
- Platform/DevOps engineer: CI integration and gating
- Service owners: contract test expansion and rule tuning
- QA/contract engineer: test generation and compliance reporting
- Architecture lead: framework selection ADR

RACI shorthand:
- Responsible: service owners + platform
- Accountable: tech lead
- Consulted: architecture lead + QA
- Informed: frontend and product stakeholders
