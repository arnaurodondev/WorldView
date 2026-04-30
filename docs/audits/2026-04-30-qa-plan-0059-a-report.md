# QA Report: PLAN-0059-A Wave A (Institutional Remediation W0)

**Date**: 2026-04-30 14:25 UTC
**Skill**: `/qa`
**Scope**: `--plan PLAN-0059-A` (frontend institutional remediation, Wave A-1 + A-2)
**Branch**: `feat/content-ingestion-wave-a1`
**Commit under review**: `99b8bcf7` ("feat(plan-0059-wave-a): institutional remediation W0 — token surgery, a11y, brand, observability foundation")
**Source documents**:
- Plan: `docs/plans/0059-frontend-institutional-remediation-master-plan.md` §3 (Wave A-1 + A-2 + A-3)
- Goals: `docs/audits/2026-04-30-deep-remediation-master-report.md` §1, §2, §3, §6
**Verdict**: **FAIL** — **2 BLOCKING bugs that prevent production build** + multiple acceptance-criteria failures + Wave A is **not deployed** to the live container (the no-cache Docker rebuild FAILED inside the build at `pnpm build`).
**Report file**: `docs/audits/2026-04-30-qa-plan-0059-a-report.md`

---

## Executive Summary

PLAN-0059-A Wave A was committed as “DONE” on 2026-04-30. This QA pass verifies the diff against the master remediation report’s W0 expectations *and* against a live-platform end-to-end test. The Wave A diff is directionally correct — the four headline silent CRITICAL findings (TradingView teal, retired Bloomberg-Dark heatmap palette, `:root`/`.dark` muted-foreground drift, no `--accent-ai`) are closed at the source-CSS level and the new `globals.css` is genuinely institutional-grade. However, the wave is **incomplete and overstated**:

1. `pnpm typecheck` fails on `app/callback/page.tsx:115` — `export const ERROR_MESSAGES` violates Next.js 15’s PageProps `{ [x: string]: never; }` constraint. This is a **BLOCKING regression** introduced by the Wave A diff itself, and means the plan’s own A-3 validation gate (“`pnpm typecheck` exits 0”) is currently red despite being marked ✅.
2. **Wave A is not in the live container**. The running `worldview-web` container is 21h old and serves the retired teal/red CSS bundle; `--build` was a no-op due to Docker layer caching, and a `--no-cache` rebuild is required before any demo. Confirmed via direct `curl` of `/_next/static/css/22d66598b18147ad.css`.
3. T-A-1-05 (disabled tokens): only `button.tsx` was migrated; **16 sites** still ship `disabled:opacity-50` (Switch, Checkbox, screener filter inputs, AskAi, MorningBrief, chat composer, …) — disabled-state contrast remains sub-WCAG-AA on those components.
4. T-A-1-07 (brand identity): only **3 of 10** specified artifacts ship (`app/icon.svg`, `app/apple-icon.svg`, `app/manifest.webmanifest`); raster icons, OG image, Twitter card, and `brand/wordmark.svg` are absent. `public/` is empty. LinkedIn/Slack/Twitter share previews will be blank — directly impacts the BlackRock-grade credibility claim.
5. T-A-1-04 (Tailwind defaults): grep test fails — `app/feedback/page.tsx:47-49` still uses `bg-blue-500/10 text-blue-400` and `bg-emerald-500/10 text-emerald-400` (neither in plan’s `app/login`/`app/error` allowlist); the `no-restricted-classnames` ESLint regression rule was never added.
6. T-A-2-02 (CI gates): only the ESLint slice landed. `depcheck`, `knip`, `bundlewatch`, `@lhci/cli` are NOT installed; no `bundlewatch.config.json`; no `.lighthouserc.json`. Plan A-3 gate steps `pnpm exec depcheck` / `pnpm exec knip` cannot pass — binaries don’t exist.
7. T-A-2-05 / T-A-2-06: minor config gaps — `experimental.reactCompiler: true` is missing from `next.config.ts` (plan specified it); `verbatimModuleSyntax: true` is missing from `tsconfig.json` (plan specified it).
8. **Test coverage**: of the ~30 net-new tests specified across the 14 Wave A tasks, only **~5 net-new tests** actually shipped (heatCellColor regression guard + a few sub-tests). The 850-test pre-existing pass rate is real, but the wave’s own acceptance gate (“all Wave A tests pass”) is unmet by ~25 missing tests.
9. **Live-platform smoke** found two pre-existing backend bugs the demo will trip into: `GET /v1/fundamentals/screen` returns 500 (route ordering bug — `screen` parsed as a UUID); `/v1/quotes/stream` is registered and 500s though Wave D shouldn’t expose it yet. These are **not** Wave A regressions but are **critical blockers** to the Bloomberg-grade demo claim.
10. **What did land cleanly**: token surgery (T-A-1-01..03), a11y media queries (T-A-1-06), sonner Toaster (T-A-2-01), legacy Sidebar deletion (T-A-2-07 file-delete portion), UtcClock hydration fix (T-A-2-04), ESLint `no-explicit-any: error` (T-A-2-02 partial), `next.config.ts` `optimizePackageImports`/`removeConsole`/`productionBrowserSourceMaps` (T-A-2-05 partial). globals.css is a high-quality institutional-grade artifact.

**Roll-up of 14 Wave A tasks**: 5 FULL, 8 PARTIAL, 1 DEFERRED (Sentry), 0 MISSED. Wave A is approximately **70% complete**. The plan and TRACKING.md should be amended to reflect partial completion and the Wave A-3 validation gate must be reopened.

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------------|----------|---------|----------|-------|-------|-----|
| QA / Test Engineer | 9 | 20 | 3 | 8 | 5 | 2 | 1 |
| Security Engineer | 8 | 5 + 6 verifications | 0 | 1 | 1 | 2 | 1 |
| Architecture Decision Lead | 8 | 10 | 1 | 2 | 5 | 2 | 0 |
| Visual / UX Reviewer | 6 | 7 | 0 | 1 | 4 | 1 | 1 |
| Distributed Systems / Live Platform | 27 endpoints + 13 DBs + 27 Kafka topics | 7 | 2 | 1 | 2 | 1 | 1 |
| **Cross-agent dedup** | — | **~28 unique** | **3** | **5** | **8** | **6** | **3** |

### Cross-Agent HIGH-Confidence Signals (flagged by ≥2 agents)

| Signal | Agents | Severity |
|--------|--------|----------|
| `export const ERROR_MESSAGES` typecheck regression | QA, Architecture | BLOCKING |
| 16 `disabled:opacity-50` sites remain (T-A-1-05 incomplete) | QA, Architecture, Visual | CRITICAL |
| Brand identity package 30% delivered (7 missing files) | QA, Architecture, Visual, Live | MAJOR/CRITICAL |
| `experimental.reactCompiler: true` missing from `next.config.ts` | QA, Architecture | MAJOR |
| `verbatimModuleSyntax` missing from `tsconfig.json` | QA, Architecture | MAJOR |
| `depcheck`/`knip`/`bundlewatch`/lhci not installed | QA, Architecture | MAJOR |
| Wave A tokens not in live CSS bundle (container 21h old) | Live | BLOCKING (demo) |
| `feedback/page.tsx` blue/emerald off-token | Architecture, Visual | MAJOR |

### Fixes Applied (in this QA pass)
None. This pass surfaces findings only — fixes deferred to a follow-up Wave A-completion patch per user instruction.

