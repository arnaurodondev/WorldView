# Zitadel Setup Guide — worldview Auth (PRD-0025)

Worldview uses [Zitadel](https://zitadel.com) as its OIDC provider. This document covers
both **local dev** (self-hosted Zitadel via Docker Compose) and **production** (Zitadel Cloud).

---

## Option A — Local Dev (Self-Hosted Zitadel)

For fully offline development:

```bash
docker compose -f infra/compose/docker-compose.zitadel.yml up -d
```

Zitadel console: **http://localhost:8088**
Default admin credentials: `zitadel-admin@zitadel.localhost` / `Password1!`

After startup:

1. Log in to the Zitadel console at http://localhost:8088
2. Create a new **Project**: name it `worldview`
3. Inside the project, create a **New Application**:
   - Type: **Web**
   - Auth Method: **PKCE**
   - Redirect URI: `http://localhost:5173/callback`
   - Post-logout URI: `http://localhost:5173`
4. Note the generated **Client ID** (no secret for PKCE)
5. Update your local S9 env file:

```bash
API_GATEWAY_OIDC_ISSUER_URL=http://localhost:8088
API_GATEWAY_OIDC_CLIENT_ID=<client-id-from-console>
API_GATEWAY_OIDC_CLIENT_SECRET=   # leave empty — PKCE uses no secret
API_GATEWAY_OIDC_AUDIENCE=<client-id-from-console>
API_GATEWAY_FRONTEND_URL=http://localhost:5173
API_GATEWAY_COOKIE_SECURE=false
```

---

## Option B — Zitadel Cloud (Production & Staging)

For production, use [Zitadel Cloud](https://zitadel.cloud) (free tier: up to 25k MAU).

1. Create a Zitadel Cloud account at https://zitadel.cloud
2. Create a new **Instance** (choose a subdomain, e.g. `worldview`)
3. From the console, create a **Project** named `worldview`
4. Create a **Web Application** (PKCE):
   - Redirect URIs: `https://app.<DOMAIN>/callback`
   - Post-logout redirect URIs: `https://app.<DOMAIN>`
   - Auth method: **PKCE** (no client secret)
   - Token type: **JWT** (RS256)
   - Enable `id_token userinfo assertion`
5. Copy the **Client ID** (no secret for PKCE)
6. Set env vars:

```bash
API_GATEWAY_OIDC_ISSUER_URL=https://<your-instance>.zitadel.cloud
API_GATEWAY_OIDC_CLIENT_ID=<client-id>
API_GATEWAY_OIDC_CLIENT_SECRET=   # empty for PKCE
API_GATEWAY_OIDC_AUDIENCE=<client-id>
API_GATEWAY_FRONTEND_URL=https://app.<DOMAIN>
API_GATEWAY_COOKIE_SECURE=true
```

Alternatively, automate Option B with Terraform (see `terraform/`).

---

## Option C — Terraform Automation (Zitadel Cloud)

The `terraform/` directory manages Zitadel Cloud resources via the
[zitadel/zitadel Terraform provider](https://registry.terraform.io/providers/zitadel/zitadel/latest/docs).

### Prerequisites

- [OpenTofu](https://opentofu.org) ≥ 1.7 (or Terraform ≥ 1.6)
- A Zitadel Cloud service account key file (JSON)
- Create `infra/zitadel/terraform/terraform.tfvars` (see `terraform/variables.tf` for required vars)

### Run

```bash
cd infra/zitadel/terraform
tofu init
tofu plan
tofu apply
```

After apply, `tofu output` prints the Client ID to set in S9's env file.

> **Note**: If the Zitadel provider has issues (OQ-007 DEFERRED), fall back to the manual
> console steps in Option B above.

---

## RSA Keypair (S9 Internal JWT)

S9 signs internal JWTs with an RSA-2048 private key. Generate one with:

```bash
./scripts/generate-internal-keypair.sh
```

Add the output to your `.env` file. The private key stays on S9 only — never share it.

---

## Required Env Vars Summary

| Service | Var | Value |
|---------|-----|-------|
| S9 | `API_GATEWAY_OIDC_ISSUER_URL` | Zitadel issuer URL |
| S9 | `API_GATEWAY_OIDC_CLIENT_ID` | PKCE client ID |
| S9 | `API_GATEWAY_OIDC_CLIENT_SECRET` | Empty (PKCE) |
| S9 | `API_GATEWAY_OIDC_AUDIENCE` | Same as CLIENT_ID |
| S9 | `API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY` | RSA-2048 PEM (from keypair script) |
| S9 | `API_GATEWAY_INTERNAL_JWT_PUBLIC_KEY` | RSA-2048 PEM (from keypair script) |
| S1–S10 | `<SERVICE>_API_GATEWAY_URL` | `http://api-gateway:8000` (docker) or `http://localhost:8000` (local) |
