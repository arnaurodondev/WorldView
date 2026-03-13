# Documentation System Bootstrap Prompt (Worldview-Style)

## Role

You are a **Documentation Architect + Technical Writer + Architecture Analyst**. Your task is to design and implement a complete, production-grade documentation system for this repository, modeled after the structure and governance style used in Worldview.

You must produce:
- a coherent docs taxonomy
- high-quality foundational docs
- per-domain docs (services/libs/apps/workflows)
- architecture decision records (ADR)
- AI-execution governance docs (planning/prompts/responses registry)

Do not generate placeholder fluff. Every section must be grounded in repository evidence.

---

## Mission

Create a **single-source-of-truth documentation system** that enables:
1. fast onboarding,
2. architecture clarity,
3. implementation consistency,
4. auditable AI-assisted execution,
5. predictable change governance.

---

## Inputs (fill before execution)

- Project root path: `<PROJECT_ROOT>`
- Project name: `<PROJECT_NAME>`
- Primary languages/runtime: `<LANG_STACK>`
- Architecture style (if known): `<ARCH_STYLE>`
- Delivery model (monolith/microservices/modular): `<DELIVERY_MODEL>`
- Existing docs path (if any): `<EXISTING_DOCS_PATH_OR_NONE>`
- Critical domains/modules: `<DOMAIN_LIST>`
- Shared libraries/packages: `<LIB_LIST_OR_NONE>`
- Applications/UIs/clients: `<APP_LIST_OR_NONE>`
- Infrastructure components: `<INFRA_LIST>`
- Compliance/security constraints: `<CONSTRAINTS_OR_NONE>`

If any input is missing, infer from code and declare assumptions explicitly in output.

---

## Mandatory discovery phase (read before writing)

1. Scan repository tree (top-level + 2 nested levels minimum).
2. Read core governance files if present:
   - README
   - CONTRIBUTING
   - AGENTS/CLAUDE/RULES equivalents
   - CI files
   - package/dependency manifests
3. Detect architecture boundaries:
   - services/modules
   - shared libraries
   - integration points
   - data stores
   - event buses and APIs
4. Detect operational lifecycle:
   - local run
   - test strategy
   - build/release/deploy
5. Detect current documentation gaps:
   - missing owner docs
   - stale API/event/config docs
   - missing ADR process
   - no index or no canonical update policy

Output a short “Discovery Findings” section before generating files.

---

## Documentation architecture to create

Create this directory structure (adapt names only if project shape requires it):

docs/
- index.md
- MASTER_PLAN.md
- architecture/
  - diagrams.md
  - decisions/
    - ADR_TEMPLATE.md
    - 0001-initial-architecture.md
    - 0002-tooling-and-runtime.md
- services/ (or modules/ if non-service architecture)
  - <one-file-per-service-or-module>.md
- libs/ (or packages/)
  - <one-file-per-shared-lib>.md
- apps/ (if applicable)
  - <one-file-per-app>.md
- workflows/
  - local-dev.md
  - testing-strategy.md
  - ci-cd.md
  - release-process.md
- ai-interactions/
  - README.md
  - ORCHESTRATOR_RUNBOOK.md
  - INTERACTIONS_REGISTRY.md
  - agent-planning/
    - 0000-prompt-library-index-and-conventions.md
    - 0001-<initial-planning-prompt>.md
    - 0005-generic-implementation-plan-and-task-breakdown-template.md
  - agent-prompts/
    - 0000-execution-prompt-index-and-conventions.md
    - 0000-exec-wave-generation-template.md
  - agent-responses/
    - 0000-response-template.md
    - 0001-review-checklist.md
    - 0002-response-evidence-addon-template.md

If a folder is not applicable (for example no apps), still create the parent taxonomy and add clear N/A notes in index.

---

## Required content specification per document

### 1) docs/index.md (single entry point)
Must include tables for:
- architecture docs
- service/module docs
- app docs
- shared library/package docs
- workflows
- governance files
- migration docs (if applicable)
- AI interactions docs

### 2) docs/MASTER_PLAN.md (system source of truth)
Must include:
- version/date/status/owner metadata
- product scope and user journeys
- non-functional goals with measurable targets
- system architecture principles
- component diagram (Mermaid)
- service/module catalog with ownership and interfaces
- data lifecycle (ingest/process/serve) with diagrams
- storage design (DB/object/cache/vector/graph if used)
- contracts section (API/event/schema standards)
- security model
- observability model
- developer workflow alignment
- phased roadmap

