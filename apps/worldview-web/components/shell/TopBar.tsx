/**
 * components/shell/TopBar.tsx — Application-wide top navigation bar
 *
 * WHY THIS EXISTS: Finance terminal top bars serve three functions:
 * 1. Global navigation trigger (logo + search)
 * 2. Market status at a glance (index prices + market status pill)
 * 3. User context + quick actions (AI assistant, alerts, profile)
 *
 * The layout follows Bloomberg Terminal conventions: left = nav/search,
 * center = market data, right = tools + user.
 *
 * WHO USES IT: app/(app)/layout.tsx — rendered at the top of every protected page
 * DATA SOURCE: auth state from AuthContext, market data from IndexTicker
 * DESIGN REFERENCE: PRD-0028 §6.5 TopBar
 */

"use client";
// WHY "use client": Uses useAuth (React context), logout() (async action),
// and DropdownMenu (Radix UI state). All require client rendering.

import { useRouter } from "next/navigation";
import { LogOut, Settings, User, Bell } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { UtcClock } from "@/components/shell/UtcClock";
import { IndexTicker } from "@/components/shell/IndexTicker";
import { MarketStatusPill } from "@/components/shell/MarketStatusPill";
import { GlobalSearch } from "@/components/shell/GlobalSearch";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
/**
 * formatPortfolioValue — compact portfolio NAV for the TopBar rail.
 * WHY compact: the TopBar has limited horizontal space. $1.2M is scannable;
 * $1,234,567 is not at the rail font size. Returns "—" while null (loading).
 */
function formatPortfolioValue(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `$${Math.round(value / 1_000)}K`;
  return `$${Math.round(value).toLocaleString()}`;
}

/**
 * getInitials — extract user initials for avatar fallback
 * WHY: Most internal users don't have avatar images; initials make the avatar
 * informative rather than showing a generic silhouette.
 */
function getInitials(name: string | null | undefined): string {
  if (!name) return "U";
  const parts = name.trim().split(" ");
  if (parts.length === 1) return parts[0]?.slice(0, 2).toUpperCase() ?? "U";
  return `${parts[0]?.[0] ?? ""}${parts[parts.length - 1]?.[0] ?? ""}`.toUpperCase();
}

interface TopBarProps {
  /** Unread alert count — passed from AlertStreamContext via layout */
  unreadAlerts?: number;
  /** Portfolio total value in USD — passed from layout REST query (null while loading) */
  portfolioValue?: number | null;
  /**
   * Today's portfolio P&L in USD (sum of qty × per-share daily change).
   * Pass null while batch quotes are loading; the value is hidden until known.
   * WHY in TopBar (C-2): Bloomberg-style top rails always surface a daily move
   * number — investors want it within sight regardless of which page they're on.
   */
  dailyPnl?: number | null;
  /** Total unrealised (mark-to-market) P&L in USD — same null semantics as above. */
  unrealisedPnl?: number | null;
}

