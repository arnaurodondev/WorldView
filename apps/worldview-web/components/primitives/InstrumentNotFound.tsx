/**
 * components/primitives/InstrumentNotFound.tsx — terminal-grade 404 surface
 *
 * WHY THIS EXISTS (PRD-0089 F2 step 10): once the URL slug is unified on
 * ticker (e.g. `/instruments/AAPL`), every typo or stale link will land on a
 * page where the page-bundle query returns 404. A blank screen or a Next.js
 * default error page is hostile for a terminal user. Instead, the instrument
 * page renders this primitive — a dense, sharp-cornered "ticker unknown"
 * affordance with optional fuzzy-match suggestions and an escape hatch to
 * the screener (the canonical "where do I find tickers?" surface).
 *
 * WHO USES IT: InstrumentPageClient (when useInstrumentBundle returns a 404
 * GatewayError). Suggested-tickers wiring (S9 fuzzy-match) is out of scope
 * for this step; the prop is accepted so the future wiring is a one-line
 * change at the consumer site, not a primitive rewrite.
 *
 * DATA SOURCE: pure presentational primitive — no data / no state / no
 * effects. All inputs come in via props.
 *
 * DESIGN REFERENCE:
 *   - PRD-0089 F2 step 10 (this step).
 *   - PRD-0089 F1 §2.1 — Bloomberg-grade Terminal Dark palette.
 *     Error red token = `--negative` (#EF5350). NOT pure `text-red-500`
 *     (banned by architecture test no-off-palette-colors).
 *   - PRD-0088 §6.11 typography: IBM Plex Sans for labels, IBM Plex Mono
 *     for tickers + numbers, tabular-nums on numeric columns.
 *   - F1 §2.4 spacing — `gap-1` (4) / `gap-2` (8) max inside this card.
 *
 * TARGET READER: junior Next.js dev. Two finance-UX conventions enforced:
 *   1. Ticker symbols MUST render in mono (Plex Mono via `font-mono`) so
 *      "AAPL" vs "AAPLO" stay column-aligned in any future list context.
 *   2. The "INSTRUMENT NOT FOUND" badge is tinted via `--negative` (muted
 *      red), not bright destructive red — terminal aesthetic is desaturated.
 *
 * SERVER COMPONENT: no useState / useEffect / event handlers. Renders pure
 * JSX with a couple of Next.js `<Link>` elements (RSC-compatible).
 */

import type { ReactElement } from "react";
import Link from "next/link";

// ── Public props ─────────────────────────────────────────────────────────────
//
// WHY readonly fields: matches the project convention for prop interfaces.
// WHY `attemptedTicker: string` not `?: string`: the consumer site (the page
// 404 branch) ALWAYS has the slug — there's no ambiguous "no ticker" branch
// here; that case is handled by the existing `entityId === "undefined"`
// redirect in InstrumentPageClient.
export interface InstrumentNotFoundProps {
  /** The slug from the URL the user attempted (already uppercase from middleware). */
  readonly attemptedTicker: string;
  /**
   * Optional fuzzy-match suggestions from S9. Up to 5; the primitive truncates
   * silently if more are passed (defensive — the API contract should already
   * cap at 5). Out of scope for this step: wiring the S9 fuzzy-match call.
   */
  readonly suggestedTickers?: readonly string[];
}

// ── Suggestion cap ───────────────────────────────────────────────────────────
//
// WHY a constant (not inline 5): keeps the cap discoverable for the future
// S9 fuzzy-match endpoint — if the contract changes, only one number moves.
const MAX_SUGGESTIONS = 5;

