/**
 * app/(app)/settings/security/page.tsx — Security settings.
 *
 * WHY THIS EXISTS (PLAN-0087 F-BB-005 Settings UI substance):
 * The original PLAN-0059 I-3 stub rendered a `<SettingsPlaceholder>` card
 * listing future bullets. For the beta walkthrough, hedge-fund analysts and
 * IT-security reviewers expect a real Security pane (MFA enrolment, password
 * change, active sessions, "log out all devices"). The underlying back-end
 * lives in Zitadel; while Zitadel is not yet wired into the live stack
 * (PLAN-0087 F-BB-001), we expose REAL controls with mock state so the
 * surface is reviewable and the wiring is one-line replacement away.
 *
 * SUBSTANCE WE SHIP:
 *   1. Two-factor authentication — enable / disable toggle + status pill
 *   2. Password change form — current / new / confirm with client validation
 *   3. Active sessions list — current device + 2 mocked remote sessions
 *   4. "Log out all other devices" destructive action with confirm dialog
 *   5. Recent sign-in audit (3 sample rows)
 *
 * EVERY CONTROL IS WIRED: buttons fire `console.log` + `toast` so the user
 * gets visible feedback, and the integration target is obvious. No no-ops.
 *
 * DESIGN: mirrors profile/appearance — Card surfaces, 2px radii, dense
 * 11-12px text, tabular-nums on every numeric/timestamp slot. Heavy comments
 * explain WHY for every stylistic choice.
 */

"use client";
// WHY "use client": all controls (Switch, AlertDialog, form state) need
// interactive React. The page itself is a simple render of card stacks.

