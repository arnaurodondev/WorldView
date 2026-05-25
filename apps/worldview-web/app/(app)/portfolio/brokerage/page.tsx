/**
 * app/(app)/portfolio/brokerage/page.tsx — Redirect stub for /portfolio/brokerage
 *
 * WHY THIS EXISTS: The SnapTrade OAuth callback lands at
 * /portfolio/brokerage/callback (handled by callback/page.tsx). The parent
 * segment /portfolio/brokerage has no page.tsx, which makes Next.js return a
 * hard 404 if anyone navigates there directly (e.g. Settings › Integrations
 * deep-link, old bookmark, or a stale URL embedded in a notification email).
 *
 * The Brokerages panel was merged into the Transactions tab on the main
 * portfolio page (see portfolio/page.tsx §"WHY no Brokerages tab"). So the
 * correct redirect destination is /portfolio?tab=transactions.
 *
 * WHY permanent=false (307): this is a product-structure redirect, not a
 * permanent URL rewrite. If we ever add a dedicated brokerage management page
 * we can promote this to a 301 or replace it with real content.
 *
 * WHO USES IT: anyone hitting /portfolio/brokerage directly (deep-link, old
 * bookmark, Settings › Integrations CTA that previously pointed here).
 *
 * DATA SOURCE: none — static redirect only.
 * PLAN REFERENCE: SA-5 beta-hardening pass (2026-05-10).
 */

import { redirect } from "next/navigation";
// WHY redirect() from next/navigation (not <meta http-equiv> or JS router):
// redirect() is the Next.js App Router primitive for server-side redirects.
// It is executed at render time, produces the correct 307 response header,
// and is entirely transparent to SEO crawlers — no client-side JS needed.

export default function BrokeragePage() {
  // WHY /portfolio/transactions: W2 moved the Transactions tab to its own route.
  // The old /portfolio?tab=transactions param no longer works after tabs were removed
  // in PRD-0089 W2 §4.19. /portfolio/transactions is the new canonical destination.
  redirect("/portfolio/transactions");
}
