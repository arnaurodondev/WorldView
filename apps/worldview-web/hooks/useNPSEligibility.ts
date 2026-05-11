/**
 * hooks/useNPSEligibility.ts — gate when the NPS prompt may fire.
 *
 * WHY THIS EXISTS (PLAN-0053 Wave G T-G-7-02):
 * NPS surveys are noisy. PLAN-0053 approved decision: "1/quarter/user".
 * This hook centralises the eligibility math so every trigger surface
 * (post-portfolio-sync handler, post-first-alert handler, and any future
 * milestone) shares one truth.
 *
 * RULES (must all be true):
 *   1. user is authenticated (NPS is per-account; anonymous skipped)
 *   2. ≥ 3 sessions on this account (avoids first-time-user bias)
 *   3. no submission in the last 30 days (any quarter)
 *   4. no submission in the current calendar quarter (1/quarter cap)
 *
 * STORAGE: localStorage holds the last-submitted ISO date and the running
 * session counter. Cross-tab sync is good-enough — duplicate prompts in
 * adjacent tabs are caught server-side too (the backend can dedupe by
 * user_id + day).
 *
 * THIS HOOK READS — IT NEVER WRITES THE LAST-SUBMITTED MARKER. The marker
 * is written by `markNPSSubmitted()` after a successful POST so the
 * eligibility check on the next render reflects reality.
 */

"use client";
// WHY "use client": reads localStorage + auth context — both browser-only.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/hooks/useAuth";

// ── Storage keys ───────────────────────────────────────────────────────────
//
// WHY namespaced under "worldview.nps.*": follows the same pattern as
// "worldview-recent-instruments" / "worldview.prefs.*" used elsewhere — no
// collisions with other apps on the same domain.

const KEY_LAST_SUBMITTED = "worldview.nps.last_submitted_at";
const KEY_SESSION_COUNT = "worldview.nps.session_count";
const KEY_LAST_SESSION_DATE = "worldview.nps.last_session_date";
const KEY_DISMISSED_THIS_QUARTER = "worldview.nps.dismissed_quarter";

const MIN_SESSIONS_BEFORE_PROMPT = 3;
const COOLDOWN_DAYS = 30;

// ── Helpers ────────────────────────────────────────────────────────────────

/**
 * currentQuarterKey — "YYYY-Q1".."YYYY-Q4" so we can store one boolean
 * per quarter and rotate automatically without a cron.
 */
function currentQuarterKey(now = new Date()): string {
  const q = Math.floor(now.getUTCMonth() / 3) + 1;
  return `${now.getUTCFullYear()}-Q${q}`;
}

/**
 * daysSince — integer days between an ISO date and now, UTC-safe.
 * Returns Infinity when the input is null/invalid so the caller treats it
 * as "no prior submission" without a guard.
 */
function daysSince(iso: string | null): number {
  if (!iso) return Infinity;
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return Infinity;
  return (Date.now() - ts) / 86_400_000;
}

/** Read an integer from localStorage with NaN → 0 fallback. */
function readInt(key: string): number {
  if (typeof window === "undefined") return 0;
  const raw = window.localStorage.getItem(key);
  if (!raw) return 0;
  const n = parseInt(raw, 10);
  return Number.isNaN(n) ? 0 : n;
}

/** Read a string from localStorage (safe in SSR). */
function readString(key: string): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(key);
}

// ── Public helpers ─────────────────────────────────────────────────────────

/**
 * recordSession — call once per browser-tab open. Bumps the running counter
 * IF this is a different calendar day from the last counted session, so
 * "session" approximates "user came back". Same-day reloads don't inflate.
 *
 * WHY exported: the (app)/layout.tsx mounts on every navigation, but we
 * only want one increment per fresh session. The hook calls this on its
 * own first render — exporting it lets tests + other surfaces force a
 * deterministic increment.
 */
export function recordSession(): void {
  if (typeof window === "undefined") return;
  const today = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
  const last = readString(KEY_LAST_SESSION_DATE);
  if (last === today) return; // already counted today
  const count = readInt(KEY_SESSION_COUNT);
  window.localStorage.setItem(KEY_SESSION_COUNT, String(count + 1));
  window.localStorage.setItem(KEY_LAST_SESSION_DATE, today);
}

/**
 * markNPSSubmitted — called by the success handler after POST /v1/feedback/nps.
 * Writes the current ISO timestamp + flags the current quarter as "done".
 */
export function markNPSSubmitted(): void {
  if (typeof window === "undefined") return;
  const nowIso = new Date().toISOString();
  window.localStorage.setItem(KEY_LAST_SUBMITTED, nowIso);
  window.localStorage.setItem(KEY_DISMISSED_THIS_QUARTER, currentQuarterKey());
}

/**
 * markNPSDismissed — record a "Maybe later" press without server submit.
 * We treat dismiss as a quarter-level commitment to avoid hassling users.
 */
export function markNPSDismissed(): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(KEY_DISMISSED_THIS_QUARTER, currentQuarterKey());
}

// ── Hook ───────────────────────────────────────────────────────────────────

export interface NPSEligibility {
  /** True when ALL rules pass and the prompt may be shown. */
  eligible: boolean;
  /** Human-readable reason — useful for telemetry / debug. */
  reason:
    | "ok"
    | "unauthenticated"
    | "too_few_sessions"
    | "cooldown_active"
    | "already_dismissed_this_quarter";
  /** Convenience setters wired to the public helpers above. */
  markSubmitted: () => void;
  markDismissed: () => void;
}

/**
 * useNPSEligibility — returns whether the NPS prompt may fire right now.
 *
 * The component should NOT auto-open on this returning true alone — it
 * waits for a milestone event (portfolio sync, first alert) and THEN reads
 * `eligible` to decide.
 */
export function useNPSEligibility(): NPSEligibility {
  const { isAuthenticated } = useAuth();

  // WHY tick state: localStorage doesn't trigger React re-renders on its
  // own. After markSubmitted() the consumer expects `eligible` to flip
  // immediately. Bumping a tick on mark* invalidates the memo below.
  const [tick, setTick] = useState(0);

  // Bump session counter once per first render in this tab.
  useEffect(() => {
    recordSession();
  }, []);

  const result = useMemo<{ eligible: boolean; reason: NPSEligibility["reason"] }>(() => {
    if (!isAuthenticated) {
      return { eligible: false, reason: "unauthenticated" };
    }
    const sessions = readInt(KEY_SESSION_COUNT);
    if (sessions < MIN_SESSIONS_BEFORE_PROMPT) {
      return { eligible: false, reason: "too_few_sessions" };
    }
    const lastSubmittedDays = daysSince(readString(KEY_LAST_SUBMITTED));
    if (lastSubmittedDays < COOLDOWN_DAYS) {
      return { eligible: false, reason: "cooldown_active" };
    }
    const thisQuarter = currentQuarterKey();
    if (readString(KEY_DISMISSED_THIS_QUARTER) === thisQuarter) {
      return { eligible: false, reason: "already_dismissed_this_quarter" };
    }
    return { eligible: true, reason: "ok" };
    // tick is intentionally a dep to force recompute after mark*().
  }, [isAuthenticated, tick]);

  const markSubmitted = useCallback(() => {
    markNPSSubmitted();
    setTick((t) => t + 1);
  }, []);

  const markDismissed = useCallback(() => {
    markNPSDismissed();
    setTick((t) => t + 1);
  }, []);

  return { ...result, markSubmitted, markDismissed };
}
