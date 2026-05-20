/**
 * contexts/PreferencesContext.tsx — User preferences (density / currency / timezone)
 *
 * PLAN-0059 I-4: institutional terminals expose three core preferences:
 *   - density   : compact | default | comfortable (row heights, font sizes)
 *   - currency  : USD / EUR / GBP / JPY / CHF / CAD / AUD / CNY / HKD / KRW / BTC / ETH
 *                 (single source of truth: lib/format.ts CURRENCY_CODES)
 *   - timezone  : IANA tz string (e.g. "America/New_York", "Europe/London")
 *
 * Today: persistence layer is `lib/storage/safe-storage.ts`. This is a
 * stop-gap until the S1 backend exposes /v1/users/me/preferences (deferred
 * to PLAN-0059 I-4 backend follow-up). The expected migration path:
 *   1. Convert PreferencesProvider into useApiClient + useAuthedQuery wrapper.
 *   2. Keep safeStorage as offline cache for fast first-paint and write-through.
 *   3. PreferencesProvider must mount INSIDE ApiClientProvider — currently
 *      satisfied by accident (root layout's ApiClientProvider is an ancestor
 *      of (app)/layout's PreferencesProvider). Document at the mount site.
 *
 * APPLIED EFFECTS:
 *   - density: sets `data-density="compact|default|comfortable"` on <body>
 *     so global CSS rules can scope styling. Applied via useLayoutEffect to
 *     prevent first-paint flicker.
 *   - currency: consumed by lib/format.ts via useUserCurrency().
 *   - timezone: consumed by lib/market-schedule.ts and timestamp formatters.
 *
 * QA-iter1 fixes:
 *   - Timezone validator now allow-lists against the curated list + try/catch
 *     wraps Intl.DateTimeFormat to defend against malicious / corrupt
 *     localStorage entries (was an uncaught RangeError → app DoS).
 *   - data-density flicker fix: useLayoutEffect with SSR guard.
 *   - CurrencyCode imported from lib/format (single source of truth).
 *   - Cross-tab sync via the `storage` event.
 *   - reset() removes the storage key entirely (not just rewrites defaults).
 */

"use client";

import * as React from "react";
import { safeStorage, type Validator } from "@/lib/storage/safe-storage";
import { CURRENCY_CODES, type CurrencyCode } from "@/lib/format";

// Re-export for ergonomics — call sites can import from a single place.
export type { CurrencyCode };

// ── Types ──────────────────────────────────────────────────────────────────

export type Density = "compact" | "default" | "comfortable";

export interface Preferences {
  density: Density;
  currency: CurrencyCode;
  /** IANA timezone string. "auto" means use the browser's resolved timezone. */
  timezone: string;
  /**
   * Chat / search history retention in days.
   * 30 | 90 | 365 | 0 (keep forever).
   * WHY 0-as-forever: avoids "Infinity" in JSON serialisation; the UI maps 0
   * to the "Keep forever" label and the backend interprets 0 as no pruning.
   * FR-6.2 / CRIT-003.
   */
  retentionDays: number;
  /**
   * Whether the destructive data-ops section (export / delete) is enabled
   * in the UI. Separate from the NEXT_PUBLIC_ENABLE_DATA_OPS flag so a
   * per-user toggle can be layered on top when the backend is ready.
   * Defaults false — the env flag is the primary gate.
   * FR-6.5.
   */
  dataOpsEnabled: boolean;
}

const DEFAULTS: Preferences = {
  density: "compact",
  currency: "USD",
  timezone: "auto",
  retentionDays: 90,
  dataOpsEnabled: false,
};

// Validation
const VALID_DENSITIES: ReadonlyArray<Density> = ["compact", "default", "comfortable"];
const VALID_CURRENCIES: ReadonlyArray<CurrencyCode> = CURRENCY_CODES;

/**
 * isValidIanaTimezone — defends against malicious/corrupt localStorage values.
 * QA-iter1: previously any non-empty string passed validation; a poisoned
 * `timezone: "Foo/Bar"` then crashed every Intl.DateTimeFormat consumer with
 * a RangeError (full app DoS until storage cleared).
 *
 * Approach: probe Intl.DateTimeFormat itself — if it throws on the candidate,
 * the timezone is invalid. Falls back to "auto" sentinel which the resolver
 * handles. "auto" is special-cased BEFORE the probe so it's always valid.
 */
function isValidIanaTimezone(tz: string): boolean {
  if (tz === "auto") return true;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

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
  if (typeof obj.timezone !== "string" || !isValidIanaTimezone(obj.timezone)) return null;

  // FR-6.2 (CRIT-003): validate retentionDays.
  // WHY coerce-missing-to-default: this field was added after the initial
  // storage schema. Existing stored objects won't have it — treat missing
  // as the 90-day default so we don't null-out an otherwise valid prefs
  // object and lose the user's density/currency/timezone settings.
  const retentionRaw = obj.retentionDays;
  const retentionDays =
    typeof retentionRaw === "number" &&
    [0, 30, 90, 365].includes(retentionRaw)
      ? retentionRaw
      : DEFAULTS.retentionDays;

  // Same additive-default strategy for dataOpsEnabled.
  const dataOpsEnabled =
    typeof obj.dataOpsEnabled === "boolean"
      ? obj.dataOpsEnabled
      : DEFAULTS.dataOpsEnabled;

  // QA-iter1: project to ONLY the known fields so future schema additions
  // in another tab/version don't silently leak through.
  return {
    density: obj.density as Density,
    currency: obj.currency as CurrencyCode,
    timezone: obj.timezone,
    retentionDays,
    dataOpsEnabled,
  };
};