### Decisions Needed
| Finding | Question | Recommendation |
|---------|----------|----------------|
| F-001 (typecheck) | Move `ERROR_MESSAGES` to a sibling module, or revert export? | Move to `app/callback/error-messages.ts`. R19-compliant. |
| F-007 (brand) | Generate the missing 7 brand assets in this wave or split to A-3? | Split: ship rasters in A-completion patch; ship `brand/*.svg` via design tooling later. |
| F-009 (CI gates) | Land `depcheck`/`knip`/`bundlewatch`/`lhci` now or in W4 (Plan §G)? | Land NOW — plan’s A-3 validation gate cannot pass otherwise. |
| F-002 (disabled-tokens codemod) | Apply codemod to remaining 16 sites in A-completion or leave for Wave 3 (Plan §F-5)? | A-completion. WCAG-AA failure on Switch/Checkbox impacts every form across the app. |

---

## Test Execution Results

| Layer | Scope | Tests | Passed | Failed | Skipped | Status |
|-------|-------|------:|-------:|-------:|--------:|--------|
| Frontend Unit (Vitest) | `apps/worldview-web` | 850 | 850 | 0 | 0 | **PASS** |
| Frontend Lint (next lint / ESLint) | `apps/worldview-web` | — | — | 0 | — | **PASS** (1 security warning re: `ws://` default) |
| Frontend Typecheck (tsc) | `apps/worldview-web` | — | — | 1 | — | **FAIL** (TS2344 `app/callback/page.tsx:115`) |
| Frontend Bundle (depcheck/knip/bundlewatch) | `apps/worldview-web` | — | — | n/a | — | **N/A — tooling not installed** |
| Service Unit / Contract / Integration / E2E | All services | — | — | — | — | **NOT RUN** — out of scope (frontend-only Wave) |
| Architecture (root pytest tests/architecture) | repo | — | — | — | — | **NOT RUN** — frontend-only Wave |
| Live API smoke (S1/S2/S6/S8/S9/S10 healthz) | live | 6 | 6 | 0 | 0 | **PASS** |
| Live API smoke (auth + 8 protected endpoints) | live | 9 | 7 | 2 | 0 | **FAIL** (`/v1/auth/me` 503 oidc; `/v1/fundamentals/screen` 500) |
| Live frontend pages (200 + CSP headers) | live | 4 | 4 | 0 | 0 | **PASS** |
| Live Kafka topics | live | 27 topics | 27 | 0 | 0 | **PASS** |
| Live DB connectivity | live | 13 DBs | 13 | 0 | 0 | **PASS** |
| Live Wave A bundle in container | live | — | — | 1 | — | **FAIL** — old CSS bundle still served |

### Per-Container Health
All 54 containers healthy (`docker compose -f infra/compose/docker-compose.yml ps`): postgres, kafka, schema-registry, valkey, minio, ollama, gliner-server, mailhog, kafka-ui, pgweb + 11 services + their workers/dispatchers/consumers.

---

## Issues — Full Investigation

## Issue F-001: `export const ERROR_MESSAGES` violates Next.js 15 PageProps constraint (BLOCKING)

### Summary
The Wave A commit added `export` to a module-scoped constant in `app/callback/page.tsx` to make it importable from a test file. Next.js 15 App Router only allows specific named exports from page files; arbitrary exports are constrained to `{ [x: string]: never; }`. The result: `pnpm typecheck` fails at TS2344. The plan’s own Wave A-3 acceptance gate (“`pnpm typecheck` exits 0”) is currently red despite being marked ✅.

### Severity / Confidence
**Severity**: BLOCKING
**Confidence**: HIGH
**Flagged by**: QA / Test Engineer (QA-017), Architecture Decision Lead (ARCH-001)

### Root Cause Analysis
- **What**: `apps/worldview-web/app/callback/page.tsx:115` — `export const ERROR_MESSAGES: Record<CallbackErrorType, string>`
- **Why**: The pre-existing test file `__tests__/wave-fh-polish.test.tsx` asserts on `ERROR_MESSAGES[type]` strings. To honour R19 (“never delete tests”), the implementation was modified to expose the constant via export. But `app/callback/page.tsx` is a Next.js 15 page; Next’s `OmitWithTag` / `PageProps` typing only permits a fixed list of recognized exports (`default`, `metadata`, `viewport`, `dynamic`, `revalidate`, `fetchCache`, `runtime`, `preferredRegion`, `experimental_ppr`, `generateStaticParams`, `generateMetadata`, `generateViewport`). Anything else is constrained to `never` — adding `export const ERROR_MESSAGES` collides with that constraint.
- **When**: Always — every `tsc --noEmit` invocation fails since commit `99b8bcf7`.
- **Where**: API/route layer (Next.js convention).
- **History**: The constant existed before as `const ERROR_MESSAGES`; only the `export` keyword was added in this wave. Pre-existing tests were importing the page module as a side effect; the export change was meant to make the import explicit and safer.

### Evidence
```
.next/types/app/callback/page.ts(12,13): error TS2344:
  Type 'OmitWithTag<typeof import("...callback/page"),
    "default" | "viewport" | "metadata" | "config" | "generateStaticParams"
    | ... 9 more ... | "experimental_ppr", "">'
    does not satisfy the constraint '{ [x: string]: never; }'.
  Property 'ERROR_MESSAGES' is incompatible with index signature.
    Type 'Record<CallbackErrorType, string>' is not assignable to type 'never'.
 ELIFECYCLE  Command failed with exit code 2.
```

- **File**: `apps/worldview-web/app/callback/page.tsx:115`
- **Diff**: see `git show 99b8bcf7 -- apps/worldview-web/app/callback/page.tsx` lines around `+export const ERROR_MESSAGES`.

### Impact
- **Immediate**: `pnpm typecheck` fails. CI gate red. `next build` will fail in production deploy mode.
- **Blast radius**: Blocks all dependent waves (B/C/D/E/F) — anyone branching off this commit hits the same error.
- **Data risk**: None.
- **User impact**: None at runtime (typecheck is build-time).

### Solution Options

#### Option A: Move `ERROR_MESSAGES` to sibling module (RECOMMENDED)
**Description**: Extract the constant + `CallbackErrorType` type to `apps/worldview-web/app/callback/error-messages.ts`; import in `page.tsx` and from tests.
**Changes required**:
- [ ] Create `app/callback/error-messages.ts` exporting `CallbackErrorType` + `ERROR_COPY` + `ERROR_MESSAGES`
- [ ] In `app/callback/page.tsx`: import the constants instead of declaring them inline
- [ ] Update `__tests__/wave-fh-polish.test.tsx` import path (or keep — they re-export through page module if tests don’t pin path)
- [ ] Re-run `pnpm typecheck` — must pass
**Benefits**: R19-compliant; restores typecheck-clean state; satisfies Next.js convention; constants stay testable; pure refactor — no behavior change.
**Drawbacks**: 5-line change; minimal.
**Effort**: Low (≈ 5 minutes).
**Risk**: Low.

#### Option B: Revert the `export` keyword
**Description**: Drop `export` and rely on side-effect imports as before.
**Changes required**:
- [ ] Remove `export` from `page.tsx:115`
- [ ] Tests revert to dynamic-import-the-page workaround
**Benefits**: Smallest diff.
**Drawbacks**: Tests become brittle (rely on Next.js compiling the page in test mode); tests might break in some corners.
**Effort**: Low.
**Risk**: Medium (test fragility).

#### Option C: Add the constant to Next’s allowlist via type augmentation
**Description**: Declare a module augmentation to allow `ERROR_MESSAGES` as a recognised export.
**Changes required**: Module augmentation file.
**Benefits**: None over Option A.
**Drawbacks**: Hacky; signals to future readers that this is OK; encourages similar violations.
**Effort**: Medium.
**Risk**: High (architectural smell).

### Recommended Option
**Option A** — sibling module extraction. It is the canonical pattern in Next.js 15 for shared constants: pages stay thin, constants live in their own module, tests import them by file path, no constraint violation, no test fragility.

### Verification Steps
- [ ] `pnpm typecheck` exits 0
- [ ] `pnpm test` still passes 850 tests (no regression in callback tests)
- [ ] `next build` (production mode) succeeds

