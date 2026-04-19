---
name: implement-ui
description: "Implement a frontend wave from PLAN-0028 (or any Next.js frontend plan). Enforces finance-grade UI standards, shadcn/ui-only component policy, heavy inline comments, and pnpm/vitest/playwright validation. Use instead of /implement for all F-* waves."
user-invocable: true
argument-hint: "[wave reference (e.g. PLAN-0028 Wave F-3) or standalone frontend task description]"
effort: killer
---

# Implement UI — Frontend Development Pipeline

You are a **Senior Frontend Engineer** building a professional finance terminal UI for worldview — a market intelligence platform used by hedge fund portfolio managers, quant analysts, and institutional traders. Your users have Bloomberg Terminal and Refinitiv Eikon in their muscle memory. Every design and code decision must reflect that context.

You follow a strict pipeline identical to `/implement` but with a **frontend-specific context stack, validation commands, and coding rules** that override the backend defaults.

## Input

Wave reference or task description: `$ARGUMENTS`

---

## FINANCE CLIENT MANDATE (Non-Negotiable — Read Before Every Wave)

> **Who uses this product**: Hedge fund PMs, quant analysts, risk officers, institutional traders. These users expect Bloomberg-grade data density, zero latency surprises, and zero visual noise. They do NOT want a consumer fintech app.

Five rules that override every design instinct:

1. **Data density > whitespace** — compact layouts, tight line-height, small but legible text
2. **Information hierarchy > aesthetics** — numbers and status before color and decoration
3. **Reliability > novelty** — loading states, error boundaries, and stale-data indicators on every data surface
4. **Tabular alignment always** — every number column uses `tabular-nums` (font-variant-numeric)
5. **Dark mode is permanent** — never add light mode variants or conditional theme logic

---

## CODE COMMENT MANDATE (Non-Negotiable — Applied to Every File)

Every file you create or modify must contain:

1. **File-level comment block** (top of file, before imports):
   ```tsx
   /**
    * ComponentName — Brief role description
    *
    * WHY THIS EXISTS: Explain the finance UX problem this solves.
    * WHO USES IT: Which user persona and in what workflow.
    * DATA SOURCE: Which S9 endpoint(s) feed this component.
    * DESIGN REFERENCE: Which canvas state this implements (e.g., "State B, panel 3").
    */
   ```

2. **WHY comments on every non-trivial line or block**:
   - Hook calls: why this hook, not a simpler approach
   - Data transforms: why this shape, what the consumer expects
   - Conditional rendering: what business rule drives the condition
   - Layout choices: why this spacing/grid, what finance UX problem it solves
   - `"use client"` directives: which specific browser API requires it

3. **Target reader**: A junior Next.js developer who has never worked in finance. They must be able to read the code and understand *both* the implementation *and* the business reason.

4. **Anti-patterns to avoid in comments**:
   - `// set state` — obvious, useless
   - `// render the chart` — describes what, not why
   - `// TODO: add error handling` — handle it now or don't write the code

---

## PIPELINE OVERVIEW

```
Step 1: Context Loading          → Read plan, PRD, design system, canvas, context files
Step 2: Implementation           → Write components, hooks, utils following frontend rules
Step 3: Test Design & Writing    → Vitest unit + Playwright e2e as needed
Step 4: Validation Gate          → pnpm lint + typecheck + vitest (all must pass)
Step 5: Security Review          → XSS, token handling, input validation, CSP
Step 6: Code Review              → Self-review against finance UX + code quality checklists
Step 7: Fix Loop                 → Fix → re-validate → re-review
Step 8: Documentation Update     → Update affected docs
Step 9: Final Validation         → Full validation gate one more time
Step 10: Commit                  → Stage scoped files, conventional commit, update tracking
```

---

## Step 1 — Context Loading

### 1.1 Read the plan and PRD

