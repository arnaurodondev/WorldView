---
id: PRD-0089-DESIGN-INDEX
title: Platform-wide Bloomberg-Grade UI Redesign — Design Index
status: in-discovery
created: 2026-05-20
parent_prd: docs/specs/0089-platform-page-redesign.md (to be written after design agents return)
---

# Platform Page Redesign — Design Index

> **Survives compaction.** If the conversation history is truncated, an agent
> reading this file can pick up exactly where we left off: per-page design
> docs, shared design tokens, agent assignments, and acceptance criteria.

## Why this exists

The current frontend (`apps/worldview-web`, branch `fix/ci-failures-cleanup`)
ships the new PLAN-0090 instrument-detail page but the user identified
multiple defects after live testing:

- Letters too large; rows too tall; padding too generous → low information
  density vs Bloomberg / TradingView / Finviz / IBKR
- The Financials sidebar is mostly empty real estate (only ANALYST CONSENSUS
  bar + 12-MO TARGET shown; everything else is whitespace)
- The legacy "AI brief" + company description + sector breakdown panel was
  removed in PLAN-0090's T-E-01 deletion; the new page never restored an
  equivalent — context the user expects is gone
- Quote and Intelligence tabs have the same density + emptiness issues
- Portfolio Overview does NOT clearly surface user positions

The goal of PRD-0089 is to redesign every primary page to Bloomberg-grade
density, restore the missing context surfaces (AI brief, company narrative,
sector exposure), and surface ALL backend data that's currently produced
but not displayed.

## Shared design tokens (every agent MUST honour these)

