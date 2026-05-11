/**
 * lib/saved-screens.ts — localStorage-backed CRUD for saved screener filter sets
 *
 * WHY THIS EXISTS (PLAN-0051 T-B-2-05): Power users build the same screen over
 * and over (e.g. "large-cap tech with P/E < 25 and ROE > 15%"). Asking them to
 * re-enter every filter every visit is hostile UX. This module gives the screener
 * a "Save current filters as a named screen" + "Load a saved screen" capability
 * without any backend round-trip — fast, offline-friendly, and zero infra cost.
 *
 * WHY localStorage (not cookies, not IndexedDB, not S9 backend):
 *   - Cookies: 4KB per-cookie hard cap; serialised filter sets quickly exceed it.
 *   - IndexedDB: async API, structured-clone semantics, overkill for ≤50 records.
 *   - S9 backend: would be ideal long-term, but PLAN-0051 marks this as MVP. The
 *     MVP prefers shipping the UX now over arguing about migrations.
 *   - localStorage: synchronous, ~5MB quota, persists across sessions, and the
 *     payload is small JSON. Perfect fit for the MVP.
 *
 * WHY a single versioned key (`worldview:savedScreens:v1`):
 *   - One JSON read = the entire collection. No multi-key consistency issues
 *     (can't get half-deleted state if a tab crashes mid-write).
 *   - The `:v1` suffix lets us rev the schema later (rename to `:v2`, ship a
 *     migration helper, deprecate `:v1`) without colliding with stale browsers.
 *
 * WHY UUIDv4 client-side IDs (crypto.randomUUID()):
 *   - Stable identity for "edit/delete this row" without server roundtrip.
 *   - randomUUID() is supported in all evergreen browsers + Node 14.17+, so the
 *     test environment (jsdom under vitest 2.x) handles it cleanly.
 *
 * WHY ALL READS ARE TRY/CATCH WRAPPED:
 *   - localStorage.getItem can THROW SecurityError in Safari private browsing
 *     and in cross-origin sandboxed iframes. We must never crash the screener
 *     just because storage is unavailable — we degrade gracefully to "no saved
 *     screens" instead.
 *   - JSON.parse can throw SyntaxError if a buggy older version corrupted the
 *     blob. Same fallback: return empty list, log nothing (this is expected).
 *
 * WHY SEPARATE READ/WRITE HELPERS (instead of a singleton class):
 *   - Stateless functions are trivially mockable in tests (no constructor, no
 *     teardown). A thin functional surface fits the "MVP" mandate of the plan.
 *
 * WHO USES IT:
 *   - components/screener/SavedScreensDialog.tsx (T-B-2-05 UI)
 *   - app/(app)/screener/page.tsx (header button + onLoad/onSaved wiring)
 *
 * RELATED: lib/screener-columns.ts uses the SAME localStorage pattern for
 * column visibility/order persistence (T-B-2-06).
 */

import type { FilterState } from "@/components/screener/ScreenerFilterBar";

// ── Storage key (versioned) ─────────────────────────────────────────────────

/**
 * Versioned key. Bump suffix (`:v2`, `:v3`) if the schema changes shape.
 * Older keys can be migrated lazily on first read or simply ignored.
 */
export const SAVED_SCREENS_KEY = "worldview:savedScreens:v1";

// ── Public type ─────────────────────────────────────────────────────────────

/**
 * SavedScreen — one persisted screener configuration.
 *
 * WHY id + name + filters + timestamps (and nothing else):
 *   - id: stable handle for delete/update without depending on the (mutable) name.
 *   - name: what the user types into the "Save as" input. Free-form string.
 *   - filters: the FilterState shape produced by ScreenerFilterBar.
 *   - createdAt / updatedAt: lets the UI sort by recency and show
 *     <DataTimestamp> "2m ago" labels. ISO 8601 UTC is the canonical format.
 */
export interface SavedScreen {
  id: string;
  name: string;
  filters: FilterState;
  createdAt: string;
  updatedAt: string;
}

// ── Internal helpers ─────────────────────────────────────────────────────────

/**
 * isBrowser — guards against SSR (Next.js renders this on the server during
 * build). localStorage doesn't exist there. Without this guard, importing this
 * module during SSR would crash the build with "localStorage is not defined".
 */
