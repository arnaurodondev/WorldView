/**
 * app/register/page.tsx — Registration redirect page
 *
 * WHY THIS EXISTS: Worldview does not have its own registration form.
 * User accounts are managed in Zitadel (our OIDC provider). New users
 * register via Zitadel's self-service registration UI.
 *
 * This page redirects to Zitadel's registration URL (OQ-05 resolution:
 * S9 provides GET /api/v1/auth/register → 302 to Zitadel register page).
 * We use a client-side redirect for consistent UX (loading state, error handling).
 *
 * WHY NOT a server-side redirect (Next.js redirect()): The Zitadel registration
 * URL depends on NEXT_PUBLIC_ZITADEL_URL (a client-side env var set at build time).
 * Server-side redirects use server env vars. Using the public var client-side
 * ensures the same URL is used in all environments.
 *
 * WHO USES IT: New users who click "Register" on the login page.
 * DATA SOURCE: None — pure redirect based on env var
 * DESIGN REFERENCE: PRD-0028 §6.6.2 Registration Flow (OQ-05)
 */

"use client";
// WHY "use client": Uses useEffect for browser-side redirect and reads
// process.env.NEXT_PUBLIC_* (only available at runtime in the browser bundle).

import { useEffect, useState } from "react";

export default function RegisterPage() {
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const zitadelBaseUrl = process.env.NEXT_PUBLIC_ZITADEL_URL;

    if (!zitadelBaseUrl) {
      setError(
        "Registration is not configured. Contact your administrator. " +
          "(Missing NEXT_PUBLIC_ZITADEL_URL)",
      );
      return;
    }

    // Redirect to Zitadel's self-registration page.
    // WHY register URL: Zitadel hosts its own registration form with email
    // verification, password rules, and MFA enrollment — no need to rebuild this.
    window.location.replace(`${zitadelBaseUrl}/ui/login/register`);
  }, []);

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-4">
        <div className="w-full max-w-sm space-y-4">
          <h1 className="text-[18px] font-semibold text-foreground">Registration unavailable</h1>
          <p className="text-[14px] text-muted-foreground">{error}</p>
          <a
            href="/login"
            className="block text-[14px] font-medium text-primary underline-offset-4 hover:underline"
          >
            Back to login
          </a>
        </div>
      </div>
    );
  }

  // WHY show loading state: The useEffect redirect is asynchronous.
  // This prevents a blank flash before the redirect fires.
  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="flex flex-col items-center gap-3">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-border border-t-primary" />
        <p className="text-[14px] text-muted-foreground">Redirecting to registration…</p>
      </div>
    </div>
  );
}
