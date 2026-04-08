import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { gateway, ScreenField, ScreenFilter, ScreenInstrumentResult } from "../lib/gateway-client";

// ── Filter form ──────────────────────────────────────────

const OP_LABELS: Record<string, string> = {
  lt: "<",
  lte: "≤",
  gt: ">",
  gte: "≥",
  eq: "=",
};

interface FilterRow {
  id: number;
  metric: string;
  op: ScreenFilter["op"];
  value: string;
}

function FilterForm({
  fields,
  filters,
  onChange,
}: {
  fields: ScreenField[];
  filters: FilterRow[];
  onChange: (rows: FilterRow[]) => void;
}) {
  const addRow = () =>
    onChange([
      ...filters,
      { id: Date.now(), metric: fields[0]?.name ?? "", op: "lt", value: "" },
    ]);

  const updateRow = (id: number, patch: Partial<FilterRow>) =>
    onChange(filters.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  const removeRow = (id: number) =>
    onChange(filters.filter((r) => r.id !== id));

  return (
    <div style={{ marginBottom: "1.5rem" }}>
      <h3 style={{ marginBottom: "0.5rem" }}>Filters</h3>
      {filters.map((row) => (
        <div
          key={row.id}
          style={{ display: "flex", gap: "0.5rem", marginBottom: "0.5rem", alignItems: "center" }}
        >
          <select
            value={row.metric}
            onChange={(e) => updateRow(row.id, { metric: e.target.value })}
            style={{ minWidth: 160 }}
          >
            {fields.map((f) => (
              <option key={f.name} value={f.name}>
                {f.label}
                {f.unit ? ` (${f.unit})` : ""}
              </option>
            ))}
          </select>
          <select
            value={row.op}
            onChange={(e) => updateRow(row.id, { op: e.target.value as ScreenFilter["op"] })}
          >
            {Object.entries(OP_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
          <input
            type="number"
            value={row.value}
            onChange={(e) => updateRow(row.id, { value: e.target.value })}
            placeholder="value"
            style={{ width: 100 }}
          />
          <button onClick={() => removeRow(row.id)} style={{ color: "var(--text-secondary)" }}>
            ✕
          </button>
        </div>
      ))}
      <button onClick={addRow}>+ Add filter</button>
    </div>
  );
}

// ── Results table ─────────────────────────────────────────

const PAGE_SIZES = [25, 50, 100] as const;

function exportCsv(results: ScreenInstrumentResult[], activeMetrics: string[]) {
  const cols = ["ticker", "name", "exchange", "sector", ...activeMetrics];
  const header = cols.join(",");
  const rows = results.map((r) => {
    const baseFields = [r.ticker ?? "", r.name ?? "", r.exchange ?? "", r.sector ?? ""];
    const metricFields = activeMetrics.map((m) => String(r.metrics[m] ?? ""));
    return [...baseFields, ...metricFields].map((v) => `"${v}"`).join(",");
  });
  const csv = [header, ...rows].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "screener-results.csv";
  a.click();
  URL.revokeObjectURL(url);
}

// ── Main page ─────────────────────────────────────────────

export function ScreenerPage() {
  const [filterRows, setFilterRows] = useState<FilterRow[]>([]);
  const [pageSize, setPageSize] = useState<number>(50);
  const [offset, setOffset] = useState(0);
  const [sortBy, setSortBy] = useState<string | null>(null);
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");
  const [submitted, setSubmitted] = useState(false);

  // Load field metadata
  const { data: fieldsData, isLoading: fieldsLoading } = useQuery({
    queryKey: ["screenFields"],
    queryFn: () => gateway.getScreenFields(),
  });

  const fields = fieldsData?.fields ?? [];

  // Build valid filters for the query
  const validFilters: ScreenFilter[] = filterRows
    .filter((r) => r.value !== "" && !isNaN(Number(r.value)))
    .map((r) => ({ metric: r.metric, op: r.op, value: Number(r.value) }));

  const activeMetrics = [...new Set(validFilters.map((f) => f.metric))];

  // Screen query — only fires when submitted and filters are valid
  const { data: screenData, isFetching } = useQuery({
    queryKey: ["screen", validFilters, pageSize, offset, sortBy, sortOrder],
    queryFn: () =>
      gateway.screenInstruments(validFilters, {
        limit: pageSize,
        offset,
        sort_by: sortBy,
        sort_order: sortOrder,
      }),
    enabled: submitted && validFilters.length > 0,
  });

  const results = screenData?.results ?? [];
  const total = screenData?.total ?? 0;
  const totalPages = Math.ceil(total / pageSize);
  const currentPage = Math.floor(offset / pageSize);

  const handleSearch = () => {
    setOffset(0);
    setSubmitted(true);
  };

  const handleSort = (col: string) => {
    if (sortBy === col) {
      setSortOrder((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(col);
      setSortOrder("asc");
    }
    setOffset(0);
  };

  const SortIndicator = ({ col }: { col: string }) =>
    sortBy === col ? <span>{sortOrder === "asc" ? " ↑" : " ↓"}</span> : null;

  if (fieldsLoading) return <p>Loading screener fields…</p>;

  return (
    <div>
      <h2>Screener</h2>
      <p style={{ color: "var(--text-secondary)", marginBottom: "1rem" }}>
        Screen companies by financial metrics.
      </p>

      <FilterForm fields={fields} filters={filterRows} onChange={setFilterRows} />

      <div style={{ display: "flex", gap: "1rem", marginBottom: "1.5rem", alignItems: "center" }}>
        <button
          onClick={handleSearch}
          disabled={validFilters.length === 0 || isFetching}
          style={{ fontWeight: "bold" }}
        >
          {isFetching ? "Searching…" : "Search"}
        </button>
        {results.length > 0 && (
          <button onClick={() => exportCsv(results, activeMetrics)}>Export CSV</button>
        )}
        <label>
          Page size:{" "}
          <select
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value));
              setOffset(0);
            }}
          >
            {PAGE_SIZES.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </div>

      {submitted && !isFetching && total === 0 && validFilters.length > 0 && (
        <p style={{ color: "var(--text-secondary)" }}>No results match your filters.</p>
      )}

      {results.length > 0 && (
        <>
          <p style={{ marginBottom: "0.75rem", color: "var(--text-secondary)" }}>
            Showing {offset + 1}–{Math.min(offset + results.length, total)} of {total} results
          </p>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.875rem" }}>
              <thead>
                <tr>
                  {(["ticker", "name", "exchange", "sector"] as const).map((col) => (
                    <th
                      key={col}
                      onClick={() => handleSort(col)}
                      style={{ cursor: "pointer", textAlign: "left", padding: "0.5rem" }}
                    >
                      {col.charAt(0).toUpperCase() + col.slice(1)}
                      <SortIndicator col={col} />
                    </th>
                  ))}
                  {activeMetrics.map((m) => {
                    const fieldMeta = fields.find((f) => f.name === m);
                    return (
                      <th
                        key={m}
                        onClick={() => handleSort(m)}
                        style={{ cursor: "pointer", textAlign: "right", padding: "0.5rem" }}
                      >
                        {fieldMeta?.label ?? m}
                        {fieldMeta?.unit ? ` (${fieldMeta.unit})` : ""}
                        <SortIndicator col={m} />
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <tr key={r.instrument_id} style={{ borderTop: "1px solid var(--border)" }}>
                    <td style={{ padding: "0.5rem", fontWeight: "bold" }}>{r.ticker ?? "—"}</td>
                    <td style={{ padding: "0.5rem" }}>{r.name ?? "—"}</td>
                    <td style={{ padding: "0.5rem" }}>{r.exchange ?? "—"}</td>
                    <td style={{ padding: "0.5rem" }}>{r.sector ?? "—"}</td>
                    {activeMetrics.map((m) => (
                      <td key={m} style={{ padding: "0.5rem", textAlign: "right" }}>
                        {r.metrics[m] != null ? r.metrics[m]!.toFixed(2) : "—"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem", alignItems: "center" }}>
              <button
                onClick={() => setOffset(Math.max(0, offset - pageSize))}
                disabled={offset === 0}
              >
                ← Prev
              </button>
              <span>
                Page {currentPage + 1} / {totalPages}
              </span>
              <button
                onClick={() => setOffset(offset + pageSize)}
                disabled={offset + pageSize >= total}
              >
                Next →
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
