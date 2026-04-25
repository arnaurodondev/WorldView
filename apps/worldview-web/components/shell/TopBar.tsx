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
}

export function TopBar({ unreadAlerts = 0 }: TopBarProps) {
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
    <header className="flex h-9 w-full shrink-0 items-center justify-between border-b border-border bg-background px-3">
      {/* ── Left: Logo + Search ───────────────────────────────────── */}
      {/* WHY gap-3 (not gap-4): tighter spacing at reduced bar height */}
      <div className="flex items-center gap-3">
        {/* Wordmark — text for crisp rendering at all DPIs */}
        <button
          onClick={() => router.push("/dashboard")}
          className="font-semibold text-foreground hover:opacity-80"
        >
          Worldview
        </button>

        <GlobalSearch />
      </div>

      {/* ── Center: Market data ───────────────────────────────────── */}
      {/* WHY absolute center: prevents the market data from shifting
          when the left/right sections change width */}
      <div className="absolute left-1/2 -translate-x-1/2">
        <IndexTicker />
      </div>

      {/* ── Right: Tools + User ──────────────────────────────────── */}
      {/* WHY gap-2 (not gap-3): compact at 36px bar height */}
      <div className="flex items-center gap-2">
        <UtcClock />

        <MarketStatusPill />

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
