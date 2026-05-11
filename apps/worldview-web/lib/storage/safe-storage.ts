/**
 * lib/storage/safe-storage.ts — Validated, corruption-safe localStorage wrapper
 *
 * WHY THIS EXISTS: Before this module, ~80 raw `localStorage.getItem(...)` /
 * `localStorage.setItem(...)` call sites scattered across the codebase. Each
 * site:
 *  1. Re-implemented the SSR guard (`typeof window === "undefined"`).
 *  2. Re-implemented JSON.parse / JSON.stringify wrappers, sometimes forgetting
 *     `try/catch` — corrupt JSON would crash the app (BP-180-class issue).
 *  3. Trusted the stored shape blindly. A user opening DevTools and editing
 *     `worldview-sidebar-width` to `"abc"` would either:
 *       - Crash the app (unhandled JSON parse error), or
 *       - Render UI with `width = NaN` (invalid CSS, layout collapse).
 *
 * `safeStorage` provides:
 *  - SSR-safe reads/writes (returns the default on the server, no-ops on write).
 *  - JSON parse with try/catch (corrupt JSON → returns default, never throws).
 *  - Validator hook (any function `(value) => T | null`) so callers shape-check
 *    on read. Today this is a hand-rolled validator type compatible with
 *    `zod.safeParse` — when zod is added to the bundle (PLAN-0059-C follow-up),
 *    callers pass `z.object({...})` directly with no API change.
 *  - Quota-exceeded handling: setItem returns false on overflow instead of
 *    throwing. Callers can decide whether to fall back, downsize, or just
 *    accept the loss (most UI prefs are fine being lost).
 *
 * USAGE — primitive value:
 *   const expanded = safeStorage.get("sidebar.expanded", isBoolean, true);
 *
 * USAGE — typed object with a validator:
 *   const validateSidebarPrefs = (raw: unknown): SidebarPrefs | null =>
 *     typeof raw === "object" && raw !== null && "expanded" in raw
 *       ? (raw as SidebarPrefs)
 *       : null;
 *   const prefs = safeStorage.get("sidebar", validateSidebarPrefs, defaultPrefs);
 *
 * MIGRATION: 80 raw call sites are converted incrementally. New code MUST use
 * this wrapper.
 */

/**
 * Validator — function-shape contract this module accepts on read.
 *
 * WHY this signature (and not zod): we want to keep zod out of the runtime
 * bundle for now (transitive dep weight). The signature here is a strict
 * subset of what `zod.safeParse(...).data` provides:
 *   - Return the validated value if valid.
 *   - Return null if invalid (caller falls back to default).
 *
 * Callers can supply a hand-rolled function or, in the future, a zod schema's
 * `.safeParse` adapter:
 *   const validate: Validator<Foo> = (raw) => {
 *     const r = fooSchema.safeParse(raw);
 *     return r.success ? r.data : null;
 *   };
 */
export type Validator<T> = (raw: unknown) => T | null;

// WHY exported: allows tests to mock storage without faking globalThis.
export interface StorageBackend {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

/**
 * isStorageAvailable — defensive read of `window.localStorage`.
 *
 * Returns false when:
 *  - SSR (no window).
 *  - Safari Private Browsing (Storage API throws on `setItem`).
 *  - User has disabled site data in browser settings.
 *
 * In all those cases we fall back to in-memory storage so writes don't crash
 * but also don't persist. The page still works; preferences just reset on reload.
 */
function isStorageAvailable(): boolean {
  if (typeof window === "undefined") return false;
  try {
    // Touch the API. Some Safari modes throw on first `setItem` access.
    const probe = "__worldview_probe__";
    window.localStorage.setItem(probe, probe);
    window.localStorage.removeItem(probe);
    return true;
  } catch {
    return false;
  }
}

// WHY a module-level fallback Map: when localStorage is unavailable (SSR or
// Safari Private), reads/writes go to this map. Per-tab, ephemeral, no leakage
// across users (the map is in the user's own JS heap).
const memoryFallback = new Map<string, string>();

const memoryBackend: StorageBackend = {
  getItem: (k) => memoryFallback.get(k) ?? null,
  setItem: (k, v) => {
    memoryFallback.set(k, v);
  },
  removeItem: (k) => {
    memoryFallback.delete(k);
  },
};

function getBackend(): StorageBackend {
  return isStorageAvailable() ? window.localStorage : memoryBackend;
}

// ── Public API ────────────────────────────────────────────────────────────────

export const safeStorage = {
  /**
   * get — read a value by key, validate its shape, fall back to default on
   * any failure (missing, malformed JSON, validator rejected).
   *
   * NEVER throws. NEVER returns the default for a valid stored value.
   */
  get<T>(key: string, validator: Validator<T>, defaultValue: T): T {
    const raw = getBackend().getItem(key);
    if (raw === null) return defaultValue;

    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      // Corrupt JSON — DevTools edit, partial write, encoding glitch.
      // Silently fall back to default (caller shouldn't have to handle this).
      return defaultValue;
    }

    const validated = validator(parsed);
    return validated ?? defaultValue;
  },

  /**
   * set — write a value as JSON.
   *
   * Returns true on success, false if quota exceeded or storage unavailable.
   * WHY a boolean return (not throw): callers usually don't care about
   * persistence failures (UI prefs are not critical), but a few do (saved
   * screens, draft notes). Those callers can branch on the return value.
   */
  set<T>(key: string, value: T): boolean {
    try {
      getBackend().setItem(key, JSON.stringify(value));
      return true;
    } catch {
      // QuotaExceededError, security errors, transient storage failures.
      return false;
    }
  },

  /**
   * remove — delete a key. No error on missing key.
   */
  remove(key: string): void {
    try {
      getBackend().removeItem(key);
    } catch {
      // Storage may have become unavailable mid-session (very rare). Swallow.
    }
  },

  /**
   * getRaw / setRaw — escape hatch for non-JSON values (e.g. a plain string
   * like the legacy "true" / "false" sidebar flag). New code should NEVER
   * use these; they exist only to ease migration of pre-existing call sites
   * that stored bare strings.
   */
  getRaw(key: string, defaultValue: string): string {
    const raw = getBackend().getItem(key);
    return raw === null ? defaultValue : raw;
  },
  setRaw(key: string, value: string): boolean {
    try {
      getBackend().setItem(key, value);
      return true;
    } catch {
      return false;
    }
  },
} as const;

// ── Common validators ─────────────────────────────────────────────────────────

// WHY shipped with the module: the most-used shapes (boolean / string / number)
// don't deserve a hand-rolled validator at every call site.

export const isBoolean: Validator<boolean> = (raw) =>
  typeof raw === "boolean" ? raw : null;

export const isString: Validator<string> = (raw) =>
  typeof raw === "string" ? raw : null;

export const isFiniteNumber: Validator<number> = (raw) =>
  typeof raw === "number" && Number.isFinite(raw) ? raw : null;

/**
 * isStringEnum — factory for string-union validators.
 *
 * Example:
 *   const validatePeriod = isStringEnum(["1D", "1W", "1M"] as const);
 *   safeStorage.get("period", validatePeriod, "1D");
 */
export function isStringEnum<T extends string>(
  values: readonly T[],
): Validator<T> {
  const set = new Set<string>(values);
  return (raw) => (typeof raw === "string" && set.has(raw) ? (raw as T) : null);
}
