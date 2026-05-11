# PLAN-0052 — New Surfaces: Landing, Docs, Feedback (Phase 4)

**Status**: in-progress
**PRD source**: `docs/audits/2026-04-28-qa-frontend-design-roadmap.md` (PART B + PART D, Phase 4)
**Created**: 2026-04-28
**Estimated effort**: 3 weeks (≈100h)
**Depends on**: **PLAN-0049 complete** (shared components). Independent of PLAN-0050/0051 — runs in parallel.

## Goal

Ship three new product surfaces:
1. **Landing page** redesign — competitive with Bloomberg / IBKR / TradingView marketing sites
2. **Documentation hub** at `/docs` — MDX-driven, full sidebar nav, cmd-K search
3. **Feedback system** — multi-channel (in-app modal, NPS, micro-surveys, beta program, public roadmap, admin dashboard)

## Wave A — Landing Page Redesign (~24h) ✅

**Status**: **DONE** — 2026-05-01 · 25 landing tests pass (1046 total) · ruff/lint + typecheck + production build clean (9.97 kB landing page, 125 kB First Load JS)

**Goal**: Replace current minimal landing at `/` with 11-section marketing experience.

**Tasks**:
- **T-A-1-01** ✅ (impl, M) — `<HeroSection>`: tagline + 2 CTAs + animated terminal mock with macOS chrome + LIVE dot
- **T-A-1-02** ✅ (impl, S) — `<LiveDataStrip>`: 6 mock tickers (SPY/QQQ/VIX/BTC/TLT/GLD) with pulsing live-dot
- **T-A-1-03** ✅ (impl, S) — `<SectorHeatmapPreview>`: 6-tile SPDR snapshot using shared `heatCellColor` 7-step gradient
- **T-A-1-04** ✅ (impl, S) — `<DifferentiatorsSection>`: 3-column News / KG / Multi-source aggregation
- **T-A-1-05** ✅ (impl, M) — `<WorkflowSection>`: ordered list Discover → Analyze → Track → Act with step badges + connector line
- **T-A-1-06** ✅ (impl, M) — `<AIDemoSection>`: example NVDA question + cited grounded answer + 3-citation Sources box
- **T-A-1-07** ✅ (impl, M) — `<ComparisonTable>`: Worldview vs Bloomberg / IBKR / TradingView / Finviz, 8 features + price row
- **T-A-1-08** ✅ (impl, S) — `<TrustBadges>`: 5 data sources with role labels + trademark disclaimer
- **T-A-1-09** ✅ (impl, M) — `<PricingTiers>`: Free / Pro / Enterprise + monthly/annual toggle (default annual −17%)
- **T-A-1-10** ✅ (impl, S) — `<Testimonials>`: 3 persona scenarios (no fake customer quotes — honest framing)
- **T-A-1-11** ✅ (impl, S) — `<FAQAccordion>`: 10 hardcoded Q&A with shadcn Accordion (radix-accordion wrapper added)
- **T-A-1-12** ✅ (impl, S) — `<Footer>`: 5-column nav (Brand / Product / Resources / Company / Legal) + status badge
- **T-A-1-13** ✅ (test) — Vitest unit tests (25) + Playwright `e2e/landing.spec.ts` (responsive 1920/1280/768/480, JSON-LD, sitemap, robots)
- **T-A-1-14** ✅ (config) — JSON-LD Organization + WebSite + FAQPage in `app/page.tsx`; `app/sitemap.ts` + `app/robots.ts`

**Files added**:
- `apps/worldview-web/components/landing/{HeroSection,LiveDataStrip,SectorHeatmapPreview,DifferentiatorsSection,WorkflowSection,AIDemoSection,ComparisonTable,TrustBadges,PricingTiers,Testimonials,FAQAccordion,Footer,LandingNav,FinalCTA}.tsx`
- `apps/worldview-web/components/ui/accordion.tsx`
- `apps/worldview-web/app/sitemap.ts`
- `apps/worldview-web/app/robots.ts`
- `apps/worldview-web/__tests__/landing.test.tsx`
- `apps/worldview-web/e2e/landing.spec.ts`

**Files modified**:
- `apps/worldview-web/app/page.tsx` — composed sections + JSON-LD

