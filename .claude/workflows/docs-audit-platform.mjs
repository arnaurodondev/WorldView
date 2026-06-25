export const meta = {
  name: 'docs-audit-platform',
  description: 'Run the docs-audit methodology per component (services, libs, app, root docs) to update + clean the entire platform documentation against the current code',
  phases: [
    { title: 'Components', detail: 'per-service + per-lib + app docs-audit, parallel, each updates only its own docs' },
    { title: 'Root', detail: 'README, AGENTS.md, MASTER_PLAN, PRODUCT_CONTEXT rewritten against current state' },
    { title: 'Consistency', detail: 'cross-doc consistency sweep (counts/ports/topics) + synthesis report' },
  ],
}

const WT = '/Users/arnaurodon/Projects/University/final_thesis/worldview-wt-md-reliability'

const SERVICES = ['alert', 'api-gateway', 'content-ingestion', 'content-store', 'intelligence-migrations', 'knowledge-graph', 'market-data', 'market-ingestion', 'nlp-pipeline', 'portfolio', 'rag-chat']
const LIBS = ['common', 'contracts', 'messaging', 'ml-clients', 'observability', 'prompts', 'storage', 'tools']

const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    unit: { type: 'string' },
    docs_updated: { type: 'array', items: { type: 'string' } },
    drift_fixed: { type: 'array', items: { type: 'string' }, description: 'doc-vs-code drift corrected (endpoints/topics/entities/config that were wrong/missing/stale)' },
    stale_removed: { type: 'array', items: { type: 'string' }, description: 'stale/obsolete content removed' },
    health: { type: 'string', description: 'state of the docs BEFORE this audit: accurate | minor-drift | major-drift | was-missing' },
    remaining_for_user: { type: 'array', items: { type: 'string' }, description: 'items needing a human decision (not auto-fixed)' },
  },
  required: ['unit', 'docs_updated', 'drift_fixed', 'health'],
}

const ACT = 'Apply fixes DIRECTLY with Edit/Write (this audit ACTS, it does not just report). Verify every claim against the actual code — never guess. Keep the existing doc structure/headings. Do NOT edit shared cross-cutting docs (docs/BUG_PATTERNS.md, docs/STANDARDS.md, docs/MASTER_PLAN.md, RULES.md, AGENTS.md, README.md) — a later phase owns those; only touch THIS unit\'s docs. DO NOT git commit.'

function servicePrompt(s) {
  const docName = s === 'alert' ? 'alert-service' : s
  return `Run the docs-audit methodology SCOPED to the **${s}** service. Work in ${WT}. Update ONLY: docs/services/${docName}.md and services/${s}/.claude-context.md.

${ACT}

STEPS:
1. Read the service's CURRENT code to establish the real surface:
   - API endpoints: services/${s}/src/*/api/ (routers — every route path + method).
   - Kafka topics produced AND consumed: services/${s}/src/*/infrastructure/messaging/ (publishers, consumers, *_consumer_main.py).
   - Domain entities + events: services/${s}/src/*/domain/.
   - Config/env vars: services/${s}/src/*/config* + services/${s}/configs/docker.env.example.
   - DB tables/migrations: services/${s}/alembic/versions/ (latest head, key tables).
   - Use cases / ports: services/${s}/src/*/application/.
2. Read the existing docs/services/${docName}.md + services/${s}/.claude-context.md.
3. Find DRIFT: documented endpoints/topics/entities/config/pitfalls that no longer match the code; current code surface missing from the docs; wrong counts, ports, DB names, topic names; stale "next steps"/TODOs that are done.
4. UPDATE the docs to accurately reflect the CURRENT code — add what is missing, correct what is wrong, delete what is stale/obsolete. Preserve useful pitfalls + the .claude-context.md structure (entities, topics, pitfalls, test commands). Make .claude-context.md a sharp, current agent quick-reference.
5. Spot-check that the doc references real files/symbols.
Return the structured summary (unit="${s}").`
}

function libPrompt(l) {
  return `Run the docs-audit methodology SCOPED to the **${l}** shared library. Work in ${WT}. Update ONLY: docs/libs/${l}.md.

${ACT}

STEPS:
1. Read the library's CURRENT public API: libs/${l}/src/ (public modules, classes, functions, their signatures/types) + libs/${l}/pyproject.toml (name, deps).
2. Read docs/libs/${l}.md.
3. Find DRIFT: documented public API that changed/was removed; new public API missing from docs; wrong usage examples; stale notes.
4. UPDATE docs/libs/${l}.md to accurately document the current public API with types + at least one correct usage example per major capability. Remove stale content.
Return the structured summary (unit="${l}").`
}

function appPrompt() {
  return `Run the docs-audit methodology SCOPED to the **worldview-web** frontend app. Work in ${WT}. Update ONLY: docs/apps/worldview-web.md.

${ACT}

STEPS:
1. Read the CURRENT app: apps/worldview-web/app/ (routes), apps/worldview-web/package.json (stack/deps/scripts), apps/worldview-web/lib/api/ (the S9 endpoints it consumes), key features/ + components/. Note the real routes, stack versions, testing setup, how it talks to S9.
2. Read docs/apps/worldview-web.md.
3. Find + fix DRIFT: wrong routes, stale stack versions, removed/added features, wrong S9 endpoint list, outdated testing/Docker notes.
4. UPDATE the doc to reflect the current app accurately.
Return the structured summary (unit="worldview-web").`
}