export function TopBar({
  unreadAlerts = 0,
  portfolioValue,
  dailyPnl,
  unrealisedPnl,
}: TopBarProps) {
  const router = useRouter();
  const { user, logout } = useAuth();

  const handleLogout = async () => {
    await logout();
    // WHY replace: don't leave the protected page in history — back button
    // should not return user to authenticated content after logout
    router.replace("/login");
  };

  return (
    // WHY h-9 (36px): PRD-0031 §4.1 — v3 reduces TopBar from 44px to 36px to
    // maximize data-display vertical space. 36px still clears WCAG touch target
    // minimums for all interactive elements (buttons have h-7 minimum within).
    // WHY border-b border-border: crisp structural edge separating chrome from content.
    //
    // PLAN-0048 Wave C-1 — Layout was previously [left] [absolute-centered ticker] [right].
    // The absolute centering meant the right cluster could overflow into the ticker at
    // narrower viewports (the ticker was painted under it because it sat outside the flex
    // flow). We now use a single flex row with three siblings where the IndexTicker is
    // the only flex-1 child, so it absorbs slack and truncates first under pressure
    // instead of colliding with the portfolio rail.
    <header className="flex h-9 w-full shrink-0 items-center gap-3 border-b border-border bg-background px-3">
      {/* ── Left: Logo + Search ───────────────────────────────────── */}
      {/* WHY shrink-0: the logo + search must never shrink — they're nav anchors.
          Slack absorbed by the IndexTicker (the only flex-1 sibling). */}
      <div className="flex shrink-0 items-center gap-3">
        {/* Wordmark — text for crisp rendering at all DPIs */}
        <button
          onClick={() => router.push("/dashboard")}
          className="font-semibold text-foreground hover:opacity-80"
        >
          Worldview
        </button>

        <GlobalSearch />
      </div>

      {/* ── Center: Market data (IndexTicker) ─────────────────────── */}
      {/* WHY flex-1 + min-w-0 + max-w-[640px]:
          - flex-1: this child absorbs all horizontal slack so left/right blocks
            stay pinned to their edges.
          - min-w-0: required for any flex child that may need to shrink below
            its intrinsic content width — without it, the SPY/QQQ/VIX/BTC row
            would force the parent to overflow at 1280px.
          - max-w-[640px]: prevents the ticker from ballooning on ultrawide
            viewports; once it exceeds ~640px the extra whitespace just adds
            empty padding around prices that should sit visually centered.
          - overflow-hidden: lets the ticker truncate gracefully (its own
            internal layout already supports truncation). */}
      <div className="flex min-w-0 max-w-[640px] flex-1 justify-center overflow-hidden">
        <IndexTicker />
      </div>

      {/* ── Right: Tools + User ──────────────────────────────────── */}
      {/* WHY shrink-0: portfolio rail must NEVER wrap or truncate — it is
          the user's account snapshot and must always be readable. The ticker
          (flex-1) is the designated truncation victim under width pressure.
          WHY gap-2: compact at 36px bar height. */}
      <div className="flex shrink-0 items-center gap-2">
        <UtcClock />

        <MarketStatusPill />

        {/* ── Portfolio rail (PLAN-0048 C-1) ──────────────────────────────
            Three labeled values rendered as a single flex group with
            explicit min-width slots so values don't jump as digits change.

            WHY explicit min-w-* on every value:
            - The width must be PRE-ALLOCATED. If the values shrink/grow with
              content (e.g. "$3K" → "+$45.6K"), neighboring labels shift left
              and right on every refetch. Tabular-nums fixes per-character
              width but not the overall span — we still need min-w to lock
              the slot. Picked widths cover worst-case strings:
                * "$1.2M" / "$123K" / "—"  → min-w-[3.25rem] (52px)
                * "+$45.6K" with sign      → min-w-[3.75rem] (60px)
            - All three numeric values use font-mono + tabular-nums so digits
              align column-wise inside their slot.
            WHY text-[11px] (was text-[10px]): user feedback (audit
            2026-04-28) — 10px is too dense; 11px gains breathing room
            without growing the 36px bar height. Labels also bumped to 11px
            for visual parity. */}

        {/* Portfolio NAV — compact value display matching Bloomberg's account rail convention.
            WHY whitespace-nowrap: prevents "PORT $1.2M" from breaking onto two
            lines if a parent ever sets flex-wrap. */}
        {portfolioValue !== undefined && (
          <span
            className="flex items-center gap-1 whitespace-nowrap font-mono text-[11px] tabular-nums text-muted-foreground/80"
            title="Total portfolio value (live quote-based)"
            aria-label={`Portfolio value ${formatPortfolioValue(portfolioValue)}`}
          >
            <span className="text-muted-foreground">PORT</span>
            {/* min-w slot reserves space so neighbour labels don't jump */}
            <span className="inline-block min-w-[3.25rem] text-right text-foreground">
              {formatPortfolioValue(portfolioValue)}
            </span>
          </span>
        )}

        {/* Day P&L — colored teal/red so direction is instantly readable.
            WHY explicit "Day P&L" label (renamed from "Daily"): user audit
            feedback — "Daily" alone is ambiguous (daily what? bar? brief?).
            "Day P&L" matches the standard Bloomberg/IBKR account rail label. */}
        {dailyPnl != null && (
          <span
            className={`flex items-center gap-1 whitespace-nowrap font-mono text-[11px] tabular-nums ${
              dailyPnl >= 0 ? "text-[hsl(var(--positive))]" : "text-[hsl(var(--negative))]"
            }`}
            title="Today's portfolio P&L (live quote-based)"
            aria-label={`Day P&L: ${dailyPnl >= 0 ? "+" : ""}${formatPortfolioValue(Math.abs(dailyPnl))}`}
          >
            <span className="text-muted-foreground">Day P&amp;L</span>
            <span className="inline-block min-w-[3.75rem] text-right">
              {dailyPnl >= 0 ? "+" : "-"}
              {formatPortfolioValue(Math.abs(dailyPnl))}
            </span>
          </span>
        )}

        {/* Total P&L — total mark-to-market vs cost basis.
            WHY "Total P&L" (renamed from "Unrlzd"): user audit feedback —
            "Unrlzd" is a finance-jargon abbreviation; "Total P&L" reads
            correctly to anyone and still fits in the rail at 11px. */}
        {unrealisedPnl != null && (
          <span
            className={`flex items-center gap-1 whitespace-nowrap font-mono text-[11px] tabular-nums ${
              unrealisedPnl >= 0 ? "text-[hsl(var(--positive))]" : "text-[hsl(var(--negative))]"
            }`}
            title="Total unrealised P&L vs cost basis (mark-to-market)"
            aria-label={`Total P&L: ${unrealisedPnl >= 0 ? "+" : ""}${formatPortfolioValue(Math.abs(unrealisedPnl))}`}
          >
            <span className="text-muted-foreground">Total P&amp;L</span>
            <span className="inline-block min-w-[3.75rem] text-right">
              {unrealisedPnl >= 0 ? "+" : "-"}
              {formatPortfolioValue(Math.abs(unrealisedPnl))}
            </span>
          </span>
        )}

        {/* Alert bell — shows unread count badge */}
        <button
          onClick={() => router.push("/alerts")}
          className="relative p-1 text-muted-foreground hover:text-foreground"
          aria-label={`${unreadAlerts} unread alerts`}
        >
          <Bell className="h-4 w-4" />
          {/* WHY destructive badge: critical alerts demand attention.
              WHY text-destructive-foreground not text-white: Bloomberg Dark palette
              prohibits pure #fff. --destructive-foreground resolves to #E0DDD4
              (warm off-white), the correct on-destructive text color in our palette. */}
          {unreadAlerts > 0 && (
            <span className="absolute -right-0.5 -top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-destructive text-[10px] font-bold text-destructive-foreground">
              {unreadAlerts > 9 ? "9+" : unreadAlerts}
            </span>
          )}
        </button>

        {/* User avatar + dropdown */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="rounded-full ring-2 ring-transparent hover:ring-border focus-visible:ring-ring">
              <Avatar className="h-7 w-7">
                <AvatarImage src={user?.avatar_url ?? undefined} alt={user?.name ?? "User"} />
                <AvatarFallback className="text-xs">{getInitials(user?.name)}</AvatarFallback>
              </Avatar>
            </button>
          </DropdownMenuTrigger>

          <DropdownMenuContent align="end" className="w-48">
            {/* User info header */}
            <div className="px-2 py-1.5">
              <p className="text-sm font-medium text-foreground">{user?.name ?? "User"}</p>
              <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
            </div>

            <DropdownMenuSeparator />

            <DropdownMenuItem onClick={() => router.push("/settings")}>
              <User className="mr-2 h-4 w-4" />
              Profile
            </DropdownMenuItem>

            <DropdownMenuItem onClick={() => router.push("/settings")}>
              <Settings className="mr-2 h-4 w-4" />
              Settings
            </DropdownMenuItem>

            <DropdownMenuSeparator />

            <DropdownMenuItem
              onClick={() => void handleLogout()}
              className="text-destructive focus:text-destructive"
            >
              <LogOut className="mr-2 h-4 w-4" />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
