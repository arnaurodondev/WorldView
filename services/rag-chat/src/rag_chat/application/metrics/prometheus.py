"""Prometheus metrics for the RAG-Chat service (T-F-4-04).

All 10 metrics from PRD §13.1. Metrics are module-level singletons
registered with the default Prometheus registry on import.
"""

from __future__ import annotations

from collections import deque

from prometheus_client import Counter, Gauge, Histogram

# ── Query lifecycle ──────────────────────────────────────────────────────────

rag_queries_total = Counter(
    "rag_chat_queries_total",
    "Total chat queries processed",
    ["intent", "provider", "tenant_id"],
)

rag_latency = Histogram(
    "rag_chat_latency_seconds",
    "Per-request latency broken down by pipeline step",
    ["intent", "step"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

rag_first_token = Histogram(
    "rag_chat_first_token_seconds",
    "Time to first token from LLM provider",
    ["provider"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

rag_retrieval_items = Histogram(
    "rag_retrieval_items_total",
    "Number of items retrieved per query by source type",
    ["source_type"],
    buckets=[0, 1, 5, 10, 15, 20, 30, 50],
)

# ── Cache ────────────────────────────────────────────────────────────────────

rag_cache_hits = Counter(
    "rag_cache_hit_total",
    "Number of cache hits",
    ["cache_type"],  # completion, hyde
)

# ── Provider ─────────────────────────────────────────────────────────────────

rag_provider_fallback = Counter(
    "rag_provider_fallback_total",
    "Number of provider fallback activations",
    ["from_provider", "to_provider"],
)

rag_provider_unavail = Counter(
    "rag_provider_unavailable_total",
    "Number of negative cache activations per provider",
    ["provider"],
)

# PLAN-0093 QA-7 P1-5: per-provider chat_with_tools failure counter.
# Companion to the structured `provider_chat_with_tools_failed` log so failures
# in the non-streaming tool-use path are dashable without scraping logs.
# Label cardinality bounded by provider chain (deepinfra / openrouter / ollama).
rag_chat_with_tools_failed = Counter(
    "rag_chat_with_tools_failed_total",
    "Number of times a provider's chat_with_tools call failed in the tool-use loop",
    labelnames=["provider"],
)

# FIX-LIVE-EE (2026-05-25): provider-chain in-place retry counter for iter-0
# chat_with_tools transient failures.  Distinct from rag_chat_with_tools_failed
# (which counts terminal per-provider failures) because retries that ultimately
# succeed are a normal happy path that we still want to track so operators can
# tune RAG_CHAT_PROVIDER_RETRY_ATTEMPTS / _BACKOFF_BASE against observed load.
#
# Labels:
#   provider — name of the provider being retried (deepinfra / openrouter)
#   attempt  — 1-indexed retry number (1 = first retry after initial failure)
#   outcome  — "success" (retry scheduled / succeeded) or "failure" (exhausted)
#
# Cardinality: at most providers (3) x attempts (<=5) x outcomes (2) = 30 series.
llm_provider_retry_attempt = Counter(
    "llm_provider_retry_attempt_total",
    "Provider-chain in-place retries on iter-0 transient failures",
    labelnames=["provider", "attempt", "outcome"],
)

# ── Threads ──────────────────────────────────────────────────────────────────

rag_thread_count = Gauge(
    "rag_thread_count",
    "Number of active (non-archived) conversation threads",
    ["tenant_id"],
)

# ── Safety ───────────────────────────────────────────────────────────────────

rag_contradiction_surfaced = Counter(
    "rag_contradiction_surfaced_total",
    "Number of contradictions surfaced to users",
    ["claim_type"],
)

rag_injection_blocked = Counter(
    "rag_injection_blocked_total",
    "Number of prompt injection attempts blocked",
)

# E-8: Layer 2 (LLM semantic) injection blocks specifically.
# Distinct from rag_injection_blocked (which covers Layer 1 regex + Layer 2).
rag_injection_blocked_layer2 = Counter(
    "rag_injection_blocked_layer2_total",
    "Number of prompt injection attempts blocked by Layer 2 LLM semantic classifier",
)

# NEW-016: Layer 2 classifier returned empty/unparseable content (e.g. reasoning
# model consumed max_tokens on chain-of-thought). We fail-open and emit this
# counter so operators see classifier dead-spots before they block real users.
rag_injection_classifier_indeterminate = Counter(
    "rag_injection_classifier_indeterminate_total",
    "Layer 2 classifier returned indeterminate output (empty/unparseable); failed open",
)

# BUG-FIX (DeepInfra 402 outage): the Layer 2 classifier could NOT RUN because
# its provider was unavailable / the transport failed (HTTP 402/429/5xx, connect
# or network error). This is DISTINCT from rag_injection_blocked_layer2 (which
# counts genuine UNSAFE verdicts) — conflating the two is exactly the bug that
# made a billing blip look like a flood of "injection detected" rejections.
# Operators alert on a sustained rate here to catch provider-availability
# incidents WITHOUT polluting the real injection-detection signal.
#
# Label ``reason`` is bounded: http_status | connect_error | network_error |
# unknown_transport_error.  ``status`` is the HTTP code string for http_status
# rows ("402"/"429"/"503"/…) and "n/a" otherwise — bounded by the small set of
# provider status codes we ever observe.
rag_injection_classifier_unavailable = Counter(
    "injection_classifier_unavailable_total",
    "Layer 2 injection classifier could not run (provider unavailable / transport error)",
    labelnames=["reason", "status"],
)

# ── Context management (PRD-0016 §13) ────────────────────────────────────────

rag_chunk_cache_hits = Counter(
    "s8_chunk_cache_hits_total",
    "Chunk cache hits — previous turn's chunks reused (all 3 conditions met)",
    ["intent"],
)

rag_chunk_cache_misses = Counter(
    "s8_chunk_cache_misses_total",
    "Chunk cache misses broken down by reason",
    ["reason"],  # no_cache | intent_mismatch | entity_mismatch | low_similarity
)

rag_turn_summary_duration = Histogram(
    "s8_turn_summary_duration_seconds",
    "Async LLM turn-summary generation latency",
    buckets=[0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0],
)

rag_context_token_estimate = Histogram(
    "s8_context_token_estimate",
    "Assembled ConversationContext token estimate per intent",
    ["intent"],
    buckets=[500, 1000, 1500, 2000, 3000, 4000, 5000, 6000],
)

# ── Retrieval quality (PLAN-0063 W5-5 T-W5-5-01) ─────────────────────────────

rag_retrieval_score_distribution = Histogram(
    "rag_retrieval_score_distribution",
    "Score distribution of chunks that survive fusion, by source_type",
    ["source"],
    buckets=[0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.0],
)

rag_source_contribution_total = Counter(
    "rag_source_contribution_total",
    "Number of queries where each source_type contributed at least one chunk to fusion",
    ["source"],
)

rag_reranker_position_change = Gauge(
    "rag_reranker_position_change",
    "Rolling fraction of queries where reranker's top-1 differed from fusion's top-1 (window=100)",
)

# Rolling window backing the gauge above. deque(maxlen=100) keeps the last 100 booleans.
_reranker_position_deque: deque[bool] = deque(maxlen=100)


def record_reranker_position_change(top_changed: bool) -> None:
    """Update the rolling reranker-position-change gauge."""
    _reranker_position_deque.append(top_changed)
    n = len(_reranker_position_deque)
    fraction = sum(_reranker_position_deque) / n if n > 0 else 0.0
    rag_reranker_position_change.set(fraction)


# ── Citation accuracy (PLAN-0063 W5-5 T-W5-5-02, PLAN-0084 A-1) ─────────────

# PLAN-0107 follow-up: the legacy ``rag_citation_accuracy`` gauge has been
# removed. It was dual-emitted with ``rag_citation_accuracy_24h`` during the
# PLAN-0099 W4 transition window, but no Grafana panel or external consumer
# ever referenced it (the new ``infra/grafana/dashboards/rag-chat.json``
# panel queries ``rag_citation_accuracy_24h`` directly), so the alias has
# been deleted cleanly. If you arrive here looking for the legacy name in a
# stored Grafana panel JSON, switch the query to ``rag_citation_accuracy_24h``.

# Cadence-explicit gauge — the metric name encodes the 24h
# dedup-by-(message_id, citation.id) cron schedule so operators don't have to
# read the help text to know what window the value covers.
rag_citation_accuracy_24h = Gauge(
    "rag_citation_accuracy_24h",
    (
        "Mean citation accuracy from the daily 24h LLM-as-judge cron "
        "(dedup by (message_id, citation.id)); 0=irrelevant … 1=direct"
    ),
)

# PLAN-0084 A-1 T-A-1-04: per-call failure counter for the citation judge cron.
# label reason: "timeout" | "provider_error" | "invalid_response"
rag_citation_accuracy_call_failures_total = Counter(
    "rag_citation_accuracy_call_failures_total",
    "Number of citation-accuracy judge call failures, broken down by reason",
    ["reason"],
)

# ── Circuit breaker (PLAN-0084 A-2 T-A-2-04) ─────────────────────────────────

rag_circuit_breaker_open = Gauge(
    "rag_circuit_breaker_open",
    "1 if circuit breaker is open for the labelled source, 0 otherwise.",
    ["source"],
)

# ── Security (F-S004) ─────────────────────────────────────────────────────────

rag_jti_check_bypass_total = Counter(
    "rag_jti_check_bypass_total",
    "Number of JTI replay checks bypassed due to Valkey unavailability (fail-open). Alert threshold: >0 in production.",
)

# ── Tool-use metrics (PLAN-0067 W11-3) ───────────────────────────────────────

rag_tool_call_total = Counter(
    "rag_tool_call_total",
    "Number of tool calls executed in the tool-use path",
    ["tool_name", "status"],  # status: "ok" | "empty" | "error"
)

rag_tool_call_latency_seconds = Histogram(
    "rag_tool_call_latency_seconds",
    "Tool call execution latency in seconds",
    ["tool_name"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

rag_tool_use_first_turn_latency_seconds = Histogram(
    "rag_tool_use_first_turn_latency_seconds",
    "Latency of the first LLM turn (blocking, non-streaming) in the tool-use path",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0],
)

# PLAN-0093 QA-7 P0-2: Regression smoke signal. The orchestrator's iteration-0
# branch breaks out of the agent loop when the LLM produces no tool_calls, which
# is the smoking gun for tool-discipline / prompt regressions. Label cardinality
# is bounded by the provider chain (≤4) — never user/tenant/entity IDs.
rag_no_tool_calls_first_turn = Counter(
    "rag_no_tool_calls_first_turn_total",
    "LLM answered without calling any tool on iteration 0 (regression smoke signal)",
    labelnames=["provider"],
)

# PLAN-0093 QA-7 P0-3: Empty-result quality signal — how many items each tool
# returned on a given call. We deliberately label by tool_name only (bounded ≤22
# by the registry) so dashboards can split the empty-result rate per tool.
rag_tool_result_items = Histogram(
    "rag_tool_result_items",
    "Number of items returned by a tool call (empty result quality signal)",
    labelnames=["tool_name"],
    buckets=(0, 1, 3, 5, 10, 20, 50, 100, 250),
)

# ── Tool-registry parity (PLAN-0093 QA P0-1) ─────────────────────────────────
#
# Drift signal between the YAML manifest and the in-process handler registry.
# The boot-time guard (validate_registry_parity) refuses to start the service
# if these two diverge, so under normal operation the two labels are always
# equal.  The gauge is published anyway because:
#   1. Ops dashboards want a single panel showing "22 tools registered" without
#      having to grep service logs.
#   2. Alert rule (documented for runbook):
#        rag_tool_registry_size{kind="manifest"}
#          != rag_tool_registry_size{kind="handled"}
#      This would never fire in healthy state — the startup guard fails first —
#      but if a future change moves validation to a non-fatal warn, the alert
#      will still catch silent drift.

rag_tool_registry_size = Gauge(
    "rag_tool_registry_size",
    "Number of tools registered in the manifest vs handlers (drift signal)",
    labelnames=["kind"],  # kind: "manifest" | "handled"
)


# ── PLAN-0103 W1 — BP-622 systemic kwarg-drop counter ────────────────────────
#
# Counts every LLM-supplied tool kwarg that the handler does NOT recognise.
# Before this counter existed the silent drop was invisible — the call would
# either crash with TypeError (swallowed by the executor as tool_argument_error)
# or, where the handler used **kwargs into a downstream that ignored unknown
# fields, fall through to a "no rows matched" answer.  Now operators can alarm
# on a sustained rate ("LLM is asking for kwargs we don't accept; either teach
# the handler the new param or update the tool description so the LLM stops
# asking").  Label cardinality is bounded by tool_name x declared LLM kwargs
# — small enough that we keep both labels for direct drill-down.
rag_chat_tool_unknown_kwarg_total = Counter(
    "rag_chat_tool_unknown_kwarg_total",
    "Number of LLM-supplied tool kwargs the handler did not recognise (BP-622)",
    labelnames=["tool_name", "kwarg"],
)

# ── E-6: Multi-turn agent loop (AgentBudget) ──────────────────────────────────

rag_agent_iterations = Histogram(
    "rag_agent_iterations",
    "Number of tool-use iterations per query",
    buckets=[1, 2, 3, 4, 5, 6, 7, 8],
)

rag_budget_exceeded_total = Counter(
    "rag_budget_exceeded_total",
    "Budget exceeded events by type",
    ["budget_type"],  # "latency" | "iterations" | "consecutive_errors"
)

# ── E-7: Citation egress allowlist ────────────────────────────────────────────

rag_citations_scrubbed_total = Counter(
    "rag_citations_scrubbed_total",
    "Citation references scrubbed from answers (not grounded in tool results)",
)

# ── PLAN-0093 Wave E-2: numeric-grounding validator ──────────────────────────

rag_grounding_validation_total = Counter(
    "rag_grounding_validation_total",
    "Numeric grounding validator outcomes per chat turn",
    # passed: response numbers all matched tool results within tolerance
    # failed_one_rewrite: first pass failed → LLM re-prompted → second pass passed
    # failed_banner: both passes failed → banner appended to the response
    ["result"],
)

# ── E-12: Per-turn audit log ──────────────────────────────────────────────────

rag_audit_entries_total = Counter(
    "rag_audit_entries_total",
    "Number of chat audit log entries written",
)

# ── Pipeline stage input-size histogram (PLAN-0093 observability) ─────────────
# Tracks the number of items entering each named pipeline stage so operators
# can spot stages that receive 0 items (silent empty-pipeline regressions) or
# suspiciously large batches (runaway retrieval).  Label cardinality is bounded
# by the fixed set of stage names (≤ 6) — never user/tenant/entity IDs.

rag_pipeline_stage_input_size = Histogram(
    "rag_pipeline_stage_input_size",
    "Number of items entering each pipeline stage",
    labelnames=["stage"],
    buckets=(0, 1, 3, 5, 10, 20, 50, 100, 250, 500),
)

# ── PLAN-0094 W2: morning-brief pre-generation worker ─────────────────────────
#
# Six metrics expose the daily pre-generation pipeline so operators can answer:
#   1. Is the scheduler firing? (runs_total{status="started"} rate)
#   2. Are runs completing successfully? (runs_total{status="completed"} vs failed)
#   3. How many users were eligible last run? (eligible_users gauge)
#   4. What fraction of users failed regeneration? (users_total{outcome=...})
#   5. What is the end-to-end vs per-user latency? (two histograms)
#   6. How often does the handler serve stale because of a failed regen? (served_stale)
#
# Label cardinality is bounded — never user/tenant/entity IDs.

rag_brief_pregeneration_runs_total = Counter(
    "rag_brief_pregeneration_runs_total",
    "Pre-generation scheduler runs",
    labelnames=["status"],  # started | completed | failed
)

rag_brief_pregeneration_users_total = Counter(
    "rag_brief_pregeneration_users_total",
    "Per-user pre-generation outcomes",
    labelnames=["outcome"],  # success | generation_failed | skipped_stale_kept
)

rag_brief_pregeneration_run_duration_seconds = Histogram(
    "rag_brief_pregeneration_run_duration_seconds",
    "End-to-end pre-generation run latency",
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1200, 1800),
)

rag_brief_pregeneration_user_duration_seconds = Histogram(
    "rag_brief_pregeneration_user_duration_seconds",
    "Per-user pre-generation latency",
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60),
)

rag_brief_pregeneration_eligible_users = Gauge(
    "rag_brief_pregeneration_eligible_users",
    "Active users found in the last run",
)

# ── Instrument-brief pre-generation (AI-brief-flag fix, 2026-06-19) ──────────
# Mirrors the morning-brief pre-gen metrics but for the entity (instrument)
# brief worker that populates the screener ``has_ai_brief`` flag.
rag_instrument_brief_pregeneration_runs_total = Counter(
    "rag_instrument_brief_pregeneration_runs_total",
    "Instrument-brief pre-generation scheduler runs",
    labelnames=["status"],  # started | completed | failed
)

rag_instrument_brief_pregeneration_instruments_total = Counter(
    "rag_instrument_brief_pregeneration_instruments_total",
    "Per-instrument pre-generation outcomes",
    labelnames=["outcome"],  # generated | skipped_fresh | failed
)

rag_instrument_brief_pregeneration_run_duration_seconds = Histogram(
    "rag_instrument_brief_pregeneration_run_duration_seconds",
    "End-to-end instrument-brief pre-generation run latency",
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1200, 1800),
)

rag_instrument_brief_pregeneration_eligible_total = Gauge(
    "rag_instrument_brief_pregeneration_eligible_total",
    "Active instruments found in the last run",
)

rag_brief_served_stale_total = Counter(
    "rag_brief_served_stale_total",
    "Times the handler served last-known-good brief instead of fresh",
)

# ── PLAN-0099 Wave A: brief-context diagnostics ──────────────────────────────
#
# Three metrics surface "silent partial context loss" failures (BP-599) and
# truncation hides tail signals (BP-600):
#   * brief_context_availability_score — 0.0 (no data) to 1.0 (all sections
#     populated). Weighted across portfolio (highest weight) + news + events
#     + alerts + sections that ended non-empty.  Operators alert when the
#     histogram bucket <0.5 fires more than ~20% of the time.
#   * brief_upstream_latency_ms{source} — per-upstream call wall time so a
#     slow source (S1 portfolio DB replica lag, S6 retrieval timeout) is
#     visible without grepping logs.
#   * brief_upstream_status{source,outcome} — bounded counter (outcome ∈
#     ok|timeout|error|empty) for at-a-glance SLO tracking.
#   * brief_cache_outcome{cache_name,outcome} — Valkey/in-memory cache hit
#     or miss along the brief path so cache-staleness regressions surface.
#   * brief_low_context_refusal_total — incremented every time the
#     context-availability score is below the configured threshold and we
#     skip the LLM call (Wave B refusal-on-low-context behaviour).

brief_context_availability_score = Histogram(
    "brief_context_availability_score",
    "Weighted fraction of brief context sources that returned non-empty data (0.0 to 1.0)",
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)

brief_upstream_latency_ms = Histogram(
    "brief_upstream_latency_ms",
    "Per-upstream call wall time (ms) during brief context gathering",
    labelnames=["source"],  # s1_portfolio | s3_quotes | s5_alerts | s6_news | s7_events
    buckets=(10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000),
)

brief_upstream_status = Counter(
    "brief_upstream_status_total",
    "Per-upstream outcome counter for brief context gathering",
    labelnames=["source", "outcome"],  # outcome ∈ ok|timeout|error|empty
)

brief_cache_outcome = Counter(
    "brief_cache_outcome_total",
    "Brief-path cache hit/miss/error counter",
    labelnames=["cache_name", "outcome"],  # outcome ∈ hit|miss|error
)

brief_low_context_refusal_total = Counter(
    "brief_low_context_refusal_total",
    "Times the brief generator refused LLM call due to low context availability score",
)

# PLAN-0103 W3 (BP-624): post-generation observability for the v4.2 6-section
# completeness gate. Incremented once per missing section name on each
# generation that did NOT honour the v4.2 prompt's "all 6 sections MANDATORY"
# rule. Label cardinality is bounded by the V42_EXPECTED_SECTIONS tuple
# (6 values: Tape, Your Portfolio Today, Macro Today, News That Matters To
# You, Risks + Opportunities, Bonus context). Operators alert when a single
# section name dominates the rate — that signals the prompt or the LLM is
# consistently dropping that bucket.
brief_section_missing_total = Counter(
    "brief_section_missing_total",
    "Per-section counter for missing v4.2 sections in generated morning briefs",
    labelnames=["section"],
)

# PLAN-0103 W6 (v4.3) — defensive injection counter.
# Increments every time GenerateBriefingUseCase had to inject a placeholder
# for a section the LLM omitted (paired with brief_section_missing_total —
# the two should track 1:1 when injection is wired correctly). Section label
# values match V42_EXPECTED_SECTIONS plus a synthetic ``__summary__`` value
# for the synthesised summary_paragraph injection.
brief_section_injected_total = Counter(
    "brief_section_injected_total",
    "Per-section counter for defensively-injected placeholder sections in morning briefs",
    labelnames=["section"],
)

# ── F-LIVE-NEW-001: entity-resolver ambiguity observability ──────────────────
#
# Counts the number of times ``IntelligenceHandler._resolve_entity_by_name``
# rejected a candidate set (returned None) along with the reason it bailed.
# Label cardinality is bounded by the fixed reason set:
#   * stop_word_strip       — query was all-stop-words after filter; skipped
#   * delta_below_threshold — top-1 vs top-2 similarity gap < threshold
#   * low_top_similarity    — top-1 absolute similarity < minimum threshold
#
# Used to detect resolver tuning regressions (e.g. "AI semiconductor space"
# fuzzy-matching SpaceX) without leaking the query text.
rag_entity_resolver_ambiguous_total = Counter(
    "entity_resolver_ambiguous_total",
    "Entity-resolver bailed because the candidate set was ambiguous or low-quality",
    labelnames=["reason"],  # stop_word_strip | delta_below_threshold | low_top_similarity
)

# ── PLAN-0099 Wave C: agentic brief generator (experimental) ─────────────────
brief_agentic_llm_calls_total = Counter(
    "brief_agentic_llm_calls_total",
    "LLM round-trips made by AgenticBriefGenerator (per generation)",
)

brief_agentic_tool_calls_total = Counter(
    "brief_agentic_tool_calls_total",
    "Tool invocations made by AgenticBriefGenerator (per generation)",
    labelnames=["tool"],
)

brief_agentic_fallback_total = Counter(
    "brief_agentic_fallback_total",
    "Times the agentic brief generator fell back to the standard path",
    labelnames=["reason"],  # exception | budget_exhausted | empty_response
)

# ── PLAN-0103 W12 / BP-631: sector-exposure weight-source telemetry ───────────
#
# Tracks which tier of the weight-fallback ladder produced the dollar-weights
# used by ``_compute_sector_exposure``. Operators can spot when the brief
# silently degraded from the preferred per-holding live price to a coarser
# fallback. Bounded label cardinality (4 fixed sources).
#
#   pnl        — preferred: P&L snapshot current_price x qty
#   db_weight  — fallback 1: PortfolioSnapshot.current_weight
#   quote      — fallback 2: P&L snapshot last_close x qty (no current)
#   equal      — last resort: equal-weight 1/N when neither P&L nor weights
#                exist (PLAN-0103 W12 / BP-631 — prevents empty risk_summary
#                when the P&L endpoint is unreachable AND DB weights are NULL)
brief_sector_exposure_weight_source = Counter(
    "brief_sector_exposure_weight_source",
    "Weight tier that produced the sector-exposure aggregation",
    labelnames=["source"],  # pnl | db_weight | quote | equal
)

# ── PLAN-0107 follow-up (agent-B + manual fix-up): per-call LLM USD cost ──────
#
# NO Counter is defined here. The cost counter
# ``rag_chat_ml_api_estimated_cost_usd_total{model_id}`` is already registered
# by the shared observability lib via ``build_ml_metrics("rag-chat")`` at app
# startup (see ``application/metrics/ml_clients.py`` + the wiring inside
# ``create_app`` in ``app.py``). The Grafana panel id=6 in
# ``infra/grafana/dashboards/rag-chat.json`` queries that observability-lib
# counter directly.
#
# Agent B initially tried to declare a SECOND Counter here with an extra
# ``call_site`` label, but the duplicate registration (same name + different
# label schema) raises ``ValueError: Duplicated timeseries in
# CollectorRegistry``. The fix-up routes the ``CostRecorder`` through the
# observability-lib singleton instead. Per-``call_site`` breakdown is still
# captured for analysis — but in the ``llm_usage_log`` DB table, NOT in
# Prometheus — keeping metric cardinality bounded.
