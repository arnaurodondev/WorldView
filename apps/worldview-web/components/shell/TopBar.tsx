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
 * DATA SOURCE: auth state from AuthContext, market data from IndexStrip (scrolling 16-ticker tape)
 * DESIGN REFERENCE: PRD-0028 §6.5 TopBar; Handoff 2026-05-01 Tier-3 #7
 */

"use client";
// WHY "use client": Uses useAuth (React context), logout() (async action),
// and DropdownMenu (Radix UI state). All require client rendering.

import type { RefObject } from "react";
import { useRouter } from "next/navigation";
import { LogOut, Settings, User, Bell } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/hooks/useAuth";
import { useHotkeyScope } from "@/contexts/HotkeyContext";
import { UtcClock } from "@/components/shell/UtcClock";
// User feedback 2026-06-10 — IndexStrip is now a continuously scrolling ticker
// tape (16 instruments, pause-on-hover, static under prefers-reduced-motion).
// This is the sanctioned NFR-6 exception — see IndexStrip.tsx header.
import { IndexStrip } from "@/components/shell/IndexStrip";
// PRD-0089 W1 §4.3 — PortfolioSwitcher between GlobalSearch and IndexStrip (slot 3/4).
import { PortfolioSwitcher } from "@/components/shell/PortfolioSwitcher";
import { MarketStatusPill } from "@/components/shell/MarketStatusPill";
import { GlobalSearch } from "@/components/shell/GlobalSearch";
// ⌘K hint chip dispatches this event; the CommandPalette (mounted in
// app/(app)/layout.tsx) listens for it. Event-based so TopBar needs no
// open-state prop drilled through the layout (same pattern as
// worldview:open-ai-panel / worldview:open-feedback).
import { OPEN_COMMAND_PALETTE_EVENT } from "@/components/shell/CommandPalette";
import { AskAiButton } from "@/components/shell/AskAiButton";
import { RefreshAllButton } from "@/components/shell/RefreshAllButton";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
// HF-10: portfolio value uses shared compact-currency formatter for consistency.
import { formatCompactCurrency } from "@/lib/format";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
/**
 * formatPortfolioValue — compact portfolio NAV for the TopBar rail.
 *
 * WHY compact: the TopBar has limited horizontal space. $1.2M is scannable;
 * $1,234,567 is not at the rail font size. Returns "—" while null (loading).
 *
 * F-122 fix (PLAN-0048 QA iter-1): the previous implementation rounded
 * sub-million values to whole thousands ($42,484 → "$42K"), which destroyed
 * the last $483 of precision. Bloomberg's account rail keeps two decimals
 * for sub-$1M values because traders care about the actual cents on small
 * accounts. We now show one decimal place in the K-range ("$42.5K") so the
 * value stays compact yet retains a useful significant figure, and use whole
 * dollars (with comma grouping) for sub-$1K values where K-suffix would feel
 * clumsy ("$847" beats "$0.8K").
 */
/**
 * F-QA-09 fix: tolerance for floating-point near-zero P&L. Without a deadband,
 * a portfolio that mathematically nets to $0.00 can render as +$0 (green) or
 * -$0 (red) depending on summation order over many positions. $0.005 is
 * smaller than the smallest displayable cent, so anything inside the band
 * is genuinely "flat" for display purposes.
 */
const PNL_FLAT_EPSILON = 0.005;

/**
 * pnlColorClass — colour the P&L slot according to direction, using a
 * deadband so floating-point dust doesn't paint a flat day red or green.
 */
function pnlColorClass(value: number): string {
  if (value > PNL_FLAT_EPSILON) return "text-[hsl(var(--positive))]";
  if (value < -PNL_FLAT_EPSILON) return "text-[hsl(var(--negative))]";
  // Inside the deadband we treat the move as flat — muted neutral colour.
  return "text-muted-foreground";
}

// HF-10: delegate to the shared compact-currency formatter.
// formatCompactCurrency renders "$1.2M" / "$42.5K" / "$847.00" with locale
// grouping. The hand-built ladder previously ignored thousands separators
// for sub-$1K values and lacked null/NaN handling.
function formatPortfolioValue(value: number | null | undefined): string {
  return formatCompactCurrency(value, "USD", { maxDecimals: 1 });
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
  /**
   * Open the AskAiPanel. Owned by app/(app)/layout.tsx so the panel can render
   * outside the TopBar's overflow context (it is fixed-positioned). Optional
   * because tests / Storybook may render TopBar without the assistant wired up.
   */
  onAskAi?: () => void;
  /** True while the AskAiPanel is currently shown — toggles the button's pressed look. */
  askAiOpen?: boolean;
  /**
   * Ref forwarded to the AskAi trigger button. F-QA-05 fix: the layout uses
   * this ref to restore focus to the trigger when the panel closes (WCAG 2.4.3).
   */
  askAiButtonRef?: RefObject<HTMLButtonElement | null>;
}

