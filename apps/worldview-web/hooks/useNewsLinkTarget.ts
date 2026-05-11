/**
 * hooks/useNewsLinkTarget.ts — user preference for how news article links open
 *
 * WHY THIS EXISTS (PLAN-0050 T-F-6-20, closes F-I-034): the dashboard's news
 * widgets currently hardcode `target="_blank"` because the assumption was
 * "users want to read the article alongside the dashboard". That works for
 * portfolio managers running multi-monitor, but single-screen users complain
 * about losing track of which tab is the dashboard. A persisted preference
 * lets each user choose; the dashboard rows then honour it.
 *
 * Persistence: localStorage, namespaced under `worldview.prefs.news_link_target`.
 * The hook is SSR-safe — it reads the stored value lazily on mount and
 * defaults to `"new-tab"` (the prior hardcoded behaviour) so existing users
 * see no change unless they opt in.
 *
 * Why a hook + setter (not React Context): the preference is read from many
 * leaf rows (each news article row) and written from one place (Settings).
 * Context would re-render every consumer on a write; a localStorage-backed
 * hook only re-renders the components that mounted *after* the change.
 * Cross-tab sync uses the `storage` event so a Settings change in tab A
 * propagates to a dashboard already open in tab B.
 */

"use client";
// WHY "use client": uses useState + useEffect, both browser-only.

import { useEffect, useState } from "react";

/** Preference values — kept tiny so future serialisation never breaks. */
export type NewsLinkTarget = "new-tab" | "same-tab";

const STORAGE_KEY = "worldview.prefs.news_link_target";
const DEFAULT_VALUE: NewsLinkTarget = "new-tab";

/** Read the stored value; safe to call on the server (returns default). */
function readStored(): NewsLinkTarget {
  if (typeof window === "undefined") return DEFAULT_VALUE;
  const v = window.localStorage.getItem(STORAGE_KEY);
  return v === "same-tab" ? "same-tab" : DEFAULT_VALUE;
}

/**
 * Public read-only accessor for non-React callers (e.g. an event handler
 * that cannot use a hook). Returns the current preference synchronously.
 *
 * WHY a sync function (not the hook): `<a href>` rendering happens before
 * the row component re-renders on a preference change. For external-link
 * decisions the up-to-the-millisecond truth is what we need.
 */
export function getNewsLinkTarget(): NewsLinkTarget {
  return readStored();
}

/**
 * useNewsLinkTarget — React hook for the news-article tab preference.
 *
 * Returns `[value, setValue]` exactly like `useState`. The setter writes
 * through to localStorage and dispatches a `storage` event so other tabs
 * pick up the change without a refresh.
 */
export function useNewsLinkTarget(): [NewsLinkTarget, (next: NewsLinkTarget) => void] {
  // Lazy initial read — avoids hydration mismatch on the very first render
  // because the SSR pass returns DEFAULT_VALUE and the client mount syncs
  // with localStorage on the first effect tick.
  const [value, setValue] = useState<NewsLinkTarget>(DEFAULT_VALUE);

  // Sync from localStorage on mount + listen for storage events.
  useEffect(() => {
    setValue(readStored());
    function onStorage(e: StorageEvent) {
      // F-QA-03 fix: accept events with our key OR a null key (jsdom +
      // some browsers omit the field on synthetic events). Re-reading
      // localStorage is cheap and safe — at worst we re-set the same value
      // which React no-ops. The narrow check (e.key === STORAGE_KEY) used
      // to drop synthetic events with key=null and miss the same-tab path.
      if (e.key === null || e.key === STORAGE_KEY) {
        setValue(readStored());
      }
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  function persist(next: NewsLinkTarget): void {
    setValue(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
      // F-QA-03 fix: browsers only fire `storage` events for OTHER tabs
      // writing to localStorage. If a second instance of this hook is
      // mounted in the same tab (e.g. the Settings panel + an open
      // dashboard widget), it would NOT see the change without this
      // synthetic dispatch. Sending a StorageEvent makes the same-tab
      // listener path identical to the cross-tab path so getNewsLinkTarget()
      // (sync) and useNewsLinkTarget() (hook state) agree at the same instant.
      // F-QA-03 fix: NO `storageArea` in the constructor — jsdom (and some
      // older browsers) reject it when the storage object isn't a real
      // Storage instance, throwing a TypeError that silently aborts the
      // dispatch. Listeners only need `key` + `newValue` to handle the
      // change, so we omit the optional storageArea field entirely.
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: STORAGE_KEY,
          newValue: next,
        }),
      );
    } catch {
      // Storage quota exceeded or disabled — preference reverts on reload.
      // Not worth surfacing to the user; the in-memory value still works
      // for the current session.
    }
  }

  return [value, persist];
}

/**
 * Compute the `target` and `rel` attributes for an `<a>` from the user's
 * preference. Centralised here so every news consumer applies the same rules:
 *   - new-tab  → target="_blank"  rel="noopener noreferrer" (default + safer
 *     against tabnabbing on external URLs)
 *   - same-tab → target="_self"   rel="noreferrer" (no opener leak on
 *     navigation either)
 */
export function newsLinkAttrs(
  target: NewsLinkTarget,
): { target: "_blank" | "_self"; rel: string } {
  if (target === "same-tab") {
    return { target: "_self", rel: "noreferrer" };
  }
  return { target: "_blank", rel: "noopener noreferrer" };
}

/**
 * isSafeNewsUrl — F-QA-02 fix: accept ONLY http: / https: URLs.
 *
 * WHY HERE: every news consumer (PortfolioNewsWidget click handler,
 * BiggestNewsRow anchor, future surfaces) eventually navigates to S6's
 * `article.url` field. React's automatic `javascript:` href sanitisation
 * applies only to JSX attributes — it does NOT cover imperative APIs like
 * `window.location.href = url` or `window.open(url, ...)`. If S6 ever
 * stores or proxies an article whose URL is `javascript:alert(1)` (server
 * bug, malicious upstream feed, RAG-summary that interpolated a URL),
 * the dashboard would otherwise execute the script in the user's session.
 *
 * WHY URL parsing (not a regex): a regex over arbitrary URL strings is a
 * footgun. `new URL(value)` rejects invalid syntax up-front; the protocol
 * check is the single tight invariant we need.
 *
 * Returns true ONLY for absolute http(s) URLs. Relative URLs are rejected
 * because S6 never returns them — a relative URL here would itself be a bug.
 */
export function isSafeNewsUrl(value: string | null | undefined): boolean {
  if (!value) return false;
  try {
    const u = new URL(value);
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
}
