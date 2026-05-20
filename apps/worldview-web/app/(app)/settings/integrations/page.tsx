/**
 * app/(app)/settings/integrations/page.tsx — Integrations management.
 *
 * WHY THIS EXISTS (PLAN-0087 F-BB-005):
 * Replaces the PLAN-0059 I-3 placeholder. Lists all third-party services
 * connected to the user's Worldview account (brokerages, alert delivery,
 * outbound webhooks). For the beta walkthrough this surface MUST exist
 * because IT-security reviewers need to see (a) which third parties have
 * data access, and (b) a clear "disconnect" path.
 *
 * SUBSTANCE WE SHIP:
 *   - Brokerage card (TastyTrade) — links to /portfolio/connect for the
 *     real connection flow already shipped under PRD-0022.
 *   - Slack card — placeholder (back-end planned via S10 outbound).
 *   - Email-digest card — connected by default; toggleable.
 *   - Webhook card — show a single mocked webhook with revoke action.
 *
 * EVERY CONTROL IS WIRED with toast feedback. Connect/disconnect intent
 * is logged + visibly acknowledged so the substitution to the real API
 * (S10 webhooks, Slack OAuth, etc.) is a one-line replacement.
 *
 * DESIGN: dense Card stack matching the Security page (12px gap, 11-12px
 * text, 2px radii). Status pills use the same colour mapping (positive =
 * connected, warning = action needed, muted = not connected).
 */

"use client";

