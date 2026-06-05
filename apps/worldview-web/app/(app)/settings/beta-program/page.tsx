/**
 * app/(app)/settings/beta-program/page.tsx — beta enrollment toggle.
 *
 * WHY THIS EXISTS (PLAN-0052 Wave E T-E-5-07):
 * Power users who want early access to in-flight features need a clear
 * opt-in surface. We expose it as its own settings sub-route (not a tab
 * inside /settings) so the URL is shareable and we can deep-link from
 * marketing copy ("Try the beta — go to Settings → Beta Program").
 *
 * BACKEND:
 *   GET    /v1/feedback/beta-program/enrollment → BetaEnrollment row
 *   PATCH  /v1/feedback/beta-program/enrollment → updated row
 * (Routed through api-gateway proxy.feedback_*_beta_enrollment.)
 *
 * UX RULES:
 *   - Toggle (Switch) reflects the server state — never optimistic.
 *     The user sees `isPending` while the PATCH is in flight; this is
 *     a 1-bit binary toggle so optimistic updates aren't worth the
 *     risk of stuck-in-wrong-state on a 401/500.
 *   - Optional `notes` textarea lets the user say WHAT they're interested
 *     in. Persisted to the backend so we can route enrollees to the right
 *     beta cohort.
 *   - Auth required — unauthenticated visitors are redirected to /login.
 *     We rely on the server 401 as the canonical guard; the client check
 *     is just for a faster redirect.
 *
 * DESIGN: matches the /settings page (max-w-3xl, semantic Card surfaces,
 * 2px-radius primitives). Toggle is the shadcn Switch with primary state
 * == "enrolled".
 */

"use client";
// WHY "use client": Switch + textarea are interactive, useBetaEnrollment
// hooks into TanStack Query (client only), useAuth reads React context.

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Beaker, Loader2 } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { useBetaEnrollment, usePatchBetaEnrollment } from "@/hooks/useBetaEnrollment";
import { GatewayError } from "@/lib/gateway";

// ── Constants ─────────────────────────────────────────────────────────────

/**
 * Notes max length — mirrors the backend BetaEnrollmentPatch.notes Field
 * constraint. Going over results in a 422; the textarea hard-stops typing
 * past this value so we never round-trip a known-bad payload.
 */
const NOTES_MAX_LEN = 500;

// ── Page ──────────────────────────────────────────────────────────────────

