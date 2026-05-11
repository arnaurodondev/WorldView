# infra/gitops — worldview-gitops Bootstrap Templates

This directory contains **starter files** for the `worldview-gitops` private repository.
They document the expected structure, scripts, and templates that worldview-gitops needs
to support production deployment of the worldview platform on Hetzner.

## How to use

1. Clone `worldview-gitops` (private repo containing production secrets):
   ```bash
   git clone git@github.com:your-org/worldview-gitops.git
   ```

2. Copy these starter templates into worldview-gitops and fill in actual secret values:
   ```bash
   cp -r infra/gitops/scripts worldview-gitops/scripts/
   cp -r infra/gitops/templates worldview-gitops/templates/
   cp -r infra/gitops/docs worldview-gitops/docs/
   ```

3. Follow `infra/gitops/docs/hetzner-setup.md` to provision the Hetzner server.

4. Follow `infra/gitops/docs/production-deployment.md` for the first deploy.

## Directory layout (target worldview-gitops structure)

```
worldview-gitops/
├── README.md
├── docs/
│   ├── hetzner-setup.md          ← Server provisioning from scratch
│   ├── production-deployment.md  ← First-deploy + update workflow
│   ├── vercel-deployment.md      ← Frontend split deployment (optional)
│   └── disaster-recovery.md      ← Backup + restore procedures
├── env/
│   ├── dev/                      ← Dev env files (copied by setup-dev.sh)
│   │   ├── portfolio.env
│   │   ├── market-ingestion.env
│   │   └── ...
│   └── prod/                     ← Production env files (copied by setup-prod.sh)
│       ├── platform.env          ← DOMAIN, ACME_EMAIL, ZITADEL_URL
│       ├── api-gateway.env       ← OIDC + RS256 keypair + all prod vars
│       └── ...                   ← One file per service
├── scripts/
│   ├── setup-dev.sh              ← Copies env/dev/* → worldview/services/*/configs/docker.env
│   ├── setup-prod.sh             ← Copies env/prod/* → worldview/services/*/configs/docker.env
│   ├── hetzner-bootstrap.sh      ← Idempotent server setup (Docker, UFW, swap)
│   └── verify-prod-health.sh     ← Post-deploy smoke tests
└── templates/
    └── platform.env.template     ← Annotated DOMAIN/ACME_EMAIL/ZITADEL template
```