import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import {
  Briefcase,
  MessageSquare,
  Mail,
  Webhook,
  ExternalLink,
  Trash2,
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

// ── Helpers ──────────────────────────────────────────────────────────────

/**
 * StatusPill — small uppercase badge used on every integration card.
 *
 * WHY a local component (not in components/ui/): the colour mapping is
 * specific to integration status semantics and shouldn't pollute the
 * shared Badge variants list.
 */
function StatusPill({ kind }: { kind: "connected" | "disconnected" | "action" }) {
  const map: Record<typeof kind, string> = {
    connected:
      "border-positive/40 bg-positive/10 text-positive",
    disconnected:
      "border-border/60 bg-muted/40 text-muted-foreground",
    action:
      "border-warning/40 bg-warning/10 text-warning",
  };
  const label =
    kind === "connected" ? "Connected" : kind === "action" ? "Action needed" : "Not connected";
  return (
    <Badge
      variant="outline"
      className={`${map[kind]} text-[10px] font-mono uppercase tracking-[0.06em]`}
    >
      {label}
    </Badge>
  );
}

// ── Mock state — webhook (the rest is read from real surfaces) ───────────

interface WebhookRow {
  id: string;
  url: string;
  events: string[];
  createdAt: string;
}

const MOCK_WEBHOOKS: WebhookRow[] = [
  {
    id: "wh-01",
    url: "https://hooks.example.com/worldview/portfolio",
    events: ["portfolio.position.changed", "alert.triggered"],
    // 5 days ago
    createdAt: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString(),
  },
];

// ── Page ─────────────────────────────────────────────────────────────────

export default function SettingsIntegrationsPage() {
  // Local state for the toggleable channels — mirrors the eventual
  // PATCH /v1/users/me/notification_channels response shape.
  const [emailDigestEnabled, setEmailDigestEnabled] = useState(true);
  const [slackConnected, setSlackConnected] = useState(false);
  const [webhooks, setWebhooks] = useState<WebhookRow[]>(MOCK_WEBHOOKS);

  // ── Handlers ───────────────────────────────────────────────────────────

  const handleSlackConnect = () => {
    // eslint-disable-next-line no-console
    console.log("[settings/integrations] start Slack OAuth flow");
    // Simulate the OAuth round-trip with a 300ms delay so the toast
    // sequence reads naturally.
    toast.info("Redirecting to Slack…");
    window.setTimeout(() => {
      setSlackConnected(true);
      toast.success("Slack connected", {
        description: "High-impact alerts will now be delivered to #worldview-alerts.",
      });
    }, 300);
  };

  const handleSlackDisconnect = () => {
    // eslint-disable-next-line no-console
    console.log("[settings/integrations] disconnect Slack");
    setSlackConnected(false);
    toast.success("Slack disconnected");
  };

  const handleEmailToggle = (next: boolean) => {
    // eslint-disable-next-line no-console
    console.log("[settings/integrations] email digest →", next);
    setEmailDigestEnabled(next);
    toast.success(next ? "Email digest enabled" : "Email digest disabled");
  };

  const handleWebhookDelete = (id: string) => {
    // eslint-disable-next-line no-console
    console.log("[settings/integrations] delete webhook", id);
    setWebhooks((prev) => prev.filter((w) => w.id !== id));
    toast.success("Webhook removed");
  };

  const handleAddWebhook = () => {
    // eslint-disable-next-line no-console
    console.log("[settings/integrations] open add-webhook dialog");
    toast.info("Webhook setup coming soon", {
      description: "Reach out to support for early access while the API is finalised.",
    });
  };

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <div className="space-y-3">
      {/* ── Brokerage ────────────────────────────────────────────────── */}
      <Card className="border-border/60 bg-card">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-[14px] font-medium text-foreground">
            <Briefcase className="h-4 w-4 text-primary" aria-hidden="true" strokeWidth={1.5} />
            Brokerage accounts
          </CardTitle>
          <CardDescription className="text-xs">
            Sync read-only positions and transactions from supported brokers.
            Connect or manage brokerages from the Portfolio page.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-start justify-between gap-3 rounded-[2px] border border-border/40 bg-card/30 p-3">
            <div className="flex items-start gap-3">
              <div
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[2px] border border-border/60 bg-muted/40 text-[10px] font-mono uppercase tracking-[0.06em] text-foreground"
                aria-hidden="true"
              >
                TT
              </div>
              <div className="min-w-0">
                <p className="text-[14px] font-medium text-foreground">TastyTrade</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Read-only positions, holdings and transaction history.
                </p>
                <p className="mt-1 font-mono text-[10px] tabular-nums text-muted-foreground/80">
                  Manage at /portfolio → Brokerages tab
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {/* Status varies per real connection — surface this hint via
                  a neutral label until we deep-link the live status. */}
              <StatusPill kind="action" />
              <Button asChild variant="outline" size="sm">
                <Link href="/portfolio/connect" aria-label="Manage brokerage connections">
                  Manage
                  <ExternalLink className="ml-1.5 h-3 w-3" aria-hidden="true" strokeWidth={1.5} />
                </Link>
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── Slack / Email / Webhooks — gated by NEXT_PUBLIC_ENABLE_INTEGRATIONS */}
      {/* WHY gate: Slack OAuth flow, email-digest backend, and webhook management
          all require backend endpoints (S10 outbound + S1 prefs) that are not
          yet live. The brokerage card above links to /portfolio/connect which
          IS live (PRD-0022 shipped). Hiding the unimplemented sections keeps
          the page honest for IT-security reviewers while preserving the code
          for when the backend ships. FR-6.6. */}
      {process.env.NEXT_PUBLIC_ENABLE_INTEGRATIONS === "true" && (
        <>
      {/* ── Slack ────────────────────────────────────────────────────── */}
      <Card className="border-border/60 bg-card">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-[14px] font-medium text-foreground">
            <MessageSquare className="h-4 w-4 text-primary" aria-hidden="true" strokeWidth={1.5} />
            Slack alert delivery
          </CardTitle>
          <CardDescription className="text-xs">
            Send high-impact news and price alerts to a Slack channel of your choice.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-start justify-between gap-3 rounded-[2px] border border-border/40 bg-card/30 p-3">
            <div className="flex items-start gap-3">
              <div
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[2px] border border-border/60 bg-muted/40 text-[10px] font-mono uppercase tracking-[0.06em] text-foreground"
                aria-hidden="true"
              >
                SL
              </div>
              <div className="min-w-0">
                <p className="text-[14px] font-medium text-foreground">Slack</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {slackConnected
                    ? "Connected to workspace acme-capital.slack.com — channel #worldview-alerts."
                    : "Not connected. Authorise Worldview to post in your Slack workspace."}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <StatusPill kind={slackConnected ? "connected" : "disconnected"} />
              {slackConnected ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="border-destructive/40 text-destructive hover:bg-destructive/10"
                  onClick={handleSlackDisconnect}
                >
                  Disconnect
                </Button>
              ) : (
                <Button variant="outline" size="sm" onClick={handleSlackConnect}>
                  Connect Slack
                </Button>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── Email digest ─────────────────────────────────────────────── */}
      <Card className="border-border/60 bg-card">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-[14px] font-medium text-foreground">
            <Mail className="h-4 w-4 text-primary" aria-hidden="true" strokeWidth={1.5} />
            Email digest
          </CardTitle>
          <CardDescription className="text-xs">
            Daily morning brief and weekly portfolio summary. Sent to your account email.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between gap-3 rounded-[2px] border border-border/40 bg-card/30 p-3">
            <div className="min-w-0">
              <p className="text-[14px] font-medium text-foreground">Daily morning brief</p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Delivered at 07:00 in your local timezone, every market day.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <StatusPill kind={emailDigestEnabled ? "connected" : "disconnected"} />
              <Switch
                checked={emailDigestEnabled}
                onCheckedChange={handleEmailToggle}
                aria-label="Toggle email digest"
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── Outbound webhooks ────────────────────────────────────────── */}
      <Card className="border-border/60 bg-card">
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-[14px] font-medium text-foreground">
                <Webhook className="h-4 w-4 text-primary" aria-hidden="true" strokeWidth={1.5} />
                Outbound webhooks
              </CardTitle>
              <CardDescription className="text-xs">
                Forward portfolio events and triggered alerts to your own URL. Useful
                for piping into Discord, custom Slack apps, or in-house tooling.
              </CardDescription>
            </div>
            <Button variant="outline" size="sm" onClick={handleAddWebhook}>
              Add webhook
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {webhooks.length === 0 ? (
            // WHY explicit empty state: matches the rest of the app's
            // "honest empty" pattern (see InlineEmptyState convention).
            <div className="rounded-[2px] border border-dashed border-border/60 bg-muted/20 px-3 py-6 text-center">
              <p className="text-xs text-muted-foreground">No webhooks configured.</p>
              <p className="mt-1 text-[11px] text-muted-foreground/80">
                Add one above to receive event notifications at your URL.
              </p>
            </div>
          ) : (
            <ul className="space-y-2">
              {webhooks.map((wh, idx) => (
                <li key={wh.id}>
                  <div className="flex items-start justify-between gap-3 rounded-[2px] border border-border/40 bg-card/30 p-3">
                    <div className="min-w-0">
                      {/* WHY break-all: webhook URLs are long; we want them
                          to wrap rather than overflow horizontally. */}
                      <p className="break-all font-mono text-xs text-foreground">{wh.url}</p>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        Events:{" "}
                        <span className="font-mono">{wh.events.join(", ")}</span>
                      </p>
                      <p className="mt-1 font-mono text-[10px] tabular-nums text-muted-foreground/80">
                        Added {new Date(wh.createdAt).toISOString().slice(0, 10)}
                      </p>
                    </div>
                    {/* Confirm dialog because deleting a webhook breaks live
                        downstream integrations; this is destructive enough to
                        warrant a second click. */}
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Delete webhook ${wh.url}`}
                        >
                          <Trash2 className="h-3.5 w-3.5" aria-hidden="true" strokeWidth={1.5} />
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>Remove this webhook?</AlertDialogTitle>
                          <AlertDialogDescription>
                            Future events will no longer be delivered to{" "}
                            <span className="font-mono">{wh.url}</span>. This cannot be undone.
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>Cancel</AlertDialogCancel>
                          <AlertDialogAction
                            onClick={() => handleWebhookDelete(wh.id)}
                            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                          >
                            Remove webhook
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </div>
                  {idx < webhooks.length - 1 && <Separator className="mt-2 bg-border/40" />}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
        </>
      )}
    </div>
  );
}
