/**
 * components/primitives/DemoBadge.tsx — "DEMO" chip in PortfolioSwitcher
 *
 * WHY THIS EXISTS: PRD-0089 F1 §3.2 + FU-1.5 — when a user is viewing a
 * demo / sample portfolio (read-only), we need an unambiguous visual flag
 * in the switcher and on the page header so they don't mistake it for a
 * real account.  Bloomberg's paper-trading panels show a similar chip.
 * WHO USES IT: PortfolioSwitcher dropdown, Dashboard header, Portfolio
 *   overview header.
 * DATA SOURCE: Pure presentational — caller decides when to render based
 *   on portfolio.kind === "demo" from /v1/portfolios.
 * DESIGN REFERENCE: PRD-0089 F1 §3.2 (DemoBadge row).
 */

import type { ReactNode } from "react";

export function DemoBadge(): ReactNode {
  return (
    <span
      role="img"
      aria-label="Demo portfolio"
      className="inline-flex items-center border border-warning px-1 font-mono text-[9px] uppercase tracking-wide text-warning"
    >
      Demo
    </span>
  );
}
