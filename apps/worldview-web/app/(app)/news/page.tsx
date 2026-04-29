/**
 * app/(app)/news/page.tsx — Redirect stub for legacy /news URL.
 *
 * WHY THIS EXISTS (F-DP1-17, audit 2026-04-29): the dedicated news feed
 * is integrated into the ``/alerts`` page (Tab 2 = Relevant News, Tab 3
 * = Top Today) and the chat ``/news`` slash-command surfaces a card. A
 * top-level ``/news`` route was previously 404'ing for users typing the
 * URL directly or following stale links.
 *
 * Resolution: server-side redirect to ``/alerts`` where the news tabs
 * actually live (see ``app/(app)/alerts/page.tsx`` Tab 2/3). 307 preserves
 * the user intent without flashing a 404.
 *
 * If PRD-0027/PLAN-0050 promotes news to a standalone page, replace this
 * redirect with the real page.
 */

import { redirect } from "next/navigation";

export default function NewsRedirect() {
  // 307 — alerts page hosts the news tabs (Tab 2: relevant; Tab 3: top).
  redirect("/alerts");
}
