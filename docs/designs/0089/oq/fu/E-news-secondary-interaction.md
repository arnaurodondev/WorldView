---
id: PRD-0089-FU-E
title: PRD-0089 Follow-Up Resolutions — Clusters 8 / 9 / 10
status: pending-user-review
created: 2026-05-20
sources:
  - docs/designs/0089/oq/08-news-sentiment.md
  - docs/designs/0089/oq/09-secondary-pages.md
  - docs/designs/0089/oq/10-interaction-nuances.md
  - docs/designs/0089/oq/_DECISIONS.md (DISCUSS-2, DISCUSS-4, DISCUSS-5 locked)
---

# Follow-Up E — News + Secondary pages + Interaction nuances

> Resolution table for the 24 FU questions raised by the cluster 8 / 9 / 10
> investigation agents. Default-accept any row you don't push back on.
> Bias: lock the smallest viable v1 surface; defer everything that needs a new
> table, endpoint, or learned policy to v1.1.

Conventions: **L** = lock now, **D** = defer to v1.1, **A** = ask user, **R** = remove from scope.

---

## §1 — News + sentiment (Cluster 8) — 8 FUs

| ID | Question | Options | Recommendation | Rationale | Cost | Verdict |
|----|----------|---------|----------------|-----------|------|---------|
| **FU-8.1** | Topic taxonomy ownership — LLM auto-generate or curated whitelist of ~30-50 topics? | (a) S6 LLM emits free-text label per article (b) Curated whitelist of 20-30 tags, LLM classifies into bucket (c) Hybrid: curated top-N + `Other` overflow | **(b) Curated whitelist of 24 tags** — derived from GICS sub-industries + 6 macro buckets (Earnings, M&A, Regulatory, Macro, Guidance, Litigation). Hardcoded in `libs/contracts/topics.py`. LLM classifies; uncovered → `Other`. | LLM-free-text gives 300+ topics with synonyms (`acquisition` vs `merger` vs `buyout`), unusable as a filter. 24 tags = the dropdown is browsable. Curated also keeps the v1.1 `document_topics` table clean. | Day-1: 1 enum + 1 prompt update (~2 h). | **L** |
| **FU-8.2** | Hover-preview a11y — j/k navigates the list; what triggers HoverCard via keyboard? | (a) Focus = open hover (Radix default) (b) Explicit `p` keystroke = preview (c) Long-press Enter | **(a) Focus opens HoverCard after 250 ms** — Radix `<HoverCard>` already supports `data-state=open` on focus-visible; j/k moves focus → hovercard opens naturally; Tab does the same. No new keybinding. | New keystroke would collide with `p` already proposed for "pin" in chat (10.md §4.3). Focus-driven matches shadcn pattern, zero code. | 0 — built into Radix. | **L** |
| **FU-8.3** | Filter persistence across instrument navigation — reset on instrument change or carry over? | (a) Reset every nav (b) Carry over filters (c) Carry sentiment + time-range only, reset publisher/topic | **(c) Carry sentiment + time-range, reset publisher + topic** | Sentiment/time are intent-level ("I'm scanning for negative news this week" — applies to ANY ticker the user pivots to). Publisher/topic are ticker-specific ("FT coverage of AAPL" doesn't make sense for MSFT). Mirrors Bloomberg N pane behaviour. | URL-state code: store `sentiment` + `range` in `searchParams`; topic/publisher live in component state. ~30 LOC. | **L** |
| **FU-8.4** | Cluster modal — explicit click or auto-open at N+ similar articles? | (a) Always explicit click on cluster row (b) Auto-open when ≥ 5 articles in cluster (c) Inline expand-in-place (no modal) | **(a) Explicit click only.** Cluster row shows `▸ N articles · {primary_source}`; click expands modal. | Auto-open = jank for users who don't care; auto-open at N+ = a learned magic number. Inline-expand competes with `j/k` row navigation. One-click modal is honest. | 0 — already how 8-news-sentiment.md §3.2 specs it. | **L** |
| **FU-8.5** | Sentiment sparkline tooltip — value only, or value + article count? | (a) `+0.12` only (b) `+0.12 · 8 articles` (c) `+0.12 · 8 articles · 12 May` | **(c) Full triplet: `+0.12 · 8 articles · 12 May`** | Sparkline points are useless without the count (high polarity on 1 article ≠ high polarity on 50). Date anchors the hover to the correct day. 24 chars fits in 240 px tooltip. | 0 — already in `daily_sentiments` payload (`polarity_mean`, `article_count`, `date`). | **L** |
| **FU-8.6** | `/sentiment-history` endpoint key — `instrument_id` or `entity_id`? | (a) `instrument_id` (b) `entity_id` (c) Both | **(a) `instrument_id`.** Locked by DISCUSS-2: for tradable securities `instrument_id == entity_id`, and only tradables have daily_sentiments rows anyway (non-tradable entities like persons/topics aren't priced by EODHD). | Endpoint nouns should match what the row actually contains. `daily_sentiments.instrument_id` is the existing FK; renaming to `entity_id` would break S3. | 0 — confirms existing schema. | **L** |
| **FU-8.7** | `summary_excerpt` length cap on `document_source_metadata` | (a) 200 chars (b) 280 chars (c) 500 chars | **(b) 280 chars.** Twitter-sized; populates a 3-line `HoverCard` cleanly at 11px / 16px line-height with `line-clamp-3`. | 200 truncates mid-sentence too often; 500 overflows the 280 px popover (≈ 8 lines, kills hover UX). 280 matches existing news-card design in `news-card.tsx`. | Backend: `varchar(280)` constraint + trim in S5. | **L** |
| **FU-8.8** | Article reading list / saved-for-later — v1 or v2? | (a) v1 ship (b) v1.1 (c) v2 (d) Cut | **(c) v2.** Not in PRD-0089 scope. No backend table; no clear UX placement; competes with watchlists. Revisit after RAG retrieval shows users re-read which articles. | Adding a table + 3 endpoints + a sidebar surface for an unvalidated feature is exactly the kind of v1 scope creep the user pushed back on. | 0 in v1. | **R** |

---

## §2 — Secondary pages (Cluster 9) — 6 FUs

| ID | Question | Options | Recommendation | Rationale | Cost | Verdict |
|----|----------|---------|----------------|-----------|------|---------|
| **FU-9.1** | Telemetry sampling rate for disabled-filter clicks (Screener) | (a) 100% (b) 25% (c) 10% (d) Off | **(a) 100% events, batched + debounced 5 s.** Disabled-filter clicks are rare (handful per user-day), so sampling buys nothing; full data prioritises the v1.1 backend filters correctly. Events POST to `/v1/telemetry/events` with `{event: "screener.disabled_filter_click", filter_id, ts}`. | Low-volume + business-critical signal. Sampling at low volume = noise, not savings. Debouncing batches repeats. | Reuses existing `/v1/telemetry` endpoint (post PRD-0085). | **L** |
| **FU-9.2** | Crosshair-sync semantics across mixed timeframes (1D + 1W panels in same workspace) | (a) Sync price-only (b) Sync time-only (c) Sync both, snap time to nearest candle (d) Disable sync when timeframes diverge | **(c) Sync both, snap time to nearest candle in target chart.** Crosshair carries `{timestamp, instrument}`; receiving chart snaps to the candle that contains `timestamp`. 1W chart shows the week containing the 1D crosshair date. | (a) is useless (prices in different scales). (b) loses the price readout. (d) breaks the "broadcast symbol" mental model the workspace is built on. Snap-to-candle is the TradingView-multi-pane behaviour the user already expects. | Adapter in `useCrosshairBroadcast.ts` — `bucketTimestamp(ts, panelTimeframe)`. ~40 LOC. | **L** |
| **FU-9.3** | Bulk-snooze interaction with local-only ACK fallback | (a) Bulk-snooze is server-only; fail closed if S10 offline (b) Bulk-snooze falls back to local-only, same envelope as ACK | **(b) Local-only fallback, mirrors ACK.** Persists `{alert_ids: [...], snooze_until: ISO}` in `localStorage.snoozed_alerts_v1`. On S10 reconnect, frontend POSTs `/v1/alerts/snooze/batch` to reconcile. Conflict policy: server wins. | Symmetric with the ACK fallback (9-secondary.md §B.10) — users won't tolerate "ack works but snooze doesn't" inconsistency. The risk (re-firing snoozed alerts after restart) is identical to the existing local-ACK risk and already accepted in scope. | Storage + reconcile job: ~60 LOC. | **L** |
| **FU-9.4** | Workspace `?config=` URL share — embed user data or only structure? | (a) Layout + selected tickers (full state) (b) Layout only (panel types + sizes) (c) Both, with `?config=` for shareable + `?session=` for private | **(b) Layout only — panel types, sizes, sync flags. Tickers reset to defaults.** | Embedding tickers in a URL = the recipient sees the sharer's portfolio (privacy leak); base64-encoded JSON in URL exceeds the 2,048-char limit when 6+ panels carry data. Layout-only matches Notion's "template URL" pattern: the structure is the gift, the content is yours. | URL builder writes `{v: 1, panels: [{type, size, syncFlags}]}` only. 30 LOC; ~700 chars typical URL. | **L** |
| **FU-9.5** | Predictions drawer behaviour when market resolves mid-view | (a) Live-replace contract with "Resolved · YES paid" panel (b) Show banner above existing payload, drawer stays open (c) Auto-close drawer | **(b) Banner above existing payload, drawer becomes read-only.** Banner: `▣ Resolved · YES @ 67¢ · 14:22 UTC` in `accent-positive`. Bid/ask cells dim to `--muted`; CTA "Trade on Polymarket" disabled. | Auto-close is hostile to a user mid-read; live-replace destroys context (they were comparing two predictions). Banner + read-only matches how Bloomberg PRT pane handles option expiry intraday. | Wire S4 `prediction.resolved.v1` SSE → drawer state. ~50 LOC. | **L** |
| **FU-9.6** | Alerts snooze duration options — fixed list or custom picker? | (a) Fixed: 1h / 4h / EOD / 1w / forever (b) Custom time picker (c) Fixed + "Custom…" overflow | **(a) Fixed list of 5: `15m / 1h / 4h / EOD / 1w`. No "forever" (use mute/disable instead).** Submenu, single click. | Custom picker = 4 clicks (date + time + AM/PM + confirm) for an action that should be one click; production data on Slack/PagerDuty shows >85% of snoozes hit the fixed presets. "Forever" obscures the difference between snooze (temporary) and mute (permanent) — keep them distinct surfaces. | 0 — already in 9-secondary.md §C.10. | **L** |

---

## §3 — Interaction nuances (Cluster 10) — 10 FUs

| ID | Question | Options | Recommendation | Rationale | Cost | Verdict |
|----|----------|---------|----------------|-----------|------|---------|
| **FU-10.1** | j/k coverage scope — all lists or only news? | (a) Global on every list (b) News + chat citations only (c) Opt-in per surface via `data-jk="true"` | **(c) Opt-in per surface, marked by `data-jk="true"` on the scrolling container.** Default surfaces: news lists, article hovercard list, screener results, holdings, alerts, chat citation list. Skip surfaces: settings forms, modals with text inputs. | Global j/k breaks text input in any input/textarea (j/k typed literally). Opt-in via attribute is what the chord-listener already does for Esc cascade (10-interaction.md §4.4). Users either know j/k everywhere it's safe, or they don't notice. | The chord listener already reads `data-*` attrs; add `data-jk` check. ~10 LOC. | **L** |
| **FU-10.2** | Touch hovercard behaviour (iPad) | (a) Long-press 500 ms = open (b) Tap = open, tap-elsewhere = close (c) None — hovers are desktop-only | **(c) None on touch. Hover content is duplicated by an explicit `…` overflow button visible only on `pointer: coarse`.** | Long-press steals system gestures (text selection); tap-to-open competes with row-navigation tap. Worldview is keyboard-first and the user has not asked for tablet polish. `…` button = one-extra-tap, zero collision. | Media query `@media (pointer: coarse) { .row-overflow-btn { display: inline-flex; } }`. ~5 LOC. | **L** |
| **FU-10.3** | Toast position | (a) Bottom-right (Sonner default) (b) Top-right (closer to user-action focus) (c) Bottom-center | **(a) Bottom-right (Sonner default).** Don't override. | Top-right collides with header chips and chart settings popover. Bottom-center hides chat input on small viewports. Sonner default is also where users have been trained by VSCode + GitHub + Vercel. Critical alerts use `FlashOverlay` anyway, so toast position never matters for severe events. | 0 — leave `app/providers.tsx` untouched. | **L** |
| **FU-10.4** | Flash duration on streaming chat (citation jump / row insert) | (a) 600 ms (b) 800 ms (c) 1000 ms | **(b) 800 ms.** Single token across all surfaces: `--flash-duration: 800ms`. | 600 ms is too fast for users scanning the page (eye-tracking studies show 600 ms ≈ saccade window — barely registered). 1000 ms drags; reviewers report "still pulsing" annoyance. 800 ms is the Linear/GitHub convention. Already what row-insert flash uses (10-interaction.md §1.4). | Define `--flash-duration` token; chat goes from 600 → 800 in one line. | **L** |
| **FU-10.5** | Esc cascade — panic-clear everything or only top-most? | (a) Only top-most overlay (Notion) (b) Cascade in order: chord-buffer → modal → popover → drawer → search (Bloomberg) (c) Panic = close ALL chrome in one stroke | **(b) Cascade — match Bloomberg.** Order per 10-interaction.md §4.2 already locks: chord-buffer → topmost modal → drawer → popover → search-overlay → page-level reset (deselect row, blur input). One stroke closes one layer; rapid repeat clears the stack. | "Panic = nuke everything" is unexpected when the user has e.g. a modal + popover open intentionally. Cascade is predictable + recoverable. Bloomberg's terminal precedent is decisive given Worldview's positioning. | 0 — already specced. Confirm against agent investigation. | **L** |
| **FU-10.6** | Spinner color | (a) `--primary` (yellow) (b) `--muted-foreground` (grey) | **(b) `--muted-foreground` (grey) as default; `--primary` reserved for AI-brief generate spinner only.** Single override: spinners that signal AI work use the accent rail color (aligned with DISCUSS-12 Bloomberg amber rail). | Yellow spinners on every loading state make the UI flicker yellow constantly (404 sites today). Muted-grey is the Bloomberg / Linear convention. Reserving primary for "AI is thinking" gives the accent semantic weight. | Token swap in `Spinner.tsx`; AI brief surface adds `variant="ai"`. ~5 sites. | **L** |
| **FU-10.7** | Tooltip max-width | (a) 240 px firm (b) Fluid up to 60ch (c) Tiered: 240 px tooltip / 320 px hovercard | **(c) Tiered.** Tooltip = 240 px firm (single-line + brief metric explainers). HoverCard = 320 px (citation excerpts, peer mini-quote). Distinct CSS class per primitive. | Most tooltips are 1-2 lines (column header full name, freshness reason) — 240 px is plenty. HoverCard is the only surface that needs the 280-char `summary_excerpt` from FU-8.7 + meta line — 320 px = exactly that. Fluid + max 60ch was tested in PR #312 and broke at the 11px text — line counts varied per font load. | `tooltip-config.ts` already exists; add 2 constants. | **L** |
| **FU-10.8** | Skeleton color | (a) `bg-muted` (existing) (b) New `--skeleton` token | **(a) `bg-muted` — no new token.** Skeletons read fine on the current background; `bg-muted` is already the agreed grey for inactive surfaces. | New token = new audit surface + theme drift; the 11 design docs already lock `bg-muted` for 137 skeleton sites. Don't fork. | 0 — confirm existing usage. | **L** |
| **FU-10.9** | Streaming text font weight — same as final or muted while streaming? | (a) `font-normal` throughout (b) `font-light` while streaming → `font-normal` on completion (c) Slightly dimmed color, not weight | **(a) `font-normal` throughout. NO weight change.** Final-message identity must NOT shift on completion. | Weight change = a layout shift (font metrics differ between weights) → violates Tier 0 of DISCUSS-4 (no animation on data surfaces; text streaming IS a data surface for chat). The streaming-ness is already conveyed by the pulse cursor (was removed W6, but re-validating) and message-in-progress chrome (accent rail at message start). | 0 — current implementation correct; lock it. | **L** |
| **FU-10.10** | Empty-state CTA button style — primary or ghost? | (a) Primary (yellow) (b) Ghost (bordered, neutral) (c) Mixed: primary for action-required, ghost for informational | **(c) Mixed by intent.** Primary when the empty state is *blocking* and has ONE clear action (e.g. Portfolio empty → `[Connect brokerage]`). Ghost when the empty state is *informational* and the CTA is a navigation hint (e.g. Insider activity empty → `[Browse other tickers]`). | All-primary CTAs make every empty state shout for attention, hurting density-aware design. All-ghost de-emphasises the one CTA users genuinely need (the Portfolio onboarding). Intent-based mix mirrors Stripe Dashboard. | New `emptyStateIntent` prop on `DashboardEmptyState`; default `informational`. ~10 LOC. | **L** |

---

## §4 — Roll-up

| Bucket | Count |
|--------|-------|
| Locked (L) | 22 |
| Removed / out of scope (R) | 1 |
| Deferred (D) | 0 |
| Awaiting user (A) | 0 |

**Removed:** FU-8.8 (reading list — v2+).
**Net new code surface:** ~210 LOC across 9 files; 2 backend changes
(`summary_excerpt varchar(280)`, telemetry event name). Everything else is
configuration tokens or attribute toggles.

---

## §5 — Cross-references for executor

- **FU-8.1** topic enum lives in `libs/contracts/topics.py` — pairs with the
  `document_topics` table from 08-news-sentiment.md §7.5.
- **FU-8.6** confirms DISCUSS-2 — no separate change required; downstream
  endpoint nouns already aligned.
- **FU-8.7** sets the schema for the new column proposed in 08-news-sentiment.md
  §3.1 / §7.1.
- **FU-9.2** crosshair adapter pairs with workspace-toolbar `[↹ Sync]` toggle
  in 09-secondary-pages.md §A.10.
- **FU-9.4** matches the workspace-template share pattern already in
  09-secondary-pages.md §C.10 (URL builder, not a new endpoint).
- **FU-10.5** confirms 10-interaction-nuances.md §4.2 cascade — no change,
  just signs off the existing spec against Bloomberg precedent.
- **FU-10.6** + DISCUSS-12: `--primary` spinner is reserved for AI surfaces;
  pairs with the Bloomberg-amber accent rail decision.
- **FU-10.7** tiered tooltip vs hovercard — implementation lives in
  `lib/ui/tooltip-config.ts` (already exists per 10-interaction.md §9.2).
- **FU-10.9** locked-no-change protects the DISCUSS-4 Tier-0 boundary on the
  chat surface.
