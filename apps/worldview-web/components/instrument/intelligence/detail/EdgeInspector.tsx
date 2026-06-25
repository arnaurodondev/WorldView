/**
 * detail/EdgeInspector.tsx — full relation (edge) dossier for the Intelligence
 * tab's selection inspector (PLAN-0099 Wave 2).
 *
 * WHY THIS EXISTS (replaces context/EdgeDetailCard.tsx):
 * The retired EdgeDetailCard could only echo back whatever fields happened to
 * ride on the cached GraphEdge (summary + ≤3 snippets) — no evidence dates, no
 * polarity, no provenance, no temporal validity. Wave 1 shipped a dedicated
 * GET /v1/relations/{relation_id} endpoint that returns the FULL edge dossier:
 * relation type, semantic mode, decay class, confidence (+ staleness flag),
 * validity period, contradiction stats, LLM summary provenance, both endpoint
 * entity summaries, and up to 25 evidence rows each carrying the raw
 * evidence_text chunk. This inspector renders all of it.
 *
 * ARTICLE-TITLE RESOLUTION (QA Wave-3 closeout, 2026-06-11):
 * Evidence rows carry document_id but NOT article title/url (R9 — no article
 * metadata in intelligence_db). The gateway added GET /v1/articles/{doc_id}
 * (content-store resolution) AFTER this inspector shipped, so titles were
 * never wired. We now resolve them client-side via useEvidenceArticleMetadata
 * (per-document cached queries) and merge into the forward-compat
 * `article_title`/`article_url` slots on RelationEvidenceItem. Rows whose
 * document_id cannot be resolved (loading / 404 / tombstoned) keep the
 * source_name + evidence_date fallback — never a dead slot.
 *
 * DATA SOURCE: useRelationDetail(relationId) → GET /v1/relations/{id};
 *              useEvidenceArticleMetadata → GET /v1/articles/{document_id}.
 * WHO USES IT: SelectionDetailPanel (edge mode).
 */

"use client";
// WHY "use client": TanStack Query hook + click handlers require the browser.

import {
  useRelationDetail,
  useEvidenceArticleMetadata,
  type EvidenceArticleMetadata,
} from "@/lib/api/intelligence";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatDate } from "@/lib/utils";
import type {
  RelationDetail,
  RelationEvidenceItem,
  RelationEntitySummary,
} from "@/lib/api/knowledge-graph";

// ── Props ────────────────────────────────────────────────────────────────────

