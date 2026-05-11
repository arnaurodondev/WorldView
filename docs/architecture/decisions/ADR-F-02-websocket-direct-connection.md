# ADR-F-02: WebSocket Direct Connection to S10 (Alert Delivery)

**Date**: 2026-04-18
**Status**: Accepted
**Deciders**: Arnau Rodon

## Context

Next.js API rewrites (configured in `next.config.ts`) operate at the HTTP level and do not
support WebSocket protocol upgrade. The alert service (S10) delivers real-time flash alerts
via WebSocket at `ws://<alert-host>:8010/v1/alerts/stream`.

The Worldview platform enforces a strict "frontend talks to S9 only" rule (R14 / CLAUDE.md
Hard Rule 14), which routes every HTTP request through the API Gateway. However, S9 is a
stateless HTTP proxy (httpx-based) and cannot transparently relay WebSocket frames.

The frontend requires a low-latency, persistent connection for CRITICAL flash alerts that
must render a full-screen overlay within milliseconds of emission.

## Decision

WebSocket connections bypass S9 API Gateway and connect **directly** to S10
(`alert-delivery:8010`) using a short-lived token obtained from S9.

The flow:

1. Frontend calls `GET /v1/auth/ws-token` on S9 (authenticated, Bearer token).
2. S9 issues a 30-second RS256 JWT scoped to WebSocket use (`purpose: "ws"`).
3. Frontend opens `ws://<NEXT_PUBLIC_WS_BASE_URL>/v1/alerts/stream?token=<ws_token>`.
4. S10 validates the short-lived token independently (RS256 verification via cached
   public key from `GET /internal/jwks`).
5. On token expiry or connection drop, the frontend obtains a fresh token and reconnects
   with exponential backoff (1s -> 2s -> 4s -> ... -> 30s cap).

This is the **ONLY** exception to the "frontend -> S9 only" rule.

**Referenced in**: `apps/worldview-web/contexts/AlertStreamContext.tsx`

## Consequences

### Positive

- Real-time alert delivery with minimal latency (no HTTP proxy hop)
- S9 remains stateless — no WebSocket session management needed in the gateway
- Short-lived token (30s) limits the blast radius of token interception

### Negative

- S10 must independently validate the short-lived JWT (additional verification logic)
- Frontend must handle WebSocket reconnection and token refresh (implemented in
  `AlertStreamContext.tsx` with exponential backoff)
- CORS for WebSocket is handled by S10, not S9 — origin validation must be configured
  on S10 separately

### Neutral

- This decision is scoped to real-time alert delivery only; all other data flows
  (including chat SSE streaming) continue to go through S9
- The WS token uses `?token=` query parameter because the browser WebSocket API does
  not support custom headers

## Alternatives Considered

| Alternative | Pros | Cons | Why Rejected |
|-------------|------|------|--------------|
| S9 WebSocket proxy | Single entry point, consistent with R14 | S9 is stateless httpx-based; WS proxy adds complexity, state, and latency | Breaks S9's stateless design; significant implementation overhead |
| SSE for alerts | Works through S9 HTTP proxy | Unidirectional only; higher latency; no binary frames; reconnection more complex | WebSocket is the standard for real-time bidirectional financial data |
| Long polling | Simplest to implement through S9 | High latency (seconds), high server load, poor UX for CRITICAL alerts | Unacceptable latency for flash alerts that require immediate overlay |

## References

- PRD-0025 (Auth Foundation) -- WebSocket JWT issuance in S9
- PRD-0028 (Worldview Web Frontend) -- Alert stream architecture
- `apps/worldview-web/contexts/AlertStreamContext.tsx` -- Implementation
- `services/api-gateway/src/api_gateway/routes/auth.py` -- `GET /v1/auth/ws-token`
- `docs/apps/worldview-web.md` -- Real-Time Patterns section
- Finding: F-MIN-008 (QA audit 2026-04-18)
