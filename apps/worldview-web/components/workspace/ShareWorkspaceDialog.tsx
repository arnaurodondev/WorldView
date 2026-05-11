/**
 * components/workspace/ShareWorkspaceDialog.tsx — Share workspace via URL
 *
 * WHY THIS EXISTS: Power users want to send their workspace setup to a
 * teammate via Slack/email without having to walk them through manual panel
 * configuration. The pattern: encode the workspace as a URL-safe base64 token,
 * append it as `?config=<token>` to the workspace page URL, and let the
 * recipient open the link to import.
 *
 * WHY a dialog (not inline button → toast): the URL itself needs to be
 * displayed and copied — toast surfaces are too short-lived for that. A
 * dialog gives the user dedicated space to inspect the URL, tap-and-hold
 * to copy on mobile, or paste it into a different sharing channel.
 *
 * WHY the encode happens in this component (not the parent): keeping the
 * encode call here makes the dialog self-contained and testable in isolation.
 * The parent only has to pass the WorkspaceConfig — the dialog handles all
 * the encoding logic including the size guard.
 *
 * SECURITY NOTE: workspace tokens are NOT signed or encrypted. They contain
 * panel layouts only, no user data, no credentials. Anyone who decodes a
 * token sees the layout only. If WorkspaceConfig ever gains sensitive fields
 * (e.g., remembered API tokens — please don't), this share path needs review.
 *
 * WHO USES IT: app/(app)/workspace/page.tsx (Share button on the active tab)
 * DESIGN REFERENCE: PLAN-0051 §T-C-3-07 (share-via-URL)
 */

"use client";
// WHY "use client": uses navigator.clipboard, useState, and Radix Dialog —
// all browser-only APIs.

import { useMemo, useState } from "react";
import { Copy, Check, AlertCircle } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  encodeWorkspace,
  MAX_TOKEN_CHARS,
} from "@/lib/workspace-share";
import type { WorkspaceConfig } from "@/contexts/WorkspaceContext";

// ── Component props ────────────────────────────────────────────────────────────

interface ShareWorkspaceDialogProps {
  /** The workspace to encode and share. */
  config: WorkspaceConfig;
  /**
   * Optional trigger override. Defaults to a small "Share" button matching the
   * tab strip styling. Pass a custom trigger to integrate with other surfaces.
   */
  trigger?: React.ReactNode;
}

// ── Component ──────────────────────────────────────────────────────────────────

