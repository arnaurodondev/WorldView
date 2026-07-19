# Built + pushed by CI (.github/workflows/deploy.yml, job build-smoke) on every
# main push touching infra/smoke/** or scripts/prod_e2e_smoke.py — never build
# this by hand (a manual build rots and ships a stale migration-head map).
#
# Minimal image for the in-cluster prod smoke CronJob: python3 (runs the harness)
# + kubectl (the harness shells out to it; in-cluster it uses the pod's
# ServiceAccount token automatically, no kubeconfig needed).
FROM python:3.11-slim

ARG KUBECTL_VERSION=v1.31.4
# curl is kept: the harness's Layer 1 (public edge) shells out to it, alongside
# kubectl. ca-certificates is required for the HTTPS/TLS-verify checks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSLo /usr/local/bin/kubectl \
        "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
    && chmod +x /usr/local/bin/kubectl \
    && rm -rf /var/lib/apt/lists/*

# The harness is stdlib-only — no pip deps.
COPY scripts/prod_e2e_smoke.py /app/prod_e2e_smoke.py
WORKDIR /app

# Default: full run, exit non-zero on any FAIL (the CronJob turns that into a
# failed Job, which a PrometheusRule alerts on). --layer overridable via args.
ENTRYPOINT ["python3", "/app/prod_e2e_smoke.py"]