function isBrowser(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

/**
 * readAll — single point of localStorage read + parse.
 *
 * WHY catch BOTH access and parse: see file-level "WHY ALL READS ARE TRY/CATCH".
 * Returns [] on any failure so callers don't need defensive code at every call site.
 */
function readAll(): SavedScreen[] {
  if (!isBrowser()) return [];
  try {
    const raw = window.localStorage.getItem(SAVED_SCREENS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    // WHY array shape check: an attacker (or an old buggy version) could have
    // written an object instead of an array. Returning [] avoids a crash and
    // lets fresh saves reset the slot to a clean shape on next write.
    if (!Array.isArray(parsed)) return [];
    // WHY filter ill-formed records: defensive — if any single record is missing
    // its id/filters we skip it rather than rendering "undefined" rows in the UI.
    return parsed.filter(
      (r): r is SavedScreen =>
        r && typeof r === "object"
        && typeof r.id === "string"
        && typeof r.name === "string"
        && r.filters && typeof r.filters === "object"
        && typeof r.createdAt === "string"
        && typeof r.updatedAt === "string",
    );
  } catch {
    return [];
  }
}

/**
 * writeAll — single point of localStorage write.
 *
 * WHY swallow QuotaExceededError: localStorage has a ~5MB quota; with 50 saved
 * screens × small filter objects we are nowhere near that, but Safari Private
 * Mode reports 0-byte quota. The user sees no crash, the call returns false,
 * and the caller can decide whether to surface an error message.
 */
function writeAll(rows: SavedScreen[]): boolean {
  if (!isBrowser()) return false;
  try {
    window.localStorage.setItem(SAVED_SCREENS_KEY, JSON.stringify(rows));
    return true;
  } catch {
    return false;
  }
}

/**
 * nowIso — single source of truth for the timestamp shape we persist.
 * WHY UTC: keeps records portable across timezones. The UI converts to local on display.
 */
function nowIso(): string {
  return new Date().toISOString();
}

/**
 * newId — UUIDv4 via the standard Web Crypto API.
 *
 * WHY crypto.randomUUID() (not Math.random hex):
 *   - Cryptographically random — no collision risk across tabs / sessions.
 *   - Native, no library cost.
 *   - Polyfill fallback below for environments lacking it (older jsdom).
 */
function newId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // Fallback: not cryptographic — only used in ancient runtimes.
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

// ── Public API ───────────────────────────────────────────────────────────────

/**
 * listSavedScreens — returns all saved screens, newest-updated first.
 *
 * WHY sort by updatedAt desc (not createdAt): a user editing a 6-month-old
 * screen probably wants to see it at the top right after editing. Sorting by
 * updatedAt mirrors the macOS Finder "last modified" mental model.
 */
export function listSavedScreens(): SavedScreen[] {
  const rows = readAll();
  return [...rows].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

/**
 * saveScreen — creates a new SavedScreen and persists it.
 *
 * WHY return the created record: the caller (dialog) immediately wants to show
 * the new entry in the "Load" tab without re-reading from localStorage.
 *
 * WHY name-collision is allowed: two screens called "My screen" coexist
 * because each has a unique id. The UI surfaces both with timestamps so the
 * user can disambiguate. Forcing unique names would surprise users who
 * intentionally clone a screen and tweak it.
 */
export function saveScreen(name: string, filters: FilterState): SavedScreen {
  const trimmed = name.trim() || "Untitled screen";
  // WHY ONE nowIso() call: createdAt and updatedAt should be IDENTICAL on first
  // save. Calling nowIso() twice could produce different ms values across the
  // sub-millisecond gap between the calls.
  const ts = nowIso();
  const screen: SavedScreen = {
    id: newId(),
    name: trimmed,
    // WHY structured clone: defensively copy the filter object so later mutations
    // of `filters` by the caller don't bleed into the stored record.
    filters: JSON.parse(JSON.stringify(filters)) as FilterState,
    createdAt: ts,
    updatedAt: ts,
  };
  const rows = readAll();
  rows.push(screen);
  writeAll(rows);
  return screen;
}

/**
 * updateScreen — partial update by id. Returns the updated row, or null if
 * no row matched (caller can decide whether to show a "not found" toast).
 *
 * WHY shallow merge: only `name` and `filters` are user-editable; we never let
 * callers overwrite `id` or `createdAt`. Stripping those keys from the patch
 * prevents accidental ID rewrites that would orphan the record.
 */
export function updateScreen(id: string, patch: Partial<SavedScreen>): SavedScreen | null {
  const rows = readAll();
  const idx = rows.findIndex((r) => r.id === id);
  if (idx < 0) return null;
  const existing = rows[idx];
  const next: SavedScreen = {
    ...existing,
    // WHY pluck only safe keys: see "WHY shallow merge" above.
    ...(patch.name !== undefined ? { name: patch.name.trim() || existing.name } : {}),
    ...(patch.filters !== undefined ? { filters: JSON.parse(JSON.stringify(patch.filters)) as FilterState } : {}),
    updatedAt: nowIso(),
  };
  rows[idx] = next;
  writeAll(rows);
  return next;
}

/**
 * deleteScreen — removes one screen by id. Returns true if a row was actually
 * removed (so the caller can show a "deleted" toast vs. "not found" toast).
 */
export function deleteScreen(id: string): boolean {
  const rows = readAll();
  const next = rows.filter((r) => r.id !== id);
  if (next.length === rows.length) return false;
  writeAll(next);
  return true;
}

/**
 * loadScreen — fetch a single screen by id. Returns null if not found.
 *
 * WHY a separate getter (instead of asking callers to filter listSavedScreens):
 *   - Self-documenting at the call site ("I want THIS screen, by id").
 *   - Cheaper if we ever migrate to IndexedDB (single-key get vs full scan).
 */
export function loadScreen(id: string): SavedScreen | null {
  const rows = readAll();
  return rows.find((r) => r.id === id) ?? null;
}
