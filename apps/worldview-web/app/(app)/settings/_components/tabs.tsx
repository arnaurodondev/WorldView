/**
 * app/(app)/settings/_components/tabs.tsx — extracted tab components.
 *
 * PLAN-0059 I-3: the legacy /settings page bundled three tabs in one route.
 * Splitting into nested routes (`/settings/profile`, `/settings/notifications`,
 * `/settings/appearance`) gives URL persistence + browser-back semantics.
 * The tab BODIES (ProfileTab / NotificationsTab / AppearanceTab) are
 * preserved verbatim from the original page.tsx to keep behaviour identical
 * — only the surrounding routing changes.
 *
 * `_components/` is a Next.js convention for non-route helper folders:
 * the leading underscore prevents the directory from becoming a URL segment.
 */

"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Separator } from "@/components/ui/separator";
import { useNewsLinkTarget } from "@/hooks/useNewsLinkTarget";

// ── Helpers ────────────────────────────────────────────────────────────────

export function getInitials(name: string | null): string {
  if (!name) return "U";
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join("");
}

// ── Notification preference rows (placeholders pending S10 prefs API) ──────

const NOTIFICATION_TYPES = [
  {
    id: "notif-price-alert",
    label: "Price alert triggers",
    description: "When an instrument crosses a threshold you set",
    defaultEnabled: true,
  },
  {
    id: "notif-news-impact",
    label: "High-impact news",
    description: "Articles scoring above the routing-tier DEEP threshold",
    defaultEnabled: true,
  },
  {
    id: "notif-watchlist-mover",
    label: "Watchlist movers",
    description: "Daily roll-up of biggest movers in your watchlists",
    defaultEnabled: false,
  },
  {
    id: "notif-contradiction",
    label: "AI contradiction detections",
    description: "When the knowledge graph flags conflicting claims",
    defaultEnabled: false,
  },
] as const;

// ── ProfileTab ──────────────────────────────────────────────────────────────

interface ProfileTabProps {
  user: {
    user_id: string;
    tenant_id: string;
    email: string;
    name: string | null;
    avatar_url: string | null;
  } | null;
}

export function ProfileTab({ user }: ProfileTabProps) {
  return (
    <Card className="border-border/60 bg-card">
      <CardHeader className="pb-3">
        <CardTitle className="text-[14px] font-medium text-foreground">
          Profile information
        </CardTitle>
        <CardDescription className="text-xs">
          Your account details are managed via the authentication provider.
          Contact support to change your name or email.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="flex items-center gap-4">
          <Avatar className="h-14 w-14">
            <AvatarImage
              src={user?.avatar_url ?? undefined}
              alt={user?.name ?? "User avatar"}
            />
            <AvatarFallback className="bg-primary/20 text-[16px] font-medium text-primary">
              {getInitials(user?.name ?? null)}
            </AvatarFallback>
          </Avatar>
          <div>
            <p className="text-[14px] font-medium text-foreground">
              {user?.name ?? "—"}
            </p>
            <p className="text-xs text-muted-foreground">{user?.email ?? "—"}</p>
          </div>
        </div>

        <Separator className="bg-border/40" />

        <dl className="grid grid-cols-[140px_1fr] gap-x-4 gap-y-2 text-xs">
          <dt className="text-muted-foreground">Name</dt>
          <dd className="text-foreground">{user?.name ?? "—"}</dd>
          <dt className="text-muted-foreground">Email</dt>
          <dd className="text-foreground">{user?.email ?? "—"}</dd>
          <dt className="text-muted-foreground">User ID</dt>
          <dd className="font-mono text-[11px] tabular-nums text-muted-foreground">
            {user?.user_id ?? "—"}
          </dd>
          <dt className="text-muted-foreground">Tenant ID</dt>
          <dd className="font-mono text-[11px] tabular-nums text-muted-foreground">
            {user?.tenant_id ?? "—"}
          </dd>
        </dl>

        <p className="rounded-[2px] bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          Profile fields are read-only in the terminal. To update your name,
          email, or avatar, visit the account settings in the authentication portal.
        </p>
      </CardContent>
    </Card>
  );
}

// ── NotificationsTab ────────────────────────────────────────────────────────

