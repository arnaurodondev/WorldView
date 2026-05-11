/**
 * components/legal/CookieConsentBanner.tsx — Cookie / storage consent banner
 *
 * PLAN-0059 I-6 hardening: GDPR / e-Privacy directive compliance for the
 * client-side storage we already use (preferences, idle-lock, hotkey hints,
 * sidebar collapse). The app does NOT set marketing or analytics cookies
 * today — this banner is here for two reasons:
 *
 *   1. Legal hygiene: even strictly-necessary localStorage usage benefits
 *      from explicit user awareness, especially when the platform expands
 *      to B2B clients with their own compliance frameworks.
 *   2. Future-proofing: the moment we add an analytics SDK or a third-party
 *      tag, the consent infrastructure is already in place — flip the
 *      `analytics` toggle and the SDK reads consent before initialising.
 *
 * THREE CATEGORIES:
 *   - necessary  : auth tokens, hotkey state, idle-lock, preferences.
 *                  Always on; user cannot disable (essential for the app
 *                  to function). Disclosed for transparency.
 *   - analytics  : reserved for future Sentry / posthog / mixpanel. Off
 *                  by default; user must opt in.
 *   - preferences: cosmetic state that survives across sessions (theme
 *                  density, news-link target, watchlists order). On by
 *                  default but user can opt out.
 *
 * PERSISTENCE: consent decision stored via lib/storage/safe-storage at
 * `worldview.cookie-consent.v1`. Once set, banner never re-shows unless
 * the user explicitly opens preferences.
 */

"use client";

import * as React from "react";
import { Cookie, X } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { safeStorage, type Validator } from "@/lib/storage/safe-storage";
import { cn } from "@/lib/utils";

// ── Types ──────────────────────────────────────────────────────────────────

export interface CookieConsent {
  /** Always true — necessary storage cannot be opted out of. */
  necessary: true;
  /** Off by default; user must opt in. */
  analytics: boolean;
  /** On by default; user can opt out. */
  preferences: boolean;
  /** ISO 8601 timestamp of when the decision was recorded. */
  decided_at: string;
  /** Schema version — bump if categories or semantics change. */
  version: 1;
}

const STORAGE_KEY = "worldview.cookie-consent.v1";

const validate: Validator<CookieConsent> = (raw) => {
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as Record<string, unknown>;
  if (obj.version !== 1) return null;
  if (typeof obj.necessary !== "boolean" || obj.necessary !== true) return null;
  if (typeof obj.analytics !== "boolean") return null;
  if (typeof obj.preferences !== "boolean") return null;
  if (typeof obj.decided_at !== "string") return null;
  return {
    version: 1,
    necessary: true,
    analytics: obj.analytics,
    preferences: obj.preferences,
    decided_at: obj.decided_at,
  };
};

function readConsent(): CookieConsent | null {
  return safeStorage.get<CookieConsent | null>(STORAGE_KEY, validate, null);
}

function writeConsent(c: CookieConsent): void {
  safeStorage.set(STORAGE_KEY, c);
}

// Public helper for app code: query the current consent state for a category.
// Defaults to FALSE if the user hasn't decided yet — analytics SDKs etc. must
// not initialise until consent is explicitly granted.
export function hasConsent(category: "analytics" | "preferences"): boolean {
  const c = readConsent();
  if (!c) return false;
  return c[category];
}

// ── Banner component ───────────────────────────────────────────────────────

export function CookieConsentBanner() {
  const [decision, setDecision] = React.useState<CookieConsent | null>(null);
  const [showCustomise, setShowCustomise] = React.useState(false);
  const [draftAnalytics, setDraftAnalytics] = React.useState(false);
  const [draftPreferences, setDraftPreferences] = React.useState(true);
  // mounted ref so the SSR pass renders nothing (prevents hydration mismatch
  // — server can't read localStorage; client-side check decides what to show).
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => {
    setMounted(true);
    setDecision(readConsent());
  }, []);

  function commit(c: Omit<CookieConsent, "version" | "necessary" | "decided_at">) {
    const full: CookieConsent = {
      ...c,
      version: 1,
      necessary: true,
      decided_at: new Date().toISOString(),
    };
    writeConsent(full);
    setDecision(full);
  }

  function acceptAll() {
    commit({ analytics: true, preferences: true });
  }

  function rejectOptional() {
    commit({ analytics: false, preferences: false });
  }

  function saveCustomised() {
    commit({ analytics: draftAnalytics, preferences: draftPreferences });
  }

  // SSR / first-paint: render nothing.
  if (!mounted) return null;
  // User has already decided: don't show banner. (A future Settings → Privacy
  // panel can re-open it via clearing localStorage.)
  if (decision) return null;

  return (
    <div
      // role=region + aria-label: identifiable landmark for AT users.
      role="region"
      aria-label="Cookie consent"
      className={cn(
        "fixed inset-x-0 bottom-0 z-50 border-t border-border bg-card/95 backdrop-blur",
        "px-4 py-3 shadow-[0_-2px_12px_-4px_rgba(0,0,0,0.4)]",
      )}
    >
      <div className="mx-auto flex max-w-5xl flex-col gap-3 md:flex-row md:items-center">
        <Cookie className="h-4 w-4 shrink-0 text-primary" aria-hidden />
        <div className="flex-1 text-[11px] leading-relaxed text-foreground">
          <p>
            Worldview uses browser storage to keep you signed in and remember
            your preferences (density, timezone, watchlists). We do not set
            marketing cookies or share data with third parties.{" "}
            <Link
              href="/legal/privacy"
              className="text-primary underline underline-offset-2"
            >
              Privacy details
            </Link>
            .
          </p>
          {showCustomise && (
            <div className="mt-2 space-y-1.5 rounded-[2px] border border-border/40 bg-background/60 p-2">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked
                  disabled
                  className="h-3 w-3 cursor-not-allowed accent-primary"
                  aria-label="Necessary storage (always on)"
                />
                <span className="text-[11px]">
                  <strong>Necessary</strong> — auth, hotkeys, idle-lock. Required.
                </span>
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={draftPreferences}
                  onChange={(e) => setDraftPreferences(e.target.checked)}
                  className="h-3 w-3 cursor-pointer accent-primary"
                />
                <span className="text-[11px]">
                  <strong>Preferences</strong> — density, currency, timezone,
                  saved layouts, news-link target. (default on)
                </span>
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={draftAnalytics}
                  onChange={(e) => setDraftAnalytics(e.target.checked)}
                  className="h-3 w-3 cursor-pointer accent-primary"
                />
                <span className="text-[11px]">
                  <strong>Analytics</strong> — none enabled today; reserved for
                  future error reporting (Sentry). (default off)
                </span>
              </label>
            </div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {!showCustomise ? (
            <>
              <Button
                density="compact"
                variant="ghost"
                onClick={() => setShowCustomise(true)}
              >
                Customise
              </Button>
              <Button density="compact" variant="outline" onClick={rejectOptional}>
                Reject optional
              </Button>
              <Button density="compact" onClick={acceptAll}>
                Accept all
              </Button>
            </>
          ) : (
            <>
              <Button
                density="compact"
                variant="ghost"
                onClick={() => setShowCustomise(false)}
                aria-label="Cancel customisation"
              >
                <X className="h-3 w-3" />
              </Button>
              <Button density="compact" onClick={saveCustomised}>
                Save preferences
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
