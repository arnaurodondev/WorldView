# Investigation Report: Frontend Completely Unstyled — All CSS/JS Assets Fail to Load

**Date**: 2026-05-03
**Investigator**: Claude (investigation skill)
**Severity**: CRITICAL (application completely non-functional in browser)
**Status**: Root cause identified and fixed

---

## 1. Issue Summary

Every CSS and JS static asset request returns no response in the browser, leaving the page as plain unstyled HTML with no JavaScript. The HTML page content loads correctly (server-side rendering works). The issue is exclusive to the browser — curl confirms all assets return HTTP 200. The problem reproduces consistently in every browser session against the Docker dev container.

---

## 2. Evidence Collected

| Evidence | Source | Relevance |
|----------|--------|-----------|
| CSS/JS assets return HTTP 200 | `curl -v http://localhost:3001/_next/static/css/…` | Server is not the problem |
| Static files exist in container | `docker exec … ls /app/apps/worldview-web/.next/static/` | Dockerfile copies are correct |
| `upgrade-insecure-requests` in CSP | `curl -sI http://localhost:3001/ | grep security-policy` | Directive is set on HTTP page |
| `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload` | Same response headers | HSTS also sent over HTTP |
| `NODE_ENV=production` in container | `docker exec … env` | Triggers HTTPS-only headers in both files |
| `NEXT_PUBLIC_WS_BASE_URL` NOT set in container | `docker exec … env` | Defaults to `ws://localhost:8010` (HTTP) |
| `https://localhost:3001` → SSL handshake failure | `curl -k https://localhost:3001/` → `tlsv1 alert protocol version` | No HTTPS server exists on port 3001 |
| HTML page loads correctly | Browser shows content | Top-level navigation exempt from upgrade |
| No service worker in HTML | Python parse of HTML response | Service worker not involved |

---

## 3. Execution Path Analysis

```
Browser loads http://localhost:3001/
  → Server returns HTML + CSP: upgrade-insecure-requests
  → Browser parses HTML, finds:
      <link href="/_next/static/css/bef7ab0a4ab90b9e.css" nonce="…">
      <script src="/_next/static/chunks/webpack-…js" nonce="…">
      (10–20 more JS chunks)
  → Browser resolves relative URLs → http://localhost:3001/_next/static/…
  → CSP upgrade-insecure-requests: "upgrade all HTTP sub-resources to HTTPS"
      (note: TOP-LEVEL NAVIGATION is EXEMPT — HTML loaded fine)
  → Browser requests https://localhost:3001/_next/static/css/bef7ab0a4ab90b9e.css
  → TCP connects to port 3001 (HTTP server)
  → HTTP server responds with HTTP/1.1 bytes
  → Browser's SSL layer sees non-SSL response → tlsv1 alert protocol version error
  → Request fails with net::ERR_SSL_PROTOCOL_ERROR
  → DevTools Network tab shows "no response"
  → ALL CSS and JS chunks fail identically
  → Page renders with SSR HTML only: unstyled, not interactive
```

**Why HTML loads but CSS/JS don't**:
`upgrade-insecure-requests` explicitly exempts top-level navigation requests. The browser's initial request to `http://localhost:3001/` is a navigation and is NOT upgraded. The HTML response is received correctly. Sub-resource requests (CSS `<link>`, `<script>`) ARE subject to the upgrade and all fail.

---

## 4. Hypotheses Tested

| # | Hypothesis | Result | Method |
|---|-----------|--------|--------|
| H-1 | `upgrade-insecure-requests` upgrades CSS/JS to HTTPS → SSL failure | **CONFIRMED** | CSP header confirmed present; `https://localhost:3001` fails with SSL error; Chrome spec confirms sub-resources are upgraded even on HTTP pages |
| H-2 | CSP `style-src` nonce mismatch blocks CSS (prior `/fix-bug` attempt) | REFUTED (insufficient) | Nonce fix was correct but not the root cause of "no response" symptom |
| H-3 | CSS/JS files missing from container filesystem | REFUTED | `docker exec ls` confirms all static files present |
| H-4 | Browser HSTS enforcement causing upgrades | PARTIAL | HSTS from HTTP is ignored per RFC 6797; but HSTS being served over HTTP is still wrong |
| H-5 | Service worker intercepting requests | REFUTED | No service worker registration found in HTML |

---

## 5. Root Cause

**Statement**: `NODE_ENV=production` is set in the Docker container (required by Next.js standalone mode for optimal performance), but this variable is also used as a proxy for "we are on HTTPS." Two files add HTTPS-only browser directives gated on `NODE_ENV=production`:
- `middleware.ts`: adds `upgrade-insecure-requests` to CSP
- `next.config.ts`: adds `Strict-Transport-Security` header