export function NotificationsTab() {
  return (
    <Card className="border-border/60 bg-card">
      <CardHeader className="pb-3">
        <CardTitle className="text-[14px] font-medium text-foreground">
          Notification preferences
        </CardTitle>
        <CardDescription className="text-xs">
          Choose which events trigger notifications. Preferences will be saved
          when the backend notification API is connected.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div
          role="note"
          className="rounded-[2px] border border-warning/40 bg-warning/5 px-3 py-2 text-xs"
        >
          <p className="font-medium text-warning/90">Coming soon</p>
          <p className="mt-0.5 text-warning/80">
            Notification delivery is under development. Toggles below are visual
            placeholders — your selections will not be saved or sent until the
            preference API ships.
          </p>
        </div>

        {NOTIFICATION_TYPES.map((notif, index) => (
          <div key={notif.id}>
            <div className="flex items-center justify-between gap-4">
              <div className="space-y-0.5">
                <Label
                  htmlFor={notif.id}
                  className="cursor-pointer text-[14px] font-medium text-foreground"
                >
                  {notif.label}
                </Label>
                <p className="text-xs text-muted-foreground">
                  {notif.description}
                </p>
              </div>
              <Switch
                id={notif.id}
                defaultChecked={notif.defaultEnabled}
                aria-label={`Toggle ${notif.label}`}
              />
            </div>
            {index < NOTIFICATION_TYPES.length - 1 && (
              <Separator className="mt-4 bg-border/40" />
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

// ── AppearanceTab ───────────────────────────────────────────────────────────

export function AppearanceTab() {
  const [newsTarget, setNewsTarget] = useNewsLinkTarget();

  return (
    <div className="space-y-4">
      <Card className="border-border/60 bg-card">
        <CardHeader className="pb-3">
          <CardTitle className="text-[14px] font-medium text-foreground">Theme</CardTitle>
          <CardDescription className="text-xs">
            Display mode and color scheme settings
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between gap-4">
            <div className="space-y-0.5">
              <Label className="text-[14px] font-medium text-foreground">Dark mode</Label>
              <p className="text-xs text-muted-foreground">
                Permanently enabled — Worldview is a finance terminal designed
                for extended dark-environment sessions.
              </p>
            </div>
            <Switch checked disabled aria-label="Dark mode permanently enabled" />
          </div>

          <Separator className="bg-border/40" />

          <div className="space-y-2 rounded-[2px] bg-muted/40 px-3 py-3">
            <p className="text-xs font-medium text-foreground">
              Why permanently dark?
            </p>
            <ul className="list-inside list-disc space-y-1 text-xs text-muted-foreground">
              <li>
                Terminal-grade near-black (#09090B) background is calibrated
                for low-light conditions
              </li>
              <li>Dark backgrounds reduce eye strain during extended sessions</li>
              <li>
                Supporting both themes doubles CSS-token complexity with no
                measurable user benefit for this audience
              </li>
            </ul>
          </div>
        </CardContent>
      </Card>

      <Card className="border-border/60 bg-card">
        <CardHeader className="pb-3">
          <CardTitle className="text-[14px] font-medium text-foreground">
            Reading preferences
          </CardTitle>
          <CardDescription className="text-xs">
            How news article links open from dashboard widgets and instrument pages.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between gap-4">
            <div className="space-y-0.5">
              <Label
                htmlFor="news-link-target"
                className="text-[14px] font-medium text-foreground"
              >
                Open news in a new tab
              </Label>
              <p className="text-xs text-muted-foreground">
                When enabled, clicking a news article opens it in a new tab.
              </p>
            </div>
            <Switch
              id="news-link-target"
              checked={newsTarget === "new-tab"}
              onCheckedChange={(c) => setNewsTarget(c ? "new-tab" : "same-tab")}
              aria-label="Open news in a new tab"
            />
          </div>
        </CardContent>
      </Card>

      <Card className="border-border/60 bg-card">
        <CardHeader className="pb-3">
          <CardTitle className="text-[14px] font-medium text-foreground">
            Color palette
          </CardTitle>
          <CardDescription className="text-xs">
            Terminal-grade dark palette — copy hex values for use in external tools.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-4">
            {[
              { name: "Background", hex: "#09090B", cssVar: "--background", usage: "Page bg" },
              { name: "Primary", hex: "#FFD60A", cssVar: "--primary", usage: "CTAs, links" },
              { name: "Positive", hex: "#00D26A", cssVar: "--positive", usage: "Price up / gain" },
              { name: "Negative", hex: "#FF3B5C", cssVar: "--negative", usage: "Price down / loss" },
              { name: "Card", hex: "#111113", cssVar: "--card", usage: "Panel bg" },
              { name: "Muted", hex: "#18181B", cssVar: "--muted", usage: "Elevated surface" },
              { name: "Warning", hex: "#F59E0B", cssVar: "--warning", usage: "Alerts / beta" },
              { name: "Text", hex: "#E4E4E7", cssVar: "--foreground", usage: "Primary text" },
            ].map((swatch) => (
              <ColorSwatch key={swatch.cssVar} {...swatch} />
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ── ColorSwatch ─────────────────────────────────────────────────────────────

interface ColorSwatchProps {
  name: string;
  hex: string;
  cssVar: string;
  usage: string;
}

function ColorSwatch({ name, hex, cssVar, usage }: ColorSwatchProps) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(hex);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      // Silent fallback in non-HTTPS contexts.
    }
  }

  return (
    <button
      type="button"
      onClick={() => void handleCopy()}
      className="group relative space-y-1.5 rounded-[2px] p-1 text-left hover:bg-muted/40 focus:outline-none focus:ring-1 focus:ring-primary"
      aria-label={`Copy ${name} hex value ${hex} to clipboard`}
      title={`Click to copy ${hex}`}
    >
      <div
        className="h-8 w-full rounded-[2px] border border-border/60"
        style={{ backgroundColor: hex }}
        aria-hidden
      />
      {copied ? (
        <span
          aria-live="polite"
          className="absolute right-1 top-1 flex items-center gap-0.5 rounded-[2px] bg-positive/15 px-1 py-0.5 font-mono text-[9px] uppercase tracking-[0.06em] text-positive"
        >
          <Check className="h-2.5 w-2.5" aria-hidden />
          Copied
        </span>
      ) : (
        <Copy
          className="absolute right-1 top-1 h-3 w-3 text-muted-foreground/40 opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100"
          aria-hidden
        />
      )}
      <p className="text-xs font-medium text-foreground">{name}</p>
      <p className="font-mono text-[10px] text-muted-foreground">{hex}</p>
      <p className="text-[10px] text-muted-foreground/60">{usage}</p>
      <span className="sr-only">{cssVar}</span>
    </button>
  );
}
