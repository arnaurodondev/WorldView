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

import React, { useMemo, useState } from "react";
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
import { watchlistMembersColumns } from "../members-columns";
import type { WatchlistMember } from "@/types/api";

export default function WatchlistDetailPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const watchlistId = params?.id;
  const gateway = useApiClient();
  const qc = useQueryClient();

  const [renameMode, setRenameMode] = useState(false);
  const [draftName, setDraftName] = useState("");
  // QA-iter1: ref to the rename trigger button so focus returns to it after
  // a successful rename submit (would otherwise land on <body>).
  const renameTriggerRef = React.useRef<HTMLButtonElement | null>(null);

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
      // QA-iter1 a11y: return focus to the rename-trigger button after the
      // form unmounts. requestAnimationFrame defers until after React paints
      // the new DOM; without this focus drops to <body>.
      requestAnimationFrame(() => renameTriggerRef.current?.focus());
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

  // WHY not useMemo: watchlistMembersColumns is a static array (no closures over
  // mutable state) — importing directly avoids unnecessary memo bookkeeping.
  const columns = watchlistMembersColumns;

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
      renameTriggerRef={renameTriggerRef}
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
              &ldquo;Add to watchlist&rdquo; action will surface this list.
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
  /** Ref to the rename-trigger button so focus can return after submit. */
  renameTriggerRef?: React.RefObject<HTMLButtonElement | null>;
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
  renameTriggerRef,
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
                ref={renameTriggerRef}
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
