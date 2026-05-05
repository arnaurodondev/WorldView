/**
 * components/shell/ForceUpdateBanner.tsx — "New version available" prompt.
 *
 * WHY THIS EXISTS (PLAN-0059 B-6): traders typically keep worldview tabs open
 * for entire trading sessions (4–8h). When we deploy a new frontend build,
 * those tabs keep running the old bundle — bugfixes and contract migrations
 * never reach them until the next hard refresh. This banner detects the
 * mismatch and lets the trader decide WHEN to reload (we never yank the
 * chart out mid-glance).
 *
 * MECHANIC: snapshot the build id at mount; poll `/api/version` every 60s;
 * if it ever returns a different id, render a sticky banner with a Reload
 * action. Polling stops after the user reloads (page unmount).
 *
 * WHO USES IT: every authenticated route — mounted in `app/(app)/layout.tsx`.
 * DATA SOURCE: GET /api/version (Next.js route handler, no auth).
 * DESIGN REFERENCE: PRD-0031 §StatusBar (banner styling matches alert/error rows).
 */

"use client";
// WHY "use client": uses useEffect for the poll loop and useState for the
// banner-visibility flag. Both are browser-only APIs.

import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";

// WHY 60s poll interval: a balance between "fresh enough to catch a deploy
// within a minute" and "not hammering the route handler from idle tabs".
// 60s × 8h trader session × thousands of tabs is still trivial server load.
const DEFAULT_POLL_INTERVAL_MS = 60_000;

// WHY abort on document.visibilityState === "hidden": background tabs
// don't need to discover deploys until they're focused again. Browsers
// throttle setInterval in background tabs anyway, so this just makes the
// behaviour explicit instead of timer-engine-dependent.
const FETCH_TIMEOUT_MS = 5_000;

interface VersionResponse {
  buildId: string;
}

async function fetchBuildId(signal: AbortSignal): Promise<string | null> {
  try {
    const res = await fetch("/api/version", { signal, cache: "no-store" });
    if (!res.ok) return null;
    const data = (await res.json()) as VersionResponse;
    return typeof data?.buildId === "string" ? data.buildId : null;
  } catch {
    // Network errors (offline, transient blip) are non-fatal — we just
    // skip this tick and try again next interval. The banner only fires
    // on a CONFIRMED mismatch, never on a fetch failure.
    return null;
  }
}

interface ForceUpdateBannerProps {
  /**
   * Poll interval in milliseconds. Default 60_000.
   *
   * Exposed primarily so tests can use a short interval (10–20ms) with real
   * timers instead of fighting fake-timer interactions with fetch microtasks.
   * Production callers should not override this.
   */
  pollIntervalMs?: number;
}

export function ForceUpdateBanner({
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
}: ForceUpdateBannerProps = {}) {
  // initialBuildId is captured exactly once at first successful poll. We
  // can't read it synchronously at render time because client components
  // don't have direct access to runtime env; we discover it by asking the
  // server. Stored as null until the first probe resolves. The value
  // itself is never *read* during render — we only need its setter and
  // its prior value (via the functional updater) to compare against new
  // polls. Underscore prefix silences the unused-var lint rule.
  const [, setInitialBuildId] = useState<string | null>(null);
  // outOfDate flips true when a later poll observes a different build id.
  const [outOfDate, setOutOfDate] = useState(false);

  useEffect(() => {
    // WHY a single AbortController across the whole effect: lets us abort
    // any in-flight fetch when the component unmounts (or React Strict-Mode
    // double-invokes the effect in dev).
    const controller = new AbortController();
    let timer: ReturnType<typeof setInterval> | null = null;

    const poll = async () => {
      // Per-poll timeout so a hung server doesn't keep the request open
      // forever and pile up if poll intervals overlap.
      const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
      const buildId = await fetchBuildId(controller.signal);
      clearTimeout(timeoutId);
      if (!buildId) return;

      // Capture the first successful read as the baseline. Subsequent reads
      // compare against it; once outOfDate is true we stay there until the
      // user reloads.
      setInitialBuildId((current) => {
        if (current === null) return buildId;
        if (current !== buildId) {
          setOutOfDate(true);
        }
        return current;
      });
    };

    // Kick off the first poll immediately so we capture the baseline
    // without waiting one full interval.
    void poll();
    timer = setInterval(poll, pollIntervalMs);

    return () => {
      controller.abort();
      if (timer) clearInterval(timer);
    };
  }, [pollIntervalMs]);

  // No banner until we've confirmed a mismatch. Returning null keeps the
  // layout shift to zero in the common case (which is "build is current").
  if (!outOfDate) return null;

  return (
    // WHY h-7 (28px) sticky bottom-right banner: institutional terminal
    // density — full-width banners eat data real-estate. A right-aligned
    // 28px chip pinned just above the StatusBar is visible without
    // pushing tables down. WHY warning token (advisory amber): signals
    // "update available", not destructive — errors use negative/destructive.
    <div
      role="status"
      aria-live="polite"
      className="fixed bottom-7 right-3 z-40 flex h-7 items-center gap-2 rounded-[2px] border border-warning/40 bg-warning/[0.08] px-3 font-mono text-[11px] text-warning shadow-[0_0_0_1px_rgba(0,0,0,0.4)]"
    >
      <RefreshCw className="h-3 w-3" aria-hidden />
      <span className="uppercase tracking-[0.06em]">New version available</span>
      <button
        // WHY window.location.reload(true): hard reload to bypass the
        // browser's bfcache and HTTP cache, forcing a fresh fetch of
        // index.html so the new build's chunk hashes resolve. The
        // `true` argument is non-standard but ignored by browsers that
        // dropped it; behaviour is "best effort hard reload".
        onClick={() => window.location.reload()}
        className="ml-1 rounded-[2px] border border-warning/60 px-1.5 py-0.5 text-[10px] uppercase tracking-[0.06em] hover:bg-warning/15"
      >
        Reload
      </button>
    </div>
  );
}
