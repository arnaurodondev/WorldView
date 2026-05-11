# PLAN-0051 — Strict QA Iteration 1

**Date**: 2026-04-29
**Auditor**: Claude (strict gate, read-only)
**Scope**: Waves A–F (Portfolio realized P&L + filters, Screener activation, Workspace persistence + symbol linking, Alerts ack/snooze/history/rule-mgr, Chat slash + markdown + rename, Portfolio polish)
**Verdict**: **CRITICAL_BLOCK** — three production-breaking bugs in the alert + chat surfaces that would each cause hard, user-visible failure on day-one.
**Findings count**: BLOCKING 0 | CRITICAL 3 | MAJOR 5 | MINOR 4 | NIT 3

---

## Phase 1 — Static analysis

### Frontend (`apps/worldview-web`)

| Check | Result |
|---|---|
| `pnpm typecheck` (`tsc --noEmit`) | PASS — clean |
| `pnpm lint` (`next lint`) | PASS — `No ESLint warnings or errors` (Next.js 16 deprecation note ignored) |
| `pnpm test --run` | **PASS — 807 / 807** in 74 files |
| `pnpm audit --audit-level=low` | 2 moderate (postcss <8.5.10 XSS via `</style>`). Transitive through `next > postcss`; cannot be patched without a Next.js bump. **MINOR**. |

Test stderr noise (non-blocking, but recorded):
- `__tests__/rule-manager-dialog.test.tsx` × 3 — *Missing `Description` or `aria-describedby={undefined}` for {DialogContent}*. Real a11y bug in `RuleManagerDialog.tsx` (no `<DialogDescription>` rendered).
- `__tests__/context-aware-starters.test.tsx` × 2 — *Query data cannot be undefined*. Symptom of the test passing a string `"AAPL"` to a code path that expects a UUID; the LLM-fetch mock returns undefined and TanStack warns. Both green.

### Backend (services)

| Service | Unit tests | Ruff |
|---|---|---|
| alert | **PASS** (count omitted in initial output, all green) | clean |
| portfolio | **PASS — 643 / 643** | clean |
| rag-chat | **PASS — 468 / 468** | clean |
| api-gateway | **PASS — 68 / 68** | clean |

Net: **all static gates green; the bugs below are missed by the in-tree test suites because the tests themselves under-specify the contract.**

---

## Phase 2 — Live containers

`docker ps` shows the full stack healthy. `make dev`–style infra was already running. Used `POST /v1/auth/dev-login` to mint a JWT and probed each new endpoint directly through S9 on `localhost:8000`. No restart required.

---

## Phase 3 — Endpoint probes

| Endpoint | Probe | Result |
|---|---|---|
| `GET /v1/portfolios/{id}/realized-pnl` | Unknown portfolio_id | 404 `PORTFOLIO_NOT_FOUND` (correct) |
| `PATCH /v1/alerts/{id}/snooze` w/ `{"snooze_until": "..."}` (frontend shape) | | **422** `Field required: until` — confirms **C-1** below |
| `PATCH /v1/alerts/{id}/snooze` w/ `{"until": "..."}` (schema shape) | Unknown alert | 404 (correct) |
| `GET /v1/alerts/history?severity=HIGH` (frontend uppercase) | | **422** `Invalid severity: must be low|medium|high|critical` — confirms **C-2** |
| `GET /v1/alerts/history?severity=high` | | 200 `{alerts:[], total:0, has_more:false}` (correct) |
| `GET /v1/alerts/history?limit=10` | | `total: 0`, `has_more: false` — NOTE backend `total` is ALWAYS the page-row count (never the universe), confirms **C-3** |
| `PATCH /v1/threads/{id}` w/ `{"title":"renamed"}` | Unknown thread | 404 (correct) |
| `PATCH /v1/threads/{id}` w/ `{}` (empty body) | Unknown thread | 404 (correct) — but on a real owned thread this would write `title=NULL` (M-1) |

---

## Phase 4 — UX / design findings

Detailed in the consolidated table below. Highlights:

- **TransactionsTable** virtualised path (`>200` rows): static `<table>` is rendered with the header row but an empty `<tbody/>`, then a separate `react-window` list of mini-`<table>`s sits below. Each mini-table sets `table-fixed` but the parent has an **empty `<colgroup>`**, so column widths are NOT inherited and rows visually misalign with the header. (M-2)
- **Chat starter substitution** uses the URL `?entity_id=<UUID>` value verbatim as the displayed "ticker", producing strings like *"What's the latest news on 2c8e3a7f-…"*. The Vitest case sneaks past this by passing `entity_id=AAPL` — a non-UUID — so the test green-lights the bug. (M-3)
- **CitationBar** with 50 citations: each segment is `flex-1` so width collapses to ~1px; no min-width or wrap fallback. Real conversations frequently exceed 10–20 citations after deep RAG. (MIN-1)
- **RuleManagerDialog** missing `<DialogDescription>` → screen-reader announcement is incomplete (NIT, but flagged by tests already).