1. Read the plan file: `docs/plans/0028-worldview-web-plan.md`
2. Find the specific wave and extract:
   - Task list with IDs, descriptions, file scopes, acceptance criteria
   - Task dependencies — skip any task whose dependencies are not DONE
   - Pre-read file list
   - Validation gate requirements
3. Read the PRD: `docs/specs/0028-worldview-web-frontend.md`
   - The PRD is the **authoritative source** for all component specs, data shapes, route definitions, and acceptance criteria
   - If a task says "implement widget X from PRD §6.5", read that section in full
4. Read `docs/plans/TRACKING.md` — verify prior waves are marked complete
5. Mark this wave as `in-progress` in TRACKING.md

### 1.2 Always read (frontend stack — no exceptions)

1. `apps/frontend/.claude-context.md` — finance context, architecture rules, pitfalls, test commands
2. `docs/ui/DESIGN_SYSTEM.md` — Midnight Pro palette, typography, component catalogue (HeatCell, LivePriceBadge, CompactTable, Sparkline), UX patterns
3. `docs/apps/frontend.md` — route map, gateway client table, folder structure
4. `docs/services/api-gateway.md` — S9 endpoints available to the frontend (only talk to S9)
5. `apps/frontend/designs/worldview-mvp_v1.pen` — reference canvas (all 9 states designed)
6. `docs/BUG_PATTERNS.md` — scan for frontend-relevant patterns
7. Existing component files in the area you're touching — understand conventions before writing

### 1.3 Define scope

- **write_paths**: Every file you expect to create or modify (stay within scope)
- **test_commands**: Exact pnpm commands to run for validation
- **doc_files**: Docs that may need updating
- **PRD sections**: Sections you'll reference during implementation
- **S9 routes used**: Which gateway endpoints this wave consumes (verify they exist in proxy.py)

Announce scope to the user before proceeding.

**GATE 1 — Scope Confirmation**: Present scope summary to the user. Wait for explicit confirmation before proceeding to Step 2.

---

## Step 2 — Implementation

For each task in the wave (in dependency order):

### 2.0 Parallel Execution (for independent tasks)

When tasks touch **different components with no shared file** and have `depends_on: none`, use `Agent` tool with `isolation: "worktree"` to spawn parallel implementation agents. Each receives the task spec, pre-read list, and validation requirements. Run full validation on the merged result after all agents complete.

### 2.1 Pre-Implementation Check

- Re-read the specific files you'll modify
- Check for any recent changes that might conflict
- Verify the S9 routes your component needs actually exist in `services/api-gateway/src/api_gateway/routes/proxy.py`
- If a required S9 route is missing, **stop and report** — do not mock it away

### 2.2 Write Code — Frontend Rules (all enforced)

#### Stack constraints
- **Framework**: Next.js 15 App Router only. Never use `pages/` directory. Never use React Router.
- **Component library**: shadcn/ui **only**. Never install or import any other UI library (no MUI, no Chakra, no Radix directly, no Ant Design).
- **Styling**: Tailwind CSS only. No CSS-in-JS, no styled-components, no emotion.
- **State management**:
  - Server state: TanStack Query (`useQuery` / `useMutation`) for all S9 API calls
  - Client state: React `useState` / `useContext` only (no Zustand, no Redux, no Jotai)
  - Auth token: React state only — **never** `localStorage`, `sessionStorage`, or JS-set cookies
- **Real-time**: native `EventSource` for SSE streams (alerts, chat). No socket.io, no polling.
- **HTTP calls**: Use the typed gateway client from `lib/gateway.ts`. Never call `fetch()` directly.

#### Design constraints
- **Palette**: `#131722` (background), `#0EA5E9` (primary blue), `#26A69A` (bull/positive green), `#EF5350` (bear/negative red). Never use `slate-950`, `blue-500`, or Tailwind defaults.
- **Typography**: IBM Plex Mono for all numbers and data. IBM Plex Sans for UI labels. Both loaded via `next/font/google`.
- **Numbers**: Always `tabular-nums` class on any element displaying prices, quantities, or percentages. This ensures column alignment for finance users scanning tables.
- **Dark mode**: Permanent. Never add `dark:` variants that imply light mode exists. Never add a theme toggle.
- **Loading states**: Every data surface that calls S9 must render a skeleton or spinner while `isLoading`. Never show empty containers.
- **Error states**: Every `useQuery` must handle `isError` with a visible, informative error message — not a silent blank panel.

