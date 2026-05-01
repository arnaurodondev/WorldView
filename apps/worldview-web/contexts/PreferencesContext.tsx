/**
 * contexts/PreferencesContext.tsx — User preferences (density / currency / timezone)
 *
 * PLAN-0059 I-4: institutional terminals expose three core preferences:
 *   - density   : compact | default | comfortable (row heights, font sizes)
 *   - currency  : USD / EUR / GBP / JPY / CHF / CAD / AUD / CNY / HKD / KRW / BTC / ETH
 *                 (matches lib/format.ts multi-currency support)
 *   - timezone  : IANA tz string (e.g. "America/New_York", "Europe/London")
 *
 * Today: persistence layer is `lib/storage/safe-storage.ts` (localStorage
 * with corruption-safe validator). This is a stop-gap until the S1 backend
 * exposes /v1/users/me/preferences (deferred to PLAN-0059 I-4 backend
 * follow-up). The ProvidedAPI is identical so swapping the source is a
 * one-file change in this provider.
 *
 * APPLIED EFFECTS:
 *   - density: sets `data-density="compact|default|comfortable"` on <body>
 *     so global CSS rules can scope styling. Existing density variants on
 *     <Button>/<Input> remain consumer-controlled — this is for future
 *     density-aware components.
 *   - currency: consumed by lib/format.ts via useUserCurrency().
 *   - timezone: consumed by lib/market-schedule.ts and timestamp formatters.
 *
 * USAGE:
 *   const { density, currency, timezone, setDensity, ... } = usePreferences();
 */

"use client";

import * as React from "react";
import { safeStorage, type Validator } from "@/lib/storage/safe-storage";

// ── Types ──────────────────────────────────────────────────────────────────

export type Density = "compact" | "default" | "comfortable";

export type CurrencyCode =
  | "USD" | "EUR" | "GBP" | "JPY" | "CHF" | "CAD" | "AUD"
  | "CNY" | "HKD" | "KRW" | "BTC" | "ETH";

export interface Preferences {
  density: Density;
  currency: CurrencyCode;
  /** IANA timezone string. "auto" means use the browser's resolved timezone. */
  timezone: string;
}

const DEFAULTS: Preferences = {
  density: "compact",
  currency: "USD",
  timezone: "auto",
};

// ── Validation (used by safe-storage) ──────────────────────────────────────

const VALID_DENSITIES: ReadonlyArray<Density> = ["compact", "default", "comfortable"];
const VALID_CURRENCIES: ReadonlyArray<CurrencyCode> = [
  "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD",
  "CNY", "HKD", "KRW", "BTC", "ETH",
];

// Validator for safeStorage.get — returns the parsed object only when every
// field passes its allow-list, otherwise null (which forces the fallback).
const validatePreferences: Validator<Preferences> = (raw) => {
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as Record<string, unknown>;
  if (
    typeof obj.density !== "string" ||
    !VALID_DENSITIES.includes(obj.density as Density)
  ) return null;
  if (
    typeof obj.currency !== "string" ||
    !VALID_CURRENCIES.includes(obj.currency as CurrencyCode)
  ) return null;
  if (typeof obj.timezone !== "string" || obj.timezone.length === 0) return null;
  return {
    density: obj.density as Density,
    currency: obj.currency as CurrencyCode,
    timezone: obj.timezone,
  };
};

const STORAGE_KEY = "worldview.preferences.v1";

// ── Context ────────────────────────────────────────────────────────────────

interface PreferencesContextValue extends Preferences {
  setDensity: (density: Density) => void;
  setCurrency: (currency: CurrencyCode) => void;
  setTimezone: (timezone: string) => void;
  reset: () => void;
  /**
   * Resolved IANA timezone — when `timezone === "auto"` returns the browser's
   * Intl.DateTimeFormat().resolvedOptions().timeZone; otherwise returns the
   * stored value verbatim.
   */
  resolvedTimezone: string;
}

const PreferencesContext = React.createContext<PreferencesContextValue | null>(null);

// ── Provider ───────────────────────────────────────────────────────────────

export function PreferencesProvider({ children }: { children: React.ReactNode }) {
  // Lazy initial state — read once on mount. SSR-safe via safe-storage which
  // returns the default when window is undefined.
  const [prefs, setPrefs] = React.useState<Preferences>(() =>
    safeStorage.get(STORAGE_KEY, validatePreferences, DEFAULTS),
  );

  // Persist on every change. Non-blocking: failures (full storage, denied
  // permissions) are swallowed by safe-storage and surface in the console.
  React.useEffect(() => {
    safeStorage.set(STORAGE_KEY, prefs);
  }, [prefs]);

  // Apply density to <body> as a data attribute so global CSS can scope
  // alternate styling. Components that opt in via density variants are
  // already independent — this is just for future global rules.
  React.useEffect(() => {
    if (typeof document !== "undefined") {
      document.body.dataset.density = prefs.density;
    }
  }, [prefs.density]);

  const resolvedTimezone = React.useMemo(() => {
    if (prefs.timezone !== "auto") return prefs.timezone;
    if (typeof Intl === "undefined") return "UTC";
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  }, [prefs.timezone]);

  const value = React.useMemo<PreferencesContextValue>(
    () => ({
      ...prefs,
      resolvedTimezone,
      setDensity: (density) => setPrefs((p) => ({ ...p, density })),
      setCurrency: (currency) => setPrefs((p) => ({ ...p, currency })),
      setTimezone: (timezone) => setPrefs((p) => ({ ...p, timezone })),
      reset: () => setPrefs(DEFAULTS),
    }),
    [prefs, resolvedTimezone],
  );

  return (
    <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>
  );
}

// ── Hooks ──────────────────────────────────────────────────────────────────

export function usePreferences(): PreferencesContextValue {
  const ctx = React.useContext(PreferencesContext);
  if (!ctx) {
    throw new Error(
      "usePreferences must be used inside <PreferencesProvider>. Mount the " +
        "provider in app/(app)/layout.tsx, inside ApiClientProvider.",
    );
  }
  return ctx;
}

/** Sugar hook for components that only care about the user's currency. */
export function useUserCurrency(): CurrencyCode {
  return usePreferences().currency;
}

/** Sugar hook for components that only care about the resolved timezone. */
export function useUserTimezone(): string {
  return usePreferences().resolvedTimezone;
}
