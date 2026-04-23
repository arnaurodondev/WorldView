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

/**
 * formatPrice — format a price with 2 decimal places in USD
 *
 * WHY 2 decimals: Standard for US equities. Not configurable per component
 * because inconsistent decimals confuse finance users scanning multiple panels.
 * Exception: crypto uses formatCryptoPrice() below.
 */
export function formatPrice(value: number | null | undefined): string {
  if (value == null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

/**
 * formatPriceCompact — abbreviated price for tight spaces (TopBar index tickers)
 * e.g., $4,892.34 → "$4,892.34" but $12,345,678 → "$12.35M"
 */
export function formatPriceCompact(value: number | null | undefined): string {
  if (value == null) return "—";
  if (Math.abs(value) >= 1_000_000_000) {
    return `$${(value / 1_000_000_000).toFixed(2)}B`;
  }
  if (Math.abs(value) >= 1_000_000) {
    return `$${(value / 1_000_000).toFixed(2)}M`;
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

/**
 * formatPercent — format a percentage change with sign prefix
 *
 * WHY sign prefix: Finance users need to instantly distinguish gain/loss
 * without looking at color (accessibility + speed scanning).
 * e.g., 0.0234 → "+2.34%", -0.0112 → "-1.12%"
 */
export function formatPercent(
  value: number | null | undefined,
  decimals = 2,
): string {
  if (value == null) return "—";
  const sign = value >= 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(decimals)}%`;
}

/**
 * formatPercentDirect — same as formatPercent but value is already in percentage
 * e.g., 2.34 → "+2.34%"  (used when API returns % not decimal)
 */
export function formatPercentDirect(
  value: number | null | undefined,
  decimals = 2,
): string {
  if (value == null) return "—";
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(decimals)}%`;
}

/**
 * formatVolume — compact volume notation for table cells
 * e.g., 1234567 → "1.23M", 987654321 → "987.65M"
 */
export function formatVolume(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(2)}B`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)}K`;
  return value.toFixed(0);
}

/**
 * formatMarketCap — compact market cap for screener + fundamentals
 * e.g., 2450000000000 → "$2.45T"
 */
export function formatMarketCap(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value >= 1_000_000_000_000)
    return `$${(value / 1_000_000_000_000).toFixed(2)}T`;
  if (value >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(2)}B`;
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  return formatPrice(value);
}

/**
 * formatRatio — PE ratio, price/book, etc. — 2 decimals, no suffix, no $ sign
 * e.g., 24.567 → "24.57x"
 */
export function formatRatio(
  value: number | null | undefined,
  suffix = "x",
): string {
  if (value == null) return "—";
  return `${value.toFixed(2)}${suffix}`;
}

/**
 * formatDate — compact date for table cells
 * e.g., "2026-04-17T14:32:00Z" → "Apr 17, 2026"
 */
export function formatDate(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(isoString));
}

/**
 * formatDateTime — date + time in UTC for alert timestamps
 * e.g., "2026-04-17T14:32:00Z" → "Apr 17, 14:32 UTC"
 */
export function formatDateTime(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    hour12: false,
  }).format(new Date(isoString)) + " UTC";
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
  if (value > 0) return "text-positive";  // hsl(var(--positive)) = #26A69A
  if (value < 0) return "text-negative";  // hsl(var(--negative)) = #EF5350
  return neutralClass;
}

/**
 * heatCellColor — 7-step color scale for sector heatmap cells
 *
 * WHY 7 steps: Matches the PRD-0028 spec and the pencil.dev canvas design.
 * Range -3% to +3% covers 95%+ of daily sector moves without clamping.
 * Returns CSS background + text color as an object for inline style usage
 * (lightweight-charts and other non-Tailwind contexts need hex values).
 */
export function heatCellColor(changePct: number | null): {
  background: string;
  color: string;
} {
  if (changePct == null) {
    return { background: "#1A2030", color: "#6B7585" }; // neutral/no data
  }

  // Clamp to [-3%, +3%] range for the 7-step scale
  const clamped = Math.max(-3, Math.min(3, changePct));

  // WHY these specific hex values: tinted backgrounds harmonize with the
  // Bloomberg Dark #0A0E14 page background. Each step blends the teal or
  // red hue into the dark blue-grey base so cells feel "part of the page"
  // rather than painted-on color blocks.
  if (clamped >= 3) return { background: "#0A2E28", color: "#26A69A" };
  if (clamped >= 1.5) return { background: "#0A2420", color: "#26A69A" };
  if (clamped >= 0.5) return { background: "#0E201C", color: "#4DB6AC" };
  if (clamped > -0.5) return { background: "#1A2030", color: "#6B7585" };
  if (clamped > -1.5) return { background: "#251218", color: "#EF9A9A" };
  if (clamped > -3) return { background: "#300E12", color: "#EF5350" };
  return { background: "#3D0A0E", color: "#EF5350" };
}

/**
 * severityColor — map AlertSeverity to Tailwind classes for badges
 */
export function severityColor(
  severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
): { bg: string; text: string } {
  switch (severity) {
    case "CRITICAL":
      return { bg: "bg-destructive/20", text: "text-negative" };
    case "HIGH":
      return { bg: "bg-warning/20", text: "text-warning" };
    case "MEDIUM":
      return { bg: "bg-muted", text: "text-muted-foreground" };
    case "LOW":
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
