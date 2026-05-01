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
  User,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: React.ElementType;
  badge?: string;
}

const NAV: NavItem[] = [
  { href: "/settings/profile", label: "Profile", icon: User },
  { href: "/settings/notifications", label: "Notifications", icon: Bell },
  { href: "/settings/appearance", label: "Appearance", icon: Palette },
  { href: "/settings/security", label: "Security", icon: ShieldCheck, badge: "soon" },
  { href: "/settings/data", label: "Data & exports", icon: Database, badge: "soon" },
  { href: "/settings/integrations", label: "Integrations", icon: Plug, badge: "soon" },
  { href: "/settings/beta-program", label: "Beta program", icon: Beaker },
];

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
                        ? "bg-primary/10 text-foreground shadow-[inset_2px_0_0_hsl(var(--primary))]"
                        : "text-muted-foreground hover:bg-muted/40 hover:text-foreground",
                    )}
                  >
                    <Icon className="h-3 w-3 shrink-0" aria-hidden />
                    <span className="flex-1 truncate">{item.label}</span>
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
