# Frontend Deployment — Vercel (PLAN-0121 SP-6 W3, T-15.1)

> **Target**: The Next.js frontend (`apps/worldview-web`) deploys to **Vercel**, NOT
> to the Hetzner k3s cluster. There is intentionally **no** in-cluster frontend
> ArgoCD Application and **no** entry for it in `.github/workflows/deploy.yml`
> (R14: the frontend talks only to S9, the api-gateway).
>
> This is a **MANUAL** deploy target configured once in the Vercel dashboard.
> `vercel.json` (next to this file) pins the build; everything else below is a
> one-time dashboard setup. Replace `<DOMAIN>` with your real apex domain
> (e.g. `example.com`) — nothing here hardcodes a real domain.

---

## 1. Connect the GitHub repo to Vercel

Vercel dashboard → **New Project** → Import the `worldview` GitHub repo, then:

| Setting | Value |
|---------|-------|
| **Root Directory** | `apps/worldview-web` |
| Framework Preset | `Next.js` (auto-detected) |
| Install Command | `pnpm install --frozen-lockfile` (from `vercel.json`) |
| Build Command | `pnpm build` (from `vercel.json`) |
| Output Directory | `.next` (from `vercel.json`) |
| Node.js version | `20.x` (matches `engines.node >= 20`) |

The **Root Directory** setting is what scopes the build to the app dir inside the
monorepo — `vercel.json` lives there so Vercel picks it up automatically.

---

## 2. Environment variables

Set in Vercel project → **Settings → Environment Variables**. Two classes:

- **Server-side** (used by Next.js SSR / route rewrites at request time):

| Variable | Value | Notes |
|----------|-------|-------|
| `API_GATEWAY_URL` | `https://api.<DOMAIN>` | S9 gateway public HTTPS URL. SSR runs outside Docker, so it CANNOT use the `http://api-gateway:8000` internal hostname — it needs the public URL. `next.config.ts` rewrites `/api/v1/*` → `API_GATEWAY_URL/v1/*`. |

- **Build-time** (`NEXT_PUBLIC_*` — baked into the client JS bundle by Next.js):

| Variable | Value | Notes |
|----------|-------|-------|
| `NEXT_PUBLIC_WS_BASE_URL` | `wss://api.<DOMAIN>` | MUST be `wss://` (not `ws://`): `middleware.ts` / `next.config.ts` enable `upgrade-insecure-requests` CSP + HSTS only when it starts with `wss://` (BP-324). Point at the gateway's WebSocket route host. |
| `NEXT_PUBLIC_ZITADEL_URL` | `https://<instance>.zitadel.cloud` | Zitadel issuer. Presence of this var also hides the local "Dev Login" affordance on the login page. |
| `NEXT_PUBLIC_ZITADEL_CLIENT_ID` | `<client-id>` | Zitadel OIDC public client id (PKCE). |

> `NEXT_PUBLIC_*` vars are frozen at **build** time, so a change requires a
> redeploy — not just a restart.

---

## 3. Custom domain

Vercel project → **Settings → Domains** → add `app.<DOMAIN>` and follow Vercel's
DNS instructions (CNAME/A record). This is the frontend origin referenced below.

---

## 4. Two backend-side changes REQUIRED for the Vercel domain to work

These live in the backend/gitops repos, **not** here, but the frontend is broken
without them:

1. **S9 CORS** — add the frontend origin to the api-gateway allow-list in
   `worldview-gitops/values/api-gateway.yaml` (`CORS_ORIGINS` /
   `API_GATEWAY_CORS_ORIGINS`), e.g. `https://app.<DOMAIN>`. Include the Vercel
   preview glob (`https://worldview-git-*.vercel.app`) if you use preview deploys.
2. **Zitadel redirect URIs** — in the Zitadel console → worldview-web app, add:
   - `https://app.<DOMAIN>/callback` (production)
   - `https://worldview-git-*.vercel.app/callback` (preview deployments)

---

## 5. Preview deployments

Vercel builds a preview URL per PR (`worldview-git-<branch>.vercel.app`). They
reuse the production `API_GATEWAY_URL` and Zitadel instance; they only additionally
need the preview-glob Zitadel redirect URI (step 4.2) and the preview-glob CORS
origin (step 4.1).

---

## 6. Smoke test after deploy

From a browser on `https://app.<DOMAIN>`:
1. Landing page renders styled (no unstyled HTML flash).
2. Login → Zitadel → `/callback` → dashboard loads.
3. DevTools → Network: `/api/v1/*` calls return 2xx (proxied to S9); the
   WebSocket to `wss://api.<DOMAIN>` connects.
4. No `upgrade-insecure-requests` / mixed-content errors.
