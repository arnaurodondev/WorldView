/**
 * app/legal/privacy/page.tsx — Privacy policy stub
 *
 * PLAN-0059 I-6: minimum-viable privacy disclosure surface that the
 * CookieConsentBanner links to. The full policy is a marketing /legal
 * deliverable; this stub describes what the platform actually stores
 * client-side today so the consent banner doesn't dead-link.
 *
 * STRUCTURE: server component, no auth gate (must be reachable from
 * unauthenticated landing-page surfaces).
 */

import Link from "next/link";

export const metadata = {
  title: "Privacy — Worldview",
  description:
    "How Worldview handles browser storage, telemetry, and personal data.",
};

export default function PrivacyPolicyPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-12 text-foreground">
      <Link
        href="/"
        className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground hover:text-foreground"
      >
        ← Back
      </Link>

      <h1 className="mt-4 text-[24px] font-semibold tracking-tight">Privacy</h1>
      <p className="mt-2 text-[14px] text-muted-foreground">
        Last updated: 2026-05-01
      </p>

      <div className="mt-8 space-y-6 text-[14px] leading-relaxed">
        <section>
          <h2 className="mb-2 text-[16px] font-semibold">What we store on your device</h2>
          <p>
            Worldview uses your browser&apos;s local storage to keep you signed
            in and remember your preferences. We do not set marketing
            cookies and we do not share data with third parties for
            advertising or profiling.
          </p>
          <ul className="ml-6 mt-3 list-disc space-y-1 text-muted-foreground">
            <li>
              <strong className="text-foreground">Necessary</strong> — auth
              tokens, hotkey state, idle-lock timer, sidebar collapse, hotkey
              cheat-sheet seen flag. Required for the app to function.
            </li>
            <li>
              <strong className="text-foreground">Preferences</strong> —
              display density (compact / default / comfortable), default
              currency, default timezone, news-link target, saved screener
              configurations, watchlist sort order. You can opt out via the
              cookie banner.
            </li>
            <li>
              <strong className="text-foreground">Analytics</strong> — none
              enabled today. Future error reporting (Sentry) will check
              your consent before initialising.
            </li>
          </ul>
        </section>

        <section>
          <h2 className="mb-2 text-[16px] font-semibold">Server-side data</h2>
          <p>
            Authentication is handled by your identity provider (Zitadel).
            Your portfolio, watchlists, alert rules, and chat history are
            stored in our backend, scoped to your user ID and tenant.
            Aggregate market data (prices, fundamentals, news) is fetched
            from licensed third-party providers (EODHD, Alpaca, Polymarket)
            and is not personal data.
          </p>
        </section>

        <section>
          <h2 className="mb-2 text-[16px] font-semibold">Your rights</h2>
          <p>
            Under GDPR and equivalent regimes you have the right to access,
            correct, export, and delete your personal data. Contact{" "}
            <a
              href="mailto:privacy@worldview.local"
              className="text-primary underline underline-offset-2"
            >
              privacy@worldview.local
            </a>{" "}
            to exercise any of these rights.
          </p>
        </section>

        <section>
          <h2 className="mb-2 text-[16px] font-semibold">This page</h2>
          <p className="text-muted-foreground">
            This is a minimum-viable disclosure surface (PLAN-0059 I-6).
            A complete privacy policy will replace this page before broader
            release.
          </p>
        </section>
      </div>
    </main>
  );
}
