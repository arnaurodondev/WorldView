/**
 * lib/utils.ts — Shared utilities: Tailwind class merging + financial formatters
 *
 * WHY THIS EXISTS: Two categories of shared logic:
 * 1. cn() — the shadcn/ui standard for conditionally merging Tailwind classes.
 *    Without this, class conflicts like "text-red-500 text-green-500" both apply;
 *    cn() deduplicates and applies the last one (tailwind-merge behavior).
 * 2. Financial formatters — Bloomberg-style number formatting used across ALL
 *    data displays. Centralised here so the format is consistent everywhere.
 *    Finance users expect consistent decimal places and SI suffixes.
 *
 * WHO USES IT: Every component file in the app.
 * DESIGN REFERENCE: docs/ui/DESIGN_SYSTEM.md §3 Typography + §2 Colors
 */

import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";
// PLAN-0059-C C-5: financial number formatters now live in lib/format.ts.
// This module re-exports them under their legacy names so existing call
// sites (lib/utils.ts has been imported in 100+ files) keep working with
// no change. New code should import from "@/lib/format" directly.
import {
  formatCompact,
  formatCompactCurrency,
  formatPrice as formatPriceCanonical,
  formatPercent as formatPercentCanonical,
  formatPercentUnsigned as formatPercentUnsignedCanonical,
  formatRatio as formatRatioCanonical,
} from "@/lib/format";

/**
 * cn — Conditional Tailwind class name utility (shadcn/ui standard)
 *
 * WHY clsx + tailwind-merge: clsx handles conditional/array inputs;
 * twMerge resolves conflicts (e.g., bg-red-500 wins over bg-blue-500
 * when passed last). Both are needed for shadcn/ui's variant system.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

// ── Financial number formatters ──────────────────────────────────────────

// PLAN-0059-C C-5: financial formatters now delegate to lib/format.ts.
// Public names below are unchanged so the 100+ existing call sites keep
// working. New code should import from "@/lib/format" instead.

export const formatPrice = (value: number | null | undefined): string =>
  formatPriceCanonical(value, "USD");

export const formatPriceCompact = (value: number | null | undefined): string =>
  formatCompactCurrency(value, "USD");

export const formatPercent = (
  value: number | null | undefined,
  decimals = 2,
): string => formatPercentCanonical(value, decimals);

/**
 * formatPercentDirect — same shape as formatPercent but for already-percentage
 * inputs (API returns 2.34 meaning 2.34%, not 0.0234).
 */
