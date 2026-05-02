/**
 * lib/api/watchlists.ts — Watchlists CRUD + members + insights.
 *
 * Includes the `mapRawWatchlist` helper which is co-located here because it is
 * the watchlists-domain shape transformer (S1 envelope → frontend `Watchlist`)
 * and is used by every method that returns a Watchlist.
 *
 * NOTE on `this`: `getWatchlist` calls `this.getWatchlistMembers` and
 * `addWatchlistMember` calls `this.getWatchlist`. After the gateway shim
 * spreads this factory's return into the merged object, `this` resolves to
 * the merged object and both methods are present, so the calls work.
 */

import type { Watchlist, WatchlistInsights, WatchlistMember } from "@/types/api";
import { apiFetch } from "./_client";

/**
 * mapRawWatchlist — transform S1's WatchlistResponse into the frontend Watchlist type
 *
 * S1 returns: { id, tenant_id, user_id, name, status, created_at }
 * Frontend expects: { watchlist_id, name, owner_id, members, member_count, created_at, updated_at }
 *
 * Key differences:
 * - `id` → `watchlist_id` (domain naming convention)
 * - `user_id` → `owner_id` (frontend uses owner_id for consistency with Portfolio)
 * - `updated_at` defaults to `created_at` (S1 does not track updated_at on watchlists)
 *
 * PLAN-0046 / BP-265 — historical bug: this mapper used to hard-code
 *   `members: []`. That silently masked the missing `GET /watchlists/{id}/members`
 *   endpoint and made the tab look empty even when symbols had been added. Lesson:
 *   collections returned by gateway mappers must always come from a real fetch —
 *   defaulting to `[]` because "we don't have it yet" hides the gap. Callers
 *   pass the real members in via the optional `members` argument; if undefined
 *   we still default to [] but only to support the create/rename payloads which
 *   genuinely don't include members. List flows MUST resolve members before
 *   handing off to the UI.
 */
function mapRawWatchlist(
  raw: {
    id: string;
    tenant_id: string;
    user_id: string;
    name: string;
    status: string;
    created_at: string;
  },
  members?: WatchlistMember[],
): Watchlist {
  // WHY ?? not ||: explicit `[]` from the caller (an empty watchlist) is a
  // real value and must NOT be replaced with another empty array. Only
  // `undefined` (no caller-supplied members) falls through to the default.
  const resolvedMembers = members ?? ([] as WatchlistMember[]);
  return {
    watchlist_id: raw.id,
    name: raw.name,
    owner_id: raw.user_id,
    members: resolvedMembers,
    member_count: resolvedMembers.length,
    created_at: raw.created_at,
    updated_at: raw.created_at, // S1 has no updated_at; use created_at as fallback
  };
}

// Minimal `this` shape used by factory methods that delegate to siblings.
// Declared explicitly (not via ReturnType) because `ReturnType<typeof
// createWatchlistsApi>` would close a circular reference when used in a
// `this:` parameter inside the very same factory.
type WatchlistsApi = {
  getWatchlist(watchlistId: string): Promise<Watchlist>;
  getWatchlistMembers(watchlistId: string): Promise<WatchlistMember[]>;
};