export interface EdgeInspectorProps {
  /** GraphEdge.id == KG relation_id (guaranteed by the addEdgeWithKey fix). */
  readonly relationId: string;
  /** Selects an endpoint entity in the inspector (subject/object chips). */
  readonly onSelectNode?: (nodeId: string) => void;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * decayClass → semantic token classes. PERMANENT/DURABLE = stable signal
 * (positive); SLOW/MEDIUM = fades (warning); FAST/EPHEMERAL = transient
 * (negative). Ported from the retired EdgeDetailCard so the colour language
 * is unchanged.
 */
function decayBadgeClass(decayClass: string | null | undefined): string {
  const d = (decayClass ?? "").toUpperCase();
  if (d === "PERMANENT" || d === "DURABLE") return "text-positive bg-positive/15";
  if (d === "SLOW" || d === "MEDIUM") return "text-warning bg-warning/15";
  if (d === "FAST" || d === "EPHEMERAL") return "text-negative bg-negative/15";
  return "text-muted-foreground bg-muted";
}

/** polarity → dot colour class. Spec: each evidence row carries a polarity dot. */
function polarityDotClass(polarity: string | null | undefined): string {
  const p = (polarity ?? "").toLowerCase();
  if (p === "positive") return "bg-positive";
  if (p === "negative") return "bg-negative";
  return "bg-muted-foreground/60";
}

/** Small uppercase metadata chip — the inspector's repeating unit. */
function Chip({ label, className }: { label: string; className?: string }) {
  return (
    <span
      className={cn(
        "text-[9px] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded-[2px]",
        className ?? "text-muted-foreground bg-muted",
      )}
    >
      {label}
    </span>
  );
}

// ── Sub-component: endpoint entity pill (subject / object) ──────────────────

function EndpointPill({
  entity,
  onSelectNode,
}: {
  entity: RelationEntitySummary | null;
  onSelectNode?: (nodeId: string) => void;
}) {
  if (!entity) {
    return <span className="text-[11px] text-muted-foreground italic">unknown</span>;
  }
  const clickable = !!onSelectNode;
  const inner = (
    <>
      <span className="truncate text-[12px] font-semibold text-foreground" title={entity.canonical_name}>
        {entity.canonical_name}
      </span>
      {entity.ticker && (
        <span className="shrink-0 font-mono text-[9px] text-muted-foreground tabular-nums">
          {entity.ticker}
        </span>
      )}
    </>
  );
  // WHY a button when selectable: clicking an endpoint flips the inspector to
  // that entity's node dossier — the natural "walk the graph" affordance.
  if (clickable) {
    return (
      <button
        type="button"
        onClick={() => onSelectNode(entity.entity_id)}
        title={`Inspect ${entity.canonical_name}`}
        className="flex items-center gap-1.5 min-w-0 hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-[2px]"
      >
        {inner}
      </button>
    );
  }
  return <span className="flex items-center gap-1.5 min-w-0">{inner}</span>;
}

// ── Sub-component: one evidence row ─────────────────────────────────────────

function EvidenceRow({
  item,
  articleMeta,
}: {
  item: RelationEvidenceItem;
  /** Resolved article metadata for item.document_id (undefined while loading
   *  or when content-store doesn't know the doc — fallback rendering kicks in). */
  articleMeta?: EvidenceArticleMetadata;
}) {
  // Merge order: gateway-embedded fields win (future-proof), then the
  // client-side /v1/articles/{id} resolution, then null → source_name fallback.
  const articleTitle = item.article_title ?? articleMeta?.title ?? null;
  const articleUrl = item.article_url ?? articleMeta?.url ?? null;
  return (
    <li className="border-l-2 border-border/40 pl-2 py-1 space-y-0.5">
      {/* The chunk — quoted block, the reason the analyst opened this panel.
          blockquote = semantic HTML for quoted source material. */}
      <blockquote className="text-[11px] leading-snug text-foreground/80">
        {item.evidence_text ?? (
          <span className="italic text-muted-foreground">No evidence text captured.</span>
        )}
      </blockquote>
      {/* Provenance line: polarity dot · source · date · extraction conf ·
          trust. Mono numerics; nulls render as absent (no "—" noise). */}
      <div className="flex items-center gap-2 flex-wrap">
        <span
          className={cn("h-1.5 w-1.5 rounded-full shrink-0", polarityDotClass(item.polarity))}
          title={`Polarity: ${item.polarity ?? "neutral"}`}
          data-testid="evidence-polarity-dot"
          aria-label={`Polarity ${item.polarity ?? "neutral"}`}
        />
        {/* Article link: title/url come either embedded on the evidence row
            (future gateway change) or resolved client-side from
            GET /v1/articles/{document_id} (see file header). Falls back to
            source_name — never a dead slot. */}
        {articleUrl && articleTitle ? (
          <a
            href={articleUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[10px] text-foreground/80 hover:underline truncate max-w-[260px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-[2px]"
            title={articleTitle}
          >
            {articleTitle}
          </a>
        ) : (
          <span className="text-[10px] font-mono text-muted-foreground">
            {item.source_name ?? item.source_type ?? "unknown source"}
          </span>
        )}
        {item.source_type && item.source_name !== item.source_type && (
          <span className="text-[9px] font-mono uppercase tracking-wider text-muted-foreground/60">
            {item.source_type}
          </span>
        )}
        {item.evidence_date && (
          <span className="font-mono text-[9px] tabular-nums text-muted-foreground/70">
            {formatDate(item.evidence_date)}
          </span>
        )}
        {typeof item.extraction_confidence === "number" && (
          <span
            className="font-mono text-[9px] tabular-nums text-muted-foreground/70"
            title="LLM extraction confidence"
          >
            conf {item.extraction_confidence.toFixed(2)}
          </span>
        )}
        {typeof item.source_trust_weight === "number" && (
          <span
            className="font-mono text-[9px] tabular-nums text-muted-foreground/70"
            title="Source trust weight"
          >
            trust {item.source_trust_weight.toFixed(2)}
          </span>
        )}
      </div>
    </li>
  );
}

// ── Component ────────────────────────────────────────────────────────────────

export function EdgeInspector({ relationId, onSelectNode }: EdgeInspectorProps) {
  const { data, isLoading, isError, refetch } = useRelationDetail(relationId);

  // ── Loading: shape-matched skeleton (header line + chips + 2 evidence rows)
  if (isLoading) {
    return (
      <div className="p-3 space-y-2" data-testid="edge-inspector-skeleton" aria-busy="true">
        <Skeleton className="h-4 w-2/3" />
        <div className="flex gap-1.5">
          <Skeleton className="h-4 w-16 rounded-[2px]" />
          <Skeleton className="h-4 w-20 rounded-[2px]" />
          <Skeleton className="h-4 w-14 rounded-[2px]" />
        </div>
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );
  }

  // ── Named error + retry (per-section isolation: canvas keeps working) ────
  if (isError) {
    return (
      <div
        data-testid="edge-inspector-error"
        className="flex h-full flex-col items-center justify-center gap-1 px-3 py-4 text-center"
      >
        <p className="text-[12px] text-foreground">Couldn&apos;t load the relation detail</p>
        <p className="text-[11px] text-muted-foreground">
          The graph canvas and other panels are unaffected.
        </p>
        <button
          type="button"
          onClick={() => void refetch()}
          className="mt-1 font-mono text-[9px] uppercase tracking-wider text-primary hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-[2px]"
        >
          Retry
        </button>
      </div>
    );
  }

  // ── 404 → null: the relation was re-canonicalised away after the graph
  // snapshot. Named state — NOT an error (nothing to retry into existence).
  if (!data) {
    return (
      <div className="px-3 py-4 text-center" data-testid="edge-inspector-gone">
        <p className="text-[12px] text-foreground">Relation no longer available</p>
        <p className="text-[11px] text-muted-foreground">
          The knowledge graph re-consolidated this edge. Refresh the graph to see the current state.
        </p>
      </div>
    );
  }

  return <EdgeDossier detail={data} onSelectNode={onSelectNode} />;
}

// ── EdgeDossier — pure render of a loaded RelationDetail ────────────────────
// Split out so the loaded path stays readable (the wrapper above is all
// loading/error/null plumbing).

function EdgeDossier({
  detail,
  onSelectNode,
}: {
  detail: RelationDetail;
  onSelectNode?: (nodeId: string) => void;
}) {
  const relationLabel = detail.canonical_type.replace(/_/g, " ").toUpperCase();
  const confidencePct =
    typeof detail.confidence === "number" ? Math.round(detail.confidence * 100) : null;
  const hasContra = (detail.strongest_contra_score ?? 0) > 0;

  // Resolve article titles/urls for the evidence provenance lines (QA Wave-3).
  // Nulls are filtered HERE so the hook receives a clean id list; the hook
  // dedupes + sorts internally for stable query ordering.
  const articleMetaById = useEvidenceArticleMetadata(
    detail.evidence
      .map((e) => e.document_id)
      .filter((id): id is string => typeof id === "string" && id.length > 0),
  );

  return (
    <div className="p-3 space-y-2.5 text-left">
      {/* ── Header: SUBJECT → RELATION → OBJECT ─────────────────────────────
          The relation reads as a sentence; endpoints are clickable pills that
          walk the inspector to the entity dossier. */}
      <div className="flex items-center gap-2 flex-wrap min-w-0">
        <EndpointPill entity={detail.subject} onSelectNode={onSelectNode} />
        <span aria-hidden className="text-muted-foreground/60 shrink-0">→</span>
        <span className="shrink-0 font-mono text-[10px] text-primary">{relationLabel}</span>
        <span aria-hidden className="text-muted-foreground/60 shrink-0">→</span>
        <EndpointPill entity={detail.object} onSelectNode={onSelectNode} />
      </div>

      {/* ── Classification chips: semantic mode / decay / period / source ── */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {detail.semantic_mode && <Chip label={detail.semantic_mode.replace(/_/g, " ")} />}
        {detail.decay_class && (
          <Chip label={detail.decay_class} className={decayBadgeClass(detail.decay_class)} />
        )}
        {detail.relation_period_type && <Chip label={detail.relation_period_type} />}
        {detail.relation_source && <Chip label={detail.relation_source} />}
      </div>

      {/* ── Confidence bar + stale indicator ────────────────────────────────
          The ported "Strength" bar from EdgeDetailCard, now fed by the raw
          relation confidence and joined by the staleness flag (a stale score
          is a different signal from a low one — never silently merge them). */}
      {confidencePct != null && (
        <div className="flex items-center gap-2">
          <span className="text-[9px] font-mono text-muted-foreground uppercase tracking-wider shrink-0">
            Confidence
          </span>
          <div className="flex-1 h-[3px] bg-muted rounded-[1px]">
            <div
              className="h-full bg-foreground/60 rounded-[1px]"
              style={{ width: `${confidencePct}%` }}
            />
          </div>
          <span className="text-[10px] font-mono tabular-nums text-muted-foreground">
            {confidencePct} / 100
          </span>
          {detail.confidence_stale && (
            <Chip label="STALE" className="text-warning bg-warning/15" />
          )}
        </div>
      )}

      {/* ── Temporal validity — "since X" or "X → Y" ───────────────────────
          WHY always render when either bound exists: an expired relation
          (valid_to set) is exactly what an investigator must not miss. */}
      {(detail.valid_from || detail.valid_to) && (
        <p className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground">
          Valid{" "}
          <span className="tabular-nums text-foreground/70">
            {detail.valid_from ? formatDate(detail.valid_from) : "—"}
          </span>
          {" → "}
          <span className="tabular-nums text-foreground/70">
            {detail.valid_to ? formatDate(detail.valid_to) : "ongoing"}
          </span>
        </p>
      )}

      {/* ── Contradiction stats — only when contradicting evidence exists ── */}
      {hasContra && (
        <p className="text-[10px] text-warning" data-testid="edge-contra-stats">
          Contradicted — strongest counter-signal{" "}
          <span className="font-mono tabular-nums">
            {(detail.strongest_contra_score ?? 0).toFixed(2)}
          </span>
          {detail.latest_contra_at && (
            <span className="text-muted-foreground">
              {" "}
              (latest {formatDate(detail.latest_contra_at)})
            </span>
          )}
        </p>
      )}

      {/* ── LLM summary + provenance ────────────────────────────────────────
          Italic-muted when absent: the SummaryWorker simply hasn't processed
          this relation yet — a known state, not a failure. */}
      <div className="space-y-0.5">
        <p
          className={cn(
            "text-[11px] leading-relaxed",
            detail.relation_summary ? "text-foreground/85" : "text-muted-foreground italic",
          )}
        >
          {detail.relation_summary ?? "No summary available."}
        </p>
        {detail.relation_summary && (detail.summary_model_id || detail.summary_generated_at) && (
          <p className="font-mono text-[8px] uppercase tracking-wider text-muted-foreground/50">
            {detail.summary_model_id ?? "llm"}
            {detail.summary_generated_at ? ` · ${formatDate(detail.summary_generated_at)}` : ""}
          </p>
        )}
      </div>

      {/* ── Evidence list — the raw chunks ─────────────────────────────────── */}
      <div className="space-y-1">
        <header className="flex items-center justify-between">
          <h4 className="text-[9px] font-mono uppercase tracking-[0.07em] text-muted-foreground">
            Evidence
          </h4>
          <span className="font-mono text-[9px] tabular-nums text-muted-foreground">
            {/* total evidence_count may exceed the fetched page (limit 25) —
                show "shown / total" only when they differ to avoid noise. */}
            {detail.evidence_count != null && detail.evidence_count > detail.evidence.length
              ? `${detail.evidence.length} of ${detail.evidence_count}`
              : detail.evidence.length}
          </span>
        </header>
        {detail.evidence.length === 0 ? (
          <p className="text-[10px] text-muted-foreground italic">
            No evidence rows recorded for this relation.
          </p>
        ) : (
          <ul role="list" className="space-y-1.5">
            {detail.evidence.map((item) => (
              <EvidenceRow
                key={item.raw_id}
                item={item}
                articleMeta={
                  item.document_id ? articleMetaById.get(item.document_id) : undefined
                }
              />
            ))}
          </ul>
        )}
      </div>

      {/* ── Footer: first/latest evidence timestamps ───────────────────────── */}
      {(detail.first_evidence_at || detail.latest_evidence_at) && (
        <p className="font-mono text-[9px] text-muted-foreground/70">
          {detail.first_evidence_at && <>First seen {formatDate(detail.first_evidence_at)}</>}
          {detail.first_evidence_at && detail.latest_evidence_at && " · "}
          {detail.latest_evidence_at && <>Last seen {formatDate(detail.latest_evidence_at)}</>}
        </p>
      )}
    </div>
  );
}
