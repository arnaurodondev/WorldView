# DeepInfra API Key — Rotation Runbook & De-Fragilization Plan

> The **entire ML pipeline** (chat, embedding, extraction, relevance scoring,
> unresolved-entity resolution, KG scheduler descriptions, and the api-gateway NL
> screener) runs on a **single DeepInfra account key**. That one key is duplicated
> across **8 environment variables in 4 services**. When it is revoked or rotated,
> every ML feature dies at once — historically with **no alert** (keys died
> 2026-06-17, 2026-06-30). This document is the source-of-truth map and rotation
> procedure so a rotation is a controlled, verifiable operation.

**NEVER commit the real key to this repo.** It lives only in the gitignored
`services/*/configs/docker.env` files, which are copied from the private
**worldview-gitops** source-of-truth repo (`scripts/setup-dev.sh` for dev,
`env/prod` overlay for prod). The tracked `*.env.example` templates carry
placeholders only.

---

## 1. The full var → service map (source of truth = worldview-gitops)

All 8 vars below must hold the **same** DeepInfra account key.

| # | Env var | Service | docker.env file | pydantic field |
|---|---------|---------|-----------------|----------------|
| 1 | `RAG_CHAT_DEEPINFRA_API_KEY` | rag-chat (S8) | `services/rag-chat/configs/docker.env` | `Settings.deepinfra_api_key` |
| 2 | `NLP_PIPELINE_EMBEDDING_API_KEY` | nlp-pipeline (S6) — embedding | `services/nlp-pipeline/configs/docker.env` | `embedding_api_key` |
| 3 | `NLP_PIPELINE_EXTRACTION_API_KEY` | nlp-pipeline (S6) — deep extraction | ″ | `extraction_api_key` |
| 4 | `NLP_PIPELINE_RELEVANCE_SCORING_API_KEY` | nlp-pipeline (S6) — relevance worker | ″ | `relevance_scoring_api_key` |
| 5 | `NLP_PIPELINE_UNRESOLVED_RESOLUTION_API_KEY` | nlp-pipeline (S6) — resolution worker | ″ | `unresolved_resolution_api_key` |
| 6 | `KNOWLEDGE_GRAPH_EMBEDDING_API_KEY` | knowledge-graph (S7) — embedding refresh | `services/knowledge-graph/configs/docker.env` | `embedding_api_key` |
| 7 | `KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY` | knowledge-graph (S7) — extraction/description | ″ | `deepinfra_api_key` |
| 8 | `API_GATEWAY_DEEPINFRA_API_KEY` | api-gateway (S9) — NL screener | `services/api-gateway/configs/docker.env` | `deepinfra_api_key` |

> `libs/ml-clients` `router_embedding_api_key` is populated per-service from one of
> the vars above (it is not a 9th independent secret). The synthetic monitor's
> `DEEPINFRA_API_KEY` (see §4) is a 9th *reference* copy used only for the health
> probe — keep it in sync too.

Each service loads `configs/docker.env` via `env_file:` in
`infra/compose/docker-compose.yml`. The env-var prefix is the service name
(pydantic-settings `env_prefix`), so field `deepinfra_api_key` in rag-chat →
`RAG_CHAT_DEEPINFRA_API_KEY`, etc.

---

## 2. Rotation procedure

### 2.1 In worldview-gitops (the source of truth — do this FIRST)
1. Generate a new key in the DeepInfra dashboard; revoke the old one **after** the
   deploy verifies (§2.3), not before, to avoid a gap.
2. Update the value in **all 8 vars** in the dev overlay (`env/dev`, consumed by
   `scripts/setup-dev.sh`) **and** the prod overlay (`env/prod`).
3. If you adopt the single-source pattern (§3), this becomes **one** line.
4. Commit + push worldview-gitops.

### 2.2 Apply to the running / fresh platform
- Dev: re-run `scripts/setup-dev.sh` (from worldview-gitops) to refresh the local
  `docker.env` files, then `make dev-rebuild` (or `docker compose up -d` for the 4
  ML services). A plain `make dev` on a fresh checkout now pulls the new key.
- Prod: redeploy per `infra/gitops/docs/production-deployment.md`.