export function createWatchlistsApi(t: string | undefined) {
  return {
    /**
     * getWatchlists — list all watchlists for the authenticated user
     *
     * WHY transform: S1 returns a bare array of `WatchlistResponse` objects with `id`
     * (not `watchlist_id`), `user_id` (not `owner_id`), and NO `members`, `member_count`,
     * or `updated_at` fields. The frontend type `Watchlist` uses domain-named fields and
     * includes member data. The list endpoint intentionally omits members for performance;
     * member data is only fetched when viewing a single watchlist.
     */
    async getWatchlists(): Promise<Watchlist[]> {
      const raw = await apiFetch<
        Array<{
          id: string;
          tenant_id: string;
          user_id: string;
          name: string;
          status: string;
          created_at: string;
        }>
      >("/v1/watchlists", { token: t });

      return (raw ?? []).map((wl) => mapRawWatchlist(wl));
    },

    /**
     * getWatchlist — single watchlist with member list
     *
     * PLAN-0046 / T-46-2-03 — now also fans out to `getWatchlistMembers` so
     * the returned `Watchlist` has a populated `members` array. Without this
     * the consumer of `getWatchlist` would see an empty tab (BP-265).
     *
     * WHY two requests: S1 keeps the watchlist metadata route and the members
     * route separate so the metadata can be cached independently. The cost is
     * one extra round-trip on a relatively cheap endpoint, which is acceptable.
     */
    async getWatchlist(this: WatchlistsApi, watchlistId: string): Promise<Watchlist> {
      // First fetch the watchlist metadata. We deliberately fire this before
      // the members request so a 404 here short-circuits the second call.
      const raw = await apiFetch<{
        id: string;
        tenant_id: string;
        user_id: string;
        name: string;
        status: string;
        created_at: string;
      }>(`/v1/watchlists/${encodeURIComponent(watchlistId)}`, { token: t });

      // Fetch the members in a second call. We do not run these in parallel
      // because if the first 404s we want to skip the second altogether.
      const members = await this.getWatchlistMembers(watchlistId);
      return mapRawWatchlist(raw, members);
    },

    /**
     * getWatchlistMembers — list members of a single watchlist
     *
     * PLAN-0046 / T-46-2-03 — pairs with the new
     * `GET /v1/watchlists/{id}/members` proxied to S1. Returns the raw
     * `WatchlistMember[]` shape used by the UI table; the gateway response
     * already matches the type so we just narrow the cast.
     *
     * WHY a method (not inlined into getWatchlist): the watchlists tab fetches
     * members lazily for the active watchlist only — fetching everyone's
     * members up-front would multiply the round-trips. Exposing this as its
     * own method lets the React component's `useQuery` cache members per
     * watchlist independently from the watchlist list.
     */
    async getWatchlistMembers(watchlistId: string): Promise<WatchlistMember[]> {
      const resp = await apiFetch<{
        members: Array<{
          entity_id: string;
          entity_type: string;
          ticker: string | null;
          name: string | null;
          instrument_id: string | null;
          added_at: string;
          // F-010 (QA 2026-04-28): backend reports "resolved" / "pending"
          // for each member so the UI can render a "resolving…" badge.
          resolution?: "resolved" | "pending";
        }>;
        total: number;
      }>(`/v1/watchlists/${encodeURIComponent(watchlistId)}/members`, { token: t });

      // Translate to the frontend `WatchlistMember` shape — `name` is a
      // required string in the type, so coerce nullable backend names to "—".
      // (Backend may return null when the local instrument cache miss
      // happened at add-time; see Alembic 0010 docstring.)
      return (resp.members ?? []).map((m) => ({
        entity_id: m.entity_id,
        instrument_id: m.instrument_id,
        ticker: m.ticker,
        name: m.name ?? "—",
        added_at: m.added_at,
        // Default to "resolved" for older backends that don't yet emit
        // the field — matches the previous behaviour (no badge).
        resolution: m.resolution ?? "resolved",
      }));
    },

    /**
     * getWatchlistInsights — composite insights for the WatchlistMoversWidget
     * (PLAN-0050 T-B-2-01).
     *
     * Replaces the widget's prior 5-query chain (members + quotes + per-member
     * overviews + news + alerts) with one round-trip. The gateway composes the
     * payload server-side so the dashboard can render gainers/losers + sector
     * concentration + active-alert flags + biggest-news callout from a single
     * cache slot.
     *
     * WHY a typed wrapper here (and not a bare apiFetch in the widget):
     * the response shape is non-trivial and shared by the widget + future
     * surfaces (e.g. an account sheet). Owning the type at the gateway boundary
     * means consumers can rely on a single source of truth for the contract.
     */
    async getWatchlistInsights(watchlistId: string): Promise<WatchlistInsights> {
      return apiFetch<WatchlistInsights>(
        `/v1/watchlists/${encodeURIComponent(watchlistId)}/insights`,
        { token: t },
      );
    },

    /**
     * createWatchlist — create a new watchlist
     *
     * WHY transform: S1 create returns the same `WatchlistResponse` shape (id, user_id, etc.)
     * which needs the same field mapping to the frontend `Watchlist` type.
     */
    async createWatchlist(name: string): Promise<Watchlist> {
      const raw = await apiFetch<{
        id: string;
        tenant_id: string;
        user_id: string;
        name: string;
        status: string;
        created_at: string;
      }>("/v1/watchlists", {
        method: "POST",
        body: { name },
        token: t,
      });

      return mapRawWatchlist(raw);
    },

    /**
     * renameWatchlist — rename a watchlist via PATCH /v1/watchlists/{id}
     *
     * WHY transform: S1 PATCH returns `WatchlistResponse` (id, user_id, …) which needs
     * the same field mapping to the frontend `Watchlist` type as create/get endpoints.
     */
    async renameWatchlist(watchlistId: string, newName: string): Promise<Watchlist> {
      const raw = await apiFetch<{
        id: string;
        tenant_id: string;
        user_id: string;
        name: string;
        status: string;
        created_at: string;
      }>(`/v1/watchlists/${encodeURIComponent(watchlistId)}`, {
        method: "PATCH",
        body: { name: newName },
        token: t,
      });

      return mapRawWatchlist(raw);
    },

    /**
     * deleteWatchlist — delete a watchlist
     */
    deleteWatchlist(watchlistId: string): Promise<void> {
      return apiFetch<void>(
        `/v1/watchlists/${encodeURIComponent(watchlistId)}`,
        { method: "DELETE", token: t },
      );
    },

    /**
     * addWatchlistMember — add an entity to a watchlist
     *
     * WHY transform: S1 returns `WatchlistMemberResponse` (the new member, not the full
     * watchlist). But the frontend expects the full `Watchlist` back. Since we don't have
     * the full watchlist data from S1's add-member response, we re-fetch the watchlist
     * after adding the member. This ensures the returned Watchlist has the correct member_count.
     */
    async addWatchlistMember(
      this: WatchlistsApi,
      watchlistId: string,
      entityId: string,
    ): Promise<Watchlist> {
      // S1 returns the new WatchlistMemberResponse, not the full watchlist
      await apiFetch<{
        id: string;
        watchlist_id: string;
        entity_id: string;
        entity_type: string;
        added_at: string;
      }>(`/v1/watchlists/${encodeURIComponent(watchlistId)}/members`, {
        method: "POST",
        body: { entity_id: entityId },
        token: t,
      });

      // Re-fetch the watchlist to return the complete Watchlist object
      // WHY re-fetch: S1's add-member endpoint returns only the new member, not the
      // full watchlist. The frontend needs the complete Watchlist with updated members.
      return this.getWatchlist(watchlistId);
    },

    /**
     * removeWatchlistMember — remove an entity from a watchlist
     */
    removeWatchlistMember(watchlistId: string, entityId: string): Promise<void> {
      return apiFetch<void>(
        `/v1/watchlists/${encodeURIComponent(watchlistId)}/members/${encodeURIComponent(entityId)}`,
        { method: "DELETE", token: t },
      );
    },
  };
}
