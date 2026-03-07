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

// ── API methods ──────────────────────────────────────────

export const gateway = {
  getCompanyOverview: (id: string) =>
    request<CompanyOverview>(`/v1/companies/${id}/overview`),

  getRelevantNews: (limit = 20) =>
    request<{ articles: Article[] }>(`/v1/news/relevant?limit=${limit}`),

  getMapLayers: () =>
    request<{ layers: MapLayer[] }>("/v1/map/layers"),

  /** Returns an EventSource for streaming chat. */
  streamChat(message: string): EventSource {
    // SSE via POST is non-standard; use fetch + ReadableStream in production.
    // This is a simplified version using EventSource on a GET fallback.
    return new EventSource(`${BASE}/v1/chat/stream?q=${encodeURIComponent(message)}`);
  },
};
