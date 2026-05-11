# Secrets Management

## Two-Repo Architecture

Worldview uses two GitHub repositories:

| Repo | Visibility | Purpose |
|------|-----------|---------|
| `worldview` | **Public** | Product source code — services, libs, frontend, infra |
| `worldview-gitops` | **Private** | All configuration — dev env files, Helm charts, SOPS secrets, ArgoCD apps |

The `worldview` repo never contains secrets or env files.
`docker.env` files are written locally by `worldview-gitops/scripts/setup-dev.sh`
and are excluded by `.gitignore` (`services/*/configs/*.env`).

---

## First-Time Dev Setup

```bash
# 1. Clone both repos as siblings
git clone git@github.com:your-org/worldview.git
git clone git@github.com:your-org/worldview-gitops.git

# 2. Fill in real API keys where needed (FILL_ME_IN placeholders)
#    Edit worldview-gitops/env/dev/rag-chat.env  → RAG_CHAT_DEEPINFRA_API_KEY
#    Edit worldview-gitops/env/dev/market-ingestion.env → MARKET_INGESTION_EODHD_API_KEY
#    Other services work with defaults (demo key, MailHog, no key required)

# 3. Copy env files into the worldview repo
cd worldview-gitops
./scripts/setup-dev.sh

# 4. Start the stack
cd ../worldview
make dev
```

To update a single service after editing its env file:

```bash
cd worldview-gitops
./scripts/setup-dev.sh nlp-pipeline
cd ../worldview
docker compose ... restart nlp-pipeline
```

---

## Configuration Structure

```
worldview-gitops/          (PRIVATE)
├── env/
│   └── dev/
│       ├── portfolio.env          # Complete dev env for S1 — infra + secrets
│       ├── market-ingestion.env   # Complete dev env for S2
│       ├── market-data.env        # Complete dev env for S3
│       ├── content-ingestion.env  # Complete dev env for S4
│       ├── content-store.env      # Complete dev env for S5
│       ├── nlp-pipeline.env       # Complete dev env for S6 (all tunable params)
│       ├── knowledge-graph.env    # Complete dev env for S7
│       ├── rag-chat.env           # Complete dev env for S8 (LLM API keys here)
│       ├── api-gateway.env        # Complete dev env for S9 (JWT keypair here)
│       └── alert.env              # Complete dev env for S10
├── scripts/
│   └── setup-dev.sh               # Copies env/dev/*.env → worldview/services/*/configs/docker.env
├── values/
│   ├── <service>.yaml             # Kubernetes / Helm values (production)
│   └── dev/
│       └── <service>.yaml         # Legacy YAML format (kept as reference; env/dev/ is canonical)
├── charts/                        # Helm charts
└── ...
```

### What goes in `env/dev/`

Each file is a complete, flat `.env` for one service. Since this repo is private, all values
(infra config, model names, thresholds, API keys) live in the same file.

| Variable type | Example |
|---|---|
| Service hostnames | `NLP_PIPELINE_KAFKA_BOOTSTRAP_SERVERS=kafka:29092` |
| LLM model names | `NLP_PIPELINE_EMBEDDING_MODEL_ID=bge-large` |
| Tuning parameters | `NLP_PIPELINE_S6_DISPLAY_WEIGHT_MARKET=0.50` |
| MinIO dev credentials | `PORTFOLIO_STORAGE_ACCESS_KEY=minioadmin` |
| Dev JWT test keypair | `API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY=...` |
| External API keys | `RAG_CHAT_DEEPINFRA_API_KEY=...` |

---

## Required Secrets (FILL_ME_IN)

Services that require real API keys to work:

| Service | Variable | Source |
|---------|----------|--------|
| rag-chat | `RAG_CHAT_DEEPINFRA_API_KEY` | https://deepinfra.com |
| market-ingestion | `MARKET_INGESTION_EODHD_API_KEY` | https://eodhd.com (or leave as `demo`) |
| knowledge-graph | `KNOWLEDGE_GRAPH_GEMINI_API_KEY` | https://aistudio.google.com (only if `DESCRIPTION_PROVIDER=gemini`) |
| knowledge-graph | `KNOWLEDGE_GRAPH_EODHD_API_KEY` | https://eodhd.com |
| rag-chat | `RAG_CHAT_ANTHROPIC_API_KEY` | https://console.anthropic.com (optional) |
| api-gateway | `API_GATEWAY_OIDC_CLIENT_SECRET` | Zitadel (only if running full OIDC stack) |
| portfolio | `PORTFOLIO_SNAPTRADE_*` | https://snaptrade.com (optional — brokerage sync) |

Services that work with defaults and need no real keys: `market-data`, `content-ingestion`,
`content-store`, `alert` (uses MailHog), `nlp-pipeline`, `api-gateway` (OIDC optional).

---

## Rotating Secrets

To rotate a secret:

1. Edit the relevant `worldview-gitops/env/dev/<service>.env`
2. Run `./scripts/setup-dev.sh <service>` from `worldview-gitops`
3. Restart the service: `docker compose ... restart <service>`

To rotate the JWT keypair:

```bash
cd worldview
./scripts/generate-internal-keypair.sh   # prints new private + public key
# Paste them into worldview-gitops/env/dev/api-gateway.env
cd ../worldview-gitops
./scripts/setup-dev.sh api-gateway
```

---

## Security Notes

- `worldview-gitops` must remain a **PRIVATE** repository
- `services/*/configs/docker.env` files are `.gitignore`d — never committed to `worldview`
- The JWT keypair in `env/dev/api-gateway.env` is a dev-only test pair — never use it in production
- In CI/CD and Kubernetes, secrets come from SOPS-encrypted files in `worldview-gitops/secrets/`
  (managed by ArgoCD + age-key, not by `setup-dev.sh`)
- Rotate real API keys after any team member departure