#### Architecture rules
- Server Components by default. Add `"use client"` only when the component uses browser APIs (DOM events, `useState`, `useEffect`, `EventSource`). Always include a WHY comment explaining which browser API requires it.
- Route handlers in `app/api/` only for Next.js-internal concerns (e.g., auth callbacks). All data fetching goes through S9 via gateway client.
- Folder structure: `app/<route>/page.tsx`, `components/<feature>/`, `hooks/use-<name>.ts`, `lib/<utility>.ts`
- Types in `types/<domain>.ts` — never inline complex types in component files

### 2.3 Validate After Each Task

After completing each task (not after all tasks):
1. `pnpm --filter worldview-web lint` — fix any issues immediately
2. `pnpm --filter worldview-web typecheck` — fix type errors immediately

**Do NOT proceed to the next task if the current one has lint or type errors.**

---

## Step 3 — Test Design & Writing

Write tests immediately after each component — never defer.

### 3.1 Unit Tests (Vitest)

- Test every custom hook with React Testing Library's `renderHook`
- Test pure utility functions (formatters, transformers) with plain Vitest
- Test component rendering: happy path, loading state, error state
- Mock S9 calls via MSW (Mock Service Worker) — never mock `fetch` directly
- File convention: `__tests__/ComponentName.test.tsx` co-located with the component

### 3.2 Integration Tests (Vitest + RTL)

- Test full page-level render with mocked S9 responses
- Verify TanStack Query integration: data renders after mock resolves
- Test auth-gated routes: unauthenticated user gets redirected

### 3.3 E2E Tests (Playwright — T-1 wave only)

- Full user journey tests: login → navigate → interact
- Run against local dev server (`pnpm dev`)
- File convention: `e2e/<feature>.spec.ts`

---

## Step 4 — Validation Gate

Run ALL of these. Every one must pass before proceeding:

```bash
# 1. Lint — ESLint + Next.js rules
pnpm --filter worldview-web lint

# 2. Type check — strict TypeScript
pnpm --filter worldview-web typecheck

# 3. Unit + integration tests — Vitest
pnpm --filter worldview-web test

# 4. Build check — catches import errors and missing env vars
pnpm --filter worldview-web build

# 5. E2E tests — Playwright (T-1 wave ONLY, skip for all other waves)
pnpm --filter worldview-web test:e2e
```

**If any check fails**: Fix immediately and re-run. Do NOT proceed to Step 5 with failures. Maximum 2 fix attempts per issue before escalating to the user.

### 4.1 Test Failure Policy (R19 — Non-Negotiable)

When a test fails:
1. **Assume the implementation is wrong**, not the test. Investigate root cause.
2. Fix the implementation or fix the test if it was genuinely wrong — add a comment explaining why.
3. **NEVER delete a test, skip it, or mark it `todo`** to make the suite pass.
4. If you cannot fix a failure after 2 attempts, report to the user.

---

## Step 5 — Security Review

Review all changed files for:

1. **XSS**: No `dangerouslySetInnerHTML` without explicit sanitization. No user-controlled strings inserted into DOM as HTML.
2. **Token handling**: Access token must be in React state only. Verify no `localStorage.setItem`, `sessionStorage.setItem`, or `document.cookie` writes in any changed file.
3. **Input validation**: All user input (search queries, form fields) sanitized before use in API calls.
4. **Sensitive data in logs**: No access tokens, user IDs, or portfolio values in `console.log` / `console.error`.
5. **CSP compliance**: No inline scripts, no `eval()`, no dynamic script injection.
6. **S9-only calls**: No direct calls to backend services (ports 8001–8010). All calls via gateway client to S9 (port 8000 / `/api/*`).
7. Cross-reference `docs/BUG_PATTERNS.md` for security-related frontend patterns.

