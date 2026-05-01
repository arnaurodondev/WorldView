/**
 * app/(app)/watchlists/[id]/page.tsx — Single watchlist detail page
 *
 * PLAN-0059 I-1: drill-down from the /watchlists hub. Shows watchlist name +
 * member table (ticker, name, status, added). Lets the user delete a member
 * (T2 confirm), rename the watchlist (inline edit), and delete the watchlist
 * (T3 typed-confirm).
 *
 * Members come from `gateway.getWatchlist(id)` which fans out to the metadata
 * + members endpoints internally (S1 split).
 */

"use client";

import { useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, Pencil, Trash2 } from "lucide-react";
import { useAuthedQuery, useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import {
  DataTable,
  type DataTableContextMenuItem,
} from "@/components/ui/data-table";
import { DestructiveButton } from "@/components/ui/destructive-button";
import type { WatchlistMember } from "@/types/api";
import type { ColumnDef } from "@tanstack/react-table";

export default function WatchlistDetailPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const watchlistId = params?.id;
  const gateway = useApiClient();
  const qc = useQueryClient();

  const [renameMode, setRenameMode] = useState(false);
  const [draftName, setDraftName] = useState("");

  const {
    data: watchlist,
    isLoading,
    isError,
    refetch,
  } = useAuthedQuery({
    queryKey: qk.watchlists.detail(watchlistId ?? ""),
    queryFn: (gw) => gw.getWatchlist(watchlistId!),
    enabled: !!watchlistId,
    staleTime: 15_000,
  });

  // ── Mutations ───────────────────────────────────────────────────────────

  const renameMut = useMutation({
    mutationFn: (newName: string) => gateway.renameWatchlist(watchlistId!, newName),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.watchlists.list() });
      void qc.invalidateQueries({ queryKey: qk.watchlists.detail(watchlistId!) });
      toast.success("Watchlist renamed");
      setRenameMode(false);
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Rename failed"),
  });

  const deleteMut = useMutation({
    mutationFn: () => gateway.deleteWatchlist(watchlistId!),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.watchlists.list() });
      toast.success("Watchlist deleted");
      router.replace("/watchlists");
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Delete failed"),
  });

  const removeMemberMut = useMutation({
    mutationFn: (entityId: string) =>
      gateway.removeWatchlistMember(watchlistId!, entityId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.watchlists.detail(watchlistId!) });
      toast.success("Member removed");
    },
    onError: (e) =>
      toast.error(e instanceof Error ? e.message : "Member removal failed"),
  });

  // ── Columns ─────────────────────────────────────────────────────────────

  const columns = useMemo<ColumnDef<WatchlistMember>[]>(
    () => [
      {
        id: "ticker",
        accessorKey: "ticker",
        header: "Ticker",
        size: 80,
        cell: ({ row }) => (
          <span className="font-mono text-[11px] tabular-nums text-primary truncate">
            {row.original.ticker ?? "—"}
          </span>
        ),
      },
      {
        id: "name",
        accessorKey: "name",
        header: "Name",
        size: 240,
        cell: ({ row }) => (
          <span className="text-[11px] text-foreground truncate">
            {row.original.name}
          </span>
        ),
      },
      {
        id: "resolution",
        accessorKey: "resolution",
        header: "Status",
        size: 90,
        cell: ({ row }) => {
          const s = row.original.resolution ?? "resolved";
          if (s === "pending") {
            return (
              <span className="rounded-[2px] bg-warning/15 px-1 font-mono text-[10px] uppercase tracking-wider text-warning">
                resolving
              </span>
            );
          }
          return (
            <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              ok
            </span>
          );
        },
      },
      {
        id: "added_at",
        accessorKey: "added_at",
        header: "Added",
        size: 100,
        cell: ({ row }) => (
          <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
            {new Date(row.original.added_at).toLocaleDateString("en-US", {
              month: "short",
              day: "numeric",
              timeZone: "UTC",
            })}
          </span>
        ),
      },
    ],
    [],
  );

  const contextMenu = useMemo<DataTableContextMenuItem<WatchlistMember>[]>(
    () => [
      {
        id: "open",
        label: "Open instrument",
        onClick: (m) =>
          router.push(`/instruments/${m.entity_id || m.instrument_id || ""}`),
      },
      {
        id: "remove",
        label: "Remove from watchlist",
        destructive: true,
        icon: <Trash2 className="h-3 w-3" />,
        onClick: (m) => removeMemberMut.mutate(m.entity_id),
      },
    ],
    [router, removeMemberMut],
  );

  // ── Render branches ─────────────────────────────────────────────────────

  if (!watchlistId) {
    return <div className="p-4 text-[11px] text-muted-foreground">Invalid URL.</div>;
  }

  if (isLoading) {
    return (
      <Shell title={null} onBack={() => router.push("/watchlists")}>
        <div className="space-y-1 p-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-[22px]" style={{ animationDelay: `${i * 30}ms` }} />
          ))}
        </div>
      </Shell>
    );
  }

  if (isError || !watchlist) {
    return (
      <Shell title={null} onBack={() => router.push("/watchlists")}>
        <div className="flex flex-col items-start gap-2 p-4">
          <InlineEmptyState message="Watchlist failed to load — it may have been deleted." />
          <Button variant="outline" density="compact" onClick={() => refetch()}>
            Retry
          </Button>
        </div>
      </Shell>
    );
  }

  return (
    <Shell
      title={watchlist.name}
      memberCount={watchlist.member_count}
      onBack={() => router.push("/watchlists")}
      renameMode={renameMode}
      onStartRename={() => {
        setDraftName(watchlist.name);
        setRenameMode(true);
      }}
      onCancelRename={() => setRenameMode(false)}
      onSaveRename={() => renameMut.mutate(draftName.trim())}
      draftName={draftName}
      onDraftChange={setDraftName}
      onDelete={() => deleteMut.mutate()}
    >
      {watchlist.members.length === 0 ? (
        <div className="flex flex-1 items-center justify-center px-4 py-12">
          <div className="max-w-md text-center">
            <h2 className="mb-1 font-mono text-sm uppercase tracking-[0.08em] text-foreground">
              No members yet
            </h2>
            <p className="text-[11px] text-muted-foreground">
              Add instruments from any instrument page or the screener — the
              "Add to watchlist" action will surface this list.
            </p>
          </div>
        </div>
      ) : (
        <DataTable<WatchlistMember>
          columns={columns}
          data={watchlist.members}
          getRowId={(m) => m.entity_id}
          density="compact"
          ariaLabel={`Members of ${watchlist.name}`}
          onRowClick={(m) =>
            router.push(`/instruments/${m.entity_id || m.instrument_id || ""}`)
          }
          contextMenu={contextMenu}
        />
      )}
    </Shell>
  );
}