---

## Issue F-001b: `globals.css:133` CSS comment contains `*/` — production build fails (BLOCKING)

### Summary
While verifying the typecheck regression by running `pnpm build`, a SECOND BLOCKING bug surfaced. The Wave A comment block at `apps/worldview-web/app/globals.css:132-136` contains the literal string `text-amber-*/bg-amber-*`, which the CSS parser reads as a comment-terminator (`*/`) followed by stray text. Result: PostCSS fails with “Unknown word (133:51)” and `next build` aborts with webpack errors before it ever reaches the TypeScript check.

### Severity / Confidence
**Severity**: BLOCKING (production build cannot complete)
**Confidence**: HIGH
**Flagged by**: Live (build-time verification during QA pass)

### Root Cause Analysis
- **What**: CSS comment contains an unescaped `*/` sequence inside its body:
  ```css
  /* AI accent — F-VISUAL-022 fix (PLAN-0059 W0):
   * Replaces hardcoded text-amber-*/bg-amber-* in AI panels (AskAi, brief,
   ...
   */
  ```
  The first `*/` (after `text-amber-`) terminates the comment early; everything that follows (`bg-amber-* in AI panels...`) is parsed as CSS top-level → "Unknown word".
- **Why**: Comment author wrote glob/wildcard syntax (`text-amber-*`, `bg-amber-*`) inside a CSS comment, not realising the `*/` substring also closes the comment.
- **When**: Always — every `next build` (production), every Docker image build.
- **Where**: `apps/worldview-web/app/globals.css:133`.

### Evidence
```
$ cd apps/worldview-web && pnpm build 2>&1 | tail -10
-- inner error --
Syntax error: ...apps/worldview-web/app/globals.css Unknown word (133:51)

  131 |
  132 |     /* AI accent — F-VISUAL-022 fix (PLAN-0059 W0):
> 133 |      * Replaces hardcoded text-amber-*/bg-amber-* in AI panels (AskAi, brief,
      |                                                   ^

> Build failed because of webpack errors
 ELIFECYCLE  Command failed with exit code 1.

# Confirmed Docker no-cache rebuild also fails:
$ docker compose ... build --no-cache worldview-web
... failed to solve: process "/bin/sh -c cd apps/worldview-web && pnpm build" did not complete successfully: exit code: 1
```

### Impact
- **Immediate**: ANY production build of the frontend fails. CI deploy pipeline cannot ship Wave A. Docker image cannot be rebuilt — the live container will continue serving the pre-Wave-A bundle until this is fixed. The user’s explicit `/qa` request to “launch the real container instances and validate against the real platform working” cannot be satisfied because the Wave A image cannot be produced.
- **Blast radius**: Same as F-001 — blocks every dependent wave; blocks every deploy.
- **Data risk**: None.
- **User impact**: None at runtime (dev `pnpm dev` likely tolerates the parser oddity since CSS HMR is more lenient; only production webpack build fails).

### Solution Options

#### Option A: Replace `*/` with `*\/` or escape via `\*/` (RECOMMENDED)
**Description**: Rewrite the comment so it does not contain the `*/` substring. Easiest: add a space — `text-amber-* / bg-amber-*` — or rephrase: `text-amber-NNN and bg-amber-NNN`.
**Changes required**:
- [ ] Edit `apps/worldview-web/app/globals.css:133` to remove the inline `*/` substring inside the comment
- [ ] Re-run `pnpm build` — must succeed
- [ ] Re-run Docker `--no-cache` build — must succeed
**Effort**: Trivial (≈ 30 seconds).
**Risk**: Zero.

### Recommended Option
**Option A**. One-line fix.

### Verification Steps
- [ ] `pnpm build` completes successfully
- [ ] `docker compose -f infra/compose/docker-compose.yml build --no-cache worldview-web` completes successfully
- [ ] After force-recreate: live CSS bundle hash changes; `--positive: 150 100% 41%` appears
- [ ] Live `/icon.svg` returns 200

---

## Issue F-002: `disabled:opacity-50` codemod incomplete — 16 sites still violate WCAG AA (CRITICAL)

### Summary
Plan T-A-1-05 specified a codemod across all `disabled:opacity-50` sites in `components/` to replace opacity-based dimming with the new `--disabled-foreground`/`--disabled-bg`/`--disabled-border` tokens. The commit message claims “19 sites replaced.” Reality: only `components/ui/button.tsx` was actually migrated. 16 occurrences of `disabled:opacity-50` remain.

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: QA (QA-007), Architecture (ARCH-008), Visual (VIS-002)

### Root Cause Analysis
- **What**: 16 sites across UI primitives and feature components retain `disabled:opacity-50`, yielding ~3.5:1 (`text-foreground`) and ~2.7:1 (`text-muted-foreground`) disabled contrast — both fail WCAG AA.
- **Why**: The codemod was either not run or only run against a narrow subset (`components/ui/button.tsx`). The grep guard test specified by the plan was never written, so the gap was invisible at commit time.
- **When**: Always — every disabled state in Switch/Checkbox/inputs across the app fails AA.
- **Where**: UI primitives (`switch.tsx`, `checkbox.tsx`) cascade to every form in the app.
- **History**: Plan T-A-1-05 explicitly listed 388 sites with codemod-driven replacement.

### Evidence
```
$ grep -rn "disabled:opacity-50" apps/worldview-web/{components,app} | wc -l
16

apps/worldview-web/components/ui/switch.tsx:14
apps/worldview-web/components/ui/checkbox.tsx:16
apps/worldview-web/components/screener/ScreenerFilterBar.tsx:334
apps/worldview-web/components/screener/ScreenerFilterBar.tsx:347
apps/worldview-web/components/screener/ExportMenu.tsx:145
apps/worldview-web/components/instrument/InstrumentBriefPanel.tsx:115
apps/worldview-web/components/instrument/InstrumentBriefPanel.tsx:167
apps/worldview-web/components/shell/AskAiPanel.tsx:301
apps/worldview-web/components/workspace/WorkspaceChatWidget.tsx:275
apps/worldview-web/components/feedback/MicroSurvey.tsx:102
apps/worldview-web/components/alerts/AddToWatchlistDialog.tsx:154
apps/worldview-web/components/dashboard/MorningBriefCard.tsx:149
apps/worldview-web/components/dashboard/MorningBriefCard.tsx:268
apps/worldview-web/app/(app)/chat/page.tsx:1268
... (button.tsx:29 is a comment, not a violation)
```

- **Related BP**: matches user-memory `feedback_audit_returned_value_persistence.md` — “audit returned values must be persisted; metrics-only consumption is a silent failure pattern.” The codemod metric “19 sites replaced” was reported but not verified by a grep guard.

### Impact
- **Immediate**: 16 components ship sub-WCAG-AA disabled state. shadcn primitives (`switch`/`checkbox`) propagate to every form.
- **Blast radius**: Every login form, screener filter, alert rule editor, settings panel, brokerage dialog, watchlist dialog, chat composer.
- **Data risk**: None.
- **User impact**: Users with low-vision, color-blind, or in bright ambient light cannot reliably distinguish disabled fields. BlackRock accessibility-committee compliance gap.

### Solution Options

#### Option A: Codemod the 16 remaining sites (RECOMMENDED)
**Description**: Apply mechanical replacement: `disabled:opacity-50` → `disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))] disabled:border-[hsl(var(--disabled-border))] disabled:cursor-not-allowed`. For inputs/textarea/composer use `text-foreground` → `text-[hsl(var(--disabled-foreground))]`; for buttons keep `disabled:bg`/`disabled:border` only.
**Changes required**:
- [ ] 16 file edits via `sed`-style codemod
- [ ] Snapshot regen for affected component tests
- [ ] Add the grep regression test specified by plan T-A-1-05 (a `__tests__/no-disabled-opacity-50.test.ts` that fails if any `disabled:opacity-50` reappears in `components/` or `app/`)
- [ ] Update component-level disabled-state stories for Storybook (if applicable)
**Effort**: Medium (≈ 30 min mechanical + tests).
**Risk**: Low.