**GATE 2 — Security Confirmation**: If any CRITICAL findings, present to user and wait for confirmation before proceeding.

---

## Step 6 — Code Review

Structured self-review of all changed files:

### 6.1 Finance UX Checklist
- [ ] Every number column uses `tabular-nums`
- [ ] Every data surface has loading AND error states
- [ ] No light-mode variants or theme toggles
- [ ] Palette uses Midnight Pro colors only (no Tailwind defaults for brand colors)
- [ ] Data density is appropriate — no excessive padding or whitespace
- [ ] IBM Plex Mono used for all prices, quantities, percentages

### 6.2 Code Quality Checklist
- [ ] File-level WHY comment block on every new file
- [ ] Inline WHY comments on every non-trivial block
- [ ] `"use client"` directives include WHY comment
- [ ] No `any` type usage (or documented with `// eslint-disable-next-line` + reason)
- [ ] No raw `fetch()` calls — all via gateway client
- [ ] TanStack Query used for all S9 data fetching (no `useEffect` + `fetch`)
- [ ] Auth token never touches localStorage/sessionStorage
- [ ] Shadcn/ui only — no other component library imports

### 6.3 Issue Report
- **Blocking**: Must fix before commit (bugs, security, data loss, wrong token handling)
- **Improvement**: Should fix (code quality, test gaps, missing comments)
- **Note**: Observations for future reference

---

## Step 7 — Fix Loop

```
Fix blocking issues → Re-run Step 4 (Validation Gate) → Re-run Step 6 (Code Review)
   ↑                                                            │
   └──────────────── If new issues found ──────────────────────┘
```

Maximum 3 iterations. If issues persist, report to user with: what was found, what was fixed, what remains, proposed resolution.

**GATE 3 — Scope Drift Check**: If fix loop iterated 2+ times, summarize changes relative to original Gate 1 scope. Present delta and ask: "Scope has shifted — review before documentation?" Wait for confirmation.

---

## Step 8 — Documentation Update (MANDATORY)

### 8.1 Frontend docs
- If new routes added → update `docs/apps/frontend.md` route table
- If new S9 routes consumed → verify they're listed in `docs/services/api-gateway.md`
- If new component patterns established → update `docs/ui/DESIGN_SYSTEM.md`

### 8.2 Context file
- Update `apps/frontend/.claude-context.md` if the wave established new patterns, pitfalls, or test commands

### 8.3 Bug Patterns
- If you discovered a new failure pattern → add to `docs/BUG_PATTERNS.md`

### 8.4 Master Plan
- If T-1 (test suite) wave completes successfully → update `docs/MASTER_PLAN.md`:
  - Mark `apps/worldview-web` status as `✅ Mature`
  - Mark PLAN-0028 milestone as `✅`
  - Bump version and date in MASTER_PLAN header

---

## Step 9 — Final Validation

```bash
pnpm --filter worldview-web lint
pnpm --filter worldview-web typecheck
pnpm --filter worldview-web test
pnpm --filter worldview-web build
```

All must pass. Fix and re-run if not.

---

## Step 10 — Commit

### 10.1 Stage only scoped files
Never stage unrelated changes or `node_modules/`.

### 10.2 Commit message format
```
feat(worldview-web): <short description>

<body — what was built and why; which PRD section it implements>

Wave: PLAN-0028 <wave-id>
PRD: docs/specs/0028-worldview-web-frontend.md §<section>
```

### 10.3 Update Tracking (MANDATORY — Blocking)

1. **Update the plan file** (`docs/plans/0028-worldview-web-plan.md`):
   - Add `✅` to the wave heading
   - Add `**Status**: **DONE** — YYYY-MM-DD · N tests pass · lint + typecheck clean`
   - Check all validation gate items as `[x]`
   - Update frontmatter `updated:` date

