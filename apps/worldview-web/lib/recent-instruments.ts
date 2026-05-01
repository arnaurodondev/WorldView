/**
 * lib/recent-instruments.ts — localStorage-backed recent instruments stack
 *
 * WHY EXTRACTED FROM GlobalSearch: TickerPicker (per-widget symbol picker) needs
 * the same "show last 5 tickers the user visited" behaviour as GlobalSearch. Rather
 * than duplicating the localStorage logic, we centralise it here.
 *
 * WHY localStorage (not server state): recent instruments are per-device UX
 * preferences, not portfolio data. They require no auth, no network, and no sync.
 * localStorage reads are synchronous — ideal for popover pre-population before
 * the search API responds.
 *
 * WHO USES IT:
 *   - components/shell/GlobalSearch.tsx (navigation search)
 *   - components/workspace/TickerPicker.tsx (per-panel symbol picker)
 */

export interface RecentInstrument {
  entityId: string;
  ticker: string;
  name: string;
}

const STORAGE_KEY = "worldview-recent-instruments";
const MAX_RECENT = 5;

/** Read the recent instruments list from localStorage. Falls back to [] on any error. */
export function readRecentInstruments(): RecentInstrument[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as RecentInstrument[]) : [];
  } catch {
    return [];
  }
}

/**
 * Prepend an instrument to the recent list, deduplicating by entityId and keeping
 * at most MAX_RECENT entries.
 */
export function saveRecentInstrument(entityId: string, ticker: string, name: string): void {
  if (typeof window === "undefined") return;
  try {
    const existing = readRecentInstruments().filter((r) => r.entityId !== entityId);
    const updated = [{ entityId, ticker, name }, ...existing].slice(0, MAX_RECENT);
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
  } catch {
    // localStorage may be unavailable (private-browsing quota, etc.) — silently ignore
  }
}
