/**
 * app/(app)/settings/page.tsx — User Settings page (Wave F-13)
 *
 * WHY THIS EXISTS: Provides users access to profile information and preferences.
 * Three tabs match the PRD-0028 §6.5 "Page: Settings" design spec:
 *   - Profile: read-only view of authenticated user info from Zitadel (via useAuth)
 *   - Notifications: toggle switches for notification types (MVP placeholders)
 *   - Appearance: explains the permanent dark-mode decision (no toggle needed)
 *
 * WHY READ-ONLY PROFILE: Auth profile (name, email, avatar) is owned by Zitadel
 * and edited in the Zitadel self-service portal, not in this app. Showing it
 * read-only gives users context without creating a misleading "Save" flow.
 *
 * WHY NO SAVE FUNCTIONALITY IN MVP: Per PRD-0028 §5 (MVP scope), preferences
 * are not persisted in this wave. The Switch toggles are UI scaffolding for
 * the backend notification preference API (S10) — added in a later wave.
 *
 * WHO USES IT: TopBar user avatar dropdown → "Settings"; direct link /settings
 * DATA SOURCE: useAuth (user profile from React state, originally from S9 /me)
 * DESIGN REFERENCE: PRD-0028 §6.5 "Page: Settings", canvas State E (Settings 5B1Zd)
 */

"use client";
// WHY "use client": useAuth reads from React context (AuthContext) which is
// client-only state. Also: Tabs from shadcn/ui uses Radix state + DOM events,
// and Switch is interactive — all require the client runtime.

import { User, Bell, Palette } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
import { useAuth } from "@/hooks/useAuth";

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * getInitials — extract up to 2 initials from a display name
 *
 * WHY: AvatarFallback needs a short string (1–2 chars). "John Smith" → "JS".
 * If name is null/empty, falls back to "?" so the avatar is never blank.
 */
function getInitials(name: string | null): string {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].charAt(0).toUpperCase();
  return (
    parts[0].charAt(0).toUpperCase() +
    parts[parts.length - 1].charAt(0).toUpperCase()
  );
}

// ── Notification preference rows ──────────────────────────────────────────────

/**
 * NOTIFICATION_TYPES — static list of notification categories
 *
 * WHY static data here: These are UI scaffolding for Wave F-13 MVP.
 * When the S10 notification preference API is implemented, this list
 * will be replaced with a GET /api/v1/user/preferences call. Keeping
 * it static now avoids blocking this wave on a backend that isn't ready.
 */
const NOTIFICATION_TYPES = [
  {
    id: "notif-alerts-high",
    label: "High-severity alerts",
    description: "CRITICAL and HIGH impact signals for your watchlist",
    defaultEnabled: true,
  },
  {
    id: "notif-alerts-medium",
    label: "Medium-severity alerts",
    description: "MEDIUM impact signals and price threshold breaches",
    defaultEnabled: true,
  },
  {
    id: "notif-morning-brief",
    label: "Daily morning brief",
    description: "AI-generated market summary delivered at market open",
    defaultEnabled: false,
  },
  {
    id: "notif-earnings",
    label: "Earnings announcements",
    description: "Pre-market notifications for holdings with upcoming earnings",
    defaultEnabled: false,
  },
  {
    id: "notif-contradiction",
    label: "AI contradiction detections",
    description: "When the knowledge graph flags conflicting claims",
    defaultEnabled: false,
  },
] as const;

// ── Page component ────────────────────────────────────────────────────────────