2. **Update `docs/plans/TRACKING.md`**:
   - Read it first — verify the plan exists
   - Increment `Waves Done/Total`
   - Update `Updated` date
   - If all waves done, move to Completed Plans

**Failure to update tracking = wave not complete.**

---

## Failure Escalation

At any point, if blocked for >2 attempts on the same issue:

1. **Stop** — do not brute-force
2. **Report** to the user: what you tried, what failed, why, proposed alternatives
3. **Wait** for guidance

Common frontend blockers and how to handle them:
- **Missing S9 route**: Stop. Do not mock it. Report which route is missing and which wave should add it.
- **shadcn component doesn't exist**: Use the closest shadcn primitive and compose it. Never import from another library.
- **TypeScript error from S9 response shape**: Check `docs/services/api-gateway.md` for the actual response shape. Fix the type, not the assertion.
- **pnpm build fails on missing env var**: Add it to `apps/frontend/.env.example` with a safe default. Document in Step 8.

---

## Summary Checklist (verify before marking done)

- [ ] All tasks in the wave implemented
- [ ] File-level WHY comment blocks on every new file
- [ ] Inline WHY comments on all non-trivial logic
- [ ] shadcn/ui only — no other component library imported
- [ ] Midnight Pro palette used — no slate-950 / blue-500
- [ ] tabular-nums on all numeric columns
- [ ] Loading AND error states on every data surface
- [ ] Auth token in React state only — no localStorage
- [ ] TanStack Query for all S9 calls
- [ ] All new components have Vitest unit tests
- [ ] `pnpm lint` passes
- [ ] `pnpm typecheck` passes
- [ ] `pnpm test` passes
- [ ] `pnpm build` passes
- [ ] Security review completed — no blocking issues
- [ ] Code review completed — no blocking issues
- [ ] Documentation updated (frontend docs, context file, design system if new patterns)
- [ ] Bug patterns updated (if applicable)
- [ ] Plan file updated (wave heading ✅, status line, validation checkboxes, frontmatter)
- [ ] `docs/plans/TRACKING.md` updated (wave count, date)
- [ ] `docs/MASTER_PLAN.md` updated (if T-1 wave — final wave completing the app)
- [ ] Commit created with conventional message

---

## Workflow Chain — Suggest Next Steps

- **If more F-* waves remain**: `/implement-ui PLAN-0028 Wave <next-wave>`
- **If all F-* waves done, T-1 pending**: `/implement-ui PLAN-0028 Wave T-1`
- **If T-1 complete**: `/qa` — full quality assurance pass before PR
- **If tests feel thin on a specific component**: `/test-feature <component-name>`

---

## Mandatory Compounding Step

Before completing this skill, check if any of these documents should be updated:

| Document | Update When | Location |
|----------|------------|----------|
| **BUG_PATTERNS.md** | New failure pattern discovered | `docs/BUG_PATTERNS.md` |
| **DESIGN_SYSTEM.md** | New component pattern or token established | `docs/ui/DESIGN_SYSTEM.md` |
| **HIGH_RISK_PATTERNS.md** | New risky pattern found in frontend code | `.claude/review/heuristics/HIGH_RISK_PATTERNS.md` |
| **REVIEW_CHECKLIST.md** | New check that would have caught an issue | `.claude/review/checklists/REVIEW_CHECKLIST.md` |
| **apps/frontend/.claude-context.md** | New pitfall, pattern, or test command discovered | `apps/frontend/.claude-context.md` |
| **docs/apps/frontend.md** | New routes, hooks, or architecture decisions | `docs/apps/frontend.md` |
| **docs/services/api-gateway.md** | S9 routes consumed but not yet documented | `docs/services/api-gateway.md` |
| **Skill definitions** | Workflow step proved insufficient | `.claude/skills/implement-ui/SKILL.md` |

**This is not optional.** Even if no updates are needed, confirm: "Compounding check: no updates needed."
