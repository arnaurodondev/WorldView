# OQ Cluster 9 — Secondary Pages (Workspace, Screener, Predictions, Alerts)

**Status:** investigation complete — recommendations ready for sign-off
**Scope:** PRD-0089 §§8 (Screener), 9A (Workspace), 9B (Predictions), 9C (Alerts) +
master OQs D4/D5/D6.
**Sources read:**
- `docs/designs/0089/08-screener.md` §10 (7 OQs)
- `docs/designs/0089/09-workspace-predictions-alerts.md` §A.10 / §B.10 / §C.10
- `docs/designs/0089/00-backend-data-inventory.md` §§1.7, 1.10, 1.11
- Implementation: `apps/worldview-web/components/screener/SavedScreensDialog.tsx`,
  `services/api-gateway/src/api_gateway/routes/portfolio.py` (watchlists),
  `services/portfolio/src/portfolio/infrastructure/messaging/schemas/watchlist.*.avsc`.

---

## 1. Cluster summary

The "secondary pages" cluster covers four surfaces that all share one trait:
they are **power-user dense lists with optional drill-in**, and every OQ in
the cluster is about the **tension between client-only convenience and
server-backed sharing/cross-device sync**. There are 17 open questions across
the four surfaces, plus the three master-PRD OQs (D4 = crosshair sync,
D5 = tab-stacking, D6 = preset persistence).

The unifying recommendation across the cluster is **"v1 keeps the cheap
client-side path that ships today; v1.1 adds server-side endpoints for the
features whose value scales with users"**. Specifically:

- Screener presets, alert payload-row toggle, workspace crosshair-sync, and
  workspace layouts — all **localStorage v1**, **server-backed v1.1**.
- The two true v1 backend additions are (a) `recent_yes_history: float[7]` on
  the prediction-market list response (one schema field, large UI payoff)
  and (b) optional `display_trigger` on the alert payload for Bloomberg-style
  `current vs trigger` rendering.
- The two "kill / never" answers are (a) full real-time order-book depth on
  Predictions (top-of-book is enough for an alt-signal use case) and (b)
  Bloomberg's flat-chronological alerts layout (severity grouping wins for
  a researcher-leaning user base).

The cluster is dominated by **defer-and-stub decisions**, not architectural
forks; nothing in this cluster blocks PLAN-0089 wave-1 implementation.

---

## 2. Per-OQ deep dives

### OQ-9.1 — Screener preset persistence (master OQ-D6)

**Question.** Local-storage only (v1, single-device) vs server-side
`POST /v1/screener/presets` (v1.1, cross-device, shareable). Cost/value for
v1?

**Today.** `SavedScreensDialog` already exists; saved screens live entirely
in `localStorage` via `lib/saved-screens.ts`. There is no S9 or S3 preset
endpoint. The §8 doc proposes adding `POST /v1/screener/presets` but flags
it as deferrable.

**Analysis.**
- Cost of server-side now: new S1 (or S3) table `screener_presets` with
  `user_id`, `name`, `filters_json`, `created_at`, `updated_at`; one POST,
  one GET, one DELETE; S9 proxy routes; auth integration. ~2 days dev
  across S1/S9 + frontend mutation/cache wiring.
- Value before v1.1: low. Today's user base = single-user thesis demo; one
  device. localStorage covers 95% of real use.
