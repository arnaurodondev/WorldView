/**
 * features/chat/components/ContradictionStrip.tsx — KG contradiction surfacing.
 *
 * WHY THIS EXISTS (PLAN-0089 K Block C, T-11):
 *   The S8 rag-chat SSE stream emits a `contradictions` event when the
 *   knowledge-graph subsystem detects conflicting claims about an entity
 *   during retrieval (e.g. "Apple Inc. founded in 1976" vs. "1977"; or two
 *   analyst notes with opposite outlook for the same ticker). Until Wave K
 *   the frontend SILENTLY DISCARDED that event — the whole point of a KG
 *   in a finance chat was wasted. T-11 surfaces it as a compact strip that
 *   renders both INLINE under the assistant turn (so the analyst sees the
 *   contradiction next to the answer that referenced it) and AGGREGATED in
 *   the right-hand `ChatContextRail` (T-16) so the analyst can review all
 *   contradictions across the thread.
 *
 *   Each row reads `claim_type` + a HIGH/MEDIUM/LOW severity derived from
 *   the `strength` score. The component does NOT fetch — it just renders
 *   the prop array the chat hook populated from the SSE event.
 *
 * DATA SOURCE: `Message['contradictions']` populated by `useChatStream.ts`
 *   from the S8 `contradictions` SSE event payload.
 *
 * DESIGN REFERENCE: docs/designs/0089/10-chat-ai.md §5 (citation/contradiction
 *   strip placement) + design system semantic tokens (`text-negative` /
 *   `text-warning` / `text-muted-foreground`).
 */

import type { Message } from "@/types/api";

/**
 * Severity is a derived enum, NOT a wire field — backend only sends
 * `strength` as a float. We map it client-side so future palette changes
 * (e.g. introducing a "critical" tier) only touch this component.
 *
 * THRESHOLD CHOICE: 0.7 / 0.4 mirrors the existing convention used by
 * `EntityHealthDot` (T-15 — coming Block D) for health_score. Re-using the
 * same break points keeps the visual language consistent across rails.
 */
type Severity = "HIGH" | "MEDIUM" | "LOW";

const HIGH_SEVERITY_MIN = 0.7;
const MEDIUM_SEVERITY_MIN = 0.4;

function deriveSeverity(strength: number | undefined | null): Severity {
  // Defensive: treat missing / NaN strength as LOW. Better to under-alarm
  // the analyst than to colour an unknown-strength claim as HIGH.
  if (typeof strength !== "number" || Number.isNaN(strength)) return "LOW";
  if (strength >= HIGH_SEVERITY_MIN) return "HIGH";
  if (strength >= MEDIUM_SEVERITY_MIN) return "MEDIUM";
  return "LOW";
}

const SEVERITY_CLASS: Record<Severity, string> = {
  HIGH: "text-negative",
  MEDIUM: "text-warning",
  LOW: "text-muted-foreground",
};

interface ContradictionStripProps {
  /**
   * Contradictions array exactly as parsed from the SSE event. We type it
   * via `NonNullable<Message['contradictions']>` so the source of truth is
   * the wire-shape interface in `types/api.ts` — if that shape evolves the
   * strip surfaces the type error at the call site.
   */
  readonly contradictions: NonNullable<Message["contradictions"]>;
  /**
   * Optional click-through. `ChatContextRail` (T-16) wires this to open
   * the full contradiction explainer drawer; inline usage under a turn
   * leaves it unset and the row is non-interactive.
   */
  readonly onOpen?: () => void;
}

/**
 * coerceStrength — `contradictions` SSE payload uses `Record<string, unknown>`
 * (Q-9 wire shape is intentionally permissive). We narrow the `strength`
 * field at the rendering boundary instead of widening the wire type, so
 * future fields can land without ripple. Returns undefined if absent.
 */
function coerceStrength(entry: Record<string, unknown>): number | undefined {
  const v = entry.strength;
  return typeof v === "number" ? v : undefined;
}

/**
 * coerceClaimType — same narrowing for `claim_type`. Falls back to
 * `"unknown"` so the row never renders a blank cell.
 */
function coerceClaimType(entry: Record<string, unknown>): string {
  const v = entry.claim_type;
  return typeof v === "string" && v.length > 0 ? v : "unknown";
}

/**
 * ContradictionStrip — see file header. Returns `null` for empty arrays
 * (same convention as `CitationStrip` / Wave K rule of "render nothing
 * when nothing to show").
 */
export function ContradictionStrip({ contradictions, onOpen }: ContradictionStripProps) {
  if (contradictions.length === 0) return null;

  return (
    <div
      className="mt-1 border border-border bg-card"
      role="list"
      aria-label="Contradictions detected by knowledge graph"
    >
      <div className="flex h-[16px] items-center gap-2 border-b border-border bg-muted/40 px-2 text-[9px] font-mono uppercase text-muted-foreground">
        <span>contradictions</span>
        <span className="tabular-nums">· {contradictions.length}</span>
      </div>
      {contradictions.map((entry, idx) => {
        const strength = coerceStrength(entry);
        const claimType = coerceClaimType(entry);
        const severity = deriveSeverity(strength);
        // Pretty-print strength as `0.82` (2 dp). Mono + tabular-nums so
        // the column aligns even when rows have different severities.
        const strengthLabel = typeof strength === "number" ? strength.toFixed(2) : "—";
        return (
          <button
            key={`${claimType}-${idx}`}
            type="button"
            data-cell
            data-contradiction-row={idx}
            onClick={onOpen}
            // Disable pointer interactions when no handler is wired — the
            // row is still a `<button>` for a11y semantics (it's a list
            // item with potential affordance) but it shouldn't show a
            // hover state if nothing happens on click.
            disabled={!onOpen}
            className="flex h-[18px] w-full items-center gap-2 border-t border-border px-2 text-left text-[10px] font-mono first:border-t-0 disabled:cursor-default enabled:hover:bg-muted/40 transition-color-only duration-75"
          >
            <span className={`uppercase tabular-nums ${SEVERITY_CLASS[severity]}`}>
              {severity}
            </span>
            <span className="truncate flex-1 text-foreground">{claimType}</span>
            <span className="text-muted-foreground tabular-nums">{strengthLabel}</span>
          </button>
        );
      })}
    </div>
  );
}