---

## Phase 5 — Edge cases

| Scenario | Verdict |
|---|---|
| Realized-PnL FIFO short sale (SELL with no open lot) | **OK** — `_apply_transaction` logs `realized_pnl_short_sale_skipped` and drops the chunk. Test exists. |
| Realized-PnL empty portfolio | **OK** — returns `Decimal(0)` totals, empty breakdown. |
| Workspace v1 → v2 migration with a panel_type that no longer exists | **PARTIAL** — `migrateV1` does not prune unknown types. They survive into v2 and render as `null` (the panel container's `default:` branch). Visual: empty placeholder where the panel should be. No crash. (MIN-2) |
| Snooze boundary `now + 30 days` | OK — `target > now + timedelta(days=30)` rejects only strictly past 30 days. Boundary just before fires `target > now+30d` False → accepted. Test exists. |
| Snooze body field name | **BROKEN** — frontend `snoozeAlert` sends `snooze_until`, backend Pydantic expects `until`. Reproduced live (422). **C-1**. |
| Alert history severity case | **BROKEN** — frontend `AlertSeverity = "LOW" \| "MEDIUM" \| ...` (uppercase) sent as-is; backend enum is lowercase. Reproduced live (422). **C-2**. |
| Alert history `Load More` pagination | **BROKEN** — backend `total = len(alerts)` (page only, per `AlertHistoryResponse` schema comment), frontend computes `hasMore = rows.length < total` (always False), `has_more` flag from server is never read by the frontend (omitted from `AlertsResponse` type). The Load More button never appears. **C-3**. |
| Slash command `/quote ` (trailing space, no ticker) | OK — returns null → falls through to LLM. |
| Slash command `/quote 0` (numeric) | OK structurally — passes to card; gateway will likely 404. NIT. |
| Slash command `/news SECTOR=` (empty value) | OK — `if (key && val)` filter drops empty value; renders empty `params`. |
| Workspace share URL near 4096 chars | OK — `oversize` banner blocks copy. |
| Decoding malformed base64 | OK — `decodeWorkspace` returns null. |
| Column customization stored unknown key | OK — `loadColumnPrefs` walks stored entries with `defaultsByKey.get(...)` and `continue`s on misses. |
| AlertHistoryTab tenant isolation (SQL) | OK — `WHERE tenant_id = :tenant_id` is the first predicate; later predicates compose with `AND`. No injection vector via filters. |
| Acknowledge / snooze on a NULL-tenant alert | **WEAK** — both use cases explicitly allow modification when `alert.tenant_id is None` ("treat as no isolation check"). Comment in `test_alert_with_null_tenant_does_not_block_ack`. Tenant isolation bypass for legacy rows. Cannot enumerate via list (history filters to current tenant), so exploitable only with knowledge of `alert_id`. **MAJ-1**. |
| Acknowledge fallback on 404 | The frontend `useAlertActions` treats *any* 404 from the backend (alert missing OR tenant mismatch OR endpoint absent) as "endpoint not deployed" and silently writes localStorage with `localOnly: true`. The user sees a successful local ACK on someone else's alert. **MAJ-2**. |
| `PATCH /v1/threads/{id}` with `{}` (no `title`) | Frontend would set `title=null` because `UpdateThreadRequest.title` defaults to `None` and `update_title` writes `.values(title=title)` unconditionally. A genuinely empty PATCH wipes the title. **MAJ-3**. |

---

## Phase 6 — Optimisation opportunities

- `useRealizedPnL` `staleTime: 60_000` is sane.
- `useAlertHistory` `staleTime: 30_000` is sane.
- TransactionsTable `useMemo`s ticker options correctly; the per-row `useMemo` skip on totals is documented and correct.
- New deps weight check (rough): `papaparse` ~50KB, `jspdf` + `jspdf-autotable` ~600KB, `write-excel-file` ~120KB, `react-window` ~30KB, `lightweight-charts` ~250KB. None lazy-imported. The screener export menu loads jspdf even for users that only need CSV. **MIN-3**: code-split the export adapters (`import("xlsx-export").then(...)` per format) — each is only used after a click.
- `realized-pnl` instrument lookup (`for iid: await uow.instruments.get(iid)`) is N×1 — for portfolios with >100 distinct instruments contributing in the window this becomes a query storm. Consider a `instruments.list_by_ids` batch fetch. **MIN-4**.

---

## Findings (consolidated, ordered by severity)

| ID | Sev | File:Line | Problem | Fix |
|----|-----|-----------|---------|-----|
| C-1 | CRITICAL | `apps/worldview-web/lib/gateway.ts:1721` | Frontend POSTs `{snooze_until: ...}` but backend Pydantic schema `SnoozeAlertRequest` (`services/alert/src/alert/api/schemas.py:134`) declares `until: datetime`. Live probe returns 422 every time. The Snooze feature is **non-functional in production**. | Send `{until: until.toISOString()}` OR alias the backend field with `Field(..., alias="snooze_until")` and set `populate_by_name=True`. Add a contract test that pins the wire format. |
| C-2 | CRITICAL | `apps/worldview-web/types/api.ts:869` (and `AlertHistoryTab.tsx:92`) | Frontend `AlertSeverity` enum is uppercase (`"LOW"` / `"MEDIUM"` / `"HIGH"` / `"CRITICAL"`) and sent verbatim as the `severity=` query param. Backend `AlertSeverity` StrEnum values are lowercase. `GET /v1/alerts/history?severity=HIGH` → 422. Severity filter on the History tab is **non-functional**. | Lowercase before sending (`p.severity = severity.toLowerCase()`) OR change the type to lowercase strings and toUpperCase only for display. Existing tests mock uppercase too — strengthen them to assert the wire value is lowercase. |
| C-3 | CRITICAL | `services/alert/src/alert/api/schemas.py:161` ↔ `apps/worldview-web/components/alerts/AlertHistoryTab.tsx:104` ↔ `apps/worldview-web/types/api.ts:910` | Backend response `AlertHistoryResponse.total` is documented as "count of items in this page" (= `len(alerts)`); a separate `has_more` flag carries the universe signal. Frontend type `AlertsResponse` omits `has_more` and the History tab computes `hasMore = rows.length < total`, which is **always False**. Result: the **"Load More" button never renders**, so all paginated histories are stuck at the first 50 rows. | Pick one: (a) change backend `total` to a `SELECT count(*)` over the filtered set and drop `has_more`, OR (b) add `has_more: boolean` to the frontend `AlertsResponse` type and read it in `AlertHistoryTab`. Option (b) is the smaller diff but keeps the "page count" semantic mismatch. Option (a) is canonical pagination. Add an integration test that exercises the page-2 path. |
| MAJ-1 | MAJOR | `services/alert/src/alert/application/use_cases/acknowledge_alert.py:65`, `snooze_alert.py:73` | Both use cases explicitly skip the tenant check when `alert.tenant_id is None` ("legacy alert"). Any tenant that knows the alert_id can mutate it. The accompanying unit test (`test_alert_with_null_tenant_does_not_block_ack`) deliberately pins this behaviour, locking in the tenant-isolation bypass. | Treat NULL `tenant_id` as forbidden for mutations (`return "forbidden"`). Backfill the column in a separate migration if any production rows still have NULL. The list-history endpoint already excludes them, so this fix is the symmetric counterpart. |
| MAJ-2 | MAJOR | `apps/worldview-web/hooks/useAlertActions.ts:74-77` | The 404 fallback conflates "endpoint not deployed" with "alert not found / forbidden" — both come back as 404 because the route layer collapses 403→404 on purpose (anti-enumeration). The user sees a successful local ACK on a non-existent or other-tenant alert. | Send a sentinel header from S9 (e.g. `X-Worldview-Endpoint: alerts-ack@v1`) and treat its absence as the "not deployed" signal, OR check the response `WWW-Authenticate` / OpenAPI on startup. Minimal fix: drop the fallback now that S10 ships the endpoint, and surface 404 as a real error. |
| MAJ-3 | MAJOR | `services/rag-chat/src/rag_chat/api/schemas.py:27` ↔ `infrastructure/db/repositories/thread_repository.py:214` | `UpdateThreadRequest.title` defaults to `None`. Repo's `update_title` writes `.values(title=title)` unconditionally — `PATCH /v1/threads/{id}` with `{}` clears the persisted title to NULL. The schema docstring even calls this a "no-op" path. | In the repo, skip the UPDATE when `title is None` (or build the values dict dynamically). Or in the use case, short-circuit and return the unchanged thread. Add a test for the empty-body PATCH. |
| MAJ-4 | MAJOR | `apps/worldview-web/components/portfolio/TransactionsTable.tsx:660-690` | Virtualised table render path: when `filtered.length > 200`, the static `<table>` renders with `<tbody />` empty (no rows), and rows live in a sibling `react-window` `FixedSizeList` that renders one mini-`<table className="table-fixed">` per row. The mini-table's `<colgroup>` is empty, so column widths come from content rather than the header table → **rows visually misalign with the header**, especially the right-aligned numeric columns (Qty / Price / Total / Fee). | Either define explicit `<col style={{width: ...}}/>` widths in both the header table and each row mini-table, or switch to a CSS-grid row that mirrors the grid template of the header. Add a Vitest case that asserts column widths match between header and a sample row when `transactions.length > 200`. |
| MAJ-5 | MAJOR | `apps/worldview-web/app/(app)/chat/page.tsx:531-532` | `entityIdFromUrl = searchParams.get("entity_id")` is a UUID; the code assigns it to `entityTicker` and interpolates it into starter strings. The `?entity_id=<uuid>` flow produces displayed text like *"What's the latest news on 0190abcd-…?"*. Test `context-aware-starters.test.tsx` masks the bug by passing `entity_id=AAPL`. | Resolve UUID → ticker via `gateway.searchEntity(entityId)` (already exists for other surfaces) before substituting; gate `entityStarters(...)` on a successful resolve and fall back to generic starters otherwise. Strengthen the test to use a real UUID. |
| MIN-1 | MINOR | `apps/worldview-web/components/chat/CitationBar.tsx:97` | `gap-px flex` with `flex-1` segments — at >25 citations each segment becomes <2px wide; visual cluster becomes a noisy rainbow bar with no scannable structure. | Add `min-w-[8px]` per segment and `flex-wrap` (or cap visible segments at e.g. 30 with a "+N more" overflow). |
| MIN-2 | MINOR | `apps/worldview-web/contexts/WorkspaceContext.tsx:207` | `migrateV1` does not strip panel types that no longer exist in the catalogue. They render as `null` via the `default:` branch in `WorkspacePanelContainer`, leaving an empty panel cell. | After parsing, filter `panels` against the current `PanelType` union: `panels.filter(p => SUPPORTED_PANEL_TYPES.has(p.type))`. Surface a one-off toast "1 unsupported panel removed". |
| MIN-3 | MINOR | `apps/worldview-web/components/screener/*Export*.tsx` (and equivalents) | `jspdf` (~600KB) + `write-excel-file` (~120KB) are eagerly imported even for CSV-only users. | Lazy-`import()` per format inside the click handler; ship CSV in the main bundle. |
| MIN-4 | MINOR | `services/portfolio/src/portfolio/application/use_cases/get_realized_pnl.py:234-239` | Per-instrument `await uow.instruments.get(iid)` inside the breakdown loop is N×1. For a 5-year portfolio touching 200 instruments this is 200 sequential round-trips on the read replica. | Add `instruments.list_by_ids(ids)` batch fetch and build the lookup once. |
| NIT-1 | NIT | `apps/worldview-web/components/alerts/RuleManagerDialog.tsx` | No `<DialogDescription>` rendered → screen-reader announces only the title. Vitest stderr already flags it. | Add a `<DialogDescription className="sr-only">Manage alert rules.</DialogDescription>`. |
| NIT-2 | NIT | `apps/worldview-web/lib/chat/slash-commands.ts:83-89` | `parseQuote("0")` returns `{ticker: "0"}` — caller will hit gateway with literally `0`. Not catastrophic; the card will render an error. | Reject non-alphabetic-leading tickers in the parser. |
| NIT-3 | NIT | `apps/worldview-web/__tests__/context-aware-starters.test.tsx:68` | Test passes `entity_id=AAPL` (a ticker) instead of a real UUID, hiding MAJ-5. | Use a UUID string in the URL params and assert that the rendered starter mentions the resolved ticker — requires mocking the resolver too. |

---

## Verdict justification

**CRITICAL_BLOCK.** Three independently reproducible CRITICAL bugs (each verified live against the running stack with curl + dev-login JWT):

1. **Snooze feature does not work** — every snooze attempt 422s because the frontend wire field name doesn't match Pydantic. (C-1)
2. **Severity filter on Alert History does not work** — backend rejects uppercase enum values; frontend always sends uppercase. (C-2)
3. **Alert History pagination is dead** — the Load More button is unreachable due to mismatched `total` semantics + missing `has_more` in the frontend type. (C-3)

Each is a contract bug between the frontend and backend that the in-tree test suites failed to catch because both sides mock or assume the wrong shape. Shipping in this state would mean three of Wave D's headline features (snooze + severity filter + history pagination) are non-functional on day one.

To clear to **CONDITIONAL_PASS**: fix C-1, C-2, C-3 with contract tests that pin the wire format end-to-end (one Vitest + one pytest per pair). MAJ-1..MAJ-5 should be addressed before broad rollout but do not need to block the wave merge — they are correctness/UX issues rather than universal failures. MIN/NIT are deferrable.