export function formatPercentDirect(
  value: number | null | undefined,
  decimals = 2,
): string {
  if (value == null) return "—";
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(decimals)}%`;
}

export const formatPercentUnsigned = (
  value: number | null | undefined,
  decimals = 2,
): string => formatPercentUnsignedCanonical(value, decimals);

export const formatVolume = (value: number | null | undefined): string =>
  formatCompact(value);

export const formatMarketCap = (value: number | null | undefined): string =>
  formatCompactCurrency(value, "USD");

export const formatRatio = (
  value: number | null | undefined,
  suffix = "x",
): string => formatRatioCanonical(value, suffix);

/**
 * formatDate — compact date for table cells
 * e.g., "2026-04-17T14:32:00Z" → "Apr 17, 2026"
 *
 * POLISH PASS 2026-05-09: hardened against the silent "Invalid Date" bug.
 * When `isoString` is a non-ISO string (legacy rows pre-PRD-0028 sometimes
 * carry "" or a timestamp without TZ marker), `new Date(...)` returns a
 * Date object whose `getTime()` is NaN. `Intl.DateTimeFormat.format()` of
 * an invalid date renders the literal string "Invalid Date" — visible to
 * the user. We probe `getTime()` BEFORE formatting and fall through to the
 * em-dash placeholder so the cell still has consistent height/layout.
 */
export function formatDate(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  const d = new Date(isoString);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(d);
}

/**
 * formatDateTime — date + time in UTC for alert timestamps
 * e.g., "2026-04-17T14:32:00Z" → "Apr 17, 14:32 UTC"
 *
 * POLISH PASS 2026-05-09: same Invalid-Date guard as `formatDate` above —
 * see that function's WHY block for the rationale.
 */
export function formatDateTime(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  const d = new Date(isoString);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    hour12: false,
  }).format(d) + " UTC";
}

/**
 * safeFormatClockTime — wall-clock "HH:MM" for chat bubbles & in-thread
 * timestamps. Returns "—" for null/undefined/Invalid-Date inputs instead
 * of leaking the literal "Invalid Date" string from `toLocaleTimeString`.
 *
 * WHY THIS EXISTS: chat MessageBubble + SlashTurnBlock historically called
 *   `new Date(message.created_at).toLocaleTimeString(...)`
 * directly. When `created_at` is null (an unhydrated optimistic message) or
 * a non-parseable string (pre-PRD-0028 cached threads), the rendered text
 * is the literal "Invalid Date" — a noisy regression that has cropped up
 * across multiple QA passes. Centralizing the guard here means future
 * callers automatically inherit the safe behaviour.
 */
export function safeFormatClockTime(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  const d = new Date(isoString);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/**
 * formatRelativeTime — human-readable relative time for news/alerts
 * e.g., "2h ago", "just now", "3d ago", "in 2h" (for future dates like economic calendar)
 *
 * BT-010 FIX: Now handles future timestamps (e.g., economic calendar events)
 * instead of producing negative values like "-1m ago".
 */
export function formatRelativeTime(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  const now = Date.now();
  const then = new Date(isoString).getTime();
  const diffSeconds = Math.floor((now - then) / 1000);

  // Future timestamps (negative diff) — used by economic calendar, scheduled events
  if (diffSeconds < 0) {
    const absDiff = Math.abs(diffSeconds);
    if (absDiff < 60) return "soon";
    if (absDiff < 3600) return `in ${Math.floor(absDiff / 60)}m`;
    if (absDiff < 86400) return `in ${Math.floor(absDiff / 3600)}h`;
    return `in ${Math.floor(absDiff / 86400)}d`;
  }

  // Past timestamps
  if (diffSeconds < 60) return "just now";
  if (diffSeconds < 3600) return `${Math.floor(diffSeconds / 60)}m ago`;
  if (diffSeconds < 86400) return `${Math.floor(diffSeconds / 3600)}h ago`;
  return `${Math.floor(diffSeconds / 86400)}d ago`;
}

// ── Color utility for P&L / price change ─────────────────────────────────

/**
 * priceChangeClass — returns Tailwind class for positive/negative/neutral
 *
 * WHY a function: Avoids duplicating ternary logic across 20+ components.
 * Uses semantic custom color tokens (--positive / --negative) not Tailwind
 * green-500/red-500, ensuring visual consistency with TradingView palette.
 */
export function priceChangeClass(
  value: number | null | undefined,
  neutralClass = "text-muted-foreground",
): string {
  if (value == null) return neutralClass;
  // PLAN-0059 W0 fix F-017 (2026-04-30): updated stale hex annotations.
  // After Wave A token surgery: --positive = #00D26A (institutional green,
  // AAA 9.18:1) and --negative = #FF3B5C (urgent red, AA 6.83:1). The semantic
  // class names (text-positive / text-negative) resolve via CSS vars so the
  // hex values shift automatically with the theme — these comments are
  // documentation only.
  if (value > 0) return "text-positive";  // hsl(var(--positive)) = #00D26A
  if (value < 0) return "text-negative";  // hsl(var(--negative)) = #FF3B5C
  return neutralClass;
}

/**
 * heatCellColor — 7-step color scale for sector heatmap cells
 *
 * WHY 7 steps: Matches the PRD-0028 spec and the pencil.dev canvas design.
 * Range -3% to +3% covers 95%+ of daily sector moves without clamping.
 * Returns CSS background + text color as an object for inline style usage.
 *
 * PLAN-0059 W0 F-VISUAL-003 fix:
 *   The previous implementation returned hardcoded blue-tinted hex values
 *   (#1A2030, #0A2E28, #0A2420, #251218, #300E12, #3D0A0E) which were
 *   leftovers from the pre-2026-04-23 "Bloomberg Dark" palette. globals.css:11
 *   explicitly forbids those colors — but this function never got the memo.
 *   Sector heatmap cells looked like cyan stickers on a zero-hue page.
 *
 *   Now derives every step from CSS variables (--positive, --negative,
 *   --surface-2, --muted-foreground) via hsl()/0.NN alpha blends. Future
 *   palette tweaks cascade automatically. Heatmap is now visually harmonized
 *   with the page hue family.
 *
 * RETURNS hsl()/CSS-var strings (not hex). Consumers that need hex literals
 * (lightweight-charts) should use lib/format/color.ts:resolveCssColor() —
 * but most callers can use these CSS strings directly in inline style.
 */
export function heatCellColor(changePct: number | null): {
  background: string;
  color: string;
} {
  if (changePct == null) {
    return {
      background: "hsl(var(--surface-2))",
      color: "hsl(var(--muted-foreground))",
    };
  }

  // Clamp to [-3%, +3%] range for the 7-step scale
  const clamped = Math.max(-3, Math.min(3, changePct));

  // WHY 7 explicit alpha steps (not opacity-blended via Tailwind /20 /30):
  // Tailwind's /NN suffix uses opacity-blend which renders slightly differently
  // on macOS Display P3 vs Windows sRGB (the audit's color-space drift finding).
  // CSS hsl()/N.NN syntax with explicit alpha matches the page hue exactly.
  // Cells feel "part of the page" rather than painted-on color blocks.
  if (clamped >= 3)
    return {
      background: "hsl(var(--positive) / 0.32)",
      color: "hsl(var(--positive))",
    };
  if (clamped >= 1.5)
    return {
      background: "hsl(var(--positive) / 0.20)",
      color: "hsl(var(--positive))",
    };
  if (clamped >= 0.5)
    return {
      background: "hsl(var(--positive) / 0.10)",
      color: "hsl(var(--positive))",
    };
  if (clamped > -0.5)
    return {
      background: "hsl(var(--surface-2))",
      color: "hsl(var(--muted-foreground))",
    };
  if (clamped > -1.5)
    return {
      background: "hsl(var(--negative) / 0.10)",
      color: "hsl(var(--negative))",
    };
  if (clamped > -3)
    return {
      background: "hsl(var(--negative) / 0.20)",
      color: "hsl(var(--negative))",
    };
  return {
    background: "hsl(var(--negative) / 0.32)",
    color: "hsl(var(--negative))",
  };
}

/**
 * severityColor — map AlertSeverity to Tailwind classes for badges
 *
 * WHY string (not union type): S10 REST API returns StrEnum values as lowercase
 * ("low", "medium", "high", "critical") while the WS stream may send uppercase.
 * Normalising to uppercase here prevents a no-match → undefined destructure crash.
 */
export function severityColor(
  severity: string,
): { bg: string; text: string } {
  switch (severity.toUpperCase()) {
    case "CRITICAL":
      return { bg: "bg-destructive/20", text: "text-negative" };
    case "HIGH":
      return { bg: "bg-warning/20", text: "text-warning" };
    case "MEDIUM":
      return { bg: "bg-muted", text: "text-muted-foreground" };
    case "LOW":
    default:
      return { bg: "bg-muted/50", text: "text-muted-foreground" };
  }
}

/**
 * truncate — truncate text to N characters with ellipsis
 * WHY: Article titles in compact cards need consistent max-width truncation
 */
export function truncate(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return text.slice(0, maxLength - 3) + "...";
}

/**
 * safeExternalUrl — allowlist only http/https URLs before using them in href attributes
 *
 * WHY THIS EXISTS: API responses may include URLs from external content pipelines
 * (news articles, prediction markets, RAG citations). Without validation, a malicious
 * or compromised backend response containing a "javascript:" or "data:" URL would
 * execute code when the user clicks the link — a stored XSS vector.
 *
 * SECURITY: Only "http:" and "https:" schemes are allowed. Anything else (javascript:,
 * data:, vbscript:, blob:, etc.) returns "#" (a safe no-op href).
 *
 * USAGE: href={safeExternalUrl(article.url)}
 */
export function safeExternalUrl(url: string | null | undefined): string {
  if (!url) return "#";
  try {
    const parsed = new URL(url);
    // Only allow safe web protocols — block javascript:, data:, vbscript:, blob:, etc.
    if (parsed.protocol === "https:" || parsed.protocol === "http:") return url;
  } catch {
    // URL parsing failed (relative path or malformed) — return safe fallback
  }
  return "#";
}

/**
 * sanitizeRedirect — validate a redirect destination is a safe same-origin relative path
 *
 * WHY THIS EXISTS: Post-login redirect targets come from URL query params and
 * sessionStorage, both of which can be attacker-controlled. Without validation,
 * `/login?redirect_to=https://evil.com` causes an open redirect after successful
 * authentication — the user is logged in but redirected to a phishing site.
 *
 * ALLOWED: Relative paths starting with "/" that are not protocol-relative ("//").
 * BLOCKED: Absolute URLs (https://...), protocol-relative (//...), and empty strings.
 *
 * USAGE: const safePath = sanitizeRedirect(searchParams.get("redirect_to"));
 */
export function sanitizeRedirect(value: string | null | undefined): string {
  if (!value) return "/dashboard";
  // Must start with "/" but not "//" (protocol-relative redirects follow absolute URLs)
  if (value.startsWith("/") && !value.startsWith("//")) return value;
  return "/dashboard";
}
