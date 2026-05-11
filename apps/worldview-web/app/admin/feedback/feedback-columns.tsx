/**
 * feedback-columns.tsx — ColumnDef factory for the admin feedback triage table.
 *
 * WHY THIS EXISTS: Extracted from app/admin/feedback/page.tsx (651 LOC) so the
 * column definitions can be tested independently of the full page component.
 * PLAN-0059 F-1 migration: replaces the raw <table>/<tbody> with DataTable.
 *
 * WHO USES IT: Admin support staff triaging incoming feedback.
 * DATA SOURCE: GET /v1/feedback/submissions (S9 → feedback service).
 *
 * FACTORY PATTERN: makeFeedbackColumns() takes per-row state refs (pending/failed
 * id sets and the PATCH callback) rather than passing them through column meta,
 * so the column renderers can close over the current Set values on each render.
 */

import React from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { FeedbackSubmission, FeedbackStatus } from "@/types/api";
import type { ColumnDef } from "@tanstack/react-table";

export const STATUS_OPTIONS: FeedbackStatus[] = [
  "open",
  "triaged",
  "in_progress",
  "resolved",
  "closed",
  "duplicate",
];

/**
 * makeFeedbackColumns — creates the 7 ColumnDef objects for the feedback table.
 *
 * WHY a factory (not a static array): three columns need per-row async state
 * (pending spinner, error glyph, status Select) that changes each render. Passing
 * those values as factory args lets the closure capture the latest Set values
 * without needing column meta or context.
 *
 * NOTE: selection column is NOT included — DataTable's selectable=true prop
 * renders it automatically.
 */
export function makeFeedbackColumns(
  rowPendingIds: Set<string>,
  rowFailedIds: Set<string>,
  updateRowStatus: (id: string, next: FeedbackStatus) => void,
): ColumnDef<FeedbackSubmission>[] {
  return [
    {
      id: "created_at",
      accessorKey: "created_at",
      header: "Created",
      size: 130,
      enableSorting: true,
      cell: ({ row }) => (
        <span className="font-mono tabular-nums text-[10px] text-muted-foreground">
          {row.original.created_at.slice(0, 19).replace("T", " ")}
        </span>
      ),
    },
    {
      id: "kind",
      accessorKey: "kind",
      header: "Kind",
      size: 100,
      enableSorting: true,
      cell: ({ row }) => (
        <span className="text-[10px] capitalize">
          {row.original.kind.replace("_", " ")}
        </span>
      ),
    },
    {
      id: "severity",
      accessorKey: "severity",
      header: "Severity",
      size: 80,
      enableSorting: true,
      cell: ({ row }) => (
        <span className="text-[10px]">{row.original.severity ?? "—"}</span>
      ),
    },
    {
      id: "status",
      accessorKey: "status",
      header: "Status",
      size: 160,
      enableSorting: true,
      cell: ({ row }) => (
        // WHY flex wrapper: the inline spinner/error glyph sits next to the
        // Select without reflowing the cell content on state changes.
        <div className="flex items-center gap-1.5">
          <Select
            value={row.original.status}
            onValueChange={(v) =>
              updateRowStatus(row.original.id, v as FeedbackStatus)
            }
            disabled={rowPendingIds.has(row.original.id)}
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
          {rowPendingIds.has(row.original.id) && (
            <Loader2
              className="h-3 w-3 motion-safe:animate-spin text-muted-foreground"
              aria-label="Saving status change"
            />
          )}
          {rowFailedIds.has(row.original.id) && (
            <AlertCircle
              className="h-3 w-3 text-destructive"
              aria-label="Failed to save — try again"
            />
          )}
        </div>
      ),
    },
    {
      id: "from",
      accessorFn: (row) => row.email ?? row.user_id ?? "",
      header: "From",
      size: 140,
      enableSorting: true,
      cell: ({ row }) => (
        <span className="font-mono text-[10px] text-muted-foreground">
          {row.original.email ?? row.original.user_id ?? "—"}
        </span>
      ),
    },
    {
      id: "description",
      accessorKey: "description",
      header: "Description",
      size: 320,
      enableSorting: false,
      cell: ({ row }) => (
        <span className="max-w-md truncate text-[10px]">
          {row.original.description}
        </span>
      ),
    },
    {
      id: "actions",
      header: "Actions",
      size: 80,
      enableSorting: false,
      cell: ({ row }) =>
        row.original.page_url ? (
          <a
            href={row.original.page_url}
            target="_blank"
            rel="noreferrer"
            className="text-[10px] text-primary underline"
            // WHY stop propagation: DataTable triggers onRowClick on any click;
            // for external links we want the browser to navigate, not the row handler.
            onClick={(e) => e.stopPropagation()}
          >
            Open page
          </a>
        ) : null,
    },
  ];
}
