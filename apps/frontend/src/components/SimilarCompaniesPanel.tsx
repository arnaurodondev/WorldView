import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { gateway, SimilarEntityResult } from "../lib/gateway-client";

// ── Score bar ─────────────────────────────────────────────

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "0.5rem",
        minWidth: 120,
      }}
    >
      <div
        style={{
          flex: 1,
          height: 6,
          background: "var(--border)",
          borderRadius: 3,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: "var(--accent, #4f8ef7)",
            borderRadius: 3,
          }}
        />
      </div>
      <span style={{ fontSize: "0.75rem", color: "var(--text-secondary)", minWidth: 32 }}>
        {pct}%
      </span>
    </div>
  );
}

// ── Result row ────────────────────────────────────────────

function SimilarEntityRow({ item }: { item: SimilarEntityResult }) {
  return (
    <tr style={{ borderTop: "1px solid var(--border)" }}>
      <td style={{ padding: "0.5rem" }}>
        <span
          style={{
            display: "inline-block",
            background: "var(--bg-secondary)",
            border: "1px solid var(--border)",
            borderRadius: 4,
            padding: "0 6px",
            fontSize: "0.75rem",
            fontWeight: "bold",
          }}
        >
          {item.ticker ?? "—"}
        </span>
      </td>
      <td style={{ padding: "0.5rem" }}>
        {item.canonical_name}
        {item.has_competes_with_relation && (
          <span
            style={{
              marginLeft: "0.5rem",
              background: "#ffe8e8",
              color: "#c0392b",
              borderRadius: 4,
              padding: "1px 6px",
              fontSize: "0.7rem",
              fontWeight: "bold",
            }}
          >
            Competitor
          </span>
        )}
      </td>
      <td style={{ padding: "0.5rem" }}>{item.exchange ?? "—"}</td>
      <td style={{ padding: "0.5rem" }}>
        <ScoreBar score={item.final_score} />
      </td>
    </tr>
  );
}

// ── "View all" modal ─────────────────────────────────────

function ViewAllModal({
  entityId,
  onClose,
}: {
  entityId: string;
  onClose: () => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["similarEntities", entityId, 50],
    queryFn: () => gateway.findSimilarEntities(entityId, { top_k: 50 }),
  });

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: "var(--bg-primary, #fff)",
          borderRadius: 8,
          padding: "1.5rem",
          maxWidth: 640,
          width: "90%",
          maxHeight: "80vh",
          overflowY: "auto",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "1rem" }}>
          <h3 style={{ margin: 0 }}>All Similar Companies</h3>
          <button onClick={onClose}>✕</button>
        </div>
        {isLoading ? (
          <p>Loading…</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.875rem" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", padding: "0.5rem" }}>Ticker</th>
                <th style={{ textAlign: "left", padding: "0.5rem" }}>Name</th>
                <th style={{ textAlign: "left", padding: "0.5rem" }}>Exchange</th>
                <th style={{ textAlign: "left", padding: "0.5rem" }}>Score</th>
              </tr>
            </thead>
            <tbody>
              {data?.results.map((item) => (
                <SimilarEntityRow key={item.entity_id} item={item} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ── Panel ──────────────────────────────────────────────────

interface SimilarCompaniesPanelProps {
  /** The knowledge-graph entity_id of the company being viewed. */
  entityId: string;
}

export function SimilarCompaniesPanel({ entityId }: SimilarCompaniesPanelProps) {
  const [expanded, setExpanded] = useState(true);
  const [showAll, setShowAll] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ["similarEntities", entityId, 10],
    queryFn: () => gateway.findSimilarEntities(entityId, { top_k: 10 }),
    enabled: expanded,
  });

  const results = data?.results ?? [];

  return (
    <section style={{ marginTop: "2rem" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          cursor: "pointer",
          padding: "0.75rem 0",
          borderTop: "1px solid var(--border)",
        }}
        onClick={() => setExpanded((v) => !v)}
      >
        <h3 style={{ margin: 0 }}>Similar Companies</h3>
        <span style={{ color: "var(--text-secondary)" }}>{expanded ? "▲" : "▼"}</span>
      </div>

      {expanded && (
        <div>
          {isLoading && (
            <div style={{ padding: "1rem 0" }}>
              {[...Array(5)].map((_, i) => (
                <div
                  key={i}
                  style={{
                    height: 32,
                    background: "var(--border)",
                    borderRadius: 4,
                    marginBottom: "0.5rem",
                    opacity: 0.5,
                  }}
                />
              ))}
            </div>
          )}

          {error && (
            <p style={{ color: "var(--text-secondary)", fontStyle: "italic" }}>
              Similar companies unavailable.
            </p>
          )}

          {!isLoading && !error && results.length === 0 && (
            <p style={{ color: "var(--text-secondary)", fontStyle: "italic" }}>
              No similar companies found.
            </p>
          )}

          {results.length > 0 && (
            <>
              <table
                style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.875rem" }}
              >
                <thead>
                  <tr>
                    <th style={{ textAlign: "left", padding: "0.5rem" }}>Ticker</th>
                    <th style={{ textAlign: "left", padding: "0.5rem" }}>Name</th>
                    <th style={{ textAlign: "left", padding: "0.5rem" }}>Exchange</th>
                    <th style={{ textAlign: "left", padding: "0.5rem" }}>Similarity</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((item) => (
                    <SimilarEntityRow key={item.entity_id} item={item} />
                  ))}
                </tbody>
              </table>

              {(data?.total ?? 0) > 10 && (
                <button
                  onClick={() => setShowAll(true)}
                  style={{ marginTop: "0.75rem", color: "var(--accent, #4f8ef7)" }}
                >
                  View all ({data!.total})
                </button>
              )}
            </>
          )}
        </div>
      )}

      {showAll && <ViewAllModal entityId={entityId} onClose={() => setShowAll(false)} />}
    </section>
  );
}
