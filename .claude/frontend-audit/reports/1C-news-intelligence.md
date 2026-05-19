# Subagent 1C — News + Intelligence Route Audit
**Quality Score: 6/10**

## Files Read
- `app/(app)/news/page.tsx` (374 lines)
- `app/intelligence/[entity_id]/page.tsx` (97 lines)
- `lib/api/news.ts` (90 lines)
- `lib/api/intelligence.ts` (248 lines)
- `components/news/ArticleCard.tsx` (245 lines)
- `components/news/ClusterArticlesModal.tsx` (252 lines)
- `components/news/ArticleImpactBadge.tsx` (86 lines)
- `components/intelligence/IntelligenceLayout.tsx` (217 lines)
- `components/intelligence/GraphPanel.tsx` (331 lines, partial)
- `components/intelligence/IntelligencePanel.tsx` (133 lines)
- `components/intelligence/EntitySidebar.tsx` (618 lines, partial)
- `components/intelligence/tabs/EvidenceTab.tsx` (205 lines)
- `components/intelligence/tabs/RelationsTab.tsx` (226 lines)
- `components/intelligence/tabs/PathsTab.tsx` (277 lines)
- `components/intelligence/HealthScoreBadge.tsx` (130 lines)
- `types/api.ts` (150+ lines)

## Layout Issues
1. News row height 24-26px vs 28px target (`py-1` + 16-18px text) — needs `py-1.5`
2. Intelligence xl:1280px breakpoint too aggressive (3-col 25/45/30 needs ~1200px; 320px graph column too narrow)
3. News "Load 50 more" button lacks aria-busy and disabled-on-fetch
4. Intelligence sidebar overflow-y-auto without min-height stutters
5. ClusterModal SheetContent ~90vw uncapped at 4K → 3456px next to 1152px sidebar

## Component Issues
1. ArticleCard supports Article + RankedArticle union but RankedArticle sentiment always null → sentiment badge logic broken
2. News sentiment shown as icon only (TrendingUp/Down/Zap) — no BULLISH/BEARISH/NEUTRAL text label
3. News filters (windowKey, tier) state-only, NOT URL-persisted → refresh resets to defaults
4. Intelligence tabs: EvidenceTab + RelationsTab render "Filtered to:" banner, PathsTab + NarrativeHistoryTab do not — asymmetric UX
5. EntitySidebar fetches depth=2 unconditionally; GraphPanel might be at depth=3+ → sidebar edges feel incomplete during graph expansion
6. ClusterArticlesModal: no debounce on rapid clusterId changes

## Design Violations
1. **PathsTab.tsx:143** — hop_count NOT tabular-nums (composite score is)
2. News "Load N more" button — NOT tabular-nums
3. Sentiment icons missing explicit BULLISH/BEARISH/NEUTRAL labels (color-only signal)
4. All border-radius correct (`rounded-[2px]` consistent in news badges)
5. Font sizes mostly consistent text-[10-11px] across intelligence tabs

## Functional Bugs
1. `app/(app)/news/page.tsx:214-221` — no aria-busy on Load More
2. `ClusterArticlesModal.tsx:176-185` — 5min cache, no manual refresh option
3. **`EntitySidebar.tsx:215-224` + `page.tsx:59`** — SelectedEntityProvider doesn't reset on entity_id param change → stale selectedEntityId on nav between intelligence pages
4. EvidenceTab:131, RelationsTab:121 — no null-check before `selectedEntityId !== entityId` (works in practice but fragile)
5. `page.tsx:71-217` — no upper bound on Load More (DOM bloat at 10k articles)

## API Calls
| Endpoint | staleTime |
|----------|-----------|
| /v1/news/top | 60s |
| /v1/news/entity/{id} | 120s |
| /v1/news/cluster/{id} | 300s |
| /v1/entities/{id}/intelligence | 60s |
| /v1/entities/{id}/paths | 300s |
| /v1/entities/{id}/narratives | Infinite |
| /v1/entities/{id}/narratives/generate | mutation |
| /v1/entities/{id}/graph | 60s |
| /v1/entities/{id}/detail | 300s |

## News-Specific
- Article rows: 24-26px (target 28px) — `py-1` should be `py-1.5`
- Filters functional: time window ✓, tier ✓, **sentiment filter MISSING** (PRD-0026 implies it)
- Pagination: explicit load-more button (not infinite scroll) — intentional for terminal UI
- Article detail view: **NOT IMPLEMENTED** — articles open external URL in new tab
- Signal badges: TrendingUp→positive, TrendingDown→negative, Zap→warning — color correct but no text label
- Primary entity (e.g., "AAPL"): **NOT CLICKABLE** — no link to /intelligence/[entity_id] (broken pivot workflow)
- Score consistency: `display_relevance_score` used; threshold-based color (≥0.7/≥0.4/else); positioned differently in news page vs ArticleCard (inconsistency)

## Priority Issues
1. **News article row height 24-26px vs 28px design spec** — `py-1` → `py-1.5`
2. **Primary entity not clickable in news** — no pivot to intelligence page; breaks key workflow
3. **Sentiment badge broken for RankedArticle** — always null; users see no BULLISH/BEARISH at a glance
4. **News filters not URL-persisted** — refresh resets; no shareable filter links
5. **EntitySidebar stale selectedEntityId on navigation** — browser back/forward shows wrong entity data