phase('Components')
const componentTasks = [
  ...SERVICES.map((s) => () => agent(servicePrompt(s), { label: `svc:${s}`, phase: 'Components', schema: SCHEMA })),
  ...LIBS.map((l) => () => agent(libPrompt(l), { label: `lib:${l}`, phase: 'Components', schema: SCHEMA })),
  () => agent(appPrompt(), { label: 'app:worldview-web', phase: 'Components', schema: SCHEMA }),
]
const components = (await parallel(componentTasks)).filter(Boolean)
log(`Components audited: ${components.length}/${componentTasks.length}`)

phase('Root')
const ROOT = [
  {
    label: 'root:README',
    file: 'README.md',
    extra: 'README.md is TOTALLY OUTDATED (last touched 5+ weeks ago). REWRITE it to reflect the current platform: what worldview is (thesis-grade market-intelligence platform), the architecture (11 services S1-S10 + intelligence-migrations, 8 shared libs, Next.js 15 frontend talking only to S9, Docker Compose infra, the Postgres OLTP/OLAP split), accurate quick-start (make dev / make seed / make fetch-secrets), the service + lib inventory (cross-check against docs/services/ + docs/libs/ which were just refreshed this run), ports, and where to read more. Make it the accurate front door.',
  },
  {
    label: 'root:AGENTS',
    file: 'AGENTS.md',
    extra: 'Audit AGENTS.md (coding standards, architecture patterns, shared libraries) against the current code. Fix the shared-lib list (8 libs: common, contracts, messaging, ml-clients, observability, prompts, storage, tools), the service count/list, and any stale architecture/pattern guidance. Keep it a sharp standards reference.',
  },
  {
    label: 'root:MASTER_PLAN',
    file: 'docs/MASTER_PLAN.md',
    extra: 'Audit docs/MASTER_PLAN.md (full system architecture) against the current state: service inventory + responsibilities, the data stores (OLTP postgres + OLAP postgres-intelligence split holding intelligence_db/nlp_db/kg_db, plus Kafka/Valkey/MinIO), the event/topic map, and the request/data flows. Fix drift; remove superseded plans.',
  },
  {
    label: 'root:PRODUCT_CONTEXT',
    file: 'docs/PRODUCT_CONTEXT.md',
    extra: 'Audit docs/PRODUCT_CONTEXT.md (product vision, users, journeys, constraints) for staleness vs the current feature set (frontend surfaces: dashboard, screener, instrument detail, portfolio, watchlists, alerts incl. the 5-type AlertWizard, chat, news, KG/intelligence). Light touch — only fix what is clearly stale/contradicted.',
  },
]
const root = (await parallel(ROOT.map((r) => () => agent(
  `Run the docs-audit methodology for **${r.file}**. Work in ${WT}. Update ONLY ${r.file}. Apply fixes DIRECTLY (Write/Edit); verify every claim against the current code + the just-refreshed docs/services/*.md + docs/libs/*.md. ${r.extra} DO NOT git commit. Return the structured summary (unit="${r.file}").`,
  { label: r.label, phase: 'Root', schema: SCHEMA },
)))).filter(Boolean)
log(`Root docs audited: ${root.length}/${ROOT.length}`)

phase('Consistency')
const all = [...components, ...root]
const consistencyReport = await agent(
  `Final cross-document CONSISTENCY sweep + synthesis after a full per-component docs-audit. Work in ${WT}.

A fan-out of agents just updated every service doc (docs/services/*.md + each services/*/.claude-context.md), every lib doc (docs/libs/*.md), the frontend doc, and the root docs (README.md, AGENTS.md, docs/MASTER_PLAN.md, docs/PRODUCT_CONTEXT.md). Their per-unit summaries (JSON): ${JSON.stringify(all).slice(0, 12000)}

YOUR JOB (apply fixes directly; do NOT commit):
1. CROSS-DOC CONSISTENCY — verify these facts agree across ALL docs + the code, fix any that do not:
   - service count/list (11: 10 services S1-S10 + intelligence-migrations), lib count/list (8).
   - port numbers (cross-check docs vs infra/compose/docker-compose.yml).
   - DB names + the Postgres OLTP/OLAP split (postgres vs postgres-intelligence holding intelligence_db/nlp_db/kg_db).
   - Kafka topic names (docs vs infra/kafka schemas vs service code).
2. Fix any remaining broken internal doc links / wrong file references you find in the touched docs.
3. WRITE a synthesis audit report to docs/audits/2026-06-25-docs-audit-platform.md: per-component health table (from the summaries), total drift items fixed, cross-doc inconsistencies fixed, and a short "remaining for user decision" list aggregated from the per-unit summaries.
Return a concise text summary: components audited, total drift fixed, consistency issues fixed, and the top remaining-for-user items.`,
  { label: 'consistency+report', phase: 'Consistency' },
)

log(`Docs audit complete: ${components.length} components + ${root.length} root docs updated.`)
log(`Consistency + report: ${consistencyReport}`)