// ── Layout shell ───────────────────────────────────────────────────────────

interface ShellProps {
  children: React.ReactNode;
  title: string | null;
  memberCount?: number;
  onBack: () => void;
  renameMode?: boolean;
  draftName?: string;
  onStartRename?: () => void;
  onCancelRename?: () => void;
  onSaveRename?: () => void;
  onDraftChange?: (v: string) => void;
  onDelete?: () => void;
}

function Shell({
  children,
  title,
  memberCount,
  onBack,
  renameMode,
  draftName,
  onStartRename,
  onCancelRename,
  onSaveRename,
  onDraftChange,
  onDelete,
}: ShellProps) {
  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex h-7 shrink-0 items-center gap-2 border-b border-border px-3">
        <Button
          variant="ghost"
          density="compact"
          onClick={onBack}
          aria-label="Back to watchlists"
          className="px-1"
        >
          <ArrowLeft className="h-3 w-3" />
        </Button>
        {title === null ? (
          <Skeleton className="h-3 w-32" />
        ) : renameMode ? (
          <form
            className="flex items-center gap-1"
            onSubmit={(e) => {
              e.preventDefault();
              onSaveRename?.();
            }}
          >
            <Input
              density="compact"
              autoFocus
              value={draftName ?? ""}
              onChange={(e) => onDraftChange?.(e.target.value)}
              className="h-5 w-48 px-1 py-0 text-[11px]"
              aria-label="Watchlist name"
            />
            <Button density="compact" type="submit" className="h-5 px-2 text-[10px]">
              Save
            </Button>
            <Button
              variant="ghost"
              density="compact"
              type="button"
              onClick={onCancelRename}
              className="h-5 px-2 text-[10px]"
            >
              Cancel
            </Button>
          </form>
        ) : (
          <>
            <h1 className="font-mono text-[11px] uppercase tracking-[0.08em] text-foreground">
              {title}
            </h1>
            {memberCount !== undefined && (
              <span className="font-mono text-[10px] tabular-nums text-muted-foreground/60">
                {memberCount}
              </span>
            )}
            {onStartRename && (
              <Button
                variant="ghost"
                density="compact"
                onClick={onStartRename}
                aria-label="Rename watchlist"
                className="px-1"
              >
                <Pencil className="h-3 w-3" />
              </Button>
            )}
          </>
        )}
        <div className="ml-auto flex items-center gap-1">
          {onDelete && title !== null && (
            <DestructiveButton
              tier="t3"
              density="compact"
              confirmTitle="Delete watchlist?"
              confirmDescription="All members will be removed. This action cannot be undone."
              typeToConfirm={title}
              onConfirm={onDelete}
            >
              <Trash2 className="h-3 w-3" /> Delete
            </DestructiveButton>
          )}
        </div>
      </div>
      {children}
    </div>
  );
}
