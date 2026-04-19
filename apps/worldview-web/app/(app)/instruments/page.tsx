/**
 * app/(app)/instruments/page.tsx — Instruments index (redirects to Screener)
 *
 * WHY THIS EXISTS: The sidebar nav links to "/instruments" but the actual
 * instrument detail page lives at "/instruments/[entityId]". Without an index
 * page, clicking "Instruments" in the sidebar shows a 404.
 *
 * WHY REDIRECT (not a standalone page): The Screener page already provides
 * instrument discovery (search, filter, sort). Duplicating that here would be
 * redundant. A client-side redirect sends users to the right place instantly.
 *
 * WHO USES IT: Sidebar "Instruments" nav link click, direct /instruments URL access
 * DATA SOURCE: None — pure redirect
 * DESIGN REFERENCE: PRD-0028 §6.3 Navigation
 */

"use client";
// WHY "use client": useRouter and useEffect require client rendering.

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function InstrumentsIndexPage() {
  const router = useRouter();

  // WHY useEffect redirect (not middleware): middleware runs server-side and
  // can't be in a route group file. Client-side redirect is simplest here.
  useEffect(() => {
    router.replace("/screener");
  }, [router]);

  // Brief loading state while the redirect fires
  return (
    <div className="flex h-64 items-center justify-center">
      <p className="text-sm text-muted-foreground">
        Redirecting to Screener…
      </p>
    </div>
  );
}