#### Option B: Defer to Wave 3 (`PLAN-0059-F-5` — Polish)
**Description**: Mark the wave “tokens added; codemod application deferred to W3 polish.”
**Changes required**: Plan + TRACKING.md edit.
**Drawbacks**: Sub-AA disabled state ships to BlackRock demo; primitives (Switch/Checkbox) cascade everywhere.
**Effort**: Low.
**Risk**: HIGH — credibility gap on accessibility audit.

### Recommended Option
**Option A** — codemod now. The plan’s own acceptance criterion (“Grep across `components/` finds zero `disabled:opacity-50`”) was claimed met but is not. The fix is mechanical. Until shipped, the wave should not be marked DONE.

### Verification Steps
- [ ] `grep -rn "disabled:opacity-50" apps/worldview-web/{components,app}` returns 0 hits (excluding comments)
- [ ] Snapshot updates committed for all affected components
- [ ] Add and run `apps/worldview-web/__tests__/no-disabled-opacity-50.test.ts` — must pass

---

## Issue F-003: Wave A tokens not present in live container CSS bundle (BLOCKING for demo)

### Summary
The running `worldview-web` Docker container is 21 hours old (built 2026-04-29T15:11:34Z). Commit `99b8bcf7` was committed today (2026-04-30 14:07). `docker compose up -d --build worldview-web` reused cached layers and did not rebuild the Next.js bundle. The live `/_next/static/css/22d66598b18147ad.css` still ships the retired `--positive: 174 42% 40%` (TradingView teal) and `--negative: 0 63% 62%` (Material Red 400). Brand assets (`/icon.svg`, `/apple-icon.svg`, `/manifest.webmanifest`) all return 404.

### Severity / Confidence
**Severity**: BLOCKING (for demo)
**Confidence**: HIGH
**Flagged by**: Distributed Systems / Live Platform (LIVE-001, LIVE-004)

### Root Cause Analysis
- **What**: Docker image `worldview-worldview-web:latest` predates the Wave A commit. CSS hash `22d66598b18147ad.css` is the pre-Wave-A bundle.
- **Why**: `docker compose ... --build` is not equivalent to `docker compose ... build --no-cache`; Docker’s layer cache reuses the previous build outputs even when source files have changed if BuildKit doesn’t detect a host-level diff in the build context for the layer that runs `pnpm build`. In this monorepo, the build context likely caches the `pnpm install` + `next build` layer.
- **When**: After every Wave A commit, until a no-cache rebuild forces fresh `next build`.
- **Where**: Frontend deploy pipeline — Dockerfile + docker-compose `--build` semantics.

### Evidence
```
$ docker compose ps worldview-web --format "{{.Status}}"
Up 21 hours (healthy)

$ CSS_PATH=$(curl -s http://localhost:3001/ | grep -oE '/_next/static/css/[a-f0-9]+\.css' | head -1)
$ echo $CSS_PATH
/_next/static/css/22d66598b18147ad.css

$ curl -s "http://localhost:3001${CSS_PATH}" | grep -oE -- "--positive:[^;]+;"
--positive:174 42% 40%;          # OLD teal — Wave A retired this

$ grep -c "150 100% 41" /tmp/wv-new.css
0                                 # New token NOT present

$ curl -sI http://localhost:3001/icon.svg | head -1
HTTP/1.1 404 Not Found
```

After force-recreate (`up -d --force-recreate --no-deps`), the same CSS hash was served — confirming Docker layer cache is the culprit, not the container restart.

### Impact
- **Immediate**: Live site looks identical to pre-Wave-A; no Wave A visual upgrade is demonstrable.
- **Blast radius**: Any stakeholder visiting `localhost:3001` sees the old palette. Any Lighthouse / visual-regression snapshot taken now reflects the old state. The acceptance criteria in plan A-1 (“Visual smoke check: green/red feel ‘Bloomberg-grade’”) cannot be met.
- **Data risk**: None.
- **User impact**: Visual gap visible to anyone evaluating the platform.

### Solution Options

#### Option A: `docker compose build --no-cache worldview-web` then `up -d` (RECOMMENDED, in progress)
**Description**: Force a clean rebuild of the worldview-web image, ignoring layer cache.
**Changes required**:
- [ ] `docker compose -f infra/compose/docker-compose.yml build --no-cache worldview-web` (≈ 6–10 min)
- [ ] `docker compose -f infra/compose/docker-compose.yml up -d --force-recreate worldview-web`
- [ ] Re-verify CSS hash changes; new tokens appear; icon.svg/apple-icon.svg/manifest.webmanifest return 200
**Status**: A `--no-cache` rebuild was launched in this QA pass and is currently running in the background (task `b4cvftwnb`). It must complete before this issue can be marked closed.
**Effort**: Low (mechanical).
**Risk**: Low.

#### Option B: Add a `next build` cache-bust step to the Dockerfile
**Description**: Pre-Dockerfile change to invalidate the build-cache layer when `apps/worldview-web/app/globals.css` (or any source file) changes.
**Changes required**: Dockerfile audit; add `ARG GIT_SHA` or similar bust token; ensure `COPY apps/worldview-web` happens before build.
**Effort**: Medium (Dockerfile review).
**Risk**: Low.

### Recommended Option
**Option A** for this wave; **Option B** as a follow-up infra improvement so that future waves don’t hit the same trap.

### Verification Steps
- [ ] After `--no-cache` rebuild and restart: `curl -s http://localhost:3001/_next/static/css/<new-hash>.css | grep -- "--positive: 150 100% 41"` returns 1 hit
- [ ] `curl -sI http://localhost:3001/icon.svg` returns 200 with `image/svg+xml`
- [ ] `curl -sI http://localhost:3001/apple-icon.svg` returns 200
- [ ] `curl -sI http://localhost:3001/manifest.webmanifest` returns 200 with `application/manifest+json`
- [ ] Open `http://localhost:3001/dashboard` in a browser — green/red price indicators read as institutional, not teal/material-red.

---

## Issue F-004: Brand identity package 30% delivered — 7 of 10 artifacts missing (CRITICAL for demo)

### Summary
Plan T-A-1-07 specified 10 brand artifacts. Only 3 shipped. `public/` directory is empty; no raster favicons; no Open Graph image; no Twitter card image; no `brand/` directory. `app/layout.tsx` declares `metadata.openGraph` and `metadata.twitter` blocks but provides no `images:` arrays — social card previews on LinkedIn/Slack/Twitter will be blank.

### Severity / Confidence
**Severity**: CRITICAL (specifically for the BlackRock-grade credibility claim)
**Confidence**: HIGH
**Flagged by**: QA (QA-009), Architecture (ARCH-003), Visual (VIS-003)

### Root Cause Analysis
- **What**: Wave A shipped the “easy” trio (SVG icon + apple icon + manifest) but skipped the assets that require design tooling (raster icons + OG/Twitter cards + wordmark SVGs).
- **Why**: Each missing artifact requires either Figma/Sketch design work or a `sharp`-based build script; neither was set up in this wave.
- **When**: Always — until raster assets exist, Chrome PWA install prompt is broken; LinkedIn link previews are blank.
- **Where**: `public/`, `brand/`, `app/layout.tsx` metadata blocks.