export function TopBar({
  unreadAlerts = 0,
  portfolioValue,
  dailyPnl,
  unrealisedPnl,
  onAskAi,
  askAiOpen,
  askAiButtonRef,
}: TopBarProps) {
  const router = useRouter();
  const { user, logout } = useAuth();
  // WHY useQueryClient: on logout we call queryClient.clear() to purge all
  // cached data. Without this, re-logging as a different user would briefly
  // flash the previous user's portfolio / watchlist data (stale cache entries
  // are served immediately on mount before the first refetch completes).
  const queryClient = useQueryClient();
  // WHY useHotkeyScope: logout must also reset the hotkey scope stack back to
  // ["global"] so any "page" or "table" scope pushed during the session doesn't
  // persist into the unauthenticated redirect (C-28 / V22).
  const { resetScopes } = useHotkeyScope();

  const handleLogout = async () => {
    // 1. Clear TanStack cache — prevents stale data flash on re-login.
    queryClient.clear();
    // 2. Reset hotkey scope stack — prevents ghost "page"/"table" scopes after redirect.
    resetScopes();
    await logout();
    // WHY replace: don't leave the protected page in history — back button
    // should not return user to authenticated content after logout
    router.replace("/login");
  };

  return (
    // WHY h-8 (32px): PLAN-0071 Phase 6.5 further reduces to 32px following
    // bloomberg-terminal reference. Minimum feasible: h-7 avatar + 2px top/bottom
    // margin = 32px. PRD-0031 §4.1 originally reduced from 44px to 36px (h-9);
    // Phase 6.5 takes the next step to 32px (h-8) for maximum data-display vertical
    // space recovery while remaining WCAG-compliant (h-7 avatar = 28px touch target +
    // surrounding 4px padding satisfies the 32px minimum for pointer-based devices).
    // WHY border-b border-border: crisp structural edge separating chrome from content.
    //
    // PRD-0089 W1: Layout is [left: logo+search+PortfolioSwitcher] [center flex-1: IndexStrip] [right: clock+pill+rail+AI+bell+avatar].
    // The center flex-1 slot absorbs horizontal slack so left/right clusters stay pinned to their edges.
    // IndexStrip cells priority-drop at narrow viewports so the strip never overflows horizontally.
    <header className="flex h-8 w-full shrink-0 items-center gap-3 border-b border-border bg-background px-3">
      {/* ── Left: Logo + Search ───────────────────────────────────── */}
      {/* WHY shrink-0: the logo + search must never shrink — they're nav anchors.
          Slack absorbed by the IndexStrip center slot (the only flex-1 sibling). */}
      <div className="flex shrink-0 items-center gap-3">
        {/* Wordmark — text for crisp rendering at all DPIs */}
        {/* WHY font-mono font-bold: Bloomberg terminal wordmarks are rendered in a
            monospace fixed-width style — proportional font reads as consumer web app */}
        <button
          onClick={() => router.push("/dashboard")}
          className="font-mono font-bold text-[13px] tracking-tight text-foreground hover:opacity-80"
        >
          Worldview
        </button>

        <GlobalSearch />

        {/* ── ⌘K command-palette hint (Round-1 Command Palette) ────────────
            WHY a visible chip: the palette is keyboard-first, but a purely
            invisible shortcut is undiscoverable — Linear/Raycast/Slack all
            show a muted "⌘K" affordance in their chrome. Clicking it opens
            the palette for mouse users; the label teaches the chord.
            WHY a CustomEvent (not a prop): the palette owns its open state
            and is mounted in the layout, not here — dispatching the event
            avoids threading an opener callback through TopBarProps.
            WHY hard-coded "⌘K" (not formatChordForDisplay): platform
            detection differs between SSR (always non-mac) and the client,
            which would cause a hydration text mismatch. The hard-coded mac
            glyph matches the pre-existing convention (GlobalSearch's old
            placeholder, StatusBar copy). Ctrl+K still works — the listener
            accepts both modifiers. */}
        <button
          type="button"
          onClick={() => window.dispatchEvent(new CustomEvent(OPEN_COMMAND_PALETTE_EVENT))}
          aria-label="Open command palette (Cmd+K or Ctrl+K)"
          title="Open command palette (⌘K / Ctrl+K)"
          className="flex h-5 shrink-0 items-center rounded-[2px] border border-border/50 bg-muted/20 px-1.5 font-mono text-[10px] text-muted-foreground-dim hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          ⌘K
        </button>
      </div>

      {/* ── Slot 3: PortfolioSwitcher ─────────────────────────────────── */}
      {/* WHY shrink-0: the switcher chip has a fixed width ("All Portfolios ▾")
          that must never collapse — if it truncates the user can't read which
          portfolio is active. The IndexStrip to its right absorbs the slack. */}
      <PortfolioSwitcher />

      {/* ── Slot 5: IndexStrip — scrolling ticker tape ──────────────── */}
      {/* WHY flex-1 min-w-0: the tape absorbs all horizontal slack between
          the left cluster (logo+search+switcher) and the right cluster (clock+
          pill+rail+AI+bell+avatar). min-w-0 allows it to shrink below its
          intrinsic width — the tape clips its own moving track internally.
          WHY overflow-hidden: stops any momentary over-width during hydration
          from causing a horizontal scrollbar flash on the TopBar.
          WHY no justify-center (removed with the marquee rewrite): the tape's
          moving track fills the entire slot edge-to-edge by design. */}
      <div className="flex min-w-0 flex-1 overflow-hidden">
        <IndexStrip />
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
                * "$1.2M" / "$42.5K" / "—" → min-w-[3.5rem] (56px)
                * "+$45.6K" with sign      → min-w-[4rem] (64px)
            F-122 follow-up: bumped slot widths after switching the formatter
            from "$42K" to "$42.5K" — the extra char needs a wider lane or
            adjacent labels jump on refetch.
            - All three numeric values use font-mono + tabular-nums so digits
              align column-wise inside their slot.
            WHY text-[11px] (was text-[10px]): user feedback (audit
            2026-04-28) — 10px is too dense; 11px gains breathing room
            without growing the 36px bar height. Labels also bumped to 11px
            for visual parity. */}

        {/* ── Portfolio metrics cluster (PLAN-0050 T-A-1-01) ────────────────
            The three values (PORT / Day P&L / Total P&L) are now visually
            grouped inside a single subtly-tinted box with a thin border and
            internal divider hairlines. Why:
            - Before: three free-floating sibling spans separated only by
              gap-2 made the rail feel like a row of unrelated badges. The
              audit (F-D-008) called this "loose" and noted the eye had to
              re-anchor on each label to follow the relationship between
              NAV, day move, and total P&L.
            - After: one box with bg-muted/20 + border-border/30 reads as
              "your account", and the divider hairlines reinforce that
              these three numbers are calculated from the same source. We
              keep the same per-value min-w slots so digits still don't jump
              on every refetch.

            WHY render the cluster wrapper even when a value is null: it
            stabilises the rail width as positions update from null → known.
            The wrapper renders its known-value children only — the
            container itself is conditional on at least one value existing
            so empty accounts still get a clean rail. */}
        {/* WHY no rounded-[2px] on the portfolio rail box: F1 radius=0 lock (C-04).
            Previously had rounded-[2px] but the W1 plan locks "no explicit border-radius
            except rounded-full for dots/avatars" for all chrome boxes. */}
        {(portfolioValue != null || dailyPnl != null || unrealisedPnl != null) && (
          <div
            className="flex items-center gap-2 border border-border/30 bg-muted/20 px-2 py-0.5"
            aria-label="Portfolio header metrics"
          >
            {/* Portfolio NAV — compact value display matching Bloomberg's account rail convention.
                F-QA-23: standardised on `!= null` (covers both null AND undefined) for
                consistency with the dailyPnl / unrealisedPnl checks below. */}
            {portfolioValue != null && (
              <span
                className="flex items-center gap-1 whitespace-nowrap font-mono text-[11px] tabular-nums text-muted-foreground/80"
                title="Total portfolio value (live quote-based)"
                aria-label={`Portfolio value ${formatPortfolioValue(portfolioValue)}`}
              >
                <span className="text-muted-foreground">PORT</span>
                <span className="inline-block min-w-[3.5rem] text-right text-foreground">
                  {formatPortfolioValue(portfolioValue)}
                </span>
              </span>
            )}

            {/* Divider hairline between PORT and Day P&L — only renders when both
                are present so a single-value cluster doesn't show a stray rule. */}
            {portfolioValue != null && dailyPnl != null && (
              <span aria-hidden="true" className="h-3 w-px bg-border/40" />
            )}

            {/* Day P&L — colored teal/red so direction is instantly readable.
                F-QA-09 fix: pnlColorClass uses a deadband to render a true
                "flat" day as neutral muted colour instead of arbitrarily
                green or red because of floating-point dust. */}
            {dailyPnl != null && (
              <span
                className={`flex items-center gap-1 whitespace-nowrap font-mono text-[11px] tabular-nums ${pnlColorClass(dailyPnl)}`}
                title="Today's portfolio P&L (live quote-based)"
                aria-label={`Day P&L: ${dailyPnl >= 0 ? "+" : ""}${formatPortfolioValue(Math.abs(dailyPnl))}`}
              >
                <span className="text-muted-foreground">Day P&amp;L</span>
                <span className="inline-block min-w-[4rem] text-right">
                  {dailyPnl >= 0 ? "+" : "-"}
                  {formatPortfolioValue(Math.abs(dailyPnl))}
                </span>
              </span>
            )}

            {dailyPnl != null && unrealisedPnl != null && (
              <span aria-hidden="true" className="h-3 w-px bg-border/40" />
            )}

            {/* Total P&L — total mark-to-market vs cost basis.
                F-QA-09 fix: same deadband as Day P&L. */}
            {unrealisedPnl != null && (
              <span
                className={`flex items-center gap-1 whitespace-nowrap font-mono text-[11px] tabular-nums ${pnlColorClass(unrealisedPnl)}`}
                title="Total unrealised P&L vs cost basis (mark-to-market)"
                aria-label={`Total P&L: ${unrealisedPnl >= 0 ? "+" : ""}${formatPortfolioValue(Math.abs(unrealisedPnl))}`}
              >
                <span className="text-muted-foreground">Total P&amp;L</span>
                <span className="inline-block min-w-[4rem] text-right">
                  {unrealisedPnl >= 0 ? "+" : "-"}
                  {formatPortfolioValue(Math.abs(unrealisedPnl))}
                </span>
              </span>
            )}
          </div>
        )}

        {/* ── Ask AI trigger (PLAN-0050 T-A-1-03) ───────────────────────────
            Persistent assistant entry-point. The actual floating panel is
            rendered at app/(app)/layout.tsx — keeping its mount above the
            TopBar means the panel is not constrained by any overflow:hidden
            container in the shell. We forward only the open callback. */}
        {onAskAi && <AskAiButton ref={askAiButtonRef} onOpen={onAskAi} isOpen={askAiOpen} />}

        {/* ── Refresh All (PLAN-0050 T-F-6-06) ───────────────────────────────
            Sits between Ask AI and the bell so the rail reads as
            "tools (AI · refresh) → notifications (bell) → identity (avatar)". */}
        <RefreshAllButton />

        {/* Alert bell — shows unread count badge */}
        <button
          onClick={() => router.push("/alerts")}
          className="relative p-1 text-muted-foreground hover:text-foreground"
          aria-label={`${unreadAlerts} unread alerts`}
        >
          {/* WHY strokeWidth={1.5}: default 2px stroke is too heavy at terminal density — 1.5px matches Bloomberg's icon weight */}
          <Bell className="h-4 w-4" strokeWidth={1.5} />
          {/* WHY destructive badge: critical alerts demand attention.
              WHY text-destructive-foreground not text-white: Bloomberg Dark palette
              prohibits pure #fff. --destructive-foreground resolves to #E0DDD4
              (warm off-white), the correct on-destructive text color in our palette. */}
          {/* WHY font-medium (not font-bold): 700-weight text at 10px renders as a blotchy heavy
              glyph on dark themes due to subpixel antialiasing — 500-weight is the maximum for small badge text */}
          {unreadAlerts > 0 && (
            <span className="absolute -right-0.5 -top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-destructive text-[10px] font-medium text-destructive-foreground">
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
                {/* WHY text-[9px]: the avatar is h-7 (28px) — text-xs (12px) fills nearly the
                    entire circle with no breathing room; 9px matches Bloomberg's compact avatar initials */}
                <AvatarFallback className="text-[9px] font-medium">{getInitials(user?.name)}</AvatarFallback>
              </Avatar>
            </button>
          </DropdownMenuTrigger>

          <DropdownMenuContent align="end" className="w-48">
            {/* User info header */}
            {/* WHY text-[11px]/text-[10px]: dropdown header must match the 10-11px density
                of the terminal chrome — text-sm (14px) is consumer-app scale */}
            <div className="px-2 py-1.5">
              <p className="text-[11px] font-medium text-foreground">{user?.name ?? "User"}</p>
              <p className="truncate text-[10px] text-muted-foreground">{user?.email}</p>
            </div>

            <DropdownMenuSeparator />

            {/* WHY strokeWidth={1.5} on all dropdown icons: default 2px stroke is too heavy
                at terminal density — 1.5px matches Bloomberg's icon weight */}
            <DropdownMenuItem onClick={() => router.push("/settings")}>
              <User className="mr-2 h-4 w-4" strokeWidth={1.5} />
              Profile
            </DropdownMenuItem>

            <DropdownMenuItem onClick={() => router.push("/settings")}>
              <Settings className="mr-2 h-4 w-4" strokeWidth={1.5} />
              Settings
            </DropdownMenuItem>

            <DropdownMenuSeparator />

            <DropdownMenuItem
              onClick={() => void handleLogout()}
              className="text-destructive focus:text-destructive"
            >
              <LogOut className="mr-2 h-4 w-4" strokeWidth={1.5} />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
