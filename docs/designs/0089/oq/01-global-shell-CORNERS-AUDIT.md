---
id: PRD-0089-F3-CORNERS
title: F3 / Wave 1 — Global Shell — Corners & Edges Audit
status: pending-user-review
created: 2026-05-20
parent: docs/designs/0089/01-global-shell.md
locked_by: _DECISIONS.md (F1 + F2 already shipped/in-flight)
---

# Wave 1 (Global Shell) — design clarity assessment + corners audit

## §A — Design clarity verdict

**Yes, the design is clear and includes a complete sketch.** The doc has:

| Required | Present in `01-global-shell.md` |
|----------|---------------------------------|
| ASCII wireframe at 1440×900 | ✅ §4.1 (full top-to-bottom render with TopBar + sidebar + main + StatusBar) |
| Grid description with px dimensions | ✅ §4.2 (4-region table with widths/heights/scroll behaviour) |
| Density target (counted cells) | ✅ §4.3 (17 TopBar slots + 24 sidebar info rows) |
| Component breakdown with file paths | ✅ §5 (every shell component with prop interface) |
| Visual spec (numerical, every px/font-size) | ✅ §6 (32px TopBar / 200px sidebar / 22px statusbar — all dimensions itemised) |
| Hotkey contract | ✅ §7.1 (most complete in the corpus — 14 chord bindings + scope rules + contract for future agents) |
| Hover behaviour | ✅ §7.2 (per-element, including the explicit `duration-0` Bloomberg convention) |
| Click handlers | ✅ §7.3 |
| Loading/error/empty per surface | ✅ §7.4 (13 distinct states catalogued) |
| Data fetching with TanStack keys + staleTime | ✅ §8 (proposed `qk.shell.*` + cache reuse map) |
| Tradeoffs with alternatives | ✅ §9 (5 explicit decisions: marquee vs strip, sparkline, 22 vs 24px, 200 vs 220px, mnemonic bar) |
| Open questions | ✅ §10 (5 listed) |

It is the **best-specified** of the 11 design docs. The wireframe gives an
analyst-grade visual; the visual spec gives an implementer-grade numerical
contract. **No additional sketch is needed** for executor agents to ship.

That said, the doc was written BEFORE F1 and F2 locked. Below are the
corners that the doc misses or contradicts, plus genuinely new edges.

---

## §B — Coverage map (what the design doc already addresses)

| Concern | Covered by |
|---------|------------|
| TopBar 32px height + 17-slot density | §4.3, §6 |
| 10-ticker IndexStrip (replaces TopBarMarquee) | §6 + §9.1 (marquee vs strip decision) |
| Sidebar 200px (down from 220px) | §6 + §9.4 |
| Watchlist 8 rows × 22px + sparkline column | §6 + §9.2 |
| StatusBar 22px (was 24px) | §6 + §9.3 |
| Chord scope stack (modal > input > chart > table > page > global) | §7.1 scope contract |
| Loading/error/empty per surface | §7.4 (13 states) |
| `qk.shell.*` cache keys with refetch intervals | §8 |
| Tradeoffs justified with competitor citation | §9 |
| `^TNX` swap for USO in IndexStrip per FU-4.3 | partially — §3 mentions, but §6 still shows USO |

---

## §C — Corners missed / contradictions with locked decisions

Severity legend: **🔴 BLOCKING** (must fix before executor dispatch) ·
**🟡 IMPORTANT** (call out in plan) · **🟢 NICE** (defer if needed)

### Conflicts with F1 design system (already shipped)

