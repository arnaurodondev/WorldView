/**
 * app/api/version/route.ts — Build-version probe for the force-update banner.
 *
 * WHY THIS EXISTS (PLAN-0059 B-6): when we deploy a new frontend build, tabs
 * already loaded by traders keep running the OLD bundle. They will silently
 * miss bugfixes / new features until the user happens to hard-refresh.
 * Worse: if S9 contracts shift in a way the old client cannot handle (rare
 * but possible during fast iteration), the user sees broken pages.
 *
 * The banner polls this endpoint every 60s. If the build id it observes
 * differs from the one snapshotted at first mount → show the banner. Only
 * the user can trigger the reload (no auto-reload — we won't yank a chart
 * out from under a trader scanning a price move).
 *
 * BUILD ID SOURCE: `process.env.NEXT_PUBLIC_BUILD_ID`. CI sets this to the
 * git commit SHA at build time; falls back to "dev" locally so the banner
 * never fires during development hot-reload.
 *
 * SECURITY: returns nothing user-specific — just the build id. Public.
 * No auth required.
 */

import { NextResponse } from "next/server";

// WHY force dynamic: a static-rendered version endpoint would cache the build
// id at *build time* on the EDGE — every poll would hit the cache and we'd
// never observe a fresh build. `force-dynamic` tells Next.js to re-evaluate
// on every request, picking up runtime env changes too.
export const dynamic = "force-dynamic";

// WHY revalidate=0: belt-and-suspenders alongside force-dynamic. Some
// deployment platforms cache responses at a CDN even when force-dynamic is
// set; revalidate=0 sets `Cache-Control: no-store, must-revalidate`.
export const revalidate = 0;

export function GET() {
  // The build id at request time. In production CI sets NEXT_PUBLIC_BUILD_ID
  // to the commit SHA; locally the fallback "dev" matches the client-side
  // value, so the banner is a no-op in dev (mismatch never happens).
  const buildId = process.env.NEXT_PUBLIC_BUILD_ID ?? "dev";

  return NextResponse.json(
    { buildId },
    {
      headers: {
        // Aggressive no-cache: any intermediary cache would defeat the point.
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
      },
    },
  );
}