### 3) docs/architecture/diagrams.md
Must include at least:
- component diagram
- one sequence diagram for critical runtime path
- one dataflow diagram
Use Mermaid only.

### 4) docs/architecture/decisions/ADR_TEMPLATE.md
Use sections:
- context
- decision
- consequences (positive/negative/neutral)
- alternatives considered
- references

### 5) ADR starter docs (0001, 0002)
Create accepted initial ADRs based on discovered architecture and tooling decisions.

### 6) Per-service/module docs
Each file must include:
- mission and boundaries (owns / never does)
- API surface or public interface table
- event/topic consumption and production (if any)
- data model/schema summary
- runtime processes/background jobs
- core workflow sequence diagram
- caching strategy (if any)
- testing plan with concrete commands
- local run commands
- known pitfalls

### 7) Per-library/package docs
Each file must include:
- package purpose and scope
- public API table (classes/functions/protocols)
- usage examples
- integration guidance for consuming modules
- common pitfalls
- testing strategy and contract compatibility notes

### 8) App docs
Each app file must include:
- mission and boundaries
- folder architecture snapshot
- routing/navigation map (if UI)
- data-fetch/integration strategy
- local development commands
- testing strategy
- deployment notes

### 9) Workflow docs
- local-dev.md: bootstrap, dependencies, environment setup, start commands
- testing-strategy.md: pyramid, markers/suites, coverage targets, CI gating policy
- ci-cd.md: pipelines, checks, artifacts, release gates
- release-process.md: versioning, changelog policy, rollback strategy

### 10) AI interactions governance
Must define:
- planning -> response -> execution prompt flow
- naming conventions for artifacts
- orchestrator/worker model
- evidence requirements (tests/docs/changed files)
- registry process and status taxonomy
- review checklist expectations

---

## Writing quality rules (mandatory)

1. No invented endpoints/events/configs; only document what exists or mark as proposed.
2. Distinguish clearly:
   - current state
   - planned state
   - open questions
3. Every command must be executable in project context.
4. Every architecture claim must map to concrete paths/files.
5. Use concise but complete technical prose.
6. Include explicit “Common Pitfalls” section in every service/lib doc.
7. For any flow with >=3 components or >=4 steps, include a Mermaid diagram.
8. Document update obligations when behavior/API/event/config/schema/tests change.
9. Prefer tables for discoverability (API, events, ownership, test commands).
10. Avoid orphan docs: if a file describes non-existing code, mark clearly as planned.

---

## Consistency and governance rules (mandatory)

Enforce these in generated content:
- documentation is updated in the same change that modifies behavior/contracts/config/schema/API/tests
- AI execution artifacts must include exact changed files, tests run, docs changed
- response artifacts must be reviewable against a checklist
- ADR required for cross-cutting architectural changes

---

## Output requirements

1. Create/overwrite required documentation files in repository.
2. At the end, provide a summary report with:
   - files created
   - files updated
   - assumptions made
   - unresolved gaps
   - recommended next 5 documentation tasks
3. Provide a “Coverage Matrix” table:
   - area (architecture/service/lib/app/workflow/ai-governance)
   - status (complete/partial/missing)
   - file path
   - notes

---

## Acceptance checklist (must pass)

- docs/index.md exists and links all major docs
- docs/MASTER_PLAN.md exists and covers architecture + lifecycle + roadmap
- ADR template + at least 2 ADRs exist
- every service/module has a dedicated doc
- every shared library/package has a dedicated doc
- workflows docs exist and include runnable commands
- ai-interactions governance docs and templates exist
- at least 3 Mermaid diagrams across architecture/service docs
- no broken internal relative links
- no undocumented critical subsystem discovered in code scan

If any item cannot be completed, explicitly report blocker and proposed fallback.

---

## Execution style

- Work in small coherent batches.
- After each batch, self-validate links and section completeness.
- Keep naming conventions stable and predictable.
- Prioritize factual correctness over broad but vague coverage.

Begin now with: **Discovery Findings**, then implement the full documentation system.
