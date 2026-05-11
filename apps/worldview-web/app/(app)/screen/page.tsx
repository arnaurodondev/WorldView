/**
 * app/(app)/screen/page.tsx — Redirect stub for /screen → /screener.
 *
 * WHY THIS EXISTS (F-DP1-17, audit 2026-04-29): some external references
 * (audits, slash-command suggestions, doc samples) use the shorter
 * ``/screen`` path while the production route is ``/screener`` (matches
 * the sidebar nav label). Pre-fix typing ``/screen`` returned 404.
 *
 * Resolution: server-side redirect to ``/screener``.
 */

import { redirect } from "next/navigation";

export default function ScreenRedirect() {
  // 307 — keep canonical /screener as the single source of truth.
  redirect("/screener");
}
