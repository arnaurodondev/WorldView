/**
 * hooks/useDebounce.ts — Debounce hook for search inputs
 *
 * WHY THIS EXISTS: GlobalSearch fires a query on every keystroke by default.
 * Debouncing by 300ms means we only send a request when the user pauses typing,
 * reducing S9 load from ~10 requests per search to 1-2.
 *
 * WHY 300ms: Standard UX debounce for search — fast enough to feel responsive,
 * slow enough to avoid flooding the server with intermediate keystrokes.
 *
 * WHO USES IT: components/shell/GlobalSearch.tsx
 * DATA SOURCE: None — pure timing utility
 */

import { useEffect, useState } from "react";

export function useDebounce<T>(value: T, delayMs: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    // Set a timer to update the debounced value after the delay
    const timer = setTimeout(() => {
      setDebouncedValue(value);
    }, delayMs);

    // WHY cleanup: If value changes before the delay expires, the previous timer
    // is cleared and a new one starts. This ensures we only emit the FINAL value
    // in a burst of rapid changes, not every intermediate state.
    return () => clearTimeout(timer);
  }, [value, delayMs]); // Rerun when value or delay changes

  return debouncedValue;
}
