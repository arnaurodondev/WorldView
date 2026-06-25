/**
 * components/primitives/EmptyState.tsx — single primitive for 5+ conditions
 *
 * WHY THIS EXISTS: PRD-0089 F1 §3.2 + FU-10.10 — every empty-state surface
 * (loading / no-data / error / permission / coming-soon) renders identically
 * to keep the visual language consistent. Per-page agents pass a `copyKey`
 * that resolves to the central dictionary in `lib/copy/empty-states.ts`.
 * Bloomberg/Eikon use a similar centralised pattern in OMS panels.
 * WHO USES IT: Dashboard widgets, Portfolio, Quote, Financials,
 *   Intelligence, Screener, Workspace, Chat — every surface that may
 *   render zero rows.
 * DATA SOURCE: Caller passes condition + copyKey + optional CTA.
 * DESIGN REFERENCE: PRD-0089 F1 §3.2 (EmptyState row) + FU-10.10/10.11.
 */

import type { ReactNode } from "react";
// WHY a type-only import: LucideIcon is just the component signature — the
// caller imports the concrete glyph (Newspaper, Share2, …), so this primitive
// adds zero icon bytes to bundles that don't pass one.
import type { LucideIcon } from "lucide-react";

import { EMPTY_COPY, type EmptyCopyKey } from "@/lib/copy/empty-states";

type EmptyCondition =
  | "loading"
  | "empty-cold-start"
  | "empty-no-data"
  | "error"
  | "permission"
  | "coming-soon";

interface EmptyStateProps {
  readonly condition: EmptyCondition;
  /** Key into `lib/copy/empty-states.ts`. Falls back to `generic.<condition>`. */
  readonly copyKey: EmptyCopyKey | string;
  /**
   * Optional CTA element rendered below the body text.
   *
   * @deprecated Prefer `action` for new code — same slot, clearer name
   * (Round-2 API alignment with the instrument surface's request). Kept so
   * existing call sites render unchanged; when both are passed, `action` wins.
   */
  readonly cta?: ReactNode;
  /**
   * Optional lucide icon component rendered ABOVE the title, muted at 16px.
   *
   * WHY (Round-2 cross-surface request, item 4): the instrument surface built
   * its own `components/instrument/shared/EmptyState.tsx` specifically because
   * this primitive was icon-less — an icon gives an instant visual category
   * ("no news" vs "no graph") that copy alone can't. Adding the prop here lets
   * that fork become a thin wrapper (Round-3 consolidation, DS §15.12).
   * Pass the COMPONENT (e.g. `icon={Newspaper}`), not an element — the
   * primitive controls size/color so every surface renders identically.
   */
  readonly icon?: LucideIcon;
  /**
   * Optional action slot rendered below the body text — typically a real
   * `<Button>` wired to an onClick (retry, regenerate), not just an href
   * `<Link>`. ReactNode (not a {label, onClick} config) so surfaces keep full
   * control over the element while the primitive owns layout position only.
   */
  readonly action?: ReactNode;
}

export function EmptyState({ condition, copyKey, cta, icon: Icon, action }: EmptyStateProps): ReactNode {
  // WHY a per-condition fallback: pages can pass any copyKey but must always
  // get a sensible render even if the key is missing (e.g. before the
  // empty-copy-dictionary arch-test catches it).
  const copy = EMPTY_COPY[copyKey] ?? EMPTY_COPY[`generic.${condition}`];
  if (!copy) {
    return null;
  }
  return (
    <div
      role="status"
      aria-live={condition === "loading" ? "polite" : "off"}
      className="flex flex-col items-center justify-center gap-1 px-3 py-4 text-center"
    >
      {/* WHY aria-hidden + muted/60: the icon is decorative category signal —
          the title carries the information for screen readers. size-4 (16px)
          + strokeWidth 1.5 matches the instrument surface's existing pattern
          so the Round-3 consolidation is pixel-identical. */}
      {Icon ? <Icon className="size-4 text-muted-foreground/60" strokeWidth={1.5} aria-hidden /> : null}
      <p className="text-[12px] text-foreground">{copy.title}</p>
      <p className="text-[11px] text-muted-foreground">{copy.body}</p>
      {/* `action` (new, preferred) wins over legacy `cta`; both occupy the
          same single slot so passing both never double-renders buttons. */}
      {action ?? cta ?? null}
    </div>
  );
}
