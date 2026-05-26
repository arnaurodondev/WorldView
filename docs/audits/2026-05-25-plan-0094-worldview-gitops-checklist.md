# PLAN-0094 — worldview-gitops Update Checklist

## env/prod/api-gateway.env — 4 vars
- API_GATEWAY_RATE_LIMIT_REQUESTS=2000
- API_GATEWAY_RATE_LIMIT_FINANCIAL_MUTATION_REQUESTS=20
- API_GATEWAY_RATE_LIMIT_UNAUTHENTICATED_REQUESTS=20
- API_GATEWAY_RATE_LIMIT_PUBLIC_FEEDBACK_REQUESTS=120

## env/prod/rag-chat.env — 7 vars
- RAG_CHAT_BRIEF_PREGEN_ENABLED=true
- RAG_CHAT_BRIEF_PREGEN_INTERVAL_HOURS=24
- RAG_CHAT_BRIEF_PREGEN_ACTIVE_WINDOW_DAYS=7
- RAG_CHAT_BRIEF_PREGEN_BATCH_SIZE=50
- RAG_CHAT_BRIEF_PREGEN_CONCURRENCY=4
- RAG_CHAT_BRIEF_FRESH_TTL_HOURS=30
- RAG_CHAT_BRIEF_LAST_GOOD_TTL_DAYS=7

## Verification after deploy
- [ ] api-gateway boots without error
- [ ] rag-chat-brief-scheduler container reaches running state
- [ ] Within 30s of boot, scheduler emits `brief_pregeneration_run_started`
- [ ] Grafana `rag_brief_pregeneration_eligible_users` matches `ZCARD active_users` in Valkey
- [ ] No 503s on GET /v1/briefings/morning during the first 24h

## Rollback
- Disable pre-gen: set `RAG_CHAT_BRIEF_PREGEN_ENABLED=false` and restart `rag-chat-brief-scheduler`; handler keeps working (falls through to on-demand or lastgood).
- Revert rate limits: zero the 3 new env vars or remove them; code defaults (20/20/120/2000) take over.
