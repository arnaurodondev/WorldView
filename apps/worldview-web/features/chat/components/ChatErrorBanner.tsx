/**
 * features/chat/components/ChatErrorBanner.tsx — Chat error banner.
 *
 * WHY THIS EXISTS (PLAN-0089 Wave K, Block E, T-18):
 *   The chat surface has two error UX paths previously inlined in
 *   `app/(app)/chat/page.tsx`:
 *     1. `auth` — JWT lapsed / 401. Surfaces a "Sign in" link routed to
 *        `/login?redirect_to=/chat`. Identified by PLAN-0052 QA round 5
 *        (2026-05-01) as the most common cause of generic "Failed to
 *        load" banners — hence the dedicated variant.
 *     2. `generic` — anything else (network, 5xx). Caller passes the
 *        message verbatim. No retry button: retry semantics differ
 *        between thread-list / message-list / stream errors so the
 *        per-call-site button stays on the page.
 *   Returns `null` when `error` is null — keeps caller JSX clean.
 *
 * WHY "use client": Next <Link> is used for the /login transition.
 */

"use client";

import type { ReactNode } from "react";
import Link from "next/link";

// ── Props ─────────────────────────────────────────────────────────────────────

/** Discriminated union — `kind` decides headline + CTA. */
export type ChatError =
  | { readonly kind: "auth" }
  | { readonly kind: "generic"; readonly message: string };

export interface ChatErrorBannerProps {
  /** Pass `null` to render nothing — convenient for the parent JSX. */
  readonly error: ChatError | null;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ChatErrorBanner({ error }: ChatErrorBannerProps): ReactNode {
  if (!error) return null;

  // destructive/30 border + destructive/10 fill is the standard error
  // surface across the app; rounded-[2px] is the terminal-density rule.
  const shell =
    "rounded-[2px] border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive";

  if (error.kind === "auth") {
    return (
      <div role="alert" data-cell="chat-error-auth" className={shell}>
        <p className="font-medium">Your session expired.</p>
        <p className="mt-1">Sign in again to load your conversations.</p>
        {/* Link (not Button): /login is a route transition; <Link> opts
            into app-router prefetch so sign-in feels instant. */}
        <Link
          href="/login?redirect_to=/chat"
          className="mt-2 inline-block rounded-[2px] border border-destructive/40 px-2 py-1 text-[11px] font-medium hover:bg-destructive/20"
        >
          Sign in
        </Link>
      </div>
    );
  }

  return (
    <div role="alert" data-cell="chat-error-generic" className={shell}>
      {error.message}
    </div>
  );
}