const STORAGE_KEY = "worldview.preferences.v1";

// ── Context ────────────────────────────────────────────────────────────────

interface PreferencesContextValue extends Preferences {
  setDensity: (density: Density) => void;
  setCurrency: (currency: CurrencyCode) => void;
  setTimezone: (timezone: string) => void;
  /** FR-6.2 (CRIT-003): update history retention window. */
  setRetentionDays: (days: number) => void;
  /** FR-6.5: toggle user-level data-ops access (UI layer gate). */
  setDataOpsEnabled: (enabled: boolean) => void;
  reset: () => void;
  /**
   * Resolved IANA timezone — when `timezone === "auto"` returns the browser's
   * Intl.DateTimeFormat().resolvedOptions().timeZone; otherwise returns the
   * stored value. Wrapped in try/catch as defense-in-depth even though the
   * stored value passed validation.
   */
  resolvedTimezone: string;
}

const PreferencesContext = React.createContext<PreferencesContextValue | null>(null);

// ── Provider ───────────────────────────────────────────────────────────────

export function PreferencesProvider({ children }: { children: React.ReactNode }) {
  const [prefs, setPrefs] = React.useState<Preferences>(() =>
    safeStorage.get(STORAGE_KEY, validatePreferences, DEFAULTS),
  );
  // Skip the first persist effect — we just READ from storage, no need to
  // immediately write the same value back.
  const skipNextWriteRef = React.useRef(true);

  React.useEffect(() => {
    if (skipNextWriteRef.current) {
      skipNextWriteRef.current = false;
      return;
    }
    safeStorage.set(STORAGE_KEY, prefs);
  }, [prefs]);

  // QA-iter1: useLayoutEffect to apply density attribute BEFORE the browser
  // paints — useEffect would mutate <body> after first paint and any
  // [data-density="X"] CSS rule would flicker.
  React.useLayoutEffect(() => {
    if (typeof document !== "undefined") {
      document.body.dataset.density = prefs.density;
    }
  }, [prefs.density]);

  // QA-iter1: cross-tab sync. Tab A changing prefs broadcasts via the native
  // `storage` event; tab B re-reads + re-validates so both tabs stay in step.
  React.useEffect(() => {
    if (typeof window === "undefined") return;
    const onStorage = (e: StorageEvent) => {
      if (e.key !== STORAGE_KEY) return;
      const next = safeStorage.get(STORAGE_KEY, validatePreferences, DEFAULTS);
      // Skip the persist effect for the cross-tab update so we don't echo.
      skipNextWriteRef.current = true;
      setPrefs(next);
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const resolvedTimezone = React.useMemo(() => {
    if (prefs.timezone !== "auto") {
      // Defense-in-depth: even though validatePreferences gates this, a
      // browser-vendor change in zone-name interpretation (or a future
      // schema migration that smuggles in a stale value) still gets a
      // safe fallback.
      try {
        new Intl.DateTimeFormat("en-US", { timeZone: prefs.timezone });
        return prefs.timezone;
      } catch {
        // fall through to browser default
      }
    }
    if (typeof Intl === "undefined") return "UTC";
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    } catch {
      return "UTC";
    }
  }, [prefs.timezone]);

  const value = React.useMemo<PreferencesContextValue>(
    () => ({
      ...prefs,
      resolvedTimezone,
      setDensity: (density) => setPrefs((p) => ({ ...p, density })),
      setCurrency: (currency) => setPrefs((p) => ({ ...p, currency })),
      setTimezone: (timezone) => setPrefs((p) => ({ ...p, timezone })),
      // FR-6.2 (CRIT-003): persists to localStorage via the existing setPrefs
      // pathway — retentionDays survives page refresh because safeStorage writes
      // on every state change (see the useEffect above).
      setRetentionDays: (retentionDays) =>
        setPrefs((p) => ({ ...p, retentionDays })),
      // FR-6.5: separate toggle so the env flag and user flag can be ANDed.
      setDataOpsEnabled: (dataOpsEnabled) =>
        setPrefs((p) => ({ ...p, dataOpsEnabled })),
      reset: () => {
        // QA-iter1: actually wipe the storage key (not rewrite defaults) so
        // a future "factory reset" feature has nothing to find.
        safeStorage.remove(STORAGE_KEY);
        skipNextWriteRef.current = true;
        setPrefs(DEFAULTS);
      },
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
        "provider in app/(app)/layout.tsx, inside the ApiClientProvider " +
        "ancestor (rooted in app/providers.tsx).",
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