> All sizes in CSS pixels. Tokens align with the existing `--background`
> (#09090B Terminal Dark) palette but tighten every spacing primitive
> and bump down every font two units. Agents propose deviations explicitly
> if a surface genuinely needs more breathing room.

### Typography scale

| Token | Size | Line height | Use |
|-------|------|-------------|-----|
| `text-[9px]`  | 9px | 12px | Tertiary labels (cell sub-text, dot legends, freshness timestamps) |
| `text-[10px]` | 10px | 14px | Group headers, column headers, small labels (UPPERCASE tracking-wide) |
| `text-[11px]` | 11px | 16px | **Body text default** — table rows, metric values, descriptions |
| `text-[12px]` | 12px | 18px | Section titles, mid-emphasis labels |
| `text-[13px]` | 13px | 20px | Page chrome (ticker, primary price, tab labels) — sparingly |
| `text-[14px]` | 14px | 22px | One-off hero numbers (e.g. portfolio total value) — banned in tables |

Every numeric cell: `font-mono tabular-nums`. Every UI label: IBM Plex Sans
default. No `text-base` (16px) or `text-sm` (14px) in dense tables.

### Spacing scale (TIGHT)

| Token | px | Use |
|-------|----|----|
| `gap-1` / `space-y-1` / `p-1` | 4px | Inside dense table rows |
| `gap-2` / `p-2` | 8px | Between section blocks |
| `gap-3` / `p-3` | 12px | Horizontal margin on tab content edges |
| `gap-4` / `p-4` | 16px | **Maximum** allowed inside a panel; banned for table-cell padding |

Row height: **22px** standard (`h-[22px]`), **20px** when paired with a
group divider above it. NEVER `h-9` (36px) for data rows.

### Color palette (Terminal Dark — unchanged from globals.css)

- `--background`: #09090B (canvas)
- `--card`: #0D0D10 (panel surface — 1 step lighter than canvas)
- `--border`: #1F1F23 (1px hairlines; never elevation shadows)
- `--foreground`: #FAFAFA (primary text)
- `--muted-foreground`: #71717A (secondary text)
- `--primary`: #FFD60A (Bloomberg yellow; active states, key CTAs)
- `--positive`: hsl(var(--positive)) → #00D26A (gains)
- `--negative`: hsl(var(--negative)) → #FF3B5C (losses)
- `--warning`: hsl(var(--warning)) → #FFB000 (Bloomberg amber; caution thresholds)

Agents must NOT introduce new colors. To gate a threshold use one of
`text-positive / text-negative / text-warning / text-muted-foreground`.
Architecture test `__tests__/architecture/no-off-palette-colors.test.ts`
bans raw `text-amber-N`, `text-emerald-N`, `text-red-N` etc.

### Density principle

Bloomberg/Finviz density target: **40-60 metric cells visible above the
fold at 1440×900**, NOT 12-15 like the current Quote tab. Every panel
should answer the question: "How can I show 2× more without scrolling?"

## Page coverage (1 doc per row)

Every doc here MUST exist before PRD-0089 is written. The master PRD
imports each per-page design as a section.

| Page / surface | Doc file | Lines | Density above-fold | Status |
|----------------|----------|------:|--------------------|--------|
| Backend data inventory | `00-backend-data-inventory.md` | 648 | 96 endpoints + 75 not-displayed fields | ✅ done |
| Global shell | `01-global-shell.md` | 491 | 17 TopBar slots + dense watchlist | ✅ done |
| Dashboard | `02-dashboard.md` | 604 | 262 cells | ✅ done |
| Portfolio Overview | `03-portfolio-overview.md` | 864 | 281 cells | ✅ done |
| Portfolio Detail (Holdings/Tx/Analytics) | `04-portfolio-detail.md` | 641 | 430-cell tx ledger | ✅ done |
| Instrument Quote | `05-instrument-quote.md` | 562 | 113 cells (2.2× target) | ✅ done |
| Instrument Financials | `06-instrument-financials.md` | 506 | 172 cells (4.3× current) | ✅ done |
| Instrument Intelligence | `07-instrument-intelligence.md` | 606 | 46 high-value items | ✅ done |
| Screener | `08-screener.md` | 779 | 20 rows × 12 cols (240 cells) | ✅ done |
| Workspace + Predictions + Alerts | `09-workspace-predictions-alerts.md` | 1439 | 220/30 markets/296 cells | ✅ done |
| Chat / AI panel | `10-chat-ai.md` | 707 | 40+ cells | ✅ done |
| **Master PRD** | `docs/specs/0089-platform-page-redesign.md` | — | — | ✅ done |

## Required structure for every per-page design doc

Each per-page doc MUST follow this skeleton so the master PRD can
import sections deterministically:

```markdown
# <Page Name> — Design Spec (PRD-0089)

## 1. Competitor research summary
- Bloomberg Terminal: what they do on this surface, density patterns, what to steal
- TradingView: same
- Finviz: same
- Interactive Brokers TWS: same
- (Optional) Refinitiv Eikon / Koyfin / FactSet / Stockanalysis.com
- Direct citations / screenshots when possible

## 2. User intent for this page
- Primary persona (who lands here): hedge-fund PM, quant analyst, etc.
- Primary tasks (top 3): e.g. "compare current price to 52W band",
  "spot earnings surprise", "decide if to add to position"
- Secondary tasks
- Anti-patterns: things this page must NOT become

## 3. Backend data available (cite the inventory doc)
- Exhaustive list of every field the backend exposes that's relevant
- Mark currently displayed vs missing
- Flag data the user explicitly mentioned (AI brief, company description, sector)

## 4. Layout
- ASCII wireframe at 1440×900 (no images — pure text so it survives diffs)
- Grid description (cols, rows, sticky regions)
- Density target (cells visible above fold)

## 5. Component breakdown
- Each component with: file path, line-budget, props, what it renders
- Cross-reference reusable shared primitives where possible

## 6. Visual spec (numerical, not vague)
- Every spacing value in px
- Every font size + line-height from the shared scale (§Typography above)
- Every color from the palette (no new tokens)
- Row heights, column widths, border-radii, animations (if any — default: none)

## 7. Interaction model
- Hotkeys (scoped to this page)
- Hover behaviour
- Click handlers
- Loading / error / empty states (all three required)

## 8. Data fetching
- TanStack Query keys (use `qk.*` from lib/query/keys.ts — propose new keys here)
- staleTime per resource
- Whether the resource is reused by other pages (dedup opportunities)

## 9. Tradeoffs & decisions
- At least 2 explicit alternatives considered
- Why the recommended path wins

## 10. Open questions
- Anything that needs user input before implementation
```

## Workflow

1. Agents run in parallel — each produces its `.md` file
2. After ALL agents return, I (coordinator) write:
   - `docs/specs/0089-platform-page-redesign.md` (the actual PRD)
   - Updated `docs/ui/DESIGN_SYSTEM.md` with the new density tokens
3. Then we iterate per-page with the user until the design is locked
4. Only THEN do we plan implementation (PLAN-00NN) and execute waves

## State block (updated by coordinator)

(empty — coordinator fills in)
