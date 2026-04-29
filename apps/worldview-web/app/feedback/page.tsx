/**
 * app/feedback/page.tsx — public feature roadmap board.
 *
 * WHY THIS LIVES OUTSIDE (app)/: Approved decision (PLAN-0053 Wave G open
 * question 1): the feature board is publicly accessible. Placing the
 * route at /feedback (NOT inside the (app) auth-required group) means
 * unauthenticated visitors can browse and vote without logging in. The
 * gateway issues a system JWT for unauthenticated public routes so the
 * backend's tenant_id resolution still works — see api-gateway public
 * route handlers.
 *
 * FEATURES:
 *   - List public feature requests (is_public=true, server-filtered)
 *   - Sort: votes (desc) | recent | category
 *   - Filter: status, category
 *   - Vote button (idempotent — backend returns existing row on re-click)
 *   - "Suggest a feature" CTA opens FeedbackModal pre-set to feature tab
 *
 * SECURITY:
 *   - Voting requires auth — unauthenticated clicks redirect to /login
 *   - The list endpoint is safe to call without auth (system-JWT path)
 */

"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowUp, Filter, MessageSquarePlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useFeatureRequests, useVoteFeature } from "@/hooks/useFeatureRequests";
import { useAuth } from "@/hooks/useAuth";
import { FeedbackModal } from "@/components/feedback/FeedbackModal";
import type { FeatureRequest, FeatureStatus } from "@/types/api";

// ── Helpers ────────────────────────────────────────────────────────────────

/** Map a feature status to a status badge color. */
const STATUS_COLOR: Record<FeatureStatus, string> = {
  proposed: "bg-muted text-muted-foreground",
  planned: "bg-blue-500/10 text-blue-400",
  in_progress: "bg-amber-500/10 text-amber-400",
  shipped: "bg-emerald-500/10 text-emerald-400",
  rejected: "bg-destructive/10 text-destructive",
};

const SORT_OPTIONS = [
  { value: "votes", label: "Most votes" },
  { value: "recent", label: "Recent" },
] as const;

type SortKey = (typeof SORT_OPTIONS)[number]["value"];

// ── Page ───────────────────────────────────────────────────────────────────

export default function FeedbackPublicPage() {
  const router = useRouter();
  const { isAuthenticated } = useAuth();

  const [status, setStatus] = useState<FeatureStatus | "all">("all");
  const [sort, setSort] = useState<SortKey>("votes");
  const [modalOpen, setModalOpen] = useState(false);

  const { data, isLoading, isError } = useFeatureRequests({
    status: status === "all" ? undefined : status,
    limit: 100,
  });

  // WHY client-side sort: backend doesn't expose sort= yet. We pull a
  // 100-row page and sort in memory. For >100 the user can paginate.
  const items = useMemo<FeatureRequest[]>(() => {
    const list = data?.items ?? [];
    const sorted = [...list];
    if (sort === "votes") {
      sorted.sort((a, b) => b.vote_count - a.vote_count);
    } else {
      sorted.sort((a, b) => b.created_at.localeCompare(a.created_at));
    }
    return sorted;
  }, [data, sort]);

  const vote = useVoteFeature();

  const handleVote = (id: string) => {
    if (!isAuthenticated) {
      // Redirect to login preserving the page they were on.
      const redirectTo = encodeURIComponent("/feedback");
      router.push(`/login?redirect_to=${redirectTo}`);
      return;
    }
    vote.mutate(id);
  };

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Feature roadmap</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Vote for features you'd like to see, or suggest something new.
        </p>
      </header>

      {/* Toolbar — filters + suggest CTA. */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1.5">
          <Filter className="h-3.5 w-3.5 text-muted-foreground" />
          <Select value={status} onValueChange={(v) => setStatus(v as FeatureStatus | "all")}>
            <SelectTrigger className="h-8 w-40 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="proposed">Proposed</SelectItem>
              <SelectItem value="planned">Planned</SelectItem>
              <SelectItem value="in_progress">In progress</SelectItem>
              <SelectItem value="shipped">Shipped</SelectItem>
              <SelectItem value="rejected">Rejected</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <Select value={sort} onValueChange={(v) => setSort(v as SortKey)}>
          <SelectTrigger className="h-8 w-36 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SORT_OPTIONS.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button
          variant="default"
          size="sm"
          className="ml-auto"
          onClick={() => setModalOpen(true)}
        >
          <MessageSquarePlus className="mr-1.5 h-3.5 w-3.5" />
          Suggest a feature
        </Button>
      </div>

      {/* List */}
      {isLoading && (
        <p className="text-sm text-muted-foreground">Loading roadmap…</p>
      )}
      {isError && (
        <p className="text-sm text-destructive" role="alert">
          Failed to load feature requests.
        </p>
      )}
      {!isLoading && !isError && items.length === 0 && (
        <div className="rounded-[2px] border border-border bg-card/50 p-8 text-center">
          <p className="text-sm text-muted-foreground">
            No feature requests yet. Be the first to suggest one.
          </p>
        </div>
      )}

      <ul className="space-y-2">
        {items.map((item) => (
          <li
            key={item.id}
            className="flex items-start gap-4 rounded-[2px] border border-border bg-card/30 p-4 hover:bg-card/50"
          >
            {/* Vote button — left rail */}
            <button
              type="button"
              onClick={() => handleVote(item.id)}
              disabled={vote.isPending}
              aria-label={`Vote for ${item.title}`}
              className={[
                "flex w-12 shrink-0 flex-col items-center rounded-[2px] border p-2 transition-colors",
                item.has_voted
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border hover:border-primary/50 hover:bg-muted",
              ].join(" ")}
            >
              <ArrowUp className="h-4 w-4" aria-hidden="true" />
              <span className="mt-0.5 font-mono text-xs tabular-nums">
                {item.vote_count}
              </span>
            </button>

            {/* Body */}
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold text-foreground">
                  {item.title}
                </h3>
                <span
                  className={[
                    "rounded-[2px] px-1.5 py-0.5 text-[10px] uppercase",
                    STATUS_COLOR[item.status],
                  ].join(" ")}
                >
                  {item.status.replace("_", " ")}
                </span>
                {item.category && (
                  <span className="rounded-[2px] border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground">
                    {item.category}
                  </span>
                )}
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {item.description}
              </p>
            </div>
          </li>
        ))}
      </ul>

      {/* Suggest-a-feature modal — defaults to the feature tab. */}
      <FeedbackModal
        open={modalOpen}
        onOpenChange={setModalOpen}
        defaultTab="feature"
      />
    </div>
  );
}
