/**
 * Typed API client for the worldview gateway (S9).
 *
 * All frontend data fetching goes through this client.
 * In development, requests are proxied via Vite to localhost:8000.
 */

const BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
    ...init,
  });
  if (!res.ok) {
    throw new Error(`Gateway ${res.status}: ${await res.text()}`);
  }
  return res.json();
}

// ── Types ────────────────────────────────────────────────

export interface OHLCVBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface CompanyOverview {
  company_id: string;
  fundamentals: Record<string, unknown>;
  ohlcv: { bars: OHLCVBar[] };
  latest_news: { articles: Article[] };
}

export interface Article {
  id: string;
  title: string;
  source: string;
  published_at: string;
  url: string;
}

export interface MapLayer {
  id: string;
  label: string;
  enabled: boolean;
}

// ── Screener types (PRD-0017) ─────────────────────────────

export interface ScreenField {
  name: string;
  label: string;
  type: "numeric" | "text";
  unit: string | null;
  description: string | null;
  observed_min: number | null;
  observed_max: number | null;
  null_fraction: number;
}

export interface ScreenFilter {
  metric: string;
  op: "lt" | "lte" | "gt" | "gte" | "eq";
  value: number;
}

export interface ScreenInstrumentResult {
  instrument_id: string;
  ticker: string | null;
  name: string | null;
  exchange: string | null;
  sector: string | null;
  metrics: Record<string, number | null>;
}

export interface ScreenResponse {
  results: ScreenInstrumentResult[];
  count: number;
  total: number;
}

// ── Similar entities types (PRD-0017) ────────────────────

export interface SimilarEntityResult {
  entity_id: string;
  canonical_name: string;
  entity_type: string;
  ticker: string | null;
  exchange: string | null;
  ann_similarity_score: number;
  competes_with_confidence: number | null;
  final_score: number;
  has_competes_with_relation: boolean;
}

export interface SimilarEntitiesResponse {
  entity_id: string;
  canonical_name: string;
  results: SimilarEntityResult[];
  total: number;
}

// ── API methods ──────────────────────────────────────────

export const gateway = {
  getCompanyOverview: (id: string) =>
    request<CompanyOverview>(`/v1/companies/${id}/overview`),

  getRelevantNews: (limit = 20) =>
    request<{ articles: Article[] }>(`/v1/news/relevant?limit=${limit}`),

  getMapLayers: () =>
    request<{ layers: MapLayer[] }>("/v1/map/layers"),

  getScreenFields: () =>
    request<{ fields: ScreenField[] }>("/v1/fundamentals/screen/fields"),

  screenInstruments: (
    filters: ScreenFilter[],
    opts: {
      limit?: number;
      offset?: number;
      sort_by?: string | null;
      sort_order?: "asc" | "desc";
    } = {},
  ) =>
    request<ScreenResponse>("/v1/fundamentals/screen", {
      method: "POST",
      body: JSON.stringify({ filters, ...opts }),
    }),

  findSimilarEntities: (
    entityId: string,
    opts: { top_k?: number; min_score?: number; include_competitors_only?: boolean } = {},
  ) =>
    request<SimilarEntitiesResponse>("/v1/entities/similar", {
      method: "POST",
      body: JSON.stringify({ entity_id: entityId, ...opts }),
    }),

  /** Returns an EventSource for streaming chat. */
  streamChat(message: string): EventSource {
    // SSE via POST is non-standard; use fetch + ReadableStream in production.
    // This is a simplified version using EventSource on a GET fallback.
    return new EventSource(`${BASE}/v1/chat/stream?q=${encodeURIComponent(message)}`);
  },
};