export function ShareWorkspaceDialog({ config, trigger }: ShareWorkspaceDialogProps) {
  // WHY local state for open: we want to auto-reset the "copied" indicator
  // when the dialog closes. Wiring open state ourselves makes that easy.
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  // ── Compute encoded token + URL ──────────────────────────────────────────
  // WHY useMemo: encoding is cheap (sub-millisecond for typical workspaces),
  // but recomputing on every render would still be wasteful when the dialog
  // is open across many parent renders. useMemo caches until config changes.
  const { token, url, oversize } = useMemo(() => {
    const tk = encodeWorkspace(config);
    const isOver = tk.length > MAX_TOKEN_CHARS;
    // WHY window.location.origin (not a hardcoded host): keeps the share URL
    // pointing at the current environment (dev → localhost, staging → preview
    // URL, prod → app.worldview.com). Falls back to a placeholder during SSR
    // tests where window is undefined.
    const origin =
      typeof window !== "undefined" ? window.location.origin : "https://app.worldview.com";
    return {
      token: tk,
      url: `${origin}/workspace?config=${tk}`,
      oversize: isOver,
    };
  }, [config]);

  /**
   * handleCopy — copy the URL to the clipboard and flash a confirmation.
   *
   * WHY navigator.clipboard.writeText (not document.execCommand): the legacy
   * execCommand approach is deprecated and unreliable on iOS Safari. The async
   * Clipboard API works across modern browsers and requires a user gesture
   * (which we have — the Copy button click).
   *
   * WHY 2000ms timeout: long enough for the user to see the checkmark animation,
   * short enough that they don't think the button is permanently in success
   * state if they click again.
   */
  async function handleCopy() {
    if (oversize) return;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // WHY swallow + visual fallback: if clipboard write fails (e.g., user
      // denied permission), we don't want to show a hard error. The URL is
      // still visible in the input — they can manually select and copy.
      // eslint-disable-next-line no-console
      console.warn("Clipboard write failed; user can manually copy the URL.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <button
            className="ml-1 shrink-0 px-2 text-xs text-muted-foreground hover:text-foreground transition-colors duration-0"
            aria-label="Share this workspace"
          >
            Share
          </button>
        )}
      </DialogTrigger>

      <DialogContent
        // WHY max-w-md: the URL is the dominant content and tends to be ~120-300
        // chars. md (28rem) gives enough horizontal space for the URL field plus
        // the Copy button without horizontal scrolling.
        className="max-w-md p-0 bg-card border border-border rounded-[2px] shadow-none"
      >
        <DialogHeader className="px-3 py-2 border-b border-border">
          {/* WHY font-mono: ADR-F-15 — dialog titles are section labels, use IBM Plex Mono */}
          <DialogTitle className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground font-mono font-normal">
            Share Workspace
          </DialogTitle>
          <DialogDescription className="text-[10px] text-muted-foreground">
            Send this URL to anyone with a Worldview account. Opening it imports
            the workspace as a new tab.
          </DialogDescription>
        </DialogHeader>

        <div className="p-3 space-y-2">
          {oversize ? (
            // ── Oversize error banner ────────────────────────────────────
            // WHY full banner (not toast): the user can't proceed; we need
            // them to see this clearly. Border-l-2 + bg-negative/10 matches
            // the canonical error pattern (e.g., alerts page error states).
            <div
              className="flex items-start gap-2 rounded-[2px] border-l-2 border-negative bg-negative/10 px-2 py-1.5"
              role="alert"
            >
              <AlertCircle
                className="h-3.5 w-3.5 shrink-0 text-negative mt-0.5"
                aria-hidden
              />
              <div className="flex-1 text-[11px] text-foreground">
                <p className="font-medium">Workspace too large to share via URL.</p>
                <p className="text-muted-foreground mt-0.5">
                  Encoded size {token.length.toLocaleString()} chars exceeds the
                  {" "}
                  {MAX_TOKEN_CHARS.toLocaleString()}-char URL limit. Export to
                  JSON is planned for a future release.
                </p>
              </div>
            </div>
          ) : (
            <>
              {/* URL display + copy button */}
              {/*
               * WHY readOnly input (not a styled div): users expect to be able
               * to manually select-all-and-copy from a text input. readOnly
               * preserves that behavior while preventing accidental edits.
               */}
              <div className="flex items-center gap-1">
                <input
                  type="text"
                  value={url}
                  readOnly
                  // WHY onClick selects all: makes manual copy (without using
                  // the Copy button) one click instead of click-and-drag.
                  onClick={(e) => (e.currentTarget as HTMLInputElement).select()}
                  className="flex-1 rounded-[2px] border border-border bg-background px-2 py-1 font-mono text-[10px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                  aria-label="Shareable workspace URL"
                  data-testid="share-url-input"
                />
                <button
                  onClick={handleCopy}
                  className="flex items-center gap-1 rounded-[2px] border border-border bg-card px-2 py-1 text-[10px] uppercase tracking-[0.08em] text-muted-foreground hover:text-foreground hover:bg-muted/40"
                  aria-label="Copy URL to clipboard"
                  data-testid="share-copy-button"
                >
                  {/*
                   * WHY two icons (Copy + Check): visual feedback after copy.
                   * The flip-back-after-2s tells the user the action succeeded
                   * without needing a separate toast.
                   */}
                  {copied ? (
                    <>
                      <Check className="h-3 w-3" aria-hidden />
                      Copied
                    </>
                  ) : (
                    <>
                      <Copy className="h-3 w-3" aria-hidden />
                      Copy
                    </>
                  )}
                </button>
              </div>

              {/* Token-size hint — informational, not warning */}
              <p className="text-[10px] text-muted-foreground">
                {token.length.toLocaleString()} / {MAX_TOKEN_CHARS.toLocaleString()} chars
              </p>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
