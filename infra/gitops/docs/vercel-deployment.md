# Vercel Deployment Guide (Frontend Split)

> **Architecture**: Next.js frontend on Vercel, all backend services on Hetzner.
> **When to use**: For global CDN and automatic preview deployments per PR.
> **Alternative**: Run everything on Hetzner (`make prod`) — simpler, recommended for thesis.

---

## Decision Matrix

| Concern | Vercel (split) | Hetzner all-in |
|---------|---------------|----------------|
| Frontend TTFB | Edge CDN ~50ms globally | Single-region ~50–200ms |
| Preview deployments | Automatic per PR | Manual |
| Cost | Free tier (≤100 GB/month) | Included in server |
| Complexity | Two deploy pipelines | One `make prod-rebuild` |
| WebSocket | Works (direct browser→Hetzner) | Works |
| CORS | Must whitelist Vercel domain | Not needed |
| API_GATEWAY_URL | Must be public HTTPS URL | Docker-internal |

**Recommendation for thesis**: Use Hetzner-only unless you need global CDN.

---

## Hetzner Backend (unchanged)

When using Vercel for the frontend, run all backends on Hetzner as normal:

```bash
make prod  # all backends + Traefik
```

Remove `worldview-web` from the prod stack by commenting it out in `docker-compose.prod.yml`
or by adding a `profiles: [backend-only]` override. This prevents running two frontend instances.

---

## Vercel Setup

### 1. Connect the repository

In Vercel dashboard → New Project → Import from GitHub:
- Select the worldview repository
- **Root directory**: `apps/worldview-web`
- Framework preset: `Next.js` (auto-detected)
- Build command: `pnpm build`
- Install command: `pnpm install --frozen-lockfile`
- Output directory: `.next` (auto-detected)
- Node.js version: `20.x`

### 2. Set environment variables

Go to Vercel project → Settings → Environment Variables.

| Variable | Value | Scope |
|----------|-------|-------|
| `API_GATEWAY_URL` | `https://api.${DOMAIN}` | Production |
| `NEXT_PUBLIC_WS_BASE_URL` | `wss://ws.${DOMAIN}` | Production |
| `NEXT_PUBLIC_ZITADEL_URL` | `https://<instance>.zitadel.cloud` | All |
| `NEXT_PUBLIC_ZITADEL_CLIENT_ID` | `<client-id>` | All |
| `NEXT_PUBLIC_APP_NAME` | `Worldview` | All |

**Why these specific values:**

- `API_GATEWAY_URL=https://api.${DOMAIN}`: Vercel SSR runs server-side (not in Docker). It cannot use `http://api-gateway:8000` (that's the Docker-internal hostname). It must use the public HTTPS URL.
- `NEXT_PUBLIC_WS_BASE_URL=wss://ws.${DOMAIN}`: Must be `wss://` (not `ws://`) — this tells `middleware.ts` to enable `upgrade-insecure-requests` CSP and HSTS headers (BP-324).
- `NEXT_PUBLIC_*` vars are baked into the JavaScript bundle at build time by Next.js.

### 3. Configure custom domain

In Vercel project → Settings → Domains:
- Add `worldview.example.com` as a custom domain
- Follow Vercel's DNS instructions (typically add a CNAME or A record)
- **If Hetzner handles the domain**: change the `worldview.example.com` A record from Hetzner server IP to Vercel's IP/CNAME

### 4. Update Zitadel redirect URIs

In Zitadel console → Projects → worldview → Applications → worldview-web → Redirect URIs:
- Add `https://worldview.example.com/callback` (production)
- Add `https://worldview-git-*.vercel.app/callback` (preview deployments, uses glob)

### 5. Update CORS on api-gateway

In `env/prod/api-gateway.env`:
```bash
API_GATEWAY_CORS_ORIGINS=https://worldview.example.com,https://worldview.vercel.app
```

Re-run `setup-prod.sh` and restart api-gateway.

---

## Preview Deployments

Vercel creates a preview URL for each PR (e.g., `worldview-git-feat-xyz.vercel.app`).
These previews need:
1. Zitadel redirect URI allowing the preview pattern (wildcard glob)
2. `NEXT_PUBLIC_ZITADEL_URL` set to your Zitadel instance (already set at project level)
3. `API_GATEWAY_URL` pointing to Hetzner — preview deployments can reuse the production API

---

## Smoke Test (after Vercel deploy)

```bash
# From browser console on https://worldview.example.com:
# 1. Landing page loads (no unstyled HTML)
# 2. Login → redirects to Zitadel → callback → dashboard loads
# 3. Open browser DevTools → Network tab
#    - /api/v1/* calls return 200 (proxy to Hetzner API)
#    - WebSocket to wss://ws.${DOMAIN} connects successfully
# 4. No upgrade-insecure-requests errors (CSS/JS load correctly)
```

---

## Fallback: Remove Vercel, Use Hetzner Frontend

If you decide to move back to Hetzner-only:

1. Remove Vercel custom domain (point DNS back to Hetzner IP)
2. Re-enable `worldview-web` in `docker-compose.prod.yml`
3. Remove the `API_GATEWAY_URL=https://api.${DOMAIN}` override from Vercel
4. `make prod-rebuild` — worldview-web runs in Docker again
