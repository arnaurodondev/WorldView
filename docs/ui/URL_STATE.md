# URL State Schema

> Canonical reference for which UI state is encoded in the URL.
> Adopted under PLAN-0059 C-6 (nuqs).

## Why URL state at all

Trader workflows are deep-link-heavy. When a PM shares a portfolio link in
chat, the recipient should land on the *exact* view the PM was looking at —
same tab, same period, same screener axis. Storing dimension state in
component-local React state breaks deep-link reproducibility.

`nuqs` is mounted at the provider tree root via `NuqsAdapter`
(`app/providers.tsx`). Any component can adopt URL-backed state with a
single hook call.

## Adopted dimensions (PLAN-0059 C-6)

| Surface | Param | Type | Default | Notes |
|---|---|---|---|---|
| `/portfolio` | `tab` | `holdings \| transactions \| watchlist` | `holdings` | `clearOnDefault` — no `?tab=holdings` noise |
| `/portfolio` | `period` | `1W \| 1M \| 3M \| 6M \| 1Y \| All` | `3M` | Equity-curve period; `clearOnDefault` |
| `/screener` | `sector` | string (GICS sector name) | `""` (all) | Free string; bar's own validation rejects unknowns |
| `/screener` | `capTier` | `ALL \| LARGE \| MID \| SMALL` | `ALL` | `clearOnDefault` |

## Out of scope (intentionally NOT in URL)

- **Full screener `FilterState`** (~25 numeric range fields). Encoding
  every range as `?peMin=10&peMax=20&pbMin=...` produces unreadable URLs
  and clutters the browser history. Use **Saved Screens** for full-state
  share/restore.
- **Workspace v1 panel layout, sidebar collapsed, column prefs**. These are
  per-user preferences (durable) — backed by `lib/storage/safe-storage.ts`
  → localStorage and (eventually) S9 user-preferences.
- **Modal open/close state**. Modals are ephemeral chrome; pushing a URL
  entry per dialog open would pollute back-button history.

## Conventions

1. **`clearOnDefault: true`** — when the value equals the default, drop the
   param so the canonical link stays short. Required for all URL-state
   adoptions.
2. **`parseAsStringLiteral([...] as const)`** — every enum-typed param uses
   this parser so unknown values fall back to the default (no crash).
3. **No JSON-encoded blobs** — keep URL params human-readable. If you find
   yourself reaching for a base64 payload, use Saved Screens / Saved
   Layouts instead.
4. **History push** is the default (back button works). Switch to
   `history: "replace"` only when the change shouldn't enter history (e.g.
   typing in a filter input — debounce + replace, then commit on blur).

## Adding a new URL-backed dimension

```tsx
import { useQueryState, parseAsStringLiteral } from "nuqs";

const [view, setView] = useQueryState(
  "view",
  parseAsStringLiteral(["grid", "list"] as const)
    .withDefault("grid")
    .withOptions({ clearOnDefault: true }),
);
```

1. Add the param row to the table above.
2. Add a unit test in `apps/worldview-web/__tests__/url-state.test.tsx`
   (round-trip + default + unknown-value fallback).
3. If the param crosses surfaces (e.g. a global "as-of date"), document
   that in the **Notes** column and consider whether it belongs in
   localStorage instead.

## Migration plan

The dimensions in §"Adopted" are the **first cut**. Future waves should
adopt URL state on:

- Workspace named layout (after Workspace v2 ships) — `?ws=<layout-id>`
- Instrument page chart timeframe — `?tf=1D|1H|5M`
- News feed source filter — `?source=<feed-id>`
- Alerts page severity — `?sev=critical|high`

Update this doc whenever a new dimension lands; the schema must stay
authoritative or deep-link contracts drift.
