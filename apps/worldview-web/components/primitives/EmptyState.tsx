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
  /** Optional CTA element rendered below the body text. */
  readonly cta?: ReactNode;
}

export function EmptyState({ condition, copyKey, cta }: EmptyStateProps): ReactNode {
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
      <p className="text-[12px] text-foreground">{copy.title}</p>
      <p className="text-[11px] text-muted-foreground">{copy.body}</p>
      {cta ?? null}
    </div>
  );
}