| # | Corner | Severity | Action |
|---|--------|---------:|--------|
| C-01 | **Watchlist row 22px vs F1 lock 20px**. Design doc §6 says `h-[22px]` for watchlist rows; F1 locked `--row-h: 20px` for `data-table-grid` and 20px as the standard tabular row height. Either: (a) apply `data-table-grid` to the watchlist panel and inherit 20px, or (b) keep 22px and document the exception. | 🔴 | Fix design doc §6 to 20px standard (matches F1) OR document why watchlist is the exception (sparkline needs the vertical breathing room) |
| C-02 | **StatusBar uses `border-t border-white/[0.06]`** — a one-off hex/opacity that isn't in F1 palette. F1 introduced `--border-subtle` (#1E1E22) for exactly this case. | 🟡 | Replace `border-white/[0.06]` with `border-border-subtle` |
| C-03 | **Sidebar active nav `border-l-2 border-primary`** — F1's no-rounded rule and FocusRing tier system aren't explicit on left-rail accents. Confirm `border-l-2` is preserved post-F1 (it's a non-rounded primitive). Also confirm the 2px isn't redundant with the new `data-table-grid` cell borders. | 🟢 | No change; document compliance in the plan |
| C-04 | **PortfolioRail box `rounded-[2px]`** — F1 locked radius to `0px` globally (rectangles); `rounded-[2px]` is banned. Strip it. | 🔴 | Drop `rounded-[2px]` from PortfolioRail spec in §6 |
| C-05 | **Bell badge** described as `h-4 w-4 bg-destructive ... rounded` (implied round) — `rounded-full` is allowed for dots/badges per F1 §3.4 (the only `rounded-full` exception). Confirm the design intends a full circle, not a 2px-rounded square. | 🟡 | Clarify in §6 that the bell badge uses `rounded-full` (allowed exception) |
| C-06 | **Animations** — design doc §7.2 says `duration-0` for sidebar hovers (Bloomberg convention). F1 4-tier policy allows Tier-1 (≤100ms colour-only). Recommend updating to `transition-color-only duration-75` (named token) instead of `duration-0` — same visual outcome, but uses the F1 token explicitly. | 🟢 | Cosmetic; align with F1 named tokens |
| C-07 | **Bloomberg amber rail / AI accent rail** — F1 mandated `border-l-2 border-[hsl(var(--accent-ai))]` for AI surfaces. The shell hosts AskAiButton + AskAiPanel — do these get the rail? Design doc doesn't say. | 🟡 | Spec the AskAiPanel as wrapped by `<AiContentRail>` per F1 §3.2 |

### Conflicts with F2 entity-id unification (in flight / just shipped)

| # | Corner | Severity | Action |
|---|--------|---------:|--------|
| C-08 | **Watchlist row click target** — design doc §7.3 says `/instruments/{entity_id}`. Post-F2, URLs are `/instruments/{TICKER}`. Same applies to IndexStrip cell clicks. | 🔴 | Update §7.3 + every click handler to use `instrument.ticker` |
| C-09 | **`+N more` link target** — design doc §7.3 says `/portfolio?tab=watchlists`. Per FU-4.2 (locked) it's `/watchlists`. | 🔴 | Update §7.3 |
| C-10 | **Index ticker URL routing** — `^TNX` / `^GSPC` have a caret. F2 corners audit C-12 didn't lock the resolution: route `/instruments/^TNX` (% encoded) or `/indices/TNX` (separate route). Whichever F2 chose, the Global Shell IndexStrip must follow. **Check what F2 actually shipped** before specifying the click handler. | 🔴 | Verify the F2 outcome; spec accordingly. If F2 deferred, lock it here: I recommend `/indices/{ticker}` (cleaner) — but the shell needs the route to exist before clicks work |
| C-11 | **Watchlist member ID semantics** — `member.entity_id` in §7.3 was the bridge field. Post-F2 the value equals `instrument_id`. Code still works because the values converged, but the field name implies the old model. v1.1 cleanup per `_DECISIONS.md` §C-03 will rename it. Document the deferred cleanup. | 🟢 | Add a note that `member.entity_id` is post-F2 redundant but kept v1 for type-stability |

### Conflicts with cluster decisions outside F1/F2

| # | Corner | Severity | Action |
|---|--------|---------:|--------|
| C-12 | **`+ N more` target page** — links to `/watchlists` (FU-4.2) which is a NEW page introduced by PRD-0089 separation from `/portfolio?tab=watchlists`. Confirm the page exists OR include "build `/watchlists` stub" in Wave 1 scope. | 🔴 | Wave 1 plan must either (a) include `/watchlists/page.tsx` stub or (b) defer the link until Wave for Watchlists page lands |
| C-13 | **Watchlist sparkline endpoint** — §8 cites `qk.instruments.intraday(entityId, "5m", "1d")`. FU-4.1 locked this as `POST /v1/ohlcv/batch` with `timeframe=5m, limit=78`. Design doc is stale. | 🔴 | Update §8 — use the batch endpoint, key as `qk.instruments.ohlcvBatch(...)` |
| C-14 | **Watchlist freshness dot** — FU-4.1 locked "server-driven `freshness_status` enum, not client timer". Design doc §7.4 says "StatusBar freshness dot — last quote tick < 5s old → green" (client-side timer). The per-row dot inside watchlist rows isn't designed; the StatusBar dot uses client timing. Reconcile: server-driven, no client timer. | 🟡 | Update §7.4 to consume `freshness_status` from the quote payload |
| C-15 | **ROOT portfolio switcher chip placement** — DISCUSS-1 locked: switcher always visible, even with 1 portfolio. Where does the chip live in the Global Shell? Candidate locations: (a) TopBar (right of search, before IndexStrip), (b) inside PortfolioRail box, (c) in the sidebar above the watchlist. Design doc doesn't address this. | 🔴 | Add §6 sub-section: "PortfolioSwitcher chip" — recommend location (a) TopBar slot before IndexStrip; chip width ~120px showing "All Portfolios ▾"; click opens a 240px dropdown listing all portfolios |
| C-16 | **DemoBadge placement** — FU-1.5 locked an opaque "DEMO" chip rendered in the switcher + page header. The Global Shell needs to host it adjacent to the PortfolioSwitcher. Design doc doesn't address. | 🟡 | Add to §6 — render `<DemoBadge>` between switcher chip and PortfolioRail when active portfolio's `kind === "demo"` |
| C-17 | **AskAiPanel citation primitive unification** — DISCUSS-6 locked: single `InlineCitationAnchor` across surfaces. AskAiPanel currently duplicates ~310 LOC of citation parsing. Wave 1 should fix this since AskAiPanel is shell-owned. | 🟡 | Add a Wave 1 task: refactor AskAiPanel to consume `<InlineCitationAnchor>` from F1 primitives; delete the duplicate parser |
| C-18 | **Search Cmd+K input — citation hovercard impact** — when the user pastes a `[cN]` ref into chat from search results, the hovercard from F1's `InlineCitationAnchor` must trigger. Wire-up isn't specified. | 🟢 | Document in Wave 1: GlobalSearch results that include citation IDs render via the shared primitive |

### Genuinely new edges (not yet identified anywhere)

| # | Corner | Severity | Action |
|---|--------|---------:|--------|
| C-19 | **TopBar overflow at < 1440px** — at 1280px the 10-ticker strip won't fit alongside search + portfolio rail + actions. Bloomberg/IBKR collapse tickers first. Design doc doesn't spec narrow-viewport behaviour. | 🟡 | Add §6 narrow-viewport rule: drop tickers from the strip in priority order (USO → GLD → BTC → DXY → TLT → DIA → VIX) until total width fits. Hide entire strip below 1024px (deferred — mobile is v1.1 anyway) |
| C-20 | **Market-closed freshness semantics** — when market is closed (weekend, holiday), the StatusBar freshness dot shouldn't show "Stale 42h". Design doc §7.4 only spec'd live-hours behaviour. | 🟡 | Add to §7.4: when `useMarketStatus().status === "closed"`, freshness dot is muted-foreground with label "MARKET CLOSED"; no "stale" rendering |
| C-21 | **Multi-tab localStorage sync** — sidebar collapsed state and active watchlist persist to localStorage. Two browser tabs open simultaneously will diverge. Standard solution: `storage` event listener to sync. Edge case. | 🟢 | Add to §7.3: subscribe to `storage` events for both keys; last-write-wins per tab |
| C-22 | **Idle-lock interaction** — `useIdleLock` (referenced in current layout.tsx) suspends UI on idle. Should it pause TanStack refetch intervals? Otherwise IndexStrip burns 4 req/min indefinitely. | 🟡 | Add to §8: when idle-locked, set every shell `refetchInterval` to false; resume on unlock |
| C-23 | **SSE auth refresh** — `useAlertStream` SSE connection uses the current access token. When token refreshes (after 15min), does the stream reconnect with the new token? If not, `WS Live` dot turns red even though everything else is fine. | 🟡 | Add to Wave 1 task list: confirm SSE reconnect on auth-token-refresh event (or document the existing behaviour) |
| C-24 | **FlashOverlay vs AlertStream WS dot** — both consume `useAlertStream`. When an alert fires, FlashOverlay shows the alert AND the StatusBar WS dot stays green. No conflict, but document that the two surfaces consume the same hook to avoid two SSE subscriptions. | 🟢 | Document the single-subscription contract in §8 |
| C-25 | **ForceUpdateBanner placement** — `ForceUpdateBanner.tsx` exists in shell/ already. Renders above TopBar (sticky)? Below? Design doc doesn't address. | 🟡 | Add to §4.1 wireframe: ForceUpdateBanner renders ABOVE TopBar as a 24px notice strip when active; pushes everything down 24px |
| C-26 | **Toast position** — FU-10.3 locked top-right (Sonner default). Where does Sonner mount in the layout tree? Likely inside layout.tsx body. Confirm z-index ≥ z-60 (per F1 z-index scale) so toasts always sit above modals. | 🟢 | Document in §6 — Sonner Toaster at `z-60` top-right |
| C-27 | **Skip-to-content link** — a11y standard: sticky TopBar means screen reader users need a way to jump past chrome. Hidden but focusable `<a href="#main">Skip to main content</a>`. Not specified. | 🟡 | Add to §6 — invisible focusable skip link as first child of `<body>` |
| C-28 | **Logout flow cache clear** — when user logs out, all TanStack caches should be wiped (other user's data otherwise leaks on re-login as different user). F1's `QK_VERSION` doesn't help here. The dropdown menu's `logout()` handler must call `queryClient.clear()`. | 🟡 | Add to §7.3: logout handler clears TanStack cache and resets HotkeyContext scope stack |
| C-29 | **Deprecated component cleanup** — `TopBarMarquee.tsx`, `MarqueeTickerChip.tsx`, `IndexTicker.tsx` are being replaced by the new static `IndexStrip` component (§5). Wave 1 must explicitly delete the deprecated files. | 🔴 | Add to Wave 1 file ledger: DELETE `TopBarMarquee.tsx`, `MarqueeTickerChip.tsx`, `IndexTicker.tsx` after the new `IndexStrip` lands |
| C-30 | **Watchlist switcher dropdown UX** — the chip header (`WATCHLIST  Tech ▾`) opens what? A native `<select>`? Custom dropdown? Per FU-4.4, watchlist add-flow uses `mod+shift+w`. But the switcher's interaction model isn't specified. | 🔴 | Add to §6/§7: switcher chip opens a 200px-wide popover listing all watchlists + a "+ New watchlist" CTA at the bottom |
| C-31 | **Sidebar collapsed state visual** — design doc §6 says collapsed is `w-10` (40px) showing icon-only nav rows. What about watchlist + alarms when collapsed? Hidden entirely? Folded into a tooltip-on-hover? | 🟡 | Add to §6: when collapsed, watchlist + alarms sections hide; only nav icons + Settings + bottom-chrome remain. Hover any icon → full-name tooltip |
| C-32 | **Hotkey cheat-sheet path filter** — `?` opens HotkeyCheatSheet with chords scoped by current pathname. After F2 the path is `/instruments/{ticker}` not `/instruments/{uuid}`. The pathname matcher uses `startsWith("/instruments/")` (per §7.1) so still works. ✓ | 🟢 | Document this still-works fact in the Wave 1 plan |
| C-33 | **Watchlist sparkline trend tint** — FU-5.6 locked trend-tinted (3-state positive/negative/flat) sparklines. Design doc §6 says `stroke-positive` / `stroke-negative` (only 2 colours; flat falls through). Add flat colour. | 🟡 | Update §6 — sparkline stroke uses `text-positive` / `text-negative` / `text-muted-foreground` per F1 `Sparkline` primitive |
| C-34 | **Sidebar drag-resize** — design says min 160px, max 340px, default 200px. Where's the drag handle? Visible at all times or only on hover? | 🟢 | Existing `CollapsibleSidebar.tsx` has a drag handle; confirm it survives the redesign without modification |
| C-35 | **IndexStrip tooltip on hover** — index cell shows ticker + price + chg%. Hover should show full name ("S&P 500" not "SPY") in a tooltip. Per F1 tooltip delay = 300ms (Radix default). Design doc §7.2 mentions no hover tooltip for IndexStrip cells (only "title-tooltip = full label" on chord hints). | 🟡 | Add to §7.2: IndexStrip cell hover triggers full-name tooltip after 300ms via Radix Tooltip primitive |
| C-36 | **Wordmark `<button>` accessibility** — left-most "Worldview" is a button that routes to `/dashboard`. Currently `font-mono font-bold text-[13px]`. Confirm it has `aria-label="Worldview — Home"` and visible focus ring (T3 chrome tier per F1). | 🟢 | Add to §6 accessibility notes |

---

## §D — Cross-cluster implications

1. **F2 ticker URLs must be DONE before Wave 1 dispatches** — every click handler depends on F2's `/instruments/{ticker}` route. Sequence: F1 → F2 → Wave 1.
2. **Wave 1 is the first Wave that consumes F1 primitives at scale** — Sparkline, FreshnessDot, DataFreshnessPill, DemoBadge, AiContentRail. If any are missing post-F1, Wave 1 stalls. F1 QA must verify primitive catalogue completeness.
3. **`/watchlists` route stub (C-12) needs to exist before the "+N more →" link works** — either Wave 1 ships a stub OR the link target is hidden until the Watchlists wave lands.
4. **Index ticker routing (C-10) blocks the IndexStrip click behaviour** — pick `/indices/` route OR `/instruments/^TICKER` URL-encoded. My recommendation: introduce `/indices/{ticker}` because (a) cleaner, (b) avoids `^` URL-encoding mess, (c) lets us style index pages differently if needed v1.1.

---

## §E — Recommended Wave 1 plan structure (draws from F1 / F2 templates)

Sections to include:
1. Mission — single-sentence
2. Bloomberg-grade resemblance checklist (TopBar density 17 slots, sidebar 200px, statusbar 22px, all locked tokens applied)
3. Visual contract — reference §4-§6 of the design doc verbatim (no duplication)
4. Pre-flight checks — F1 primitives exist, F2 ticker URLs work, `/watchlists` and `/indices` routes either exist or are stubbed in this wave
5. File-by-file change set:
   - 5.1 TopBar.tsx — replace marquee with IndexStrip; add PortfolioSwitcher chip + DemoBadge
   - 5.2 IndexStrip.tsx (new)
   - 5.3 PortfolioSwitcher.tsx (new)
   - 5.4 CollapsibleSidebar.tsx — tighten to 200px; replace section gaps with hairlines
   - 5.5 WatchlistPanel.tsx — add sparkline column; switch to `ohlcvBatch` endpoint; fix `+N more` link; switcher popover UX
   - 5.6 StatusBar.tsx — flip to 22px; replace `border-white/[0.06]` with `border-border-subtle`; market-closed handling
   - 5.7 AskAiPanel.tsx — consume `<InlineCitationAnchor>`; wrap with `<AiContentRail>`; delete duplicate parser
   - 5.8 DELETE: TopBarMarquee.tsx, MarqueeTickerChip.tsx, IndexTicker.tsx
6. New stub routes (if applicable): `/watchlists/page.tsx`, `/indices/[ticker]/page.tsx`
7. localStorage + a11y additions (multi-tab sync, skip-to-content, focus ring tiers)
8. Tests — unit per new component, Playwright for sidebar collapse + hotkey navigation, density canary verifying 17 TopBar slots visible
9. Acceptance criteria — including: no `rounded-*` in shell/, no `border-white/[0.06]`, every click target uses ticker URLs
10. Estimation: ~5-6 engineer-days (was 3-4 in §D wave plan — adjusted for corners audit work)

---

## §F — Final verdict

**The design is clear and complete enough to ship — the wireframe + visual
spec is the most rigorous in the corpus.** But 36 corners need addressing,
12 of them BLOCKING. Most are mechanical updates to align with F1 + F2 locks
that postdate the original design doc.

**Recommended next step**:
- **Option A** — Patch the design doc inline with the corners list above,
  then draft the Wave 1 plan (similar 500-line depth to F1 / F2).
- **Option B** — Draft the Wave 1 plan directly with the corners baked in
  (the plan supersedes the design doc anyway for execution).

I recommend **Option B**. Plans are executable; design docs are reference.
Inline patches to the design doc would duplicate effort without benefit.

Reply with `option B` and I'll write the Wave 1 plan in the same depth as
F2, then produce the executor prompt.