### Evidence
| Artifact | Plan | Shipped? |
|----------|------|---------|
| `public/favicon.ico` | required | ❌ MISSING |
| `app/icon.svg` | required | ✅ shipped |
| `app/apple-icon.svg` (was `public/icon.svg`) | required | ✅ shipped |
| `public/icon-16.png` | required | ❌ MISSING |
| `public/icon-32.png` | required | ❌ MISSING |
| `public/icon-180.png` | required | ❌ MISSING |
| `public/icon-192.png` | required (PWA install) | ❌ MISSING |
| `public/icon-512.png` | required (PWA install) | ❌ MISSING |
| `app/manifest.webmanifest` | required | ✅ shipped |
| `public/og-image.png` (1200×630) | required | ❌ MISSING |
| `public/og-image-square.png` | required | ❌ MISSING |
| `public/twitter-card.png` | required | ❌ MISSING |
| `brand/worldview-mark.svg` | required | ❌ MISSING |
| `brand/worldview-wordmark.svg` | required | ❌ MISSING |
| `brand/worldview-mark-mono.svg` | required | ❌ MISSING |
| `app/layout.tsx` `metadata.openGraph.images` | required | ❌ NOT SET |
| `app/layout.tsx` `metadata.twitter.images` | required | ❌ NOT SET |

`ls apps/worldview-web/public/` → only `.gitkeep`
`ls apps/worldview-web/brand/` → directory does not exist

Additional defect surfaced by Visual reviewer (VIS-004): `manifest.webmanifest` references `/apple-icon.svg`, but Next.js App Router serves the file at `/apple-icon` (no extension). The literal URL will 404 in production.

### Impact
- **Immediate**: PWA install button disabled in Chrome (no PNG ≥192px); LinkedIn/Slack/Twitter previews blank; bookmark in Chrome may show generic placeholder; print PDF has no logo.
- **Blast radius**: First impression for every external evaluator.
- **Data risk**: None.
- **User impact**: Direct credibility gap — the master report’s §1.2 claim of “polished consumer fintech, drifting” is exactly the gap this task was supposed to close.

### Solution Options

#### Option A: Generate missing assets via `sharp`-driven build script (RECOMMENDED)
**Description**: Add `apps/worldview-web/scripts/generate-brand-assets.mjs` that:
1. Renders `public/icon-{16,32,180,192,512}.png` from `app/icon.svg` via `sharp`
2. Composes `public/og-image.png` (1200×630) and `public/twitter-card.png` (1200×600) from a wordmark + tagline template
3. Outputs `public/favicon.ico` (multi-size .ico)
**Changes required**:
- [ ] Add `sharp` devDep
- [ ] Create the generation script
- [ ] Run script as a `prebuild` hook in `package.json`
- [ ] Update `app/layout.tsx` metadata to include `openGraph.images: [{ url: '/og-image.png', width: 1200, height: 630, alt: 'Worldview — institutional market intelligence' }]` + `twitter.images: ['/twitter-card.png']`
- [ ] Fix manifest.webmanifest icon URLs to omit `.svg` extension or move SVG into `public/`
- [ ] Hand-design `brand/worldview-{mark,wordmark,mark-mono}.svg` (one-time design task; can be a follow-up if a designer is unavailable)
**Effort**: Medium (≈ 1–2h script + 1h design).
**Risk**: Low.

#### Option B: Demote T-A-1-07 to PARTIAL in plan/TRACKING.md
**Description**: Acknowledge gap; defer to a Wave A-completion patch.
**Changes required**: Documentation only.
**Drawbacks**: BlackRock-grade credibility claim is unmet during this period.
**Effort**: Low.
**Risk**: Medium (the demo timeline).

