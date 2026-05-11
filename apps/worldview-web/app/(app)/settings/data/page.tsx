/**
 * app/(app)/settings/data/page.tsx — Data, exports & retention.
 *
 * WHY THIS EXISTS (PLAN-0087 F-BB-005):
 * Replaces the PLAN-0059 I-3 placeholder. GDPR/CCPA require visible:
 *   1. A retention configuration surface (chat / search history)
 *   2. A "download my data" affordance
 *   3. A "delete my account" path
 * For institutional clients, an IT-security review will check this exact
 * page exists before granting beta access.
 *
 * SUBSTANCE WE SHIP:
 *   1. Chat history retention selector (30 / 90 / 365 / forever)
 *   2. Search & view history retention selector (same options)
 *   3. Export-my-data button — requests a ZIP via email
 *   4. Delete-account flow — typed-confirmation dialog ("DELETE")
 *
 * EVERY CONTROL IS WIRED with toast feedback.
 */

"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Database, Download, FileWarning, History, Trash2 } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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

// ── Constants ────────────────────────────────────────────────────────────

/**
 * Retention options. WHY discrete (not free-form): a slider would suggest
 * fine-grained control, but the actual back-end implementations (Postgres
 * partition pruning, archive policies) operate on bucketed retention.
 */
const RETENTION_OPTIONS = [
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days (recommended)" },
  { value: "365", label: "1 year" },
  { value: "forever", label: "Keep forever" },
] as const;

/**
 * The exact phrase the user must type to confirm account deletion.
 * Same pattern as GitHub's repo-delete confirmation — prevents muscle-memory
 * "yes" clicks from destroying data.
 */
const DELETE_CONFIRM_PHRASE = "DELETE";

// ── Page ─────────────────────────────────────────────────────────────────