export default function BetaProgramPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const { data, isLoading, isError, error, refetch } = useBetaEnrollment();
  const patch = usePatchBetaEnrollment();

  // ── Auth guard ──────────────────────────────────────────────────────────
  // We redirect on the client for a faster experience. The backend 401 is
  // still the canonical security boundary — see api-gateway.routes.proxy.
  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      const redirect = encodeURIComponent("/settings/beta-program");
      router.replace(`/login?redirect_to=${redirect}`);
    }
  }, [authLoading, isAuthenticated, router]);

  // ── Local notes draft ──────────────────────────────────────────────────
  // We hold a local copy so the user can type without re-firing the PATCH
  // on every keystroke. A "Save notes" button commits the change. This
  // matches the dense terminal UX where every keystroke is intentional.
  const [notesDraft, setNotesDraft] = useState<string>("");

  // PLAN-0052 Wave E QA-iter1 bugs/C1 + arch/M-4: track the LAST server
  // value we synced into the draft. The sync effect only overwrites the
  // draft when it matches the prior server value — i.e. when the user
  // hasn't started typing. Without this guard, a 30s background refetch
  // (TanStack Query default for staleTime: 30_000 + window-focus refetch)
  // would silently destroy mid-typed notes by re-running the effect with
  // unchanged server data and clobbering the draft.
  const lastSyncedNotesRef = useRef<string | null>(null);

  useEffect(() => {
    if (data?.notes === undefined) return;
    const serverValue = data.notes ?? "";
    // First sync after load — always seed the draft.
    if (lastSyncedNotesRef.current === null) {
      setNotesDraft(serverValue);
      lastSyncedNotesRef.current = serverValue;
      return;
    }
    // Subsequent syncs: only overwrite if the user hasn't typed since the
    // last sync (i.e. their draft still matches what we last wrote into it).
    if (notesDraft === lastSyncedNotesRef.current) {
      setNotesDraft(serverValue);
      lastSyncedNotesRef.current = serverValue;
    } else {
      // User has unsaved typing — keep their draft, but record the new
      // server value so the next dirty-check has the latest baseline.
      lastSyncedNotesRef.current = serverValue;
    }
    // notesDraft intentionally not in deps — we want to react to SERVER
    // changes, not every keystroke. Using a ref for the comparison
    // sidesteps the missing-dep lint while preserving correctness.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.notes]);

  // ── Derived state ──────────────────────────────────────────────────────

  /** Toggle disabled while loading initial state OR while a PATCH is in flight. */
  const toggleDisabled = isLoading || patch.isPending || !data;

  /** Notes "Save" button is only meaningful when the draft differs from server. */
  const notesDirty = useMemo(
    () => (data ? (data.notes ?? "") !== notesDraft.trim() : false),
    [data, notesDraft],
  );

  // ── Handlers ───────────────────────────────────────────────────────────

  const handleToggle = (next: boolean) => {
    // WHY include notes in the PATCH: if the user typed notes but didn't
    // press "Save notes" yet, flipping the toggle would otherwise wipe
    // their draft (server returns a row without their pending notes).
    // Including the current draft is the principle-of-least-surprise.
    patch.mutate({
      enrolled: next,
      ...(notesDirty ? { notes: notesDraft.trim() || null } : {}),
    });
  };

  const handleSaveNotes = () => {
    patch.mutate({ notes: notesDraft.trim() || null });
  };

  // ── Render ─────────────────────────────────────────────────────────────

  // WHY render-while-redirecting: the auth-redirect runs in useEffect, so
  // the first render still shows the page. Returning a loading shell
  // avoids a flash of empty state.
  if (authLoading || !isAuthenticated) {
    return <div className="p-3 text-xs text-muted-foreground">Loading…</div>;
  }

  // Error rendering — most likely a network blip; offer a retry instead of
  // a hard fail. 401 already redirects above, so we don't expect that here.
  if (isError) {
    const message =
      error instanceof GatewayError ? error.message : "Failed to load beta program.";
    return (
      <div className="space-y-3">
        <Card className="border-border/60 bg-card">
          <CardContent className="py-4">
            <p className="text-xs text-destructive" role="alert">
              {message}
            </p>
            <Button
              variant="outline"
              size="sm"
              className="mt-3"
              onClick={() => void refetch()}
            >
              Retry
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* No back-button header — the settings sidebar nav already provides
          navigation to all sections. Adding a header here creates visual
          noise and wastes vertical space. */}

      <Card className="border-border/60 bg-card">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-foreground">
            <Beaker className="h-4 w-4 text-primary" aria-hidden="true" strokeWidth={1.5} />
            Beta Program
          </CardTitle>
          <CardDescription>
            Get early access to in-flight features and shape the product direction.
            Beta features are subject to change and may have rough edges — feedback
            is required (we&apos;ll prompt you to comment on what works).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* ── Enrollment toggle row ──────────────────────────────────── */}
          <div className="flex items-start justify-between gap-4 rounded-[2px] border border-border/40 bg-card/30 p-3">
            <div className="min-w-0 flex-1">
              <Label
                htmlFor="beta-enrolled-switch"
                className="block text-sm font-medium text-foreground"
              >
                Enroll in beta
              </Label>
              <p className="mt-1 text-xs text-muted-foreground">
                {data?.enrolled
                  ? data.enrolled_at
                    ? `Enrolled since ${new Date(data.enrolled_at).toLocaleDateString()}`
                    : "Currently enrolled"
                  : "Currently not enrolled"}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {patch.isPending && (
                <Loader2
                  className="h-3.5 w-3.5 motion-safe:animate-spin text-muted-foreground"
                  aria-hidden="true"
                  strokeWidth={1.5}
                />
              )}
              {/* PLAN-0052 Wave E QA-iter1 a11y/M-2: removed aria-label so the
                  visible <Label htmlFor="beta-enrolled-switch"> is what
                  screen readers announce. ARIA spec: aria-label OVERRIDES
                  the htmlFor association — having both meant AT users
                  heard "Leave the beta program" but never the visible
                  "Enroll in beta" copy. The dynamic on/off state is
                  conveyed by the Switch's own aria-checked. */}
              <Switch
                id="beta-enrolled-switch"
                checked={data?.enrolled ?? false}
                disabled={toggleDisabled}
                onCheckedChange={handleToggle}
              />
            </div>
          </div>

          {/* ── Notes / interests ─────────────────────────────────────── */}
          <div>
            <Label
              htmlFor="beta-notes-textarea"
              className="block text-sm font-medium text-foreground"
            >
              What are you most interested in? (optional)
            </Label>
            <textarea
              id="beta-notes-textarea"
              value={notesDraft}
              onChange={(e) => setNotesDraft(e.target.value.slice(0, NOTES_MAX_LEN))}
              maxLength={NOTES_MAX_LEN}
              rows={3}
              placeholder="e.g. graph features, brokerage integrations, mobile…"
              // PLAN-0052 Wave E QA-iter1 design/#4: ring-2 + ring-offset
              // matches the Button focus pattern used everywhere else in
              // the design system. Previously was a thinner ring-1 with
              // no offset, which read as "lower-tier input".
              className="mt-1 w-full rounded-[2px] border border-border bg-background p-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            />
            <div className="mt-1 flex items-center justify-between">
              <span className="text-[11px] tabular-nums text-muted-foreground">
                {notesDraft.length} / {NOTES_MAX_LEN}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={!notesDirty || patch.isPending}
                onClick={handleSaveNotes}
              >
                {patch.isPending && (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 motion-safe:animate-spin" aria-hidden="true" strokeWidth={1.5} />
                )}
                Save notes
              </Button>
            </div>
          </div>

          {patch.isError && (
            <p className="text-xs text-destructive" role="alert">
              {patch.error instanceof GatewayError
                ? patch.error.message
                : "Couldn't save — please retry."}
            </p>
          )}
        </CardContent>
      </Card>

      {/* ── Footer help ────────────────────────────────────────────────── */}
      <p className="text-[11px] text-muted-foreground">
        We&apos;ll notify you by email before enabling new beta features. You can leave
        the program at any time — your existing data is unaffected.
      </p>
    </div>
  );
}
