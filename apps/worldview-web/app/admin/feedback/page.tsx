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

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Download, Filter as FilterIcon } from "lucide-react";
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
  const escape = (v: string | null | undefined) =>
    v === null || v === undefined ? "" : `"${v.replace(/"/g, '""')}"`;
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
    queryKey: ["nps-aggregate", 30],
    queryFn: () => createGateway(accessToken).getNPSAggregate(30),
    enabled: !!accessToken,
    staleTime: 60_000,
  });

  if (isError) return null; // 403 → don't show the strip silently
  if (!data) {
    return (
      <div className="mb-4 h-16 animate-pulse rounded-[2px] border border-border bg-card/30" />
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
    <div className="mx-auto max-w-7xl p-6">
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

      {/* Filters */}
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
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-[2px] border border-border">
        <table className="w-full text-xs">
          <thead className="bg-muted/30 text-left text-[10px] uppercase">
            <tr>
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
                <td colSpan={7} className="p-4 text-center text-muted-foreground">
                  Loading…
                </td>
              </tr>
            )}
            {!rowsLoading && items.length === 0 && (
              <tr>
                <td colSpan={7} className="p-4 text-center text-muted-foreground">
                  No submissions match these filters.
                </td>
              </tr>
            )}
            {items.map((row) => (
              <tr key={row.id} className="border-t border-border hover:bg-muted/10">
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
