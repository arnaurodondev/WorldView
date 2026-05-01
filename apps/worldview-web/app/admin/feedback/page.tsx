/**
 * app/admin/feedback/page.tsx — admin triage dashboard.
 *
 * WHY THIS EXISTS (PLAN-0053 Wave G T-G-7-07):
 * Support staff need a single place to triage incoming feedback:
 *   - filterable table (status, kind, severity)
 *   - bulk PATCH (assign, status)
 *   - CSV export of the current view
 *   - NPS aggregate strip at the top (admin-only metric)
 *
 * ROLE GUARD:
 * UserProfile doesn't carry `role` yet (TODO: add to S1 /me response in
 * a future wave). We compute admin-ness defensively from the JWT claim if
 * the user payload happens to include it; otherwise we fall back to
 * "show the page but rely on backend 403". The backend is the actual
 * security boundary — see _require_admin in services/portfolio/.../feedback.py.
 *
 * VIRTUALISATION: For v1 we pull a 200-row page (backend max). React-Window
 * is overkill for that size; a plain map keeps the diff small. Swap to
 * useVirtualizer when the row count grows beyond 500.
 */

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { CheckSquare, Download, Filter as FilterIcon, Loader2, MinusSquare, Square } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import {
  useFeedbackSubmissions,
  usePatchFeedbackSubmission,
} from "@/hooks/useFeedbackSubmissions";
import { useAuth } from "@/hooks/useAuth";
import { createGateway } from "@/lib/gateway";
import { qk } from "@/lib/query/keys";
import type {
  FeedbackKind,
  FeedbackStatus,
  FeedbackSubmission,
} from "@/types/api";

// ── Helpers ────────────────────────────────────────────────────────────────

const STATUS_OPTIONS: FeedbackStatus[] = [
  "open",
  "triaged",
  "in_progress",
  "resolved",
  "closed",
  "duplicate",
];

const KIND_OPTIONS: FeedbackKind[] = ["bug", "feature_request", "ux", "design", "other"];

/** Read role from any UserProfile-shaped object — tolerant of schema drift. */
function readRole(user: unknown): string | null {
  if (user && typeof user === "object" && "role" in user) {
    const r = (user as { role?: unknown }).role;
    return typeof r === "string" ? r : null;
  }
  return null;
}

