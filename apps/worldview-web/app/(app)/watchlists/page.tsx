/**
 * app/(app)/watchlists/page.tsx — Redirect stub for legacy /watchlists URL.
 *
 * WHY THIS EXISTS (F-DP1-17, audit 2026-04-29): some bookmarks, slash-command
 * cards (e.g. ``/watchlist`` in chat), and external links target the bare
 * ``/watchlists`` path. The actual watchlist surfaces live inside the
 * Workspace (``WorkspaceWatchlistWidget``) and the Dashboard
 * (``WatchlistMoversWidget``), so a top-level page is not part of the
 * production IA. Pre-fix this URL 404'd.
 *
 * Resolution: server-side redirect to ``/workspace`` (the canonical home of
 * the watchlist widget). ``next/navigation``'s ``redirect()`` returns a 307
 * with ``location: /workspace`` so the browser preserves the original
 * intent (bookmark → workspace) without flashing a 404.
 *
 * If a dedicated ``/watchlists`` IA emerges later, replace this redirect
 * with a real page.tsx — the route shell is already in place.
 */

import { redirect } from "next/navigation";

export default function WatchlistsRedirect() {
  // 307 Temporary Redirect — preserves the original HTTP method and lets
  // future IA changes lift the redirect without consumers caching it.
  redirect("/workspace");
}
