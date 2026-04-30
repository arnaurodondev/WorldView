/**
 * app/callback/error-messages.ts — OIDC callback error copy
 *
 * WHY THIS FILE EXISTS (PLAN-0059 W0 fix F-001 — 2026-04-30):
 * Next.js 15 App Router page files (`page.tsx`) only allow specific named
 * exports recognised by the framework (`default`, `metadata`, `viewport`,
 * `dynamic`, `revalidate`, `fetchCache`, `runtime`, `preferredRegion`,
 * `experimental_ppr`, `generateStaticParams`, `generateMetadata`,
 * `generateViewport`). Any additional export collides with the page
 * type-constraint `{ [x: string]: never; }` and breaks `tsc` (TS2344) AND
 * `next build`. The previous Wave A diff added `export const ERROR_MESSAGES`
 * to `page.tsx` so tests could import it; that broke production build.
 *
 * Fix: relocate the constants to this sibling module. `page.tsx` imports
 * from here; tests also import from here. No more page-export collision.
 *
 * BUG PATTERN: BP-NEW — "Next.js page module export collides with PageProps
 * never constraint". See docs/BUG_PATTERNS.md.
 */

// ── Error types for user-facing messages ──────────────────────────────────────
// WHY four discrete types: each failure mode has a different remediation.
// Surfacing a specific guidance line ("start over" vs "open in the original
// tab" vs "try again") helps the user resolve the issue without guessing.
export type CallbackErrorType =
  | "state_mismatch"    // CSRF: state in URL doesn't match sessionStorage
  | "missing_code"      // Zitadel didn't return a code (auth was cancelled or failed)
  | "exchange_failed"   // S9 token exchange returned an error
  | "missing_verifier"; // sessionStorage was cleared mid-flow (tab was closed and re-opened)

// WHY both `title` and `description`: the title gives a quick scan signal
// (what happened) while the description gives the recovery action (what to
// do about it). Two-line layouts are standard for institutional error pages.
export interface CallbackErrorCopy {
  title: string;
  description: string;
}

export const ERROR_COPY: Record<CallbackErrorType, CallbackErrorCopy> = {
  state_mismatch: {
    title: "Security check failed",
    description:
      "The state token in the callback URL doesn't match the one we issued. " +
      "This usually happens when the callback was opened in a different browser " +
      "or after the login session expired. Please start over from the login page.",
  },
  missing_code: {
    // WHY "or failed" in the title: keeps the legacy phrase for tests +
    // covers the case where the IdP returned ?error= (server-side failure)
    // in addition to user cancellation.
    title: "Authentication was cancelled or failed",
    description:
      "We didn't receive an authorization code from the identity provider. " +
      "This typically means you cancelled the sign-in or the provider rejected " +
      "the request. Please try again.",
  },
  exchange_failed: {
    title: "Unable to complete sign-in",
    description:
      "The token exchange with the identity provider failed. This could be a " +
      "temporary network issue or a problem with the gateway. Wait a moment and try again.",
  },
  missing_verifier: {
    title: "Login session expired",
    description:
      "We couldn't find the verifier we stored when you started signing in. " +
      "This happens if the browser tab was closed or storage was cleared mid-flow. " +
      "Please open the login page in the same tab and start over.",
  },
};

// Backwards-compat alias: existing tests assert on ERROR_MESSAGES[type] strings.
// Map the new title+description into the legacy single-string shape so old
// assertions keep passing while new tests can opt into the richer copy.
export const ERROR_MESSAGES: Record<CallbackErrorType, string> = Object.fromEntries(
  Object.entries(ERROR_COPY).map(([k, v]) => [k, `${v.title}. ${v.description}`]),
) as Record<CallbackErrorType, string>;
