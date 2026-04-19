# Secrets Management

## Overview
Confidential credentials (API keys, OIDC secrets, email provider tokens) are stored
in a private GitHub repository (`worldview-config`), NOT in the main `worldview` repo.

## Repository Structure

```
worldview-config/
├── dev/                    # Development environment
│   ├── api-gateway.env     # S9 OIDC + JWT keys (test)
│   ├── portfolio.env       # S1 SnapTrade + storage
│   ├── market-ingestion.env # S2 EODHD key
│   ├── rag-chat.env        # S8 DeepInfra key
│   ├── alert.env           # S10 email provider
│   └── worldview-web.env   # Frontend env
├── prod/                   # Production environment
│   ├── api-gateway.env     # Real Zitadel OIDC + production JWT keys
│   ├── ...
│   └── worldview-web.env
└── README.md
```

## Fetching Secrets

```bash
# Requires: gh CLI authenticated with access to worldview-config
make fetch-secrets          # Fetches dev/ secrets
make fetch-secrets-prod     # Fetches prod/ secrets
```

## Creating the worldview-config Repo

1. Create a new PRIVATE repo on GitHub: `worldview-config`
2. Add `dev/` and `prod/` directories
3. For each service, create `<service-name>.env` with the confidential values
4. Only the variables that contain REAL credentials go here
5. Non-secret config (ports, hostnames, log levels) stays in the main repo's `.env.example` files

## What Goes Where

| Variable Type | Where | Example |
|-------------|-------|---------|
| API keys | worldview-config | EODHD_API_KEY, DEEPINFRA_API_KEY |
| OIDC secrets | worldview-config | OIDC_CLIENT_SECRET |
| JWT keypairs | worldview-config | INTERNAL_JWT_PRIVATE_KEY |
| Email credentials | worldview-config | RESEND_API_KEY, SMTP_PASSWORD |
| Service URLs | main repo (.env.example) | PORTFOLIO_URL=http://localhost:8001 |
| Port numbers | main repo (.env.example) | PORT=8001 |
| Log levels | main repo (.env.example) | LOG_LEVEL=INFO |
| Feature flags | main repo (.env.example) | DEBUG=false |

## Security Notes

- `worldview-config` must be a **PRIVATE** repository
- Only grant access to team members who need to run services locally
- Rotate secrets periodically (especially after team member departures)
- The `services/*/configs/docker.env` files are `.gitignore`d and will never be committed
- In CI/CD, secrets should come from GitHub Actions secrets or a proper vault, not from this repo