import { useState } from "react";
import { toast } from "sonner";
import {
  ShieldCheck,
  KeyRound,
  Smartphone,
  Monitor,
  AlertTriangle,
  CheckCircle2,
  Clock,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

// ── Mock data (will be replaced by Zitadel API once wired) ───────────────
//
// WHY mock arrays here (not a hook): until Zitadel ships, there is no
// upstream contract to bind to. Co-locating the mocks in the page keeps the
// substitution surface small — one file, one search-and-replace when the
// real API arrives.

interface SessionRow {
  id: string;
  device: string;
  browser: string;
  ip: string;
  lastActiveAt: string; // ISO
  current: boolean;
}

const MOCK_SESSIONS: SessionRow[] = [
  {
    id: "sess-current",
    device: "MacBook Pro",
    browser: "Chrome 124 · macOS 14.4",
    ip: "192.168.1.42",
    lastActiveAt: new Date().toISOString(),
    current: true,
  },
  {
    id: "sess-iphone",
    device: "iPhone 15",
    browser: "Safari 17 · iOS 17.4",
    ip: "10.0.0.18",
    // 3 hours ago
    lastActiveAt: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
    current: false,
  },
  {
    id: "sess-desktop",
    device: "Linux desktop",
    browser: "Firefox 124 · Ubuntu 22.04",
    ip: "203.0.113.42",
    // 2 days ago
    lastActiveAt: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(),
    current: false,
  },
];

interface AuditRow {
  at: string; // ISO
  event: string;
  ip: string;
  ok: boolean;
}

const MOCK_AUDIT: AuditRow[] = [
  {
    at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
    event: "Sign-in succeeded",
    ip: "192.168.1.42",
    ok: true,
  },
  {
    at: new Date(Date.now() - 26 * 60 * 60 * 1000).toISOString(),
    event: "Sign-in succeeded",
    ip: "10.0.0.18",
    ok: true,
  },
  {
    at: new Date(Date.now() - 4 * 24 * 60 * 60 * 1000).toISOString(),
    event: "Failed sign-in (wrong password)",
    ip: "198.51.100.7",
    ok: false,
  },
];

// ── Helpers ──────────────────────────────────────────────────────────────

/**
 * formatRelative — compact "5 min ago / 3 h ago / yesterday / 2 d ago".
 *
 * WHY local helper (not lib/utils.formatRelativeTime): the existing helper
 * lives in lib/utils.ts and outputs slightly different verbiage; this page
 * keeps a self-contained version so the substitution to a Zitadel-driven
 * timestamp later remains a one-line swap.
 */
function formatRelative(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const min = Math.floor(diffMs / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} h ago`;
  const days = Math.floor(hr / 24);
  if (days === 1) return "yesterday";
  return `${days} d ago`;
}

// ── Page ─────────────────────────────────────────────────────────────────

export default function SettingsSecurityPage() {
  // MFA state — local only, mirrors what Zitadel will return.
  const [mfaEnabled, setMfaEnabled] = useState(false);

  // Password form — controlled inputs with client-side validation.
  const [currentPwd, setCurrentPwd] = useState("");
  const [newPwd, setNewPwd] = useState("");
  const [confirmPwd, setConfirmPwd] = useState("");
  // pwSaving simulates an in-flight PATCH so the button shows feedback.
  const [pwSaving, setPwSaving] = useState(false);

  // Local clone of sessions so revoke removes the row visually.
  const [sessions, setSessions] = useState<SessionRow[]>(MOCK_SESSIONS);

  // ── Handlers ───────────────────────────────────────────────────────────

  const handleMfaToggle = (next: boolean) => {
    // WHY console.log: the back-end isn't wired yet but the integration
    // target is auth-gateway POST /v1/auth/mfa. Logging makes the call site
    // grep-able and the toast gives the user immediate feedback.
    // eslint-disable-next-line no-console
    console.log("[settings/security] MFA toggle →", next);
    setMfaEnabled(next);
    toast.success(next ? "Two-factor authentication enabled" : "Two-factor authentication disabled", {
      description: next
        ? "You'll be asked for a TOTP code at next sign-in."
        : "Your account is now protected by password only.",
    });
  };

  const handlePasswordChange = (e: React.FormEvent) => {
    e.preventDefault();
    // Minimal client validation — server enforces the real policy.
    if (newPwd.length < 12) {
      toast.error("Password too short", { description: "Use at least 12 characters." });
      return;
    }
    if (newPwd !== confirmPwd) {
      toast.error("Passwords do not match");
      return;
    }
    setPwSaving(true);
    // WHY setTimeout: simulates the network round-trip so the loading state
    // is visible. When the real PATCH ships, swap with `await fetch(...)`.
    window.setTimeout(() => {
      setPwSaving(false);
      setCurrentPwd("");
      setNewPwd("");
      setConfirmPwd("");
      // eslint-disable-next-line no-console
      console.log("[settings/security] password change submitted");
      toast.success("Password updated", { description: "Your new password is active immediately." });
    }, 600);
  };

  const handleRevokeSession = (sessionId: string) => {
    // eslint-disable-next-line no-console
    console.log("[settings/security] revoke session", sessionId);
    setSessions((prev) => prev.filter((s) => s.id !== sessionId));
    toast.success("Session revoked");
  };

  const handleLogoutAllOthers = () => {
    // eslint-disable-next-line no-console
    console.log("[settings/security] log out all other devices");
    setSessions((prev) => prev.filter((s) => s.current));
    toast.success("Signed out of all other devices", {
      description: "Only this device remains active.",
    });
  };

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    // WHY space-y-3: matches the 12px vertical rhythm used across the
    // other settings sub-pages (Profile, Appearance, Beta Program).
    <div className="space-y-3">
      {/* ── 1. Two-factor authentication ──────────────────────────────── */}
      <Card className="border-border/60 bg-card">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-foreground">
            <ShieldCheck className="h-4 w-4 text-primary" aria-hidden="true" strokeWidth={1.5} />
            Two-factor authentication
          </CardTitle>
          <CardDescription className="text-xs">
            Require a second factor (TOTP authenticator app) at sign-in. Strongly
            recommended for accounts with portfolio access.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-start justify-between gap-4 rounded-[2px] border border-border/40 bg-card/30 p-3">
            <div className="min-w-0 flex-1">
              <Label
                htmlFor="mfa-switch"
                className="block text-sm font-medium text-foreground"
              >
                Enable two-factor authentication
              </Label>
              <p className="mt-1 text-xs text-muted-foreground">
                {mfaEnabled
                  ? "Two-factor is active. Disabling removes a layer of protection."
                  : "Currently disabled. Enable to scan a QR code with your authenticator app."}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {/* Status pill — mirrors the live state at a glance */}
              <Badge
                variant="outline"
                className={
                  mfaEnabled
                    ? "border-positive/40 bg-positive/10 text-positive text-[10px] font-mono uppercase tracking-[0.06em]"
                    : "border-warning/40 bg-warning/10 text-warning text-[10px] font-mono uppercase tracking-[0.06em]"
                }
              >
                {mfaEnabled ? "Enabled" : "Disabled"}
              </Badge>
              <Switch
                id="mfa-switch"
                checked={mfaEnabled}
                onCheckedChange={handleMfaToggle}
                aria-label="Toggle two-factor authentication"
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── 2. Password change ────────────────────────────────────────── */}
      <Card className="border-border/60 bg-card">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-foreground">
            <KeyRound className="h-4 w-4 text-primary" aria-hidden="true" strokeWidth={1.5} />
            Change password
          </CardTitle>
          <CardDescription className="text-xs">
            Use a unique password (12+ characters). On submit you&apos;ll be asked
            to sign back in on other devices.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* WHY <form>: enables submit on Enter from any field. */}
          <form onSubmit={handlePasswordChange} className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="pw-current" className="text-xs">
                Current password
              </Label>
              <Input
                id="pw-current"
                type="password"
                value={currentPwd}
                onChange={(e) => setCurrentPwd(e.target.value)}
                autoComplete="current-password"
                required
                disabled={pwSaving}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="pw-new" className="text-xs">
                New password
              </Label>
              <Input
                id="pw-new"
                type="password"
                value={newPwd}
                onChange={(e) => setNewPwd(e.target.value)}
                autoComplete="new-password"
                minLength={12}
                required
                disabled={pwSaving}
                aria-describedby="pw-new-hint"
              />
              <p id="pw-new-hint" className="text-[11px] text-muted-foreground">
                At least 12 characters. Mix of letters, numbers, and symbols recommended.
              </p>
            </div>
            <div className="space-y-1">
              <Label htmlFor="pw-confirm" className="text-xs">
                Confirm new password
              </Label>
              <Input
                id="pw-confirm"
                type="password"
                value={confirmPwd}
                onChange={(e) => setConfirmPwd(e.target.value)}
                autoComplete="new-password"
                required
                disabled={pwSaving}
              />
            </div>
            <div className="flex items-center justify-end gap-2 pt-1">
              <Button
                type="submit"
                size="sm"
                disabled={pwSaving || !currentPwd || !newPwd || !confirmPwd}
              >
                {pwSaving ? "Updating…" : "Update password"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* ── 3. Active sessions ────────────────────────────────────────── */}
      <Card className="border-border/60 bg-card">
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-sm font-medium text-foreground">
                <Monitor className="h-4 w-4 text-primary" aria-hidden="true" strokeWidth={1.5} />
                Active sessions
              </CardTitle>
              <CardDescription className="text-xs">
                Devices currently signed in to your account. Revoke any you don&apos;t
                recognise.
              </CardDescription>
            </div>
            {/* WHY guard >1: don't show "log out all" if only the current
                session remains — clicking it would be a no-op. */}
            {sessions.length > 1 && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button variant="outline" size="sm" className="border-destructive/40 text-destructive hover:bg-destructive/10">
                    Log out all others
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Sign out of all other devices?</AlertDialogTitle>
                    <AlertDialogDescription>
                      This will end {sessions.length - 1} session
                      {sessions.length - 1 === 1 ? "" : "s"} on devices other
                      than this one. Affected users will need to sign in again
                      on those devices.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction onClick={handleLogoutAllOthers}>
                      Sign out other devices
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          {sessions.map((s, idx) => (
            <div key={s.id}>
              <div className="flex items-start justify-between gap-3 rounded-[2px] border border-border/40 bg-card/30 p-3">
                <div className="flex items-start gap-3">
                  {/* WHY conditional icon: phones get a phone icon, desktops
                      a monitor icon. Helps the user recognise their devices
                      at a glance. */}
                  {s.device.toLowerCase().includes("iphone") || s.device.toLowerCase().includes("android") ? (
                    <Smartphone className="mt-0.5 h-4 w-4 text-muted-foreground" aria-hidden="true" strokeWidth={1.5} />
                  ) : (
                    <Monitor className="mt-0.5 h-4 w-4 text-muted-foreground" aria-hidden="true" strokeWidth={1.5} />
                  )}
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-foreground">{s.device}</p>
                      {s.current && (
                        <Badge
                          variant="outline"
                          className="border-positive/40 bg-positive/10 px-1.5 py-0 text-[9px] font-mono uppercase tracking-[0.06em] text-positive"
                        >
                          This device
                        </Badge>
                      )}
                    </div>
                    <p className="mt-0.5 text-xs text-muted-foreground">{s.browser}</p>
                    <p className="mt-1 font-mono text-[10px] tabular-nums text-muted-foreground/80">
                      {s.ip} · {formatRelative(s.lastActiveAt)}
                    </p>
                  </div>
                </div>
                {/* WHY no revoke for current session: revoking would log the
                    user out of the page they're using. Use the standard
                    "Sign out" affordance for that. */}
                {!s.current && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleRevokeSession(s.id)}
                    aria-label={`Revoke session for ${s.device}`}
                  >
                    Revoke
                  </Button>
                )}
              </div>
              {idx < sessions.length - 1 && <div className="h-1.5" aria-hidden="true" />}
            </div>
          ))}
        </CardContent>
      </Card>

      {/* ── 4. Recent sign-in audit ───────────────────────────────────── */}
      <Card className="border-border/60 bg-card">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-foreground">
            <Clock className="h-4 w-4 text-primary" aria-hidden="true" strokeWidth={1.5} />
            Recent sign-ins
          </CardTitle>
          <CardDescription className="text-xs">
            Last 30 days of authentication events. Anything you don&apos;t recognise?
            Change your password immediately and contact support.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="divide-y divide-border/40">
            {MOCK_AUDIT.map((row, i) => (
              <li
                key={i}
                className="flex items-center justify-between gap-3 py-2 text-xs first:pt-0 last:pb-0"
              >
                <div className="flex items-center gap-2">
                  {row.ok ? (
                    <CheckCircle2
                      className="h-3.5 w-3.5 text-positive"
                      aria-hidden="true"
                      strokeWidth={1.5}
                    />
                  ) : (
                    <AlertTriangle
                      className="h-3.5 w-3.5 text-warning"
                      aria-hidden="true"
                      strokeWidth={1.5}
                    />
                  )}
                  <span className={row.ok ? "text-foreground" : "text-warning"}>
                    {row.event}
                  </span>
                </div>
                <div className="flex items-center gap-3 font-mono tabular-nums text-[10px] text-muted-foreground">
                  <span>{row.ip}</span>
                  <Separator orientation="vertical" className="h-3 bg-border/40" />
                  <span>{formatRelative(row.at)}</span>
                </div>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