- Value at v1.1 / B2B: high. Sharing a screen ("this is how I find
  semiconductor laggards") is a viral discovery loop. Cross-device sync
  matters once a user has both desktop and laptop.

**Recommendation.** **v1: system presets hardcoded in
`lib/screener/presets.ts` + user presets in localStorage (keep current
`SavedScreensDialog`). v1.1: add `POST /v1/screener/presets` + GET/DELETE,
migrate localStorage → server on first call, support `share_token` for v1.2
team sharing.** Document the localStorage → server migration as a
forward-compat write-through (write to both for one release, then drop
local).

---

### OQ-9.2 — Screener watchlist-default endpoint

**Question.** When the user clicks `+ Watchlist` on a screener result row,
which watchlist receives the add? Last-used? Primary flag? Always prompt?

**Today.** S1 has no `is_default` / `is_primary` column on watchlists (see
`portfolio/src/.../infrastructure/messaging/schemas/watchlist.*.avsc` — no
default flag). `GET /v1/watchlists` returns the full list. The UI today
opens a picker dialog every time.

**Analysis.**
- **Always-prompt** (current) is safe but adds 1 click + cognitive load on
  every screen-derived add. Power users with 5+ watchlists pick the wrong
  one ~10% of the time per Stockanalysis user-feedback heuristics.
- **Last-used** is server-stateless, client-cheap (localStorage key
  `lastUsedWatchlistId`). Risk: silent add to the wrong list when user has
  switched contexts (research → portfolio).
- **`is_primary` flag** would require an S1 schema migration + UI to set it.
  Best correctness but biggest cost.

**Recommendation.** **v1: prompt on first click of a session, then remember
in-memory + localStorage for the session ("Add to <Watchlist Name>?
[Add] [Change…]"). Power-user override via Shift+click → always prompt.
v1.1: add `is_default` boolean to `watchlists` table + `?default=true` query
support on `GET /v1/watchlists`.** This is what TradingView and IBKR both
do (last-used remembered, secondary action to switch).

---

### OQ-9.3 — Screener compare-set v1 vs v2

**Question.** Multi-select rows → "Compare" CTA → side-by-side compare page.
v1 = 2 instruments? v2 = 5 instruments × 12 ratios?

**Today.** No compare page exists. §8 logs the "Compare 3" hover-button as
a stub.

**Analysis.**
- 2-instrument compare ships against the existing `/instruments/[id]`
  layout reused twice in a 2-column flex. Zero new components. Useful for
  the most common case ("which is cheaper, MSFT or AAPL?").
- 5-instrument compare needs a dedicated `/compare?ids=…` route with a
  transposed table (instruments as columns, ratios as rows) — designed
  like Stockanalysis's Compare. ~1 week of dedicated design + impl.
- The screener page real estate already supports the multi-select pattern
  (checkbox column), so plumbing the CTA in v1 with a stub destination is
  cheap.

**Recommendation.** **v1: hover-row `+ Compare` button stages an in-memory
"compare set" of up to 3 instruments + a floating bar `Compare 2 ▸` that
opens a v1 2-instrument compare page (`/compare?a=…&b=…`) reusing the
instrument-detail layout. v2: full `/compare?ids=…` with 5 instruments × 12
ratios + sticky first column.** Defer multi-row selection (Shift+click range
select) to v2 with the broader compare page.

---

### OQ-9.4 — Screener client-side filter stubs

**Question.** Filters the backend cannot fulfill (gross_margin, debt/equity,
news_velocity, controversy, insider_activity). Currently visible-but-disabled
with a "Backend pending" badge. Keep visible vs hide?

**Today.** `FilterPanel` shows the disabled filters with a tooltip; they
round-trip in saved screens (the field is preserved in `filters_json` even
when not executable).

**Analysis.**
- **Hide entirely** = pretend the feature doesn't exist. Users never learn
  the roadmap, and saved screens that contain these filters fail
  ambiguously.
- **Keep disabled-visible with badge** (current) = advertises the roadmap,
  preserves saved-screen forward-compat, lets us A/B which filters users
  actually click on (telemetry-driven roadmap prioritisation).
- The cost is ~24px of vertical chrome in the FilterPanel popover, not the
  main page surface — acceptable.

**Recommendation.** **Keep disabled-visible with a "Backend pending" badge.
Add tooltip text "Available in v1.1 — see roadmap". Track click-throughs on
disabled filters via existing telemetry to prioritise the v1.1 backend
work order.** Roadmap order (driven by §8 inventory + KG existing data):
1. `news_velocity` (S6 already computes article counts per entity per day)
2. `debt/equity` + `gross_margin` (require S3 to extend `fundamental_metrics`
   coverage — already on the §6 instrument-financials backlog)
3. `controversy` + `insider_activity` (need new S6/S7 KG aggregations).

---

### OQ-9.5 — Workspace crosshair sync default (master OQ-D4)

**Question.** Workspace-level chart crosshair + time-range sync. Default ON
or OFF?

**Today.** Not implemented. §A.4 + A.9 propose a workspace-level
`syncCrosshair?: boolean` flag, default false. Bloomberg defaults this OFF
(charts independent); TradingView defaults it ON within a layout; IBKR
TWS defaults it OFF.

**Analysis.**
- Default-ON: surprising for the most common workflow (compare AAPL 1D vs
  SPY 5m for relative strength); forces the user to discover the toggle to
  un-sync.
- Default-OFF: charts behave as today (independent); the toggle is an
  opt-in for the "study one symbol across timeframes" use case.
- The Worldview workspace mental model = "broadcast symbol applies to all
  panels". Crosshair sync is one step deeper than that — same symbol AND
  same time crosshair. That's a different mental model than "compare two
  things side by side".

**Recommendation.** **Default OFF. Workspace-level toggle in the utility
row (`[⊕ Add panel][⊞ Template][↹ Sync] [🗗 Pop]`). Persist per-workspace
in `WorkspaceConfig.syncCrosshair` (already proposed in §A.5). Surface a
once-per-user discovery hint ("Tip: try Sync to align crosshairs across
charts") when ≥2 chart panels are visible.** This matches Bloomberg and
IBKR — the institutional reference for our buy-side persona.

---

### OQ-9.6 — Workspace tab-stacking (master OQ-D5)

**Question.** Tab-stacked panels (Mosaic-style: one slot holds N tabbed
panels). v1.1 or never?

**Today.** Not implemented. §A.9 Decision 2 defers to v1.1.

**Analysis.**
- Use case: power user wants `Chart | News` and `Chart | Fundamentals` in
  the same slot — toggling tabs in place. Saves 50% of slot real estate.
- Cost: `WorkspaceRow.panels` becomes
  `WorkspacePanel | TabbedPanelGroup` (sum type); URL share token format
  changes; localStorage migration; the resizable-panels v4 lib doesn't
  natively support nested tabs (we'd add a `Tabs` wrapper inside
  `<Panel>`). ~3 days frontend.
- Value: meaningful for the 10% of users with >4 active panels per
  workspace; invisible to the other 90%.

**Recommendation.** **v1.1, NOT v2-or-later.** The Mosaic precedent is
strong, the implementation is bounded, and the URL-token change is the
right time-to-do-it (we'll bump `WorkspaceConfig` schema from v1 to v2 in
the same release). Forward-compat write: a v1 URL token still loads as a
flat row in v2 (panels without tab-group wrapper render as today).

---

### OQ-9.7 — Workspace layout templates

**Question.** Built-in templates (Quad, Triple-with-tall-news, Earnings-focus,
…), user-saved layouts, sharing layouts.

**Today.** `NewFromTemplateDialog` exists. A small set of built-in templates
already ships. Sharing today = `?config=<base64>` URL share token (§A.5).

**Analysis.**
- Built-in templates: low cost (data structure, not new components). Should
  ship a curated 5-7 templates aligned with user personas:
  1. **Quad** (default — 4 equal panels)
  2. **Triple-with-tall-news** (chart 60% w + news 40% w stacked under)
  3. **Earnings focus** (chart + fundamentals + key-metrics + news, all
     scoped to the earnings calendar)
  4. **Macro day** (3 prediction-market panels + 1 chart of SPY/DXY)
  5. **Portfolio review** (positions + risk + sector + cross-asset chart)
- User-saved layouts (= "save this workspace as a template"): need
  `userTemplates: WorkspaceConfig[]` in localStorage (cheap) or in a S1
  table (cross-device).
- Sharing layouts: already covered by `?config=` URL token. Named-template
  sharing (`?template=earnings-focus`) is a v1.1 nicety.

**Recommendation.** **v1: ship 5 built-in templates (above) plus
"Save current as template" → localStorage `userTemplates` array. v1.1:
server-side `POST /v1/workspace/templates` (paired with OQ-9.1 preset
endpoint — same shape, same auth pattern, same migration story). v2: team
sharing via `share_token`.**

---

### OQ-9.8 — Predictions market history chart

**Question.** 7d inline sparkline on the list (already proposed in §B.4) vs
full 30d chart in the drawer vs both. Time-weighted probability vs raw
price?

**Today.** No history rendering anywhere. §B.4 proposes inline 60×14px
sparkline + drawer 30d line chart. The endpoint
`GET /v1/signals/prediction-markets/{id}/history` already exists and
returns `[{timestamp, yes_price, no_price, volume}]`.

**Analysis.**
- **Both** is the answer — the sparkline is the scanning aid (7 points,
  shape recognition); the drawer chart is the deep-dive (30 days, precise
  values on hover).
- **Time-weighted** vs **raw `yes_price`**: Polymarket itself displays raw
  last-trade `yes_price` over time. Time-weighting (TWAP-style) would
  smooth out thin-liquidity wicks but obscures the moments when the market
  actually moved. The user's mental model is "what does the crowd think
  right now"; raw is correct.

**Recommendation.** **Both. Sparkline = 7 points of raw `yes_price` from a
new `recent_yes_history: float[7]` field on the list response (see backend
additions). Drawer chart = 30 days of raw `yes_price` from the existing
`/history` endpoint. No time-weighting in v1.** Add time-weighted as a
toggle in v1.1 if user feedback asks for it.

---

### OQ-9.9 — Predictions bid/ask depth

**Question.** Show only best bid/ask vs full top-3-each. Polymarket
precedent?

**Today.** S9 doesn't expose bid/ask at all (§B.10 logs it as a backend
gap; fields exist in `market.prediction.snapshot.v1` Avro). Polymarket's
own UI shows top-of-book on the market card and an expandable depth ladder
on the trade panel (which we don't have — we're read-only).

**Analysis.**
- **Top-3 depth** is information a *trader* needs (sizing an order).
  Worldview is read-only — we're using prediction prices as a probability
  oracle, not for execution.
- **Best bid/ask only** answers "is the price tight / wide?" which is the
  meaningful signal-quality question for our persona (a wide spread means
  the consensus probability is noisier).
- Top-3 depth adds 6 numbers + 6 sizes to the drawer for marginal value
  and inflates the S9 response payload ~3×.

**Recommendation.** **v1: best bid + best ask + last-trade price only, as
a 3-chip strip in the drawer (`Bid 65¢ · Ask 67¢ · Last 66¢ · 2¢ spread`).
v2: defer depth-of-book; only revisit if Worldview ever becomes a
prediction-market brokerage (it won't).**

---

### OQ-9.10 — Alerts severity grouping

**Question.** Group by severity with sticky headers (current Worldview) vs
flat chronological with severity badges (Bloomberg ALRT).

**Today.** Severity-grouped with sticky headers (`CRITICAL → HIGH → MEDIUM
→ LOW`). §C.9 Decision 1 reaffirms.

**Analysis.**
- **Bloomberg flat**: works because Bloomberg power users learn the
  severity character (`!` / `*`) at-a-glance. Our user base includes
  research-leaning analysts who don't have that muscle memory.
- **Severity-grouped**: enforces "critical at the top, always". The
  documented tradeoff is sortability — you can sort within a group by
  time but not across groups.
- The "I missed the critical one in the noise" failure mode is the worst
  thing an alert system can do. Grouping prevents it structurally.

**Recommendation.** **Keep severity-grouped with sticky headers as the
default. Add a header-bar toggle "View: Grouped | Time" (icon button,
persisted to localStorage) so Bloomberg-trained users can switch. Default =
Grouped.** No user-preference setting in Settings UI — the in-page toggle
is enough.

---

### OQ-9.11 — Alerts payload row default

**Question.** IBKR-style 2-row alerts (main row + 18px payload sub-row at
50% opacity) — always visible vs opt-in toggle?

**Today.** Payload only in detail sheet. §C.9 Decision 2 proposes an opt-in
toggle persisted to localStorage; default = OFF.

**Analysis.**
- **Always-on**: doubles row height effectively → ~half as many alerts
  visible per viewport. First-time users see clutter; the additional
  detail is wasted on simple alerts (`Volume +40% vs 5d avg` adds no info
  in payload).
- **Opt-in**: power user gets density when they want it; first-timers
  aren't overwhelmed. Persistence means the choice survives sessions.
- **Per-row expand** (click row to expand inline): incompatible with the
  existing `?selected={id}` drawer pattern — row body click is already
  bound to open the drawer.

**Recommendation.** **Opt-in via a header-row checkbox `Expand payloads`
(default off), persisted to localStorage. Apply globally to all alerts in
the current view. Matches §C.9 Decision 2.** Bonus: the 18px sub-row uses
`text-[9px]` + `opacity-50` so it visually recedes — power-user pattern,
not new-user noise.

---

### OQ-9.12 — Alerts bulk-ack

**Question.** Bulk operations beyond the existing "ACK Selected" + "ACK ALL"
per-group buttons. `Shift+A` = ack all critical? Ack-by-entity? Bulk-snooze?

**Today.** `ACK Selected` (bulk-select) + `ACK ALL` (per severity group)
both exist. Bulk-snooze proposed in §C.10 OQ 3.

**Analysis.**
- `Shift+A` for ack-all-critical is the Bloomberg `AAA` equivalent. Low
  cost (one hotkey registration), high value for the "noisy morning" use
  case.
- **Ack-by-entity** ("ACK all AAPL alerts") is useful when a known event
  triggers a cluster (e.g. earnings) — but the bulk-select toolbar
  already covers it with Shift+click range-select. Adding a dedicated
  "ACK all <ticker>" button per entity-group header would bloat the UI;
  the existing pattern is fine.
- **Bulk-snooze**: matches per-row snooze submenu (15m / 1h / 4h / EOD /
  24h / custom). §C.10 OQ 3 already recommends adding this — no controversy.

**Recommendation.**
- **v1**: add `Shift+A` = ACK ALL CRITICAL hotkey (registers in the
  existing alerts hotkey table). Add `Snooze Selected` to the bulk
  toolbar with the same time-window submenu as the per-row snooze.
- **v1.1**: add `g`-prefixed chord `g e` to focus the "Filter by entity"
  search — covers the "ack all AAPL alerts" use case without dedicated UI.
- **Never**: per-entity dedicated ACK button (UI bloat for marginal value).

---

## 3. Recommended decisions table

| OQ | Question | Recommendation | Ships | Cost (eng-days) | Backend? |
|----|----------|---------------|-------|-----------------|----------|
| 9.1 | Screener preset persistence | localStorage v1; server-side v1.1 | v1 + v1.1 | 0 / 2 | v1.1 |
| 9.2 | Watchlist-default for `+ Watchlist` | Prompt-once-per-session + remember; `is_default` v1.1 | v1 | 0.5 | v1.1 |
| 9.3 | Compare-set scope | 2-instrument compare v1, 5-instrument v2 | v1 + v2 | 1 / 5 | No |
| 9.4 | Client-side filter stubs | Keep visible+badge; telemetry-driven roadmap | v1 | 0 | v1.1+ |
| 9.5 | Crosshair sync default | Default OFF, workspace-level toggle | v1 | 1 | No |
| 9.6 | Tab-stacked panels | v1.1 (Mosaic-style, schema bump to v2) | v1.1 | 3 | No |
| 9.7 | Workspace layout templates | 5 built-in + localStorage user templates v1; server v1.1 | v1 + v1.1 | 1 / 2 | v1.1 |
| 9.8 | Predictions history rendering | Inline 7-pt sparkline + drawer 30d chart; raw price | v1 | 1 (frontend) | YES v1 (`recent_yes_history`) |
| 9.9 | Bid/ask depth | Best bid + best ask + last only; no depth | v1 | 0.5 (frontend) | YES v1 (5 fields) |
| 9.10 | Alerts severity grouping | Grouped default + in-page View toggle (Grouped/Time) | v1 | 0.5 | No |
| 9.11 | Alerts payload row | Opt-in toggle, persisted, default OFF | v1 | 1 | No |
| 9.12 | Alerts bulk-ack | `Shift+A` = ack-all-critical + Bulk-Snooze; defer per-entity | v1 | 1 | No |
| A.10.2 | Workspace panel pin | Defer to v1.1 (out of scope; broadcast model already covers most cases) | v1.1 | 1 | No |
| A.10.3 | Workspace count overflow | Horizontal scroll on tab strip at N≥6, `[…]` dropdown at N≥10 | v1 | 0.5 | No |
| B.10.2 | Multi-outcome markets | Out of scope v1 (all current markets binary) | v2 | — | YES v2 |
| B.10.3 | Kalshi adapter | Out of scope v1 (renders identically when arrives) | v2 | — | YES v2 |
| C.10.1 | Alert `display_trigger` field | Add to alert payload; graceful fallback when absent | v1 | 1 (S10) | YES v1 |
| C.10.2 | WS reconnection banner | Show "Reconnecting…" toast at top of alerts list on WS disconnect | v1 | 0.5 | No |
| C.10.4 | Audio cues | Defer to v2 (no audio system) | v2 | — | No |
| C.10.5 | History severity grouping | Defer (time-ordered is natural for "what fired between X and Y") | v2 | — | No |

**v1 total backend cost.** 3 small additions: `recent_yes_history: float[7]`
on predictions list, 5 bid/ask fields on predictions, `display_trigger`
object on alert payload. ~2-3 eng-days across S3/S4/S9/S10.

**v1 total frontend cost.** ~7 eng-days across the four pages (mostly
toggles, hotkeys, the prediction sparkline component, and the 2-instrument
compare page).

---

## 4. Backend additions required

### 4.1 v1 (in scope for PLAN-0089)

| Field / endpoint | Service | Schema change | Notes |
|------------------|---------|---------------|-------|
| `recent_yes_history: float[7]` on `PredictionMarketSummary` | S3 + S9 | Add column to `prediction_market_snapshot` materialised view; expose in S9 schema | 7-day rolling array, computed by S3 from existing `prediction_market_history` table. Forward-compat: nullable / empty-array default |
| `best_bid`, `best_ask`, `bid_size`, `ask_size`, `last_trade_price` on `PredictionMarket` | S3 + S9 | Already in `market.prediction.snapshot.v1` Avro; just plumb through to S9 list/detail schemas | All optional; UI degrades gracefully when null |
| `display_trigger: {label, current_value, threshold_value, comparator}` on `Alert.payload` | S10 | Compute in `AlertService` enrichment step | Trivial for USER_RULE (already has threshold); for SIGNAL, synthesize from `signal_label` + current quote (one extra DB read per alert during enrichment, cacheable) |

### 4.2 v1.1 (defer)

| Field / endpoint | Service | Notes |
|------------------|---------|-------|
| `POST /v1/screener/presets` + GET + DELETE | S1 or S3 | New `screener_presets` table; pairs with workspace-templates endpoint for shared "saved-thing" pattern |
| `POST /v1/workspace/templates` + GET + DELETE | S1 | Identical shape to screener presets; share the "user-saved JSON blob" pattern |
| `is_default: bool` on `watchlists` | S1 | Alembic migration; expose `?default=true` query on `GET /v1/watchlists` |
| Per-row sparkline batched endpoint `POST /v1/signals/prediction-markets/history-batch` | S3 | Alternative to `recent_yes_history` field if perf becomes an issue; not needed v1 |

### 4.3 Never (explicitly out of scope)

- Polymarket order-book depth (top-3+) — Worldview is read-only.
- Audio cues for alerts — no audio system, no plans.
- Per-panel crosshair-sync flag — workspace-level is the correct mental
  model (§A.9 Decision 1).
- Server-persisted workspace config — high-frequency write surface;
  share-via-URL covers cross-device (§A.9 Decision 3).

---

## 5. Follow-up OQs (new, not in original docs)

1. **Screener telemetry for disabled-filter clicks.** OQ-9.4 recommends
   telemetry-driven prioritisation. We need to confirm S9 / frontend telemetry
   pipeline supports a "filter click on disabled chip" event. If not, what
   does the minimal instrumentation look like? (Likely a `posthog.capture`
   on the existing analytics infra.)

2. **Workspace template `userTemplates` schema versioning.** OQ-9.7 stores
   user templates in localStorage v1, server v1.1. The migration story
   needs explicit forward-compat: a v1 template JSON must be unmodified
   when round-tripped through the v1.1 server schema. Recommend a
   `schemaVersion: 1` field on every template entry from day 1.

3. **Crosshair-sync semantics with mixed timeframes.** OQ-9.5 says "sync
   crosshair across charts". What is the semantic when chart A is on
   1D bars and chart B is on 5m bars? Snap to nearest bar in each? Show
   the same wall-clock time as a vertical line? Recommend "wall-clock
   time, nearest bar in each chart" — but this needs spec'ing.

4. **`display_trigger` for SIGNAL alerts — computed where?** OQ C.10.1
   says S10 computes it. For SIGNAL alerts the threshold is implicit
   (the signal model fired). Should `display_trigger.threshold_value` be
   the model's decision boundary (often opaque)? Or omit `threshold_value`
   and render only `current_value`? Recommend the latter: when
   `threshold_value` is null, the UI renders just `AAPL last 234.12`.

5. **Bulk-snooze interaction with localStorage local-only ACKs.** OQ-9.12
   adds Bulk-Snooze. The existing local-only ACK fallback (when backend
   returns 404) means some alerts in the selection may be local-only.
   Does bulk-snooze fall back to local-only too? Recommend: yes, same
   pattern — fire-and-forget backend PATCH per alert, fall back to
   localStorage on 404, render the `(local only)` badge.

6. **Compare page persistence.** OQ-9.3 v1 compare set is in-memory. When
   the user navigates away and comes back, should the comparison persist?
   Recommend: persist the compare-set in URL (`/compare?a=…&b=…`) and
   nowhere else — the URL is the source of truth, no localStorage needed
   for v1.

---

**End of cluster file.**
