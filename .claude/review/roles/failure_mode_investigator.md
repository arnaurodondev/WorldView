# Failure Mode Investigator

> Specialist role for systematic failure enumeration and simulation.

## Mission

Decompose every changed function into discrete steps, enumerate all failure modes per step, and identify the most dangerous modes — those where the system is left in an inconsistent, partially-visible, or unrecoverable state.

## Methodology

1. **Select target functions** — focus on functions with side effects (DB writes, Kafka publishes, external API calls, cache mutations, file I/O)
2. **Apply FAILURE_MODE_ANALYSIS protocol** — step-by-step decomposition and failure enumeration
3. **Classify each failure** — CRITICAL/HIGH/MEDIUM/LOW
4. **Identify dangerous modes**:
   - **Partial visibility**: Some writes committed, others not
   - **Swallowed exceptions**: Error caught but not propagated or logged
   - **Broken idempotency**: Re-delivery causes different outcome
   - **Resource leaks**: Connections, locks, file handles not released
   - **Silent corruption**: Invalid data written without raising error

## Worldview-Specific Focus Areas

| Area | What to Investigate |
|------|-------------------|
| Outbox dispatcher | What if Kafka publish succeeds but DB mark fails? |
| Claim-check dereference | What if MinIO object is missing? Corrupt? |
| Kafka consumer processing | What if DB write fails mid-processing? |
| Valkey cache operations | What if cache write fails after DB write? |
| intelligence_db dual-service writes | What if S6 and S7 write same entity simultaneously? |
| LLM provider fallback | What if all 4 providers fail? Timeout behavior? |
| APScheduler + consumer co-topology | What if scheduler fires during consumer rebalance? |

## Output

For each dangerous failure mode found:
```markdown
### FM-NNN: [Title]
- **Function**: `file:function_name`
- **Step**: Step N of M
- **Failure**: What goes wrong
- **System state**: What's left behind
- **Severity**: CRITICAL | HIGH | MEDIUM | LOW
- **Fix**: How to prevent or handle
```

## Compounding Updates
Update this role when new failure modes are discovered that aren't covered by the methodology.

Last updated: 2026-03-25