### Recommended Option
**Option A** — even partial completion (rasters + OG image, deferring brand/*.svg) closes 80% of the demo-visible gap.

### Verification Steps
- [ ] `ls apps/worldview-web/public/` shows favicon.ico + icon-{16,32,180,192,512}.png + og-image.png + twitter-card.png
- [ ] `curl -sI http://localhost:3001/og-image.png` returns 200
- [ ] LinkedIn share preview (or `https://www.linkedin.com/post-inspector/`) renders the OG image
- [ ] Chrome → Install Worldview as App → install button enabled
- [ ] `app/layout.tsx` metadata blocks include `images:` arrays

---

## Issue F-005: T-A-2-02 CI gates not installed — `depcheck`/`knip`/`bundlewatch`/`@lhci/cli` missing (MAJOR)

### Summary
T-A-2-02 specified five CI gates: ESLint `no-explicit-any: error` + `depcheck` + `knip` + `bundlewatch` + Lighthouse CI. Only the ESLint slice landed. The four binaries are NOT installed, no `bundlewatch.config.json`, no `.lighthouserc.json`. The plan’s own Wave A-3 validation gates (“`pnpm exec depcheck` exits 0”, “`pnpm exec knip` exits 0”) cannot pass.

### Severity / Confidence
**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: QA (QA-011), Architecture (ARCH-006)

### Root Cause Analysis
- **What**: Four devDeps + two config files + CI yaml additions not shipped.
- **Why**: T-A-2-02 was scoped large (CI infrastructure for an entire wave) and only the lowest-friction item (ESLint config tweak) was completed.
- **When**: A-3 validation gate is silently broken.
- **Where**: `apps/worldview-web/package.json`, `apps/worldview-web/bundlewatch.config.json` (missing), `apps/worldview-web/.lighthouserc.json` (missing), `.github/workflows/ci.yml` (no new jobs).

### Evidence
```
$ grep -E '"depcheck"|"knip"|"bundlewatch"|"@lhci/cli"|"lighthouse-ci"' apps/worldview-web/package.json
(no matches)

$ ls apps/worldview-web/bundlewatch.config.json apps/worldview-web/.lighthouserc.json 2>&1
ls: cannot access ...: No such file or directory
```

### Impact
- **Immediate**: Plan’s A-3 gate `pnpm exec depcheck` fails with `command not found`. Future bundle-size regressions will not be caught. Future dead-export regressions will not be caught.
- **Blast radius**: Wave G (Plan §G — performance) depends on these gates being live; without them, perf regressions creep in undetected.
- **Data risk**: None.
- **User impact**: Indirect (performance / bundle bloat).

### Solution Options

#### Option A: Land all four tools + configs + CI jobs in this wave (RECOMMENDED)
**Description**: Bundle into a single Wave A-completion patch.
**Changes required**:
- [ ] `pnpm add -D depcheck knip bundlewatch @lhci/cli`
- [ ] Create `bundlewatch.config.json` with route budgets per plan (`/dashboard < 220KB gz`, etc.)
- [ ] Create `.lighthouserc.json` with LCP/CLS/Perf thresholds
- [ ] Add CI jobs for each gate
- [ ] Run all four locally; resolve any current dep-check / knip / bundle violations
**Effort**: Medium (≈ 2h).

#### Option B: Defer to Wave G (Performance)
**Description**: Accept the gap; document deferral.
**Changes required**: Plan + TRACKING.md edit.
**Drawbacks**: Wave A’s claimed acceptance gates remain broken; A-3 status is misleading.

### Recommended Option
**Option A** — these are foundational guards meant to be in place BEFORE the dependent waves create bundle regressions.

### Verification Steps
- [ ] `pnpm exec depcheck` exits 0
- [ ] `pnpm exec knip` exits 0
- [ ] `pnpm exec bundlewatch` exits 0 (after committing budgets)
- [ ] CI runs all four gates green on next PR

---

## Issue F-006: `next.config.ts` missing `experimental.reactCompiler: true` (MAJOR)

### Summary
T-A-2-05 explicitly listed `experimental.reactCompiler: true` as part of the config tuning; the test list included `test_react_compiler_enabled`. The shipped `next.config.ts` has only `optimizePackageImports`, `compiler.removeConsole`, and `productionBrowserSourceMaps`. React Compiler (auto-memoization) was the primary perf win of this task.

### Severity / Confidence
**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: QA (QA-014), Architecture (ARCH-004)

### Evidence
```
$ grep "reactCompiler" apps/worldview-web/next.config.ts
(no matches)

# Plan T-A-2-05 What to build:
# experimental: {
#   reactCompiler: true,
#   optimizePackageImports: [...]
# }
```

### Impact
- W4 (Plan §G) perf budgets will be measured against the wrong baseline (un-memoized).
- React 19 / Compiler auto-memoization not active; manual `useMemo` / `React.memo` patterns must be added later for the same effect.

### Solution
Either (a) enable it now and install `babel-plugin-react-compiler`, or (b) update the plan to formally defer with reason. Recommend (a).

### Verification
- [ ] `next.config.ts` has `experimental.reactCompiler: true`
- [ ] `next build` succeeds with the flag
- [ ] React DevTools Profiler shows Compiler-injected `_useMemo` / `_useCallback` calls

---

## Issue F-007: `tsconfig.json` missing `verbatimModuleSyntax: true` (MAJOR)

### Summary
T-A-2-06 specified three flags: `noImplicitOverride`, `noFallthroughCasesInSwitch`, `verbatimModuleSyntax`. Only the first two shipped.

### Severity / Confidence
**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: QA (QA-015), Architecture (ARCH-005)

### Evidence
```
$ grep -E "verbatimModuleSyntax" apps/worldview-web/tsconfig.json
(no matches)
```

### Impact
- TS imports cannot be cleanly distinguished between value / type imports → larger bundles, slower TS server, future Bun/edge-runtime compatibility risk.
- Plan acceptance criterion “Three new flags present” unmet.

### Solution
Add `"verbatimModuleSyntax": true`; expect 10–30 mechanical `import` → `import type` fixes; resolve in same patch.

---

## Issue F-008: `feedback/page.tsx` retains `bg-blue-500/10`/`bg-emerald-500/10` (MAJOR)

### Summary
T-A-1-04 acceptance criterion: zero hits of `text-blue-/text-amber-/text-yellow-/bg-blue-` etc. in `components/`/`app/` outside `app/login` and `app/error` allowlist. Shipped: 2 violations in `app/feedback/page.tsx:47,49`.

### Severity / Confidence
**Severity**: MAJOR
**Confidence**: HIGH
**Flagged by**: Architecture (ARCH-002), Visual (VIS-001)

### Evidence
```ts
// apps/worldview-web/app/feedback/page.tsx:47-49
const STATUS_COLOR = {
  planned:  "bg-blue-500/10 text-blue-400",      // ← off-token
  shipped:  "bg-emerald-500/10 text-emerald-400", // ← off-token
  ...
};
```

The `no-restricted-classnames` ESLint rule specified by the plan was also not added — no regression guard exists.

### Solution
- Replace `planned` colors with `bg-[hsl(var(--accent-ai)/0.1)] text-[hsl(var(--accent-ai))]`
- Replace `shipped` colors with `bg-[hsl(var(--positive)/0.1)] text-[hsl(var(--positive))]`
- Add the `no-restricted-classnames` ESLint rule with `app/login`+`app/error` allowlist

---

## Issue F-009: Test coverage shortfall — only ~5 of ~30 specified Wave A tests shipped (CRITICAL)

### Summary
Plan A-3 validation gate: “All Wave A-1 + A-2 tests pass (~30 new tests).” Actually shipped: ~5 net-new tests (forbidden-hex regression in `utils.test.ts`, plus a few minor tweaks). Missing: token contrast tests, color-token resolution tests, accessibility media-query tests, brand identity tests, sonner toaster tests, UtcClock hydration tests, next.config flag tests, orphan-check tests.

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH
**Flagged by**: QA (QA-001..016)

### Coverage by task
| Task | Specified tests | Shipped | Coverage |
|------|----------------:|--------:|---------:|
| T-A-1-01 muted-fg sync | 2 | 0 | 0% |
| T-A-1-02 color tokens | 6 | 0 | 0% |
| T-A-1-03 heatCellColor | 8 | 5 | 63% |
| T-A-1-04 amber codemod | 3 | 0 | 0% |
| T-A-1-05 disabled tokens | 3 | 0 | 0% |
| T-A-1-06 a11y media queries | 4 | 0 | 0% |
| T-A-1-07 brand identity | 4 | 0 | 0% |
| T-A-2-01 sonner Toaster | 3 | 0 | 0% |
| T-A-2-02 CI gates | 4 | 0 | 0% |
| T-A-2-03 Sentry | 5 | 0 | DEFERRED |
| T-A-2-04 UtcClock hydration | 3 | 0 | 0% |
| T-A-2-05 next.config | 3 | 0 | 0% |
| T-A-2-06 tsconfig stage 1 | — | — | — |
| T-A-2-07 orphan check | 2 | 0 | 0% |
| **Total** | **~30** | **~5** | **~17%** |

### Solution
Land the missing tests in a Wave A-completion patch alongside the corresponding fixes from F-001 through F-008. The combined patch is the only way to honestly mark Wave A DONE.

---

## Issue F-010: Live `/v1/fundamentals/screen` GET 500 (BLOCKING for demo, NOT a Wave A regression)

### Summary
`GET /v1/fundamentals/screen` returns 500 because the market-data service routes `/api/v1/fundamentals/{instrument_id}` BEFORE the literal `/api/v1/fundamentals/screen`, so the literal `screen` is parsed as a UUID → asyncpg DataError. The frontend Screener page will fail to load.

### Severity / Confidence
**Severity**: BLOCKING (for the Bloomberg-grade demo claim)
**Confidence**: HIGH
**Flagged by**: Distributed Systems / Live Platform (LIVE-002)

### Evidence
```
$ curl -i -H "Authorization: Bearer $DEV_TOKEN" http://localhost:8000/v1/fundamentals/screen
HTTP/1.1 500 Internal Server Error
{"detail":"internal server error"}

market-data-1 logs:
asyncpg.exceptions.DataError: invalid input for query argument $1:
  'screen' (invalid UUID 'screen': length must be between 32..36 chars, got 6)

# Workaround confirms route exists:
$ curl -X POST -H "..." http://localhost:8000/v1/fundamentals/screen -d '{...}' → 200
$ curl http://localhost:8000/v1/fundamentals/screen/fields → 200
```

### Solution
In market-data router: declare `/fundamentals/screen` and `/fundamentals/screen/fields` BEFORE `/fundamentals/{instrument_id}`. Or constrain `{instrument_id}` to UUID-only via FastAPI path param regex / Pydantic `UUID` type.

### Note
This is **not** a Wave A regression — the bug pre-existed. But the Bloomberg-grade demo cannot ship while a core endpoint 500s.

---

## Issue F-011: Live `/v1/quotes/stream` 500 — should not be exposed yet (CRITICAL, NOT a Wave A regression)

### Summary
`GET /v1/quotes/stream` is registered in api-gateway and returns 500 (downstream market-data 500). Per master report §2 the WebSocket `/v1/quotes/stream` is Wave D (PLAN-0059-D) scope and should not exist yet. Registered-but-broken is worse than 404.

### Severity / Confidence
**Severity**: CRITICAL (NOT a Wave A regression)
**Confidence**: HIGH
**Flagged by**: Live (LIVE-003)

### Solution
Either remove route registration until Wave D ships, or stub to `503 not_implemented_yet`.

---

## Issue F-012: Live `/v1/auth/me` returns 503 oidc_unavailable (MAJOR)

### Summary
`/v1/auth/me` requires Zitadel OIDC introspection; in dev (where Zitadel is not configured), the route returns 503 even when a valid dev-login JWT is presented. Other protected routes accept the dev token. Frontend session-bootstrap code calling `/auth/me` will see 503 and may bounce the user.

### Severity / Confidence
**Severity**: MAJOR (NOT a Wave A regression)
**Confidence**: HIGH
**Flagged by**: Live (LIVE-005)

### Solution
Make `/v1/auth/me` fall back to decoding the local internal JWT and returning `{user_id, tenant_id, email}` when Zitadel is unavailable. The dev-login response already contains this shape.

---

## Issue F-013: CSP `'unsafe-inline'` deferred-without-pinned-wave (MINOR)

**Severity**: MINOR
**File**: `apps/worldview-web/next.config.ts:106`
**Issue**: TODO comment for nonce-based CSP exists ("upgrade to nonce-based CSP via Next.js Middleware when attack surface justifies it") but doesn’t name a specific wave/task. Master report F-CODE-NEW-011 names Wave 6.
**Fix**: Pin TODO to `// DEFERRED: PLAN-0059 Wave 6 (PLAN-0059-I) — see master report §F-CODE-NEW-011`.
**Auto-fixable**: YES.

---

## Issue F-014: `productionBrowserSourceMaps: true` ships without Sentry upload pipeline (MINOR)

**Severity**: MINOR
**File**: `apps/worldview-web/next.config.ts:55`
**Issue**: Sourcemaps published alongside JS reveal absolute build paths and unminified source. Comment says it's for Sentry; Sentry upload not wired (T-A-2-03 deferred).
**Fix**: Add `headers()` rule returning 404 for `/_next/static/**/*.map` until Sentry upload is wired, OR defer the flag until A-3.
**Auto-fixable**: YES.

---

## Issue F-015: WebSocket JWT still in URL (CRITICAL, NOT a Wave A regression)

**Severity**: CRITICAL
**File**: `apps/worldview-web/contexts/AlertStreamContext.tsx:160-163`
**Issue**: `new WebSocket('/v1/alerts/stream?token=' + ws_token)` — token leaks to logs/Referer/process tables. Master report F-CODE-008.
**Note**: Untouched by Wave A — pre-existing, deferred to PLAN-0059-D-3 (S9 alerts WS proxy with subprotocol auth).
**Fix**: Move to `Sec-WebSocket-Protocol` subprotocol header; coordinated S10 + frontend change.

---

## Issue F-016: NEXT_PUBLIC_WS_BASE_URL prod-warn-only (MINOR)

**Severity**: MINOR
**File**: `apps/worldview-web/next.config.ts:18-24`
**Issue**: Production deploy with default `ws://` only logs a `console.warn` from `next.config.ts`; a misconfigured prod build still ships plaintext WebSocket carrying a JWT.
**Fix**: Promote to a build-time `throw new Error(...)` for `NODE_ENV==="production" && scheme==="ws://"`.
**Auto-fixable**: YES.

---

## Issue F-017: Stale palette comments in `lib/utils.ts` (MINOR)

**Severity**: MINOR
**File**: `apps/worldview-web/lib/utils.ts:231-232`
**Issue**: Inline comments still annotate `--positive = #26A69A` and `--negative = #EF5350` (pre-Wave-A values). After Wave A these are `#00D26A` / `#FF3B5C`. Misleads future maintainers.
**Fix**: Update or drop the trailing-comment hex annotations.
**Auto-fixable**: YES.

---

## Issue F-018: `prefers-contrast: more` block under-bumps price colors (MINOR)

**Severity**: MINOR
**File**: `apps/worldview-web/app/globals.css:380-386`
**Issue**: High-contrast block bumps `--foreground`/`--muted-foreground`/`--border` but leaves `--positive`/`--negative`/`--primary` at default chroma. The print block (lines 388+) correctly darkens them; the high-contrast block should mirror that pattern.
**Fix**: Add boosted-luminance variants for the price/brand tokens inside the `prefers-contrast: more` block.
**Auto-fixable**: YES.

---

## Issue F-019: `--accent-ai-fill` comment hex doesn’t match HSL (NIT)

**Severity**: NIT
**File**: `apps/worldview-web/app/globals.css:138`
**Issue**: `--accent-ai-fill: 268 75% 50%; /* #8E44CE */` — `hsl(268 75% 50%)` is `#9233D9`, not `#8E44CE`.
**Fix**: Recompute or recolor.
**Auto-fixable**: YES.

---

## Issue F-020: AlertStream silent-swallow of malformed S10 frames (NIT)

**Severity**: NIT
**File**: `apps/worldview-web/contexts/AlertStreamContext.tsx:174-177`
**Issue**: `try/catch {}` with comment "Logging would be appropriate here in production" — no log emitted.
**Fix**: `console.warn("[AlertStream] malformed S10 frame", { sample: String(event.data).slice(0,200) })` (bounded length avoids token leak); will flow to Sentry once T-A-2-03 ships.
**Auto-fixable**: YES.

---

## Wave A Task-by-Task Status Roll-up

| Task | Status | Coverage notes |
|------|:------:|---------------|
| T-A-1-01 sync `.dark --muted-foreground` | **FULL** | Both blocks at `240 4% 55%`; computed contrast 5.55:1 vs `#09090B` (passes AA). 0 tests. |
| T-A-1-02 token replacements + `--accent-ai` | **FULL** | All 6 tokens correct in `:root` + `.dark`; positive/negative fills present. 0 tests. |
| T-A-1-03 `heatCellColor()` rewrite | **FULL** | CSS-var derived, retired hex purged, regression guard test added. 5 of 8 specified tests. |
| T-A-1-04 amber/blue replacement + ESLint rule | **PARTIAL** | `feedback/page.tsx:47-49` still has off-token blue/emerald; `no-restricted-classnames` rule MISSING. 0 tests. |
| T-A-1-05 disabled tokens | **PARTIAL** | Tokens added to globals.css; only `button.tsx` migrated; **16 sites still violate**. 0 tests. |
| T-A-1-06 a11y media queries | **FULL** | All 4 blocks present and well-formed. 0 tests. |
| T-A-1-07 brand identity (10 artifacts) | **PARTIAL** | 3 of 10 shipped (icon.svg, apple-icon.svg, manifest); raster + OG/Twitter + brand/* missing; OG/Twitter `images:` arrays not set; manifest references wrong icon URL. 0 tests. |
| T-A-2-01 dead deps + sonner | **FULL** | 3 dead deps removed, `sonner@1.7.4` mounted. 0 tests. |
| T-A-2-02 depcheck/knip/bundlewatch/lhci + ESLint | **PARTIAL** | Only ESLint `no-explicit-any: error`; 4 CI tools and 2 config files MISSING. 0 tests. |
| T-A-2-03 Sentry wiring | **DEFERRED** | Acknowledged; blocks observability of upcoming waves. 0 tests. |
| T-A-2-04 UtcClock hydration fix | **FULL** | Empty SSR + `useEffect` populate; clean fix. 0 tests. |
| T-A-2-05 `next.config.ts` tuning | **PARTIAL** | `optimizePackageImports`✓, `removeConsole`✓, `productionBrowserSourceMaps`✓; `experimental.reactCompiler: true` MISSING. 0 tests. |
| T-A-2-06 tsconfig stage 1 | **PARTIAL** | 2 of 3 flags (`noImplicitOverride`, `noFallthroughCasesInSwitch`); `verbatimModuleSyntax` MISSING. |
| T-A-2-07 delete legacy Sidebar + CI guard | **PARTIAL** | File deleted ✓; `scripts/check-orphans.ts` + `worldview/no-orphan-shell-components` ESLint rule MISSING. |

| Status | Count | % |
|--------|:-----:|:-:|
| FULL | 5 | 36% |
| PARTIAL | 8 | 57% |
| DEFERRED | 1 | 7% |
| MISSED | 0 | 0% |

---

## Comparison to Master Remediation Report Goals

The master report §2 listed 17 cross-section CRITICAL signals to be closed across Waves W0–W7. Wave A’s scope was the four W0 items + the brand package. Mapping:

| Cross-section signal | Wave | Status after Wave A |
|----------------------|:----:|---------------------|
| #26A69A is TradingView teal, not Bloomberg green | W0 | **CLOSED at source** — pending live-bundle rebuild |
| Heat scale uses retired Bloomberg Dark palette | W0 | **CLOSED at source** — pending live-bundle rebuild |
| Silent `:root`/`.dark` drift on `--muted-foreground` (WCAG) | W0 | **CLOSED at source** — pending live-bundle rebuild |
| Three dead npm dependencies | W0 | **CLOSED** (`react-grid-layout`, `react-resizable`, `@radix-ui/react-toast` removed; `sonner` mounted) |
| No brand identity | W0 | **PARTIAL** — 3 of 10 artifacts; OG/Twitter previews still blank |
| No real-time WebSocket quote stream | W2 | **OPEN** — Wave D scope |
| Hand-typed types/api.ts drift risk | W1 | **OPEN** — Wave C scope |
| Three different B/M/T compaction implementations | W1 | **OPEN** — Wave C scope |
| God-pages portfolio/chat actively growing | W2 | **OPEN** — Wave E scope |
| shadcn defaults shadowed by ad-hoc h-6/text-[11px] | W1 | **OPEN** — Wave F scope |
| Three chart libraries (lw-charts + recharts + sigma) | W3 | **OPEN** — Wave G scope |
| No URL state for filters/tabs/periods | W1 | **OPEN** — Wave C scope |
| TanStack Query keys scattered (169 declarations) | W1 | **OPEN** — Wave C scope |
| No ContextMenu primitive | W3 | **OPEN** — Wave F scope |
| Dead StatusBar chord shortcuts | W1 | **OPEN** — Wave B scope |
| No global symbol input | W1 | **OPEN** — Wave B scope |
| No command palette superset | W1 | **OPEN** — Wave B scope |
| Hardcoded USD; multi-currency unsupported | W1 | **OPEN** — Wave C scope |

**Wave A goal achievement**: 4 of 5 W0 signals closed at source (visual + dep hygiene), 1 partially closed (brand). Approximately **80% of the Wave 0 source-level expectations met**, dropping to **~70% when accounting for the typecheck regression and the test-coverage shortfall**.

**Bloomberg-grade competitor readiness verdict**: NOT YET READY. The platform has genuine institutional-grade backend depth (10 services healthy, 27 Kafka topics, real news flowing, prediction markets, fundamentals, alerts, RAG chat) but the frontend is currently:
- Showing pre-Wave-A palette in the live container (cache problem)
- Running on a typecheck-broken commit
- Still has 16 disabled-state WCAG-AA failures
- Missing 7 brand assets that show on the *first impression* every demo audience has

Once F-001..F-005 are addressed in a Wave A-completion patch, the Wave A foundation will be genuinely complete and ready to enable Waves B/C/D/E/F.

---

## Supplementary Checks

| Check | Status | Notes |
|-------|--------|-------|
| Import Guards | NOT RUN | Frontend-only Wave; no Python touched |
| Service Structure | NOT RUN | Frontend-only Wave |
| Avro Schema Validation | NOT RUN | No schema changes in this commit |
| Doc Freshness | WARN | Plan/TRACKING.md mark Wave A ✅ but should be `~PARTIAL` per findings above |
| Security Scan | PASS | No new injection / XSS / secret-leak vectors; SVG assets verified clean |
| Dependency Check | WARN | 4 plan-required devDeps not installed (depcheck/knip/bundlewatch/lhci) |
| Live Health | PASS | 54 / 54 containers healthy |

---

## Recommendations (priority-ordered)

1. **(BLOCKING)** Apply F-001 fix: extract `ERROR_MESSAGES` to `app/callback/error-messages.ts` so `pnpm typecheck` exits 0. Verify on CI.
2. **(BLOCKING for demo)** Complete `--no-cache` rebuild + force-recreate `worldview-web` container; verify Wave A tokens are in the live CSS bundle and brand assets return 200 (F-003). The rebuild is currently running in the background.
3. **(CRITICAL)** Codemod the remaining 16 `disabled:opacity-50` sites (F-002). Add the grep regression test specified by the plan.
4. **(CRITICAL)** Generate the missing 7 brand assets — at minimum favicon.ico + icon-{192,512}.png + og-image.png + twitter-card.png — and wire `metadata.openGraph.images` + `metadata.twitter.images` (F-004). Fix `manifest.webmanifest` icon URLs.
5. **(MAJOR)** Land the 4 missing CI gates (F-005) so plan A-3 can be honestly green.
6. **(MAJOR)** Close the small config gaps: F-006 (`reactCompiler`), F-007 (`verbatimModuleSyntax`), F-008 (`feedback/page.tsx` blue/emerald), F-013 (CSP TODO pinning), F-014 (sourcemap public-serving), F-016 (prod-`ws://` build-time fail).
7. **(CRITICAL)** Fix backend bugs that block the demo: F-010 (`/v1/fundamentals/screen` 500), F-011 (`/v1/quotes/stream` registered-but-broken), F-012 (`/v1/auth/me` 503 oidc_unavailable). These are pre-existing, not Wave A regressions, but block the Bloomberg-grade demo.
8. **(MAJOR)** Land the missing ~25 Wave A tests (F-009) before declaring A-3 complete.
9. **(plan hygiene)** Update `docs/plans/0059-frontend-institutional-remediation-master-plan.md`: mark Wave A as **PARTIAL** with explicit deferral notes for T-A-1-04, T-A-1-05, T-A-1-07, T-A-2-02, T-A-2-03, T-A-2-05, T-A-2-06, T-A-2-07. Update `docs/plans/TRACKING.md` accordingly.
10. **(BUG_PATTERNS update)** Add a new pattern: **BP-NEW-X — Docker layer cache silently serves stale frontend bundle**: `--build` is not equivalent to `build --no-cache`; CSS hash is the canary; verify with `curl /_next/static/css/*.css | grep <new-token>` after every visual deploy.

---

## Compounding Step

| Document | Update needed | Reason |
|----------|--------------|--------|
| `docs/BUG_PATTERNS.md` | YES — add BP-NEW-X (Docker stale frontend bundle), BP-NEW-Y (Next.js page export collides with PageProps `never` constraint) | Both surfaced this pass; will recur |
| `docs/plans/0059-frontend-institutional-remediation-master-plan.md` | YES — mark Wave A as PARTIAL; add explicit deferral notes per task | Plan currently misrepresents completion state |
| `docs/plans/TRACKING.md` | YES — set PLAN-0059-A QA column to 2026-04-30; status PARTIAL/FAIL | Per skill compounding requirement |
| `RULES.md` | NO | No new rule warranted |
| `.claude/review/checklists/REVIEW_CHECKLIST.md` | YES — add: “Frontend: verify CSS hash changes after visual deploy; verify deploy with `curl /_next/static/css/*.css | grep <new-token>`” | Catch BP-NEW-X earlier |
| `apps/worldview-web/.claude-context.md` | NO (no path change) | Wave A didn’t change architecture |
| `MEMORY.md` | YES — add: Docker `--build` ≠ `--no-cache` for Next.js standalone bundles; rebuild canary = CSS hash | Cross-session retention |

---

## Verdict

**FAIL** — Wave A is approximately 70% complete and cannot be honestly marked DONE. The plan’s own A-3 validation gate is currently red (`pnpm typecheck` fails) and the live container does not reflect any Wave A changes (`--no-cache` rebuild required). The token surgery, a11y media queries, sonner Toaster, UtcClock fix, and the CSS-source upgrades are excellent and ship-quality; everything else listed here is a Wave A-completion patch away from genuine completion. Recommend a focused 4–6 hour Wave A-completion sprint addressing F-001 through F-008 before Waves B/C/D/E/F kick off.
