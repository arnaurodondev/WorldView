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

## Wave C — Documentation Content Authoring (~20h)

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
- **T-C-3-01** through **T-C-3-12** — Author MDX content for each section. Each task: ~2h.

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

## Wave E — Feedback System Frontend (~16h)

**Goal**: In-app modal + NPS prompt + micro-survey + admin dashboard + public roadmap.

**Tasks**:
- **T-E-5-01** (impl, S) — `<FeedbackButton>` floating bottom-right (56px circular) on all authenticated routes
- **T-E-5-02** (impl, M) — `<FeedbackModal>` form: type select, textarea (10-5000 chars), screenshot toggle, console-log toggle, optional email
- **T-E-5-03** (impl, M) — `<ScreenshotCapture>` using html2canvas; preview + blur tool; upload to S3 via pre-signed URL
- **T-E-5-04** (impl, S) — `<ConsoleLogCapture>` last 50 entries with PII review before send
- **T-E-5-05** (impl, M) — `<NPSPrompt>` modal triggered on key actions or 30-day check
- **T-E-5-06** (impl, S) — `<MicroSurvey>` inline thumbs up/down (used by docs feedback widget too)
- **T-E-5-07** (impl, S) — Beta program toggle in `/settings/beta-program` route
- **T-E-5-08** (impl, S) — Bug-report deep link `?feedback=bug&page=X` opens form pre-filled
- **T-E-5-09** (impl, M) — Public roadmap at `/feedback`: feature requests list with upvoting; "Suggest Feature" button
- **T-E-5-10** (impl, M) — Admin dashboard at `/admin/feedback`: table with filters, tagging, CSV export, bulk status update
- **T-E-5-11** (test) — Vitest + Playwright for full feedback flows

**Depends_on**: Wave D backend
**Effort**: 16h

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