export function InstrumentNotFound({
  attemptedTicker,
  suggestedTickers,
}: InstrumentNotFoundProps): ReactElement {
  // WHY toUpperCase defensively: the unification middleware (PRD-0089 F2 step 9)
  // uppercases on redirect, but this primitive may be reused in a test harness
  // or a future surface that bypasses the middleware. Cheap, idempotent.
  const ticker = attemptedTicker.toUpperCase();

  // WHY slice(0, MAX_SUGGESTIONS): defensive truncation in case the future
  // S9 caller passes more than the agreed cap. Empty array → no list block.
  const suggestions = (suggestedTickers ?? []).slice(0, MAX_SUGGESTIONS);

  return (
    // WHY flex column + items-start: dense terminal-grade layout, left-aligned
    // (no consumer-app vertical centering). gap-2 (8px) is the upper ceiling
    // for this small block per F1 §2.4.
    // WHY border-border-strong NOT shadow: F1 mandates zero shadows on the
    // terminal palette; the boundary affordance is a 1px hairline border.
    // WHY p-3 (12px): F1 §2.4 — panel inner padding.
    // WHY bg-card: surface elevation 1 — same as the panels the user is used to.
    <div className="flex flex-col items-start gap-2 border border-border-strong bg-card p-3">
      {/* ── Error label ─────────────────────────────────────────────────────
          WHY text-[10px] uppercase tracking-wide: F1 §2.3 typography token
          for column / group headers. Matches MetricLabel sizing so visual
          weight is consistent with the rest of the instrument page.
          WHY text-negative (NOT text-destructive): F1 docs/ui/DESIGN_SYSTEM.md
          maps "price down / loss / error" to `--negative` (#EF5350 muted red).
          `text-destructive` is reserved for *delete* actions (CTAs). */}
      <span className="text-[10px] uppercase tracking-wide text-negative">
        INSTRUMENT NOT FOUND
      </span>

      {/* ── Attempted ticker ───────────────────────────────────────────────
          WHY font-mono + tabular-nums: IBM Plex Mono with tabular figures
          guarantees the ticker renders in the same cell-grid metric used
          elsewhere on the platform. tabular-nums is harmless for letters
          and the same span may later display alphanumeric tickers (e.g.
          "BRK.B"). text-[14px] is the F1 §2.3 "hero" tier — this is the
          single most prominent number/symbol on the surface, matching the
          instrument page's primary-price tier. */}
      <span className="text-[14px] font-mono tabular-nums uppercase text-foreground">
        {ticker}
      </span>

      {/* ── Suggestions (optional) ─────────────────────────────────────────
          WHY conditional render: when there are zero suggestions, the
          "Did you mean" block disappears entirely — no empty header,
          no reserved row. F1 §1 acceptance signal: density floor enforced. */}
      {suggestions.length > 0 ? (
        <div className="flex flex-col gap-1">
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Did you mean:
          </span>
          {/* WHY flex-wrap + gap-2: tickers are short (≤6 chars typically);
              wrapping keeps the block dense on narrow viewports. */}
          <div className="flex flex-wrap gap-2">
            {suggestions.map((suggestion) => {
              // WHY uppercase + .toUpperCase(): same defensive normalisation
              // as the attempted ticker. Future S9 callers may pass lowercase.
              const candidate = suggestion.toUpperCase();
              return (
                <Link
                  key={candidate}
                  href={`/instruments/${candidate}`}
                  // WHY font-mono on suggestions: tickers must always be mono.
                  // WHY text-primary (Bloomberg yellow): F1 §2.1 — `--primary`
                  // is the affordance colour for interactive surfaces in
                  // terminal-dark. hover:underline is the Tier-1 affordance
                  // transition; per F1 §2.6, hover state is allowed and
                  // limited to color/border-color (no transforms / shadows).
                  className="text-[11px] font-mono tabular-nums text-primary hover:underline"
                >
                  {candidate}
                </Link>
              );
            })}
          </div>
        </div>
      ) : null}

      {/* ── Escape hatch ───────────────────────────────────────────────────
          WHY always rendered: even with suggestions, the user may want to
          browse the full screener. The arrow glyph is a deliberate terminal
          affordance (Bloomberg HELP overlays use the same "→" pattern). */}
      <Link
        href="/screener"
        className="text-[11px] text-muted-foreground hover:text-foreground hover:underline"
      >
        Browse all instruments →
      </Link>
    </div>
  );
}