/** Convert the current visible rows into a CSV blob and trigger a download. */
function exportCsv(rows: FeedbackSubmission[]) {
  const headers = [
    "id",
    "created_at",
    "kind",
    "severity",
    "status",
    "user_id",
    "email",
    "page_url",
    "description",
  ];
  // WHY \"\" escapes: CSV escape rule — embedded double-quotes become "".
  //
  // PLAN-0052 Wave E QA-iter1 sec/M-1: CSV formula injection defence.
  // Excel / LibreOffice / Google Sheets evaluate any cell beginning with
  // `=`, `+`, `-`, `@`, tab, or carriage return as a formula — even when
  // wrapped in double quotes (the parsers strip the wrapper before the
  // formula check). User-supplied free-text (description, email) is the
  // attack surface; backend PII redaction does NOT remove these chars.
  // Mitigation: prepend a single apostrophe, which Excel treats as a
  // text-quote prefix and discards on display while neutralising the
  // formula. Same defence used by Google Sheets / Microsoft guidance.
  const FORMULA_TRIGGERS = /^[=+\-@\t\r]/;
  const sanitiseCell = (v: string) =>
    FORMULA_TRIGGERS.test(v) ? `'${v}` : v;
  const escape = (v: string | null | undefined) => {
    if (v === null || v === undefined) return "";
    return `"${sanitiseCell(v).replace(/"/g, '""')}"`;
  };
  const lines = [headers.join(",")];
  for (const r of rows) {
    lines.push(
      [
        escape(r.id),
        escape(r.created_at),
        escape(r.kind),
        escape(r.severity),
        escape(r.status),
        escape(r.user_id),
        escape(r.email),
        escape(r.page_url),
        // WHY single-line description: collapse newlines to keep CSV readable.
        escape(r.description.replace(/\r?\n/g, " ").slice(0, 500)),
      ].join(","),
    );
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `feedback-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ── NPS Aggregate strip ────────────────────────────────────────────────────

function NPSStrip() {
  const { accessToken } = useAuth();
  const { data, isError } = useQuery({
    // PLAN-0052 Wave E QA-iter1 arch/M-3 + C-1: lifted from inline
    // ["nps-aggregate", 30] to the qk.feedback.npsAggregate factory.
    // Stays under the qk.feedback.* cascade so admin-side feedback
    // mutations also refresh the aggregate strip.
    queryKey: qk.feedback.npsAggregate(30),
    queryFn: () => createGateway(accessToken).getNPSAggregate(30),
    enabled: !!accessToken,
    staleTime: 60_000,
  });

  if (isError) return null; // 403 → don't show the strip silently
  if (!data) {
    return (
      <div
        className="mb-4 h-16 animate-pulse rounded-[2px] border border-border bg-card/30"
        role="status"
        aria-busy="true"
        aria-label="Loading NPS aggregate"
      />
    );
  }

  return (
    <div className="mb-4 grid grid-cols-2 gap-3 rounded-[2px] border border-border bg-card/30 p-4 sm:grid-cols-5">
      <Metric label="NPS Score" value={data.nps_score.toFixed(1)} />
      <Metric label="Promoters" value={data.promoter_count.toString()} />
      <Metric label="Passives" value={data.passive_count.toString()} />
      <Metric label="Detractors" value={data.detractor_count.toString()} />
      <Metric label="Sample size" value={`${data.sample_size} (${data.period_days}d)`} />
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase text-muted-foreground">{label}</div>
      <div className="mt-0.5 font-mono text-lg tabular-nums text-foreground">
        {value}
      </div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function AdminFeedbackPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading, user } = useAuth();
  const role = readRole(user);

  // Auth + role guard.
  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace(`/login?redirect_to=${encodeURIComponent("/admin/feedback")}`);
    }
  }, [isLoading, isAuthenticated, router]);

  const [statusFilter, setStatusFilter] = useState<FeedbackStatus | "all">("all");
  const [kindFilter, setKindFilter] = useState<FeedbackKind | "all">("all");

  const { data, isLoading: rowsLoading, isError, error } = useFeedbackSubmissions({
    status: statusFilter === "all" ? undefined : statusFilter,
    kind: kindFilter === "all" ? undefined : kindFilter,
    limit: 200,
  });

  const patch = usePatchFeedbackSubmission();

  const items = useMemo(() => data?.items ?? [], [data]);

  // ── Bulk-selection state (PLAN-0052 Wave E T-E-5-10) ────────────────────
  // We track selected row ids in a Set so toggle-all and per-row toggle are
  // both O(1). The set is refreshed when the underlying items change so a
  // status-filter change (which removes rows from view) doesn't leave
  // dangling ids selected. Bulk action picks a single status to apply to
  // every selected row; we issue the patches in parallel via Promise.all
  // and rely on usePatchFeedbackSubmission to invalidate the list cache.
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkStatus, setBulkStatus] = useState<FeedbackStatus | "">("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkError, setBulkError] = useState<string | null>(null);

  // Trim the selection whenever the visible items change so we never carry
  // ids that aren't on screen (avoids confusing UX where the count chip
  // claims rows that the user can't see).
  useEffect(() => {
    if (selectedIds.size === 0) return;
    const visible = new Set(items.map((row) => row.id));
    setSelectedIds((prev) => {
      const next = new Set<string>();
      for (const id of prev) if (visible.has(id)) next.add(id);
      return next.size === prev.size ? prev : next;
    });
  }, [items, selectedIds.size]);

  const allSelected = items.length > 0 && selectedIds.size === items.length;
  const someSelected = selectedIds.size > 0 && !allSelected;

  const toggleAll = () => {
    if (allSelected || someSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(items.map((r) => r.id)));
    }
  };

  const toggleRow = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Ref to the bulk-error banner so we can move focus to it after a
  // partial failure — the banner sits above the table while the user's
  // focus lives on the Apply button below, so without the focus jump
  // the error is easy to miss. PLAN-0052 Wave E QA-iter1 a11y/M-4.
  const bulkErrorRef = useRef<HTMLParagraphElement | null>(null);

  const applyBulkStatus = async () => {
    if (!bulkStatus || selectedIds.size === 0) return;
    setBulkBusy(true);
    setBulkError(null);
    // PLAN-0052 Wave E QA-iter1 bugs/C-3 + sec/M-2: Promise.allSettled
    // surfaces per-row outcomes so a partial failure produces accurate
    // counts ("3 of 50 failed") instead of a misleading "Failed to update
    // one or more rows" that omits which rows succeeded. We also clear
    // the SUCCESSFUL rows from the selection so the user can re-Apply
    // on just the failed subset.
    const ids = Array.from(selectedIds);
    const results = await Promise.allSettled(
      ids.map((id) =>
        patch.mutateAsync({ id, fields: { status: bulkStatus } }),
      ),
    );
    const failedIds = new Set<string>();
    let okCount = 0;
    results.forEach((res, i) => {
      if (res.status === "fulfilled") {
        okCount += 1;
      } else {
        failedIds.add(ids[i]);
      }
    });
    if (failedIds.size === 0) {
      // All succeeded — clear selection so the next bulk op starts fresh.
      setSelectedIds(new Set());
      setBulkStatus("");
    } else {
      // Keep only the failed ids in the selection so Apply re-runs on
      // just the subset that didn't go through.
      setSelectedIds(failedIds);
      setBulkError(
        `Updated ${okCount} of ${ids.length}. ${failedIds.size} failed — selection narrowed to the failures so you can retry.`,
      );
      // Move focus to the error banner so AT users (and sighted keyboard
      // users) hear the result without hunting up the page.
      // requestAnimationFrame so the DOM is mounted before .focus().
      requestAnimationFrame(() => bulkErrorRef.current?.focus());
    }
    setBulkBusy(false);
  };

  if (isLoading) {
    return <div className="p-8 text-sm text-muted-foreground">Loading…</div>;
  }

  // WHY surface the 403 instead of redirecting: the backend is the
  // canonical guard — if it 403s the front-end shouldn't pretend it's
  // unauthorized at the route level. We just show a clean message.
  if (isError) {
    return (
      <div className="mx-auto max-w-3xl p-8">
        <h1 className="text-2xl font-semibold">Admin: Feedback</h1>
        <p className="mt-2 text-sm text-destructive">
          Access denied — your account is not authorised to view this page.
          {error instanceof Error ? ` (${error.message})` : ""}
        </p>
      </div>
    );
  }

  return (
    // PLAN-0052 Wave E QA-iter1 design/#7: p-6 → p-3 to match the
    // terminal density used elsewhere (settings, beta-program).
    <div className="mx-auto max-w-7xl p-3">
      <header className="mb-4 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Admin: Feedback</h1>
          <p className="mt-1 text-xs text-muted-foreground">
            {role ? `Signed in as ${role}` : "Server enforces admin role"} ·{" "}
            {items.length} row(s)
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => exportCsv(items)}>
          <Download className="mr-1.5 h-3.5 w-3.5" />
          Export CSV
        </Button>
      </header>

      <NPSStrip />

      {/* Filters + bulk action bar */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <FilterIcon className="h-3.5 w-3.5 text-muted-foreground" />
        <Select
          value={statusFilter}
          onValueChange={(v) => setStatusFilter(v as FeedbackStatus | "all")}
        >
          <SelectTrigger className="h-8 w-40 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            {STATUS_OPTIONS.map((s) => (
              <SelectItem key={s} value={s}>
                {s.replace("_", " ")}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select
          value={kindFilter}
          onValueChange={(v) => setKindFilter(v as FeedbackKind | "all")}
        >
          <SelectTrigger className="h-8 w-40 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All kinds</SelectItem>
            {KIND_OPTIONS.map((k) => (
              <SelectItem key={k} value={k}>
                {k.replace("_", " ")}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* Bulk action — only enabled when ≥1 row is selected.
            PLAN-0052 Wave E QA-iter1 design/#2: visual separator (vertical
            divider + extra padding at sm+) so the destructive bulk-write
            surface is structurally distinct from the read-only filter chips.
            QA-iter1 a11y/C-1: dropped role="status" on the count chip — the
            polite live region was firing on every selection toggle ("5
            selected", "6 selected"…) producing torrents of audio spam. The
            count is now ambient text; the bulk-Apply error banner below
            carries the announcement when a result happens. */}
        <div
          className="ml-auto flex items-center gap-2 sm:border-l sm:border-border/40 sm:pl-2"
          aria-label="Bulk actions"
        >
          <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
            {selectedIds.size > 0
              ? `${selectedIds.size} selected`
              : "No rows selected"}
          </span>
          <Select
            value={bulkStatus}
            onValueChange={(v) => setBulkStatus(v as FeedbackStatus)}
            disabled={selectedIds.size === 0 || bulkBusy}
          >
            <SelectTrigger
              className="h-8 w-44 text-xs"
              aria-label="Bulk status"
            >
              <SelectValue placeholder="Set status…" />
            </SelectTrigger>
            <SelectContent>
              {STATUS_OPTIONS.map((s) => (
                <SelectItem key={s} value={s}>
                  Set to {s.replace("_", " ")}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {/* PLAN-0052 Wave E QA-iter1 design/#3: Loader2 spinner (matches
              the beta-program Save button + every other in-flight action
              in the shell) instead of a text swap. */}
          <Button
            variant="outline"
            size="sm"
            disabled={selectedIds.size === 0 || !bulkStatus || bulkBusy}
            onClick={() => void applyBulkStatus()}
          >
            {bulkBusy && (
              <Loader2
                className="mr-1.5 h-3.5 w-3.5 motion-safe:animate-spin"
                aria-hidden="true"
              />
            )}
            {bulkBusy ? "Applying…" : "Apply"}
          </Button>
        </div>
      </div>
      {/* PLAN-0052 Wave E QA-iter1 a11y/M-4: aria-live="assertive" so the
          banner interrupts and is heard immediately; tabIndex={-1} lets
          us focus() it programmatically after a partial-failure result
          (see applyBulkStatus). */}
      {bulkError && (
        <p
          ref={bulkErrorRef}
          className="mb-2 text-xs text-destructive focus:outline-none"
          role="alert"
          aria-live="assertive"
          tabIndex={-1}
        >
          {bulkError}
        </p>
      )}

      {/* Table */}
      <div className="overflow-x-auto rounded-[2px] border border-border">
        <table className="w-full text-xs">
          <thead className="bg-muted/30 text-left text-[10px] uppercase">
            <tr>
              {/* Bulk-select header — clickable cell renders a tri-state
                  glyph (empty / partial / all). WHY a button (not native
                  checkbox): the partial / indeterminate state is awkward
                  to wire on a real <input>. The button + lucide icons give
                  us the same affordance with a single render path.
                  PLAN-0052 Wave E QA-iter1 a11y/B-2: explicit
                  role="checkbox" + aria-checked={"true"|"false"|"mixed"}
                  so screen readers convey ALL THREE selection states.
                  Without these, AT users heard "button, deselect all"
                  with no signal of WHAT was selected.
                  QA-iter1 design/#6: distinct MinusSquare icon for the
                  partial state — opacity drop alone was too subtle for
                  many sighted users to register the difference. */}
              <th className="p-2">
                <button
                  type="button"
                  role="checkbox"
                  aria-checked={
                    allSelected ? "true" : someSelected ? "mixed" : "false"
                  }
                  onClick={toggleAll}
                  aria-label={
                    allSelected ? "Deselect all rows" : "Select all rows"
                  }
                  className="inline-flex items-center justify-center text-muted-foreground hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-1 focus-visible:ring-offset-background"
                >
                  {allSelected ? (
                    <CheckSquare className="h-3.5 w-3.5 text-primary" />
                  ) : someSelected ? (
                    <MinusSquare className="h-3.5 w-3.5 text-primary" />
                  ) : (
                    <Square className="h-3.5 w-3.5" />
                  )}
                </button>
              </th>
              <th className="p-2">Created</th>
              <th className="p-2">Kind</th>
              <th className="p-2">Severity</th>
              <th className="p-2">Status</th>
              <th className="p-2">From</th>
              <th className="p-2">Description</th>
              <th className="p-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rowsLoading && (
              <tr>
                <td colSpan={8} className="p-4 text-center text-muted-foreground">
                  Loading…
                </td>
              </tr>
            )}
            {!rowsLoading && items.length === 0 && (
              <tr>
                <td colSpan={8} className="p-4 text-center text-muted-foreground">
                  No submissions match these filters.
                </td>
              </tr>
            )}
            {items.map((row) => (
              <tr key={row.id} className="border-t border-border hover:bg-muted/10">
                <td className="p-2">
                  {/* PLAN-0052 Wave E QA-iter1 a11y/B-2: role="checkbox" +
                      aria-checked is the correct ARIA model for selection.
                      Previously used aria-pressed (toggle-button semantics)
                      which reads as "pressed/not pressed" instead of
                      "checked/not checked" — semantically wrong AND
                      inconsistent with the header tri-state checkbox. */}
                  <button
                    type="button"
                    role="checkbox"
                    aria-checked={selectedIds.has(row.id)}
                    onClick={() => toggleRow(row.id)}
                    aria-label={
                      selectedIds.has(row.id)
                        ? `Deselect submission ${row.id}`
                        : `Select submission ${row.id}`
                    }
                    className="inline-flex items-center justify-center text-muted-foreground hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-1 focus-visible:ring-offset-background"
                  >
                    {selectedIds.has(row.id) ? (
                      <CheckSquare className="h-3.5 w-3.5 text-primary" />
                    ) : (
                      <Square className="h-3.5 w-3.5" />
                    )}
                  </button>
                </td>
                <td className="p-2 font-mono tabular-nums">
                  {row.created_at.slice(0, 19).replace("T", " ")}
                </td>
                <td className="p-2 capitalize">{row.kind.replace("_", " ")}</td>
                <td className="p-2">{row.severity ?? "—"}</td>
                <td className="p-2">
                  <Select
                    value={row.status}
                    onValueChange={(v) =>
                      patch.mutate({
                        id: row.id,
                        fields: { status: v as FeedbackStatus },
                      })
                    }
                  >
                    <SelectTrigger className="h-7 w-32 text-[10px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {STATUS_OPTIONS.map((s) => (
                        <SelectItem key={s} value={s}>
                          {s.replace("_", " ")}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </td>
                <td className="p-2 font-mono text-[10px]">
                  {row.email ?? row.user_id ?? "—"}
                </td>
                <td className="max-w-md truncate p-2">{row.description}</td>
                <td className="p-2">
                  {row.page_url && (
                    <a
                      href={row.page_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[10px] text-primary underline"
                    >
                      Open page
                    </a>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