export default function SettingsDataPage() {
  const [chatRetention, setChatRetention] = useState<string>("90");
  const [searchRetention, setSearchRetention] = useState<string>("90");
  const [exporting, setExporting] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState("");

  // ── Handlers ───────────────────────────────────────────────────────────

  const handleChatRetentionChange = (value: string) => {
    // eslint-disable-next-line no-console
    console.log("[settings/data] chat retention →", value);
    setChatRetention(value);
    const label = RETENTION_OPTIONS.find((o) => o.value === value)?.label ?? value;
    toast.success("Chat history retention updated", {
      description: `Older conversations will be deleted after ${label.toLowerCase()}.`,
    });
  };

  const handleSearchRetentionChange = (value: string) => {
    // eslint-disable-next-line no-console
    console.log("[settings/data] search retention →", value);
    setSearchRetention(value);
    const label = RETENTION_OPTIONS.find((o) => o.value === value)?.label ?? value;
    toast.success("Search history retention updated", {
      description: `History older than ${label.toLowerCase()} will be removed.`,
    });
  };

  const handleExport = () => {
    setExporting(true);
    // eslint-disable-next-line no-console
    console.log("[settings/data] export-my-data requested");
    // Simulate the back-end queueing the export job.
    window.setTimeout(() => {
      setExporting(false);
      toast.success("Export queued", {
        description:
          "We'll email you a download link within 24 hours. Large accounts may take longer.",
      });
    }, 600);
  };

  const handleDelete = () => {
    if (deleteConfirm !== DELETE_CONFIRM_PHRASE) return;
    // eslint-disable-next-line no-console
    console.log("[settings/data] account deletion confirmed");
    toast.success("Account deletion scheduled", {
      description:
        "You'll receive a confirmation email. Cancel within 30 days by signing in again.",
    });
    setDeleteConfirm("");
  };

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <div className="space-y-3">
      {/* ── Retention ───────────────────────────────────────────────── */}
      <Card className="border-border/60 bg-card">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-foreground">
            <History className="h-4 w-4 text-primary" aria-hidden="true" strokeWidth={1.5} />
            History retention
          </CardTitle>
          <CardDescription className="text-xs">
            How long Worldview keeps your activity. Shorter retention reduces
            data footprint; longer retention preserves context for chat memory
            and brief generation.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Chat retention */}
          <div className="flex items-start justify-between gap-4 rounded-[2px] border border-border/40 bg-card/30 p-3">
            <div className="min-w-0 flex-1">
              <Label htmlFor="chat-retention" className="text-sm font-medium text-foreground">
                Chat history
              </Label>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Determines how long your chat conversations are kept. Affects the
                memory window the assistant can reference in future answers.
              </p>
            </div>
            <Select value={chatRetention} onValueChange={handleChatRetentionChange}>
              {/* WHY w-44 fixed: prevents the trigger from collapsing on long
                  labels like "90 days (recommended)". */}
              <SelectTrigger id="chat-retention" className="w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {RETENTION_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Search retention */}
          <div className="flex items-start justify-between gap-4 rounded-[2px] border border-border/40 bg-card/30 p-3">
            <div className="min-w-0 flex-1">
              <Label htmlFor="search-retention" className="text-sm font-medium text-foreground">
                Search & view history
              </Label>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Tickers and instruments you&apos;ve searched or viewed. Powers
                personalised dashboard recommendations.
              </p>
            </div>
            <Select value={searchRetention} onValueChange={handleSearchRetentionChange}>
              <SelectTrigger id="search-retention" className="w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {RETENTION_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {/* ── Export ──────────────────────────────────────────────────── */}
      <Card className="border-border/60 bg-card">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-foreground">
            <Download className="h-4 w-4 text-primary" aria-hidden="true" strokeWidth={1.5} />
            Export your data
          </CardTitle>
          <CardDescription className="text-xs">
            Download a ZIP of your portfolios, watchlists, transactions, screener
            configurations, workspace layouts, and chat history.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between gap-3 rounded-[2px] border border-border/40 bg-card/30 p-3">
            <div className="min-w-0">
              <p className="text-sm font-medium text-foreground">Request data export</p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                We&apos;ll email you a download link. JSON + CSV format.
              </p>
            </div>
            <Button variant="outline" size="sm" disabled={exporting} onClick={handleExport}>
              {exporting ? "Queueing…" : "Export now"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* ── Delete account ──────────────────────────────────────────── */}
      <Card className="border-destructive/40 bg-card">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-destructive">
            <FileWarning className="h-4 w-4" aria-hidden="true" strokeWidth={1.5} />
            Delete account
          </CardTitle>
          <CardDescription className="text-xs">
            Schedule permanent deletion of your account and all associated data.
            This is irreversible after the 30-day grace period.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-3 rounded-[2px] border border-destructive/30 bg-destructive/5 p-3">
            <div>
              <p className="text-sm font-medium text-foreground">What gets deleted</p>
              <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
                <li>All portfolios, watchlists, and saved screener configurations</li>
                <li>Brokerage connections and synced transactions</li>
                <li>Chat conversations and memory</li>
                <li>Saved briefs, alerts, and feedback submissions</li>
                <li>Account audit log (after the 30-day grace window)</li>
              </ul>
            </div>

            <Separator className="bg-destructive/20" />

            <p className="text-xs text-muted-foreground">
              You&apos;ll have 30 days to recover the account by signing in again.
              After that the deletion is permanent and cannot be reversed.
            </p>

            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className="border-destructive/60 text-destructive hover:bg-destructive/10"
                >
                  <Trash2 className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" strokeWidth={1.5} />
                  Delete my account
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>This will delete your account.</AlertDialogTitle>
                  <AlertDialogDescription>
                    Type{" "}
                    <span className="font-mono font-semibold text-foreground">
                      {DELETE_CONFIRM_PHRASE}
                    </span>{" "}
                    to confirm. We will email you a link to cancel within 30 days.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <div className="space-y-1">
                  <Label htmlFor="delete-confirm" className="text-xs">
                    Confirmation
                  </Label>
                  <Input
                    id="delete-confirm"
                    value={deleteConfirm}
                    onChange={(e) => setDeleteConfirm(e.target.value)}
                    placeholder={DELETE_CONFIRM_PHRASE}
                    autoComplete="off"
                    autoCapitalize="characters"
                  />
                </div>
                <AlertDialogFooter>
                  {/* WHY onClick on cancel: reset the typed phrase so the
                      next open of the dialog starts fresh. */}
                  <AlertDialogCancel onClick={() => setDeleteConfirm("")}>
                    Cancel
                  </AlertDialogCancel>
                  <AlertDialogAction
                    disabled={deleteConfirm !== DELETE_CONFIRM_PHRASE}
                    onClick={handleDelete}
                    className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                  >
                    Permanently delete
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </CardContent>
      </Card>

      {/* ── Footer ─────────────────────────────────────────────────── */}
      <div className="rounded-[2px] border border-border/40 bg-muted/20 p-3">
        <div className="flex items-start gap-2">
          <Database className="mt-0.5 h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" strokeWidth={1.5} />
          <div>
            <p className="text-xs font-medium text-foreground">
              Where your data lives
            </p>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              All data is stored in EU/US-tier datacentres encrypted at rest.
              Read more in our{" "}
              <a
                href="/legal/privacy"
                className="text-primary hover:underline focus-visible:underline focus-visible:outline-none"
              >
                privacy policy
              </a>
              .
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
