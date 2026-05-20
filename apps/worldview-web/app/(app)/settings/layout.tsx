/**
 * app/(app)/settings/layout.tsx — Settings nested-route layout
 *
 * PLAN-0059 I-3: replaces the single-page tabset with a sidebar-nav layout
 * spanning multiple nested routes (`/settings/profile`,
 * `/settings/notifications`, `/settings/appearance`, `/settings/security`,
 * `/settings/data`, `/settings/integrations`, `/settings/beta-program`).
 *
 * Each route navigates via the sidebar; the layout owns the nav so the
 * sidebar persists during transitions (no flash on each navigation).
 */

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bell,
  Beaker,
  Database,
  Palette,
  Plug,
  ShieldCheck,
  Sliders,
  User,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: React.ElementType;
  badge?: string;
}

// ── Nav item list ────────────────────────────────────────────────────────────
//
// WHY conditional security item: when NEXT_PUBLIC_ENABLE_SECURITY is not
// "true", the /settings/security page returns notFound(). Keeping the nav
// item would render a clickable link to a 404 page — confusing. We filter
// it out at the nav level so no blank gap appears in the sidebar (the flex-col
// layout naturally reflows the remaining items). FR-6.4 / FR-6.8.
//
// WHY filter (not ternary inside JSX): the filter keeps the nav array uniform
// and avoids conditional rendering complexity inside the map below. TypeScript
// keeps the array typed as NavItem[] so we get full type checking.
const ALL_NAV: NavItem[] = [
  { href: "/settings/profile", label: "Profile", icon: User },
  { href: "/settings/preferences", label: "Preferences", icon: Sliders },
  { href: "/settings/notifications", label: "Notifications", icon: Bell },
  { href: "/settings/appearance", label: "Appearance", icon: Palette },
  // PLAN-0087 F-BB-005: dropped the "soon" badge — these three sub-pages
  // ship substantive (mocked-state) UI as of the beta-readiness pass.
  // FR-6.4: Security is hidden when NEXT_PUBLIC_ENABLE_SECURITY !== "true".
  { href: "/settings/security", label: "Security", icon: ShieldCheck },
  { href: "/settings/data", label: "Data & exports", icon: Database },
  { href: "/settings/integrations", label: "Integrations", icon: Plug },
  { href: "/settings/beta-program", label: "Beta program", icon: Beaker },
];

// WHY runtime filter: NEXT_PUBLIC_* env vars are baked into the bundle at
// build time. The filter is cheap (≤8 items) and keeps the nav reactive to
// whatever was set at build time without needing a server component.
const NAV: NavItem[] = ALL_NAV.filter((item) => {
  if (item.href === "/settings/security") {
    return process.env.NEXT_PUBLIC_ENABLE_SECURITY === "true";
  }
  return true;
});

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Page header */}
      <div className="flex h-7 shrink-0 items-center border-b border-border px-3">
        <h1 className="font-mono text-[11px] uppercase tracking-[0.08em] text-foreground">
          Settings
        </h1>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <nav
          aria-label="Settings sections"
          className="w-48 shrink-0 border-r border-border bg-card/30 p-1 overflow-y-auto"
        >
          <ul className="space-y-px">
            {NAV.map((item) => {
              const active = pathname === item.href || pathname?.startsWith(item.href + "/");
              const Icon = item.icon;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex h-7 items-center gap-2 rounded-[2px] px-2 text-[11px] transition-colors",
                      active
                        ? // QA-iter1: combine inset shadow accent (rendered in
                          // normal mode) with a left border (preserved under
                          // forced-colors / Windows High Contrast where
                          // bg-primary/10 + box-shadow are stripped). Either
                          // mode renders a visible left-edge marker.
                          "bg-primary/10 text-foreground shadow-[inset_2px_0_0_hsl(var(--primary))] border-l-2 border-l-primary -ml-px"
                        : "border-l-2 border-l-transparent -ml-px text-muted-foreground hover:bg-muted/40 hover:text-foreground",
                    )}
                  >
                    <Icon className="h-3 w-3 shrink-0" aria-hidden strokeWidth={1.5} />
                    {/* WHY max-w-[140px] truncate: long labels like "Data & exports"
                        must not overflow the 192px (w-48) sidebar or push the badge
                        off-screen. 140px leaves 4px padding on each side after the
                        12px icon + 8px gap. FR-6.8. */}
                    <span className="flex-1 truncate max-w-[140px]">{item.label}</span>
                    {item.badge && (
                      <span className="shrink-0 rounded-[2px] bg-muted/60 px-1 font-mono text-[9px] uppercase tracking-wider text-muted-foreground">
                        {item.badge}
                      </span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        {/* Content */}
        <main className="flex-1 overflow-auto">
          <div className="mx-auto max-w-3xl p-3">{children}</div>
        </main>
      </div>
    </div>
  );
}