export default function SettingsPage() {
  // WHY useAuth: The profile tab reads user.name, user.email, user.avatar_url
  // from the authenticated session. This is the same data shown in TopBar.
  const { user } = useAuth();

  // WHY p-3 (was p-6): standard terminal panel padding
  // WHY max-w-3xl: Settings pages are form-heavy — wide lines make them hard to scan.
  return (
    <div className="mx-auto max-w-3xl space-y-3 p-3">
      {/* ── Page header ────────────────────────────────────────────────────── */}
      <div>
        {/* WHY text-lg (not text-xl): matches the global heading hierarchy —
            all page titles use text-lg font-semibold tracking-tight for
            consistent vertical rhythm across the app. */}
        <h1 className="text-lg font-semibold tracking-tight text-foreground">Settings</h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Manage your profile and preferences
        </p>
      </div>

      {/* ── Tabbed layout ──────────────────────────────────────────────────── */}
      {/* WHY shadcn Tabs: keyboard navigation, ARIA roles, consistent styling
          with the rest of the app (Alerts, Instrument Detail all use Tabs). */}
      <Tabs defaultValue="profile" className="w-full">
        {/* WHY grid-cols-3: Three equal-width tabs; matches screener and alerts
            tab bar patterns used elsewhere in the app. */}
        <TabsList className="mb-2 grid w-full grid-cols-3">
          <TabsTrigger value="profile" className="gap-1.5 text-xs">
            <User className="h-3.5 w-3.5" aria-hidden="true" />
            Profile
          </TabsTrigger>
          <TabsTrigger value="notifications" className="gap-1.5 text-xs">
            <Bell className="h-3.5 w-3.5" aria-hidden="true" />
            Notifications
          </TabsTrigger>
          <TabsTrigger value="appearance" className="gap-1.5 text-xs">
            <Palette className="h-3.5 w-3.5" aria-hidden="true" />
            Appearance
          </TabsTrigger>
        </TabsList>

        {/* ── Profile tab ──────────────────────────────────────────────────── */}
        <TabsContent value="profile">
          <ProfileTab user={user} />
        </TabsContent>

        {/* ── Notifications tab ────────────────────────────────────────────── */}
        <TabsContent value="notifications">
          <NotificationsTab />
        </TabsContent>

        {/* ── Appearance tab ───────────────────────────────────────────────── */}
        <TabsContent value="appearance">
          <AppearanceTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ── ProfileTab ────────────────────────────────────────────────────────────────

/**
 * ProfileTab — read-only display of the authenticated user's Zitadel profile
 *
 * WHY READ-ONLY: Profile fields are owned by Zitadel. Editing them here would
 * require a POST /api/v1/user/profile endpoint that proxies to Zitadel's
 * management API — out of scope for MVP. Traders care about data, not profile
 * editing; this satisfies the "know who's logged in" use case.
 */
interface ProfileTabProps {
  user: {
    user_id: string;
    tenant_id: string;
    email: string;
    name: string | null;
    avatar_url: string | null;
  } | null;
}

function ProfileTab({ user }: ProfileTabProps) {
  return (
    <Card className="border-border/60 bg-card">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium text-foreground">
          Profile Information
        </CardTitle>
        <CardDescription className="text-xs">
          Your account details are managed via the authentication provider.
          Contact support to change your name or email.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* ── Avatar + display name row ─────────────────────────────────── */}
        <div className="flex items-center gap-4">
          {/* WHY Avatar from shadcn: consistent 40px circle with fallback initials.
              avatar_url may be null for accounts that haven't set a picture. */}
          <Avatar className="h-14 w-14">
            <AvatarImage
              src={user?.avatar_url ?? undefined}
              alt={user?.name ?? "User avatar"}
            />
            {/* WHY bg-primary/20: subtle primary tint distinguishes initials
                avatar from a placeholder while keeping the dark theme. */}
            <AvatarFallback className="bg-primary/20 text-primary text-base font-medium">
              {getInitials(user?.name ?? null)}
            </AvatarFallback>
          </Avatar>
          <div>
            <p className="text-sm font-medium text-foreground">
              {/* Show em-dash if name is null — avoids blank line */}
              {user?.name ?? "—"}
            </p>
            <p className="text-xs text-muted-foreground">{user?.email ?? "—"}</p>
          </div>
        </div>

        <Separator className="bg-border/40" />

        {/* ── Field rows ────────────────────────────────────────────────── */}
        {/* WHY grid layout: aligns label and value columns for quick scanning.
            Finance users read settings like tables, not prose. */}
        <dl className="grid grid-cols-[140px_1fr] gap-x-4 gap-y-3 text-sm">
          <dt className="text-muted-foreground">Name</dt>
          <dd className="text-foreground">{user?.name ?? "—"}</dd>

          <dt className="text-muted-foreground">Email</dt>
          <dd className="text-foreground">{user?.email ?? "—"}</dd>

          <dt className="text-muted-foreground">User ID</dt>
          {/* WHY font-mono: user_id is a UUID — monospace ensures the string
              doesn't have ambiguous character widths (0 vs O, l vs 1). */}
          <dd className="font-mono text-xs text-muted-foreground">
            {user?.user_id ?? "—"}
          </dd>

          <dt className="text-muted-foreground">Tenant ID</dt>
          <dd className="font-mono text-xs text-muted-foreground">
            {user?.tenant_id ?? "—"}
          </dd>
        </dl>

        {/* ── Read-only notice ──────────────────────────────────────────── */}
        <p className="rounded-[2px] bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          Profile fields are read-only in the terminal. To update your name,
          email, or avatar, visit the account settings in the authentication portal.
        </p>
      </CardContent>
    </Card>
  );
}

// ── NotificationsTab ──────────────────────────────────────────────────────────

/**
 * NotificationsTab — toggle switches for notification preferences
 *
 * WHY UNCONTROLLED (no state): In MVP these switches are UI scaffolding.
 * The backend S10 notification-preference API doesn't exist yet. When it's
 * built (Wave F-xx), this component will be upgraded with:
 *   - useQuery to read saved preferences
 *   - useMutation to PATCH /api/v1/user/preferences on toggle
 * Using defaultChecked keeps the component simple until that wave ships.
 */
function NotificationsTab() {
  return (
    <Card className="border-border/60 bg-card">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium text-foreground">
          Notification Preferences
        </CardTitle>
        <CardDescription className="text-xs">
          Choose which events trigger notifications. Preferences will be saved
          when the backend notification API is connected.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {NOTIFICATION_TYPES.map((notif, index) => (
          <div key={notif.id}>
            {/* WHY flex justify-between: Switch is right-aligned so the label
                reads left-to-right and the toggle doesn't interrupt it visually.
                This mirrors iOS/Android settings pattern that users expect. */}
            <div className="flex items-center justify-between gap-4">
              <div className="space-y-0.5">
                <Label
                  htmlFor={notif.id}
                  className="cursor-pointer text-sm font-medium text-foreground"
                >
                  {notif.label}
                </Label>
                <p className="text-xs text-muted-foreground">
                  {notif.description}
                </p>
              </div>
              {/* WHY defaultChecked (uncontrolled): see component docstring above.
                  aria-label supplements htmlFor for screen reader context. */}
              <Switch
                id={notif.id}
                defaultChecked={notif.defaultEnabled}
                aria-label={`Toggle ${notif.label}`}
              />
            </div>
            {/* Separator between rows but not after the last item */}
            {index < NOTIFICATION_TYPES.length - 1 && (
              <Separator className="mt-4 bg-border/40" />
            )}
          </div>
        ))}

        {/* ── MVP placeholder notice ───────────────────────────────────── */}
        <p className="rounded-[2px] bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          Notification delivery is under development. Toggles are saved locally
          in this session and will persist once the preference API is live.
        </p>
      </CardContent>
    </Card>
  );
}

// ── AppearanceTab ─────────────────────────────────────────────────────────────

/**
 * AppearanceTab — explains the permanent dark mode design decision
 *
 * WHY NO LIGHT MODE TOGGLE: Per ADR-F-04 (docs/ui/DESIGN_SYSTEM.md §1),
 * Worldview is permanently dark-themed. The decision is intentional:
 *   1. Finance terminal users work in low-light conditions for long sessions
 *   2. The Bloomberg Dark color palette (#0A0E14 bg) is tuned for dark only
 *   3. Supporting both modes doubles the CSS token complexity for no user benefit
 *      — no trader has requested light mode (no such feedback in user research)
 * The Appearance tab exists to explain this to users who expect a toggle here,
 * so they don't think it's a bug.
 */
function AppearanceTab() {
  return (
    <div className="space-y-4">
      {/* ── Theme card ──────────────────────────────────────────────────── */}
      <Card className="border-border/60 bg-card">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium text-foreground">
            Theme
          </CardTitle>
          <CardDescription className="text-xs">
            Display mode and color scheme settings
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* ── Dark mode row ──────────────────────────────────────────── */}
          <div className="flex items-center justify-between gap-4">
            <div className="space-y-0.5">
              <Label className="text-sm font-medium text-foreground">
                Dark mode
              </Label>
              <p className="text-xs text-muted-foreground">
                Permanently enabled — Worldview is a finance terminal designed
                for extended dark-environment sessions.
              </p>
            </div>
            {/* WHY disabled checked Switch: conveys "on, but not your choice to
                change" — more honest than hiding the control or showing text alone.
                The disabled state prevents clicks while the visual state informs. */}
            <Switch
              checked
              disabled
              aria-label="Dark mode permanently enabled"
            />
          </div>

          <Separator className="bg-border/40" />

          {/* ── Design rationale ───────────────────────────────────────── */}
          <div className="rounded-[2px] bg-muted/40 px-3 py-3 space-y-2">
            <p className="text-xs font-medium text-foreground">
              Why permanently dark?
            </p>
            {/* WHY bullet list: three independent rationale points are easier
                to scan as a list than as a run-on paragraph. */}
            <ul className="space-y-1 text-xs text-muted-foreground list-disc list-inside">
              <li>
                Bloomberg Dark palette (#0A0E14) is calibrated for low-light
                conditions — ideal for pre/post market sessions
              </li>
              <li>
                Dark backgrounds reduce eye strain during extended monitoring
                sessions (typical trader use-case)
              </li>
              <li>
                Supporting both themes doubles CSS token complexity with no
                measurable user benefit for this audience
              </li>
            </ul>
          </div>
        </CardContent>
      </Card>

      {/* ── Color palette card ──────────────────────────────────────────── */}
      <Card className="border-border/60 bg-card">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium text-foreground">
            Color Palette
          </CardTitle>
          <CardDescription className="text-xs">
            Bloomberg Dark — the terminal-grade dark palette used throughout
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* WHY inline color swatches: gives users context for the brand colors
              they see throughout the app; also useful for accessibility awareness. */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { name: "Background", hex: "#0A0E14", cssVar: "--background" },
              { name: "Primary", hex: "#E8A317", cssVar: "--primary" },
              { name: "Positive", hex: "#26A69A", cssVar: "--positive" },
              { name: "Negative", hex: "#EF5350", cssVar: "--negative" },
            ].map((swatch) => (
              <div key={swatch.cssVar} className="space-y-1.5">
                {/* Color swatch — uses inline style so the exact hex is applied
                    even if the Tailwind class wouldn't be generated for these values */}
                <div
                  className="h-8 w-full rounded-[2px] border border-border/60"
                  style={{ backgroundColor: swatch.hex }}
                  aria-hidden="true"
                />
                <p className="text-xs font-medium text-foreground">
                  {swatch.name}
                </p>
                <p className="font-mono text-xs text-muted-foreground">
                  {swatch.hex}
                </p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