**Validation**:
- [x] pnpm typecheck — clean
- [x] pnpm lint — no errors in landing/* (only pre-existing PLAN-0059-C queryKey migration warnings)
- [x] pnpm test — 1046/1046 pass (97 files), 25 new landing tests
- [x] pnpm build — production build green; static pre-render of all 25 routes including /sitemap.xml + /robots.txt

**Depends_on**: PLAN-0049 complete
**Effort**: 24h

---

## Wave B — Documentation Hub `/docs` Foundation (~26h) ✅

**Status**: **DONE** — 2026-05-01 · 16 docs tests pass (1081 total) · ruff/lint + typecheck + production build clean (5 SSG-prerendered docs routes, 4.72 kB / 120 kB FLJ)

**Goal**: MDX-driven docs site with sidebar nav, cmd-K search, TOC, breadcrumb, feedback widget.

**Tasks**:
- **T-B-2-01** ✅ (config) — Added `next-mdx-remote@5.0.0`, `rehype-pretty-code@0.14.1`, `shiki@1.29.2`, `fuse.js@7.1.0`, `gray-matter@4.0.3` (exact versions). `remark-gfm` already installed. **Skipped contentlayer** (deprecated, last release 2023) — replaced by `next-mdx-remote/rsc` which is the Vercel-recommended Next.js 15 App Router pattern.
- **T-B-2-02** ✅ (impl, M) — `app/docs/[[...slug]]/page.tsx` optional catch-all dynamic route with `generateStaticParams` (SSG every doc) + `lib/docs.ts` file-based loader (walks `content/docs/**/*.mdx`, frontmatter via `gray-matter`, in-memory cache, `getAllDocs`/`getDocBySlug`/`getSidebarSections`/`getSearchIndex`/`extractHeadings` with code-fence-aware regex)
- **T-B-2-03** ✅ (impl, M) — `app/docs/layout.tsx` 3-col grid (sidebar / content / TOC reserved) + `<DocsSidebar>` (`usePathname` active-link highlight, sticky-top scroll container, sections grouped by frontmatter `section`)
- **T-B-2-04** ✅ (impl, M) — `<DocsTableOfContents>` IntersectionObserver scroll-spy (rootMargin -80px / -66% so heading is "active" while in upper third of viewport, picks topmost intersecting)
- **T-B-2-05** ✅ (impl, M) — `<Callout>` (info/warn/tip with semantic-tinted left-border + icon), `<CodeBlock>` (clipboard copy + filename label, group-hover reveal + always-on for touch), `<DocsTabs>` + `<DocsTab>` (radix-grade ARIA tablist + tabpanel + storeKey localStorage), `<Steps>` + `<Step>` (numbered gutter badges, connector line); plus `mdxComponents` map themeing every HTML tag (h1-h4 with anchor-ID slug, p, ul/ol, code, table, blockquote, hr) — `slugify()` mirrors `extractHeadings()` so TOC anchors agree
- **T-B-2-06** ✅ (impl, S) — `<DocsBreadcrumb>` (Docs > segment > title with `aria-current=page`) + `<DocsFooter>` (Intl-formatted last-updated + edit-on-GitHub link via `NEXT_PUBLIC_REPO_URL`)
- **T-B-2-07** ✅ (impl, M) — `<DocsSearch>` cmd/ctrl-K dialog (radix Dialog), Fuse.js index with weighted keys (title×3 / description×2 / section×1 / body×1), threshold 0.35, ignoreLocation, top 8 matches, ↑↓/Enter keyboard nav, click + auto-close + router.push deep-link with `#hash` for heading anchors
- **T-B-2-08** ✅ (impl, S) — `<DocsFeedback>` thumbs up/down at every page footer; thumbs-up fires direct POST to `/api/v1/feedback/micro-survey` (Wave D endpoint), thumbs-down opens textarea + Send; soft-fail on network errors so reading isn't disrupted

