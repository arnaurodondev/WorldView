"use client";

/**
 * useDebugFlag — read `?debug=1` from the URL once and memoize.
 *
 * WHY this hook exists (PRD-0089 Q-8):
 * Wave K introduces debug surfaces (ToolTraceDrawer) that expose internal
 * retrieval-plan / tool-call trace data. Q-8 decided that the ONLY way to
 * unlock these surfaces is via the `?debug=1` URL query parameter — there
 * MUST be no cookie, no localStorage, and no sessionStorage persistence.
 *
 * WHY no persistence:
 * - URL sharing is the only intended distribution vector ("paste me the
 *   `?debug=1` link and reproduce the issue") — thesis-grade auditability.
 * - No risk of a developer accidentally enabling debug on a demo by clicking
 *   a button and forgetting to disable it on browser restart.
 * - No GDPR/privacy concern about a persisted "debug user" classification.
 *
 * WHY useMemo over the `params` object:
 * Next.js `useSearchParams()` returns a `ReadonlyURLSearchParams` whose
 * identity is stable across renders for a given URL but may change on
 * navigation. Memoizing on the `params` reference keeps the boolean
 * referentially stable for downstream `useEffect` deps (e.g. the chord
 * registration in `useToolTraceChord`) so we don't tear down + re-add
 * listeners on every parent re-render.
 *
 * WHY "use client":
 * `useSearchParams` is a Client Component hook — it reads from the browser
 * URL. Server Components don't have a URL bar.
 */

import { useSearchParams } from "next/navigation";
import { useMemo } from "react";

export function useDebugFlag(): boolean {
  // `useSearchParams` may return null during the initial render in some
  // edge cases (e.g. when used outside a Suspense boundary on first paint).
  // We guard with `?.` to default to "not debug" — safest default.
  const params = useSearchParams();
  return useMemo(() => params?.get("debug") === "1", [params]);
}
