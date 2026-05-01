/**
 * components/feedback/FeedbackDeepLinkHandler.tsx — query-param trigger.
 *
 * WHY THIS EXISTS (PLAN-0052 Wave E T-E-5-08):
 * Marketing emails, error notifications, and external bug-tracker macros
 * want to deep-link a user straight into the feedback modal with sensible
 * defaults — for example:
 *
 *   https://app.worldview.io/dashboard?feedback=bug&page=/portfolio
 *
 * This handler watches the URL search params on every navigation; when it
 * sees `feedback=<kind>`, it fires the existing
 * `worldview:open-feedback` CustomEvent (consumed by FeedbackButton) with
 * the appropriate tab + a pre-filled description that surfaces the
 * `page=...` value. Then it strips the params via `router.replace` so a
 * page refresh doesn't re-trigger the modal.
 *
 * VALID `feedback` values (must match FeedbackButton's allow-list):
 *   bug | feature | ux | general | contact
 * Any other value is ignored silently — we never crash on a typo.
 *
 * WHY a Suspense-friendly component (must be wrapped in <Suspense> by the
 * parent): `useSearchParams` opts the entire route into client-side
 * rendering on Next.js 15, but only the parts that USE it. By isolating
 * the hook here, we keep the rest of the (app) shell statically renderable
 * (RSC streaming preserved), and Next requires the boundary so the
 * pre-rendered HTML doesn't suspend mid-stream.
 *
 * SECURITY:
 *   - We only READ params, never write them to anything user-visible
 *     without sanitisation. The page= value is sliced to 200 chars and
 *     embedded inside a fixed prefix string ("Reported from: ...") to
 *     avoid arbitrary text becoming a UI/CSS injection vector.
 *   - The cleanup `router.replace` uses the current pathname + the
 *     remaining (non-feedback) params; this avoids URL pollution but does
 *     NOT escape user data — Next.js's URLSearchParams handles encoding.
 */

"use client";
// WHY "use client": uses useSearchParams + useRouter + side-effect dispatch,
// all of which require the React runtime in the browser.

import { useEffect, useRef } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

/** Allow-list of valid `feedback` query values. Anything else is ignored. */
const VALID_KINDS = new Set(["bug", "feature", "ux", "general", "contact"]);

/**
 * Cap on the `page` query value before we stuff it into the description.
 * Keeps the prefilled body within the 5000-char backend limit even after
 * concatenation with the prefix and any user typing.
 */
const MAX_PAGE_HINT_LEN = 200;

/**
 * Always strip the feedback-related params from the URL after we process
 * them — even when `feedback=` was an invalid value. Stripping the failed
 * param prevents a refresh loop where each render re-evaluates the effect,
 * sees the same garbage value, and never cleans it. We preserve every
 * other param (e.g. `utm_source=email`) and the URL fragment.
 */
function buildCleanedUrl(
  pathname: string,
  searchParams: URLSearchParams,
): string {
  const next = new URLSearchParams(searchParams.toString());
  next.delete("feedback");
  next.delete("page");
  const remaining = next.toString();
  // Restore the fragment so URLs that carry meaningful state in `#…`
  // (e.g. anchor links, OAuth state) survive the cleanup.
  // PLAN-0052 Wave E QA-iter1 sec/m-1: previously dropped silently.
  const hash = typeof window !== "undefined" ? window.location.hash : "";
  return `${pathname}${remaining ? `?${remaining}` : ""}${hash}`;
}

export function FeedbackDeepLinkHandler() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // PLAN-0052 Wave E QA-iter1 bugs/B1: dedup against React StrictMode's
  // double-mount AND against the searchParams-snapshot-changes-on-every-
  // commit pattern. The ref records the last `feedback=...` value we
  // already handled; when the same value re-arrives within the lifetime
  // of this component instance we skip dispatch + URL cleanup. The ref
  // resets to `null` only on unmount (component is global so that's at
  // sign-out / route-group exit).
  const lastHandledRef = useRef<string | null>(null);

  useEffect(() => {
    // PLAN-0052 Wave E T-E-5-08: read params on every navigation tick.
    // searchParams is reactive in Next 15 — switching pages re-runs this
    // effect with the new URL.
    const kind = searchParams.get("feedback");

    // No `feedback=` param at all → nothing to do; reset the dedup ref so
    // the next deep link starts fresh (e.g. user navigates to /dashboard
    // then to /portfolio?feedback=bug — second link must fire).
    if (!kind) {
      lastHandledRef.current = null;
      return;
    }

    // Build the dedup signature from kind + page so two consecutive
    // identical deep links collapse but `?feedback=bug&page=/a` then
    // `?feedback=bug&page=/b` count as two distinct intents.
    const pageRaw = searchParams.get("page") ?? "";
    const signature = `${kind}::${pageRaw}`;
    if (lastHandledRef.current === signature) {
      // Already processed this exact deep link — likely React StrictMode
      // dev double-mount or an effect re-fire from an unrelated parent
      // re-render. Skip silently.
      return;
    }
    lastHandledRef.current = signature;

    // Always strip the params from the URL — even when the kind is
    // invalid — so a refresh doesn't keep re-evaluating garbage and the
    // user can't see `?feedback=bogus` lingering in the address bar.
    // PLAN-0052 Wave E QA-iter1 bugs/M-4.
    const cleanedUrl = buildCleanedUrl(pathname, searchParams);

    if (!VALID_KINDS.has(kind)) {
      // Strip and exit — nothing to dispatch, but we still need to clean
      // the URL so the bad value doesn't pollute history.
      router.replace(cleanedUrl, { scroll: false });
      return;
    }

    // Page hint — optional, may be absent for "open feedback for this
    // arbitrary page" links. We slice + trim to keep the prefill compact.
    const pageHint = pageRaw.slice(0, MAX_PAGE_HINT_LEN).trim();

    // Build the prefill body. WHY a fixed prefix: surface the page hint
    // as plain context the user can edit/delete before submitting. We
    // never inject HTML — this is a textarea value.
    const description = pageHint ? `Reported from: ${pageHint}\n\n` : "";

    // Fire the event the FeedbackButton listens for. We type the detail
    // shape inline so consumers know exactly what arrives.
    window.dispatchEvent(
      new CustomEvent("worldview:open-feedback", {
        detail: { tab: kind, description },
      }),
    );

    // WHY router.replace (not push): replace doesn't add a history entry;
    // back-button still returns to the previous page rather than this URL
    // sans-feedback-params (which would feel broken to the user).
    router.replace(cleanedUrl, { scroll: false });

    // We intentionally exclude `router` and `pathname` from the deps so the
    // effect only runs on actual searchParams change — including them
    // would re-fire after the cleanup replace() triggers a re-render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  // No visual output — this is a pure side-effect component.
  return null;
}