**Files added**:
- `apps/worldview-web/lib/docs.ts` (file-based MDX loader with cache, sidebar grouping, search index, heading extraction)
- `apps/worldview-web/app/docs/layout.tsx` (3-col grid + header with cmd-K search)
- `apps/worldview-web/app/docs/[[...slug]]/page.tsx` (catch-all dynamic route, SSG, MDXRemote/RSC + remarkGfm + rehypePrettyCode/shiki "github-dark")
- `apps/worldview-web/components/docs/{DocsSidebar,DocsTableOfContents,DocsBreadcrumb,DocsFooter,DocsSearch,DocsFeedback}.tsx`
- `apps/worldview-web/components/docs/mdx/{Callout,CodeBlock,DocsTabs,Steps,components}.tsx`
- `apps/worldview-web/content/docs/{index,getting-started/index,api-reference/index,changelog,faq}.mdx` (5 seed pages — Wave C will author the full set)
- `apps/worldview-web/__tests__/docs.test.tsx` (16 vitest assertions — loader, sidebar, TOC, breadcrumb, MDX components, feedback POST contract, IntersectionObserver stub)
- `apps/worldview-web/e2e/docs.spec.ts` (Playwright: index, nested, 404, cmd-K open + result list, sidebar nav)

**Validation**:
- [x] pnpm typecheck — clean
- [x] pnpm lint — no errors in docs/* (only pre-existing PLAN-0059-C queryKey migration warnings)
- [x] pnpm test — 1081/1081 pass (100 files), 16 new docs tests
- [x] pnpm build — production build green; `/docs/[[...slug]]` SSG-prerendered for 5 routes (4.72 kB / 120 kB FLJ)

**Notes**:
- Followed shadcn/ui-only policy: only existing `Dialog` primitive + `Accordion` (added in Wave A) + lucide icons
- Heavy comments policy honored: every component has WHY-style header
- 2px radius policy honored throughout
- `disabled:opacity-50` policy honored (used semantic `--disabled-bg` / `--disabled-foreground` tokens on the Send-feedback button instead)

**Depends_on**: PLAN-0049
**Effort**: 26h

---

## Wave C — Documentation Content Authoring (~20h) ✅

**Status**: **DONE** — 2026-05-05 · 1805 frontend tests pass (158 files) · production build clean (50 SSG-prerendered docs routes, `[+47 more paths]` confirmed in Next.js build output)

**Goal**: Write the actual MDX content for ~50 doc pages. Can run in parallel with Wave B once foundations ship.

**Pages to write** (organized by sidebar section):
- Getting Started (5 pages): index, sign-up, workspace-tour, connect-brokerage, first-watchlist
- Dashboard (5): overview, widgets, ai-brief, alerts, keyboard-shortcuts
- Instruments (4): overview, fundamentals, news, intelligence-graph
- Portfolio (5): index, holdings, transactions, watchlists, allocation
- Screener (3): index, filters, saved-screens
- Alerts (5): index, rule-builder, price-alerts, news-alerts, channels
- Chat/AI (4): index, asking-questions, citations, slash-commands
- Workspace (4): index, panels, layouts, templates
- Data Sources (5): index, eodhd, finnhub, polymarket, sec-edgar
- API Reference (7): index, authentication, quotes, fundamentals, news, chat, error-codes
- FAQ (1)
- Changelog (1)

**Tasks** (one per major section):
- **T-C-3-01** ✅ Getting Started (5 pages): index (expanded), sign-up, workspace-tour, connect-brokerage, first-watchlist
- **T-C-3-02** ✅ Dashboard (5 pages): index, widgets, ai-brief, alerts, keyboard-shortcuts
- **T-C-3-03** ✅ Instruments (4 pages): index, fundamentals, news, intelligence-graph
- **T-C-3-04** ✅ Portfolio (5 pages): index, holdings, transactions, watchlists, allocation
- **T-C-3-05** ✅ Screener (3 pages): index, filters, saved-screens
- **T-C-3-06** ✅ Alerts (5 pages): index, rule-builder, price-alerts, news-alerts, channels
- **T-C-3-07** ✅ Chat & AI (4 pages): index, asking-questions, citations, slash-commands
- **T-C-3-08** ✅ Workspace (4 pages): index, panels, layouts, templates
- **T-C-3-09** ✅ Data Sources (5 pages): index, eodhd, finnhub, polymarket, sec-edgar
- **T-C-3-10** ✅ API Reference (7 pages): index (expanded), authentication, quotes, fundamentals, news, chat, error-codes
- **T-C-3-11** ✅ FAQ (expanded to 10 Q&A pairs)
- **T-C-3-12** ✅ Changelog (updated with v1.0.0 entry)

**Files added** (45 new + 5 updated seed pages = 50 total):
- `apps/worldview-web/content/docs/getting-started/{sign-up,workspace-tour,connect-brokerage,first-watchlist}.mdx`
- `apps/worldview-web/content/docs/dashboard/{index,widgets,ai-brief,alerts,keyboard-shortcuts}.mdx`
- `apps/worldview-web/content/docs/instruments/{index,fundamentals,news,intelligence-graph}.mdx`
- `apps/worldview-web/content/docs/portfolio/{index,holdings,transactions,watchlists,allocation}.mdx`
- `apps/worldview-web/content/docs/screener/{index,filters,saved-screens}.mdx`
- `apps/worldview-web/content/docs/alerts/{index,rule-builder,price-alerts,news-alerts,channels}.mdx`
- `apps/worldview-web/content/docs/chat/{index,asking-questions,citations,slash-commands}.mdx`
- `apps/worldview-web/content/docs/workspace/{index,panels,layouts,templates}.mdx`
- `apps/worldview-web/content/docs/data-sources/{index,eodhd,finnhub,polymarket,sec-edgar}.mdx`
- `apps/worldview-web/content/docs/api-reference/{authentication,quotes,fundamentals,news,chat,error-codes}.mdx`

**Files updated** (expanded from seeds):
- `apps/worldview-web/content/docs/getting-started/index.mdx`
- `apps/worldview-web/content/docs/api-reference/index.mdx`
- `apps/worldview-web/content/docs/faq.mdx`
- `apps/worldview-web/content/docs/changelog.mdx`

**Validation**:
- [x] pnpm test — 1805/1805 pass (158 files), all existing tests maintained
- [x] pnpm build — production build green; `/docs/[[...slug]]` SSG-prerendered for 50 routes (`[+47 more paths]` in build output)

**Depends_on**: Wave B (foundations)
**Effort**: 20h

---

## Wave D — Feedback System Backend + Schema (~14h) ✅

**Status**: **DONE** — 2026-04-29 · 66 new tests pass (17 PII + 22 use-case + 13 route + 14 proxy) · ruff + format clean

**Goal**: Postgres schema + S9 endpoints for feedback submissions, NPS, micro-surveys, feature requests.

**Tasks**:
- **T-D-4-01** (schema) — Alembic migration adding 6 tables: `feedback_submissions`, `nps_scores`, `feature_requests`, `feature_votes`, `micro_survey_responses`, `beta_enrollments`. All tenant-scoped with RLS. Decision D-3 from audit: extend api-gateway / portfolio_db, not new service.
- **T-D-4-02** (impl, M) — Pydantic schemas: `FeedbackSubmissionCreate`, `FeedbackSubmissionResponse`, `NPSSubmissionCreate`, `MicroSurveyCreate`, `FeatureRequestResponse` in `services/api-gateway/src/api_gateway/schemas/feedback.py`
- **T-D-4-03** (impl, M) — Endpoints: POST/GET/PATCH/DELETE `/v1/feedback/submissions`, POST `/v1/feedback/nps`, GET `/v1/feedback/nps/aggregate` (admin), GET/POST `/v1/feedback/features`, POST `/v1/feedback/features/{id}/vote`, POST `/v1/feedback/micro-survey`, GET/PATCH `/v1/feedback/beta-program/enrollment`
- **T-D-4-04** (impl, M) — PII redaction: regex blacklist for API keys / auth tokens / Bearer headers in description + console_logs JSONB. 90d S3 TTL on screenshots; 7d on console logs.
- **T-D-4-05** (test) — Contract tests for all 12 endpoints; PII redaction unit tests

**Depends_on**: PLAN-0049
**Effort**: 14h

---

## Wave E — Feedback System Frontend (~16h) ✅

**Status**: **DONE** — 2026-05-01 · 1,196/1,196 frontend tests pass · ruff/lint clean (errors-free for Wave E surface) · typecheck + production build clean

**Goal**: In-app modal + NPS prompt + micro-survey + admin dashboard + public roadmap.

**Tasks**:
- **T-E-5-01** ✅ (impl, S) — `<FeedbackButton>` floating bottom-right (56px circular) mounted in `(app)/layout.tsx`. QA-iter1: collapsed two parallel state slots into a single `prefill` shape with one reset path, replaced verbose `aria-label` with clean `"Send feedback"` + standard `aria-keyshortcuts="Meta+Shift+Slash Control+Shift+Slash"`, gated press-scale animation behind `motion-safe:`.
- **T-E-5-02** ✅ (impl, M) — `<FeedbackModal>` 5-tab Sheet (bug/feature/ux/general/contact). QA-iter1: `defaultDescription` prop + one-shot consume via `lastAppliedPrefillRef` so a parent re-render doesn't clobber user typing.
- **T-E-5-03** ✅ (impl, M) — `<ScreenshotCapture>` html2canvas with blur-toggle V1; data URI rides in `console_logs` JSON column under 1MB cap (presigned S3 upload deferred).
- **T-E-5-04** ✅ (impl, S) — `<ConsoleLogCapture>` last-50 entries with PII review and live IDE-style preview.
- **T-E-5-05** ✅ (impl, M) — `<NPSPrompt>` modal + `NPSPromptHost` shell-mounted listener for `worldview:request-nps` CustomEvent. QA-iter1: WAI-ARIA radiogroup keyboard model (roving tabindex + ArrowLeft/Right/Up/Down/Home/End + focus-visible ring), local state reset on dismiss/close (no stale score on re-open), skip redundant `markDismissed` after `submit.isSuccess`, `motion-safe:` on spinners.
- **T-E-5-06** ✅ (impl, S) — `<MicroSurvey>` inline thumbs widget (used by docs feedback widget — no changes from PLAN-0053 baseline).
- **T-E-5-07** ✅ (impl, S) — `/settings/beta-program` route (page + `<Switch>` toggle + `<textarea>` notes + Save button). New `useBetaEnrollment` + `usePatchBetaEnrollment` hooks (TanStack Query, registered under `qk.feedback.betaEnrollment` factory entry). New `getBetaEnrollment`/`patchBetaEnrollment` gateway methods + `BetaEnrollment`/`BetaEnrollmentPatch` types in `types/api.ts`. QA-iter1: notes-draft sync guarded with `lastSyncedNotesRef` so a 30s background refetch doesn't clobber mid-typed notes; resolved Switch htmlFor/aria-label conflict (kept the `<Label>` association); textarea focus ring upgraded to `ring-2 ring-offset-2`.
- **T-E-5-08** ✅ (impl, S) — `<FeedbackDeepLinkHandler>` Suspense-wrapped at the (app) shell. Reads `?feedback=<kind>&page=<X>`, dispatches `worldview:open-feedback` CustomEvent with `{tab, description}` detail (FeedbackButton listens). QA-iter1: dedup signature via `lastHandledRef` (StrictMode-safe), URL strip happens for invalid `kind` values too (no garbage refresh-loop), `window.location.hash` preserved through cleanup.
- **T-E-5-09** ✅ (impl, M) — `/feedback` public roadmap with feature requests list, upvote (idempotent), status/sort filters, "Suggest a feature" CTA opens FeedbackModal on the feature tab.
- **T-E-5-10** ✅ (impl, M) — `/admin/feedback` table with status/kind filters, per-row status edit, CSV export. QA-iter1: tri-state header checkbox (`role="checkbox"` + `aria-checked="mixed"` + distinct `MinusSquare` icon for partial state); per-row checkbox switched from button-toggle `aria-pressed` to checkbox-semantics `aria-checked`; bulk PATCH uses `Promise.allSettled` with per-row outcome surface + selection narrowed to failures + assertive aria-live error banner with `requestAnimationFrame` focus jump; CSV formula-injection escape (`'` prefix on cells starting with `[=+\-@\t\r]`); bulk toolbar visual separator + `Loader2` spinner consistency + density `p-3`; `qk.feedback.npsAggregate` factory.
- **T-E-5-11** ✅ (test) — `__tests__/feedback-wave-e.test.tsx` (7 vitest tests covering useBetaEnrollment auth gating + mutation, FeedbackButton CustomEvent prefill happy + invalid-tab fallback + manual-click reset). `e2e/feedback.spec.ts` (Playwright: public roadmap renders without auth, Suggest-a-feature opens feature tab, /admin/feedback + /settings/beta-program redirect when unauthed, deep-link on public route is no-op).

**Files added (Wave E iter-1)**:
- `apps/worldview-web/hooks/useBetaEnrollment.ts`
- `apps/worldview-web/app/(app)/settings/beta-program/page.tsx`
- `apps/worldview-web/components/feedback/FeedbackDeepLinkHandler.tsx`
- `apps/worldview-web/__tests__/feedback-wave-e.test.tsx`
- `apps/worldview-web/e2e/feedback.spec.ts`

**Files modified (Wave E iter-1)**:
- `apps/worldview-web/components/feedback/{FeedbackButton,FeedbackModal,NPSPrompt}.tsx`
- `apps/worldview-web/app/admin/feedback/page.tsx`
- `apps/worldview-web/app/(app)/layout.tsx` (Suspense + handler mount — landed via PLAN-0059 Wave I-A merge)
- `apps/worldview-web/lib/gateway.ts` + `apps/worldview-web/lib/query/keys.ts` + `apps/worldview-web/types/api.ts`

**Validation**:
- [x] pnpm typecheck — clean
- [x] pnpm lint — only pre-existing PLAN-0059-C migration warnings (no errors in Wave E surface)
- [x] pnpm test — 1,196/1,196 pass (107 files, 7 new wave-E tests)
- [x] pnpm build — production build green; `/settings/beta-program` (4.89 kB / 139 kB FLJ), `/admin/feedback` (10.3 kB / 164 kB FLJ), `/feedback` static-prerendered

**QA-iter1 closure** (5-agent parallel pass):
- 3 BLOCKING closed — deep-link StrictMode double-fire (B1), NPS radio keyboard nav (B-1), tri-state ARIA (B-2)
- 5 CRITICAL closed — notes-draft clobber (C1), bulk PATCH partial-failure (C-3), CSV formula injection (M-1 sec), noisy `role="status"` chip (C-1 a11y), missing `qk` factory entry (C-1 arch)
- 8 MAJOR closed — aria-label punctuation (M-1 a11y), Switch Label conflict (M-2 a11y), description nuke on prop change (M-2 bugs), invalid-kind URL leak (M-4 bugs), reduced-motion (M-3 a11y), bulk error focus mgmt (M-4 a11y), duplicate Notifications copy (#1 design — already removed by parallel commit), bulk toolbar separator + `Loader2` (#2/#3 design)
- Deferred (non-blocking polish): admin tagging (no API), screenshot presigned-S3 upload (out of scope), MINOR design items (icon size scaling, focus-ring tuning)

**Depends_on**: Wave D backend
**Effort**: 16h (planned) + ~6h iter-1 polish

---

## Wave Tracker

| Wave | Tasks | Effort |
|------|-------|--------|
| A — Landing page | 14 | 24h |
| B — Docs foundation | 8 | 26h |
| C — Docs content | 12 | 20h |
| D — Feedback backend | 5 | 14h |
| E — Feedback frontend | 11 | 16h |
| **Total** | **50** | **100h ≈ 3 weeks** |

Waves A, B, D can run fully in parallel (independent surfaces). Wave C depends on B; Wave E depends on D.

---

## Cross-Cutting

- **New endpoints**: 12 under `/v1/feedback/*` (Wave D)
- **Schema additions**: 6 new tables (Wave D)
- **New routes**: `/`, `/docs/[[...slug]]`, `/feedback`, `/admin/feedback`, `/settings/beta-program`
- **New deps**: next-mdx-remote, contentlayer, remark-gfm, rehype-pretty-code, shiki, fuse.js, html2canvas
- **Docs**: api-gateway.md (feedback endpoints), MASTER_PLAN.md (note new feedback subsystem)

## Risk

- **Wave A copy/design** may need 1-2 review iterations with the user — reserve buffer
- **Wave C** content authoring is time-consuming and easy to under-estimate; may overflow into PLAN-0053
- **Wave D PII redaction** must be airtight — security-audit pass required before merge
- **Wave E screenshot upload** — verify S3 bucket policy allows pre-signed PUT