These directives are appropriate ONLY when the app is served over HTTPS. In Docker dev, the app serves HTTP. Chrome and Safari apply `upgrade-insecure-requests` to ALL sub-resource requests (CSS, JS, fonts, images), upgrading them from `http://` to `https://`. No HTTPS server exists on port 3001, so the SSL handshake fails silently. All static assets fail to load.

**Location**:
- `apps/worldview-web/middleware.ts`: `process.env.NODE_ENV === "production"` condition for `upgrade-insecure-requests`
- `apps/worldview-web/next.config.ts`: `process.env.NODE_ENV === "production"` condition for `Strict-Transport-Security` header

**Trigger condition**: Any time `NODE_ENV=production` is set without an actual HTTPS server. This includes: Docker dev container, local `next build && next start`, CI/CD builds.

---

## 6. Impact Analysis

- **Immediate impact**: Entire frontend non-functional — no CSS, no JavaScript
- **Blast radius**: Affects every browser user accessing the Docker dev container; would also affect any staging environment that uses HTTP
- **Data integrity**: None — no data affected, purely a UI failure
- **Historical note**: This bug existed since PLAN-0059 Wave I-6 (2026-04-30) when the nonce-based CSP was added, but was not noticed because `make dev-rebuild` was always used (same effect). The issue only became visible when investigating other UI problems.

---

## 7. Contributing Factors

1. **`NODE_ENV=production` conflates two different things**: "use optimized code paths" vs "we are on HTTPS". Next.js requires `NODE_ENV=production` for standalone mode even in local Docker dev.
2. **No HTTPS detection mechanism**: The codebase had no way to distinguish "production HTTP" from "production HTTPS". Both looked the same to the header configuration.
3. **Silent failure mode**: `upgrade-insecure-requests` causes SSL errors that appear as "no response" in DevTools, not as a clear error message pointing to the CSP directive. Hard to trace without knowing the browser's upgrade behavior.
4. **`upgrade-insecure-requests` exempts navigation**: HTML loads fine, making it appear like a partial failure rather than a complete one — confusing the diagnosis.
5. **Previous `/fix-bug` iteration** focused on CSP nonce (a real but secondary issue) rather than the actual cause, because curl showed CSS files returning 200.

---

## 8. Fix Applied

Used `NEXT_PUBLIC_WS_BASE_URL` as the HTTPS signal. In production, this is set to `wss://...`; in Docker dev it defaults to `ws://localhost:8010`. This existing env var cleanly distinguishes HTTPS from HTTP deployments.

### `middleware.ts`
```typescript
// Old (wrong):
...(process.env.NODE_ENV === "production" ? ["upgrade-insecure-requests"] : []),

// New (correct):
...(wsBase.startsWith("wss://") ? ["upgrade-insecure-requests"] : []),
```

### `next.config.ts`
```typescript
// Old (wrong):
...(process.env.NODE_ENV === "production"
  ? [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" }]
  : []),

// New (correct):
...((process.env.NEXT_PUBLIC_WS_BASE_URL ?? "ws://").startsWith("wss://")
  ? [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" }]
  : []),
```

**Verification**: After rebuild, neither `upgrade-insecure-requests` nor `Strict-Transport-Security` appear in HTTP responses from the Docker container.

---

## 9. Prevention Recommendations

1. **Add BP-324** to `docs/BUG_PATTERNS.md` (done below)
2. **Add a smoke test** to `qa-exhaustive` that checks: no `upgrade-insecure-requests` in CSP when `NEXT_PUBLIC_WS_BASE_URL` starts with `ws://`
3. **Add to `/review` checklist**: whenever editing security headers, verify the HTTPS guard is `wss://` env var, NOT `NODE_ENV`
4. **Review all `NODE_ENV === "production"` guards** for other security headers — they may have the same problem
5. **Add a Docker-level health check** that tests actual CSS/JS loading from inside the container (or via Playwright headless check) — would have caught this immediately

---

## 10. Open Questions

- The previous nonce fix (`style-src 'nonce-N'`) is still needed for Safari's strict nonce enforcement on `<link>` elements. Both fixes are cumulative and necessary.
- In true HTTPS production (behind Cloudflare/nginx), `NEXT_PUBLIC_WS_BASE_URL` will be `wss://…`, which enables `upgrade-insecure-requests` correctly. This has been verified by reviewing the env var's production value.