### 2.3 Verify (redact to last-4 in any shared output)
```sh
# 1. Every container carries the SAME new key (tally last-4):
for c in $(docker ps --format '{{.Names}}'); do \
  docker exec "$c" sh -c 'printenv | grep -iE "DEEPINFRA_API_KEY|EMBEDDING_API_KEY|EXTRACTION_API_KEY|RELEVANCE_SCORING_API_KEY|UNRESOLVED_RESOLUTION_API_KEY"' 2>/dev/null; \
done | sed -E 's/=.*(.{4})$/ -> ...\1/' | awk '{print $NF}' | sort | uniq -c
# Expect a single distinct last-4 group. Two groups = a stale container.

# 2. The key authenticates (expect HTTP 200):
docker exec worldview-rag-chat-1 sh -c \
  'curl -s -o /dev/null -w "%{http_code}\n" \
   -H "Authorization: Bearer $RAG_CHAT_DEEPINFRA_API_KEY" \
   https://api.deepinfra.com/v1/openai/models'

# 3. No 401s in recent logs:
docker logs --since 10m worldview-rag-chat-1 2>&1 | grep -iE "401|unauthorized"
```
Only after all three pass: revoke the old key in DeepInfra.

---

## 3. De-fragilization proposal — collapse 8 vars → 1

**Goal:** the next rotation is a **one-line** change instead of an 8-place edit.

Because `env_file:` values are literal (no interpolation), the safe path is to move
the key out of the per-service `docker.env` files and inject it via compose
`environment:` interpolation from a single `${DEEPINFRA_API_KEY}` defined once in
`infra/compose/.env` (auto-loaded by compose) — sourced, in turn, from a single
`DEEPINFRA_API_KEY` line in the worldview-gitops overlay.

For each of the 4 ML services in `docker-compose.yml`, add an `environment:` block
that maps the service-specific var to the single source:
```yaml
  rag-chat:
    env_file: [../../services/rag-chat/configs/docker.env]
    environment:
      RAG_CHAT_DEEPINFRA_API_KEY: "${DEEPINFRA_API_KEY:?set DEEPINFRA_API_KEY}"
  nlp-pipeline:
    environment:
      NLP_PIPELINE_EMBEDDING_API_KEY: "${DEEPINFRA_API_KEY:?set DEEPINFRA_API_KEY}"
      NLP_PIPELINE_EXTRACTION_API_KEY: "${DEEPINFRA_API_KEY:?set DEEPINFRA_API_KEY}"
      NLP_PIPELINE_RELEVANCE_SCORING_API_KEY: "${DEEPINFRA_API_KEY:?set DEEPINFRA_API_KEY}"
      NLP_PIPELINE_UNRESOLVED_RESOLUTION_API_KEY: "${DEEPINFRA_API_KEY:?set DEEPINFRA_API_KEY}"
  knowledge-graph:
    environment:
      KNOWLEDGE_GRAPH_EMBEDDING_API_KEY: "${DEEPINFRA_API_KEY:?set DEEPINFRA_API_KEY}"
      KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY: "${DEEPINFRA_API_KEY:?set DEEPINFRA_API_KEY}"
  api-gateway:
    environment:
      API_GATEWAY_DEEPINFRA_API_KEY: "${DEEPINFRA_API_KEY:?set DEEPINFRA_API_KEY}"
```
Notes / safety:
- `environment:` **overrides** `env_file:`, so remove the key lines from the
  `docker.env` files at the same time to avoid two sources of truth.
- Use the `:?` (error-if-unset) form, **not** `:-` (empty default) — an empty
  default would silently override the env_file value with `""` and break the
  pipeline on a fresh deploy. `:?` fails the `docker compose up` loudly instead.
- This must be coordinated with worldview-gitops **in the same change**: replace
  the 8 lines in each overlay with one `DEEPINFRA_API_KEY=<key>` in
  `infra/compose/.env` (dev) / the prod overlay. Doing it half-way breaks deploys,
  which is why it is **not** applied unilaterally in this repo yet — it is a staged
  migration to run with a gitops PR.

**Interim (already applied in this repo):** all 4 `docker.env.example` templates now
document every DeepInfra var together with a shared-key note pointing here, so the
map is discoverable and a fresh `cp docker.env.example docker.env` is complete.

---

## 4. Safeguard — 401 freshness alert (applied)

`infra/synthetic/synthetic_monitor.py` gained `probe_deepinfra_key`, which every
60s calls DeepInfra `GET /v1/openai/models` with `DEEPINFRA_API_KEY` and reports
`synthetic_probe_success{probe_name="probe_deepinfra_key"}=0` on 401/403. Two
alerts consume it in `infra/prometheus/rules/alert-rules.yml`:
- generic `SyntheticProbeDown` (5m), and
- dedicated **`DeepInfraKeyDead`** (2m, critical) with this runbook linked.

Wiring: the `synthetic-monitor` compose service passes
`DEEPINFRA_API_KEY: "${DEEPINFRA_API_KEY:-}"` (empty = probe skips, no false alarm).
Set `DEEPINFRA_API_KEY` in `infra/compose/.env` to the same value as the service
keys so the probe is active in dev/prod. This closes the "no freshness alert" gap.
