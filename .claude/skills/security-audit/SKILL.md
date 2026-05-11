---
name: security-audit
description: "Perform a focused security audit on changes or a specific service. Covers OWASP Top 10, multi-tenant isolation, input validation, secrets management, and project-specific security patterns. Use before PRs with security-sensitive changes or periodically for full audits."
user-invocable: true
argument-hint: "[service name, file paths, or 'full' for complete audit]"
effort: heavy
paths:
  - "**/api/**/*.py"
  - "**/api/routes/**/*.py"
  - "**/infrastructure/**/*.py"
---

# Security Audit — Focused Security Analysis

You are a **Security Engineer** performing a targeted security audit. You think adversarially — your job is to find what could go wrong from a security perspective, not to confirm that things work.

## Input

Audit scope: `$ARGUMENTS`

---

## Phase 1 — Scope & Threat Model

### 1.1 Identify Attack Surface
For the code under review, identify:
- **External inputs**: API endpoints, Kafka messages, RSS feeds, file uploads, user queries
- **Trust boundaries**: Where does trusted code interact with untrusted data?
- **Privileged operations**: DB writes, file system access, external API calls, Kafka publishing
- **Authentication/Authorization points**: Where are permissions checked?

### 1.2 Threat Categories (Project-Specific)
Based on worldview's architecture, prioritize these threats:

| Priority | Threat | Relevance to Worldview |
|----------|--------|----------------------|
| P0 | **Multi-tenant data leakage** | All services handle tenant_id; cross-tenant query = data breach |
| P0 | **SQL injection** | Multiple PostgreSQL databases, SQLAlchemy ORM (usually safe, but raw SQL exists) |
| P0 | **Secrets exposure** | API tokens (EODHD), DB credentials, Kafka creds in env vars |
| P1 | **Input validation bypass** | External content from RSS, EODHD API, user chat input |
| P1 | **Prompt injection** (RAG/Chat) | S8 RAG Chat processes user queries that interact with LLMs |
| P1 | **Kafka message tampering** | Events flow between services; malformed events = cascading failures |
| P2 | **SSRF** | Services make outbound HTTP calls (EODHD API, RSS feeds) |
| P2 | **Denial of service** | Unbounded queries, uncontrolled Kafka consumption |
| P3 | **Dependency vulnerabilities** | Python/Node.js package supply chain |

### 1.3 Load Context
- Read `RULES.md` rules R13-R15 (security rules)
- Read `docs/BUG_PATTERNS.md` for security-related patterns
- Read `.claude/review/heuristics/HIGH_RISK_PATTERNS.md`
- Read service-specific security notes in `docs/services/<service>.md`

---

## Phase 2 — Code Analysis

### 2.1 OWASP Top 10 Scan

For each file in scope:

#### A01: Broken Access Control
- [ ] All API endpoints check authentication
- [ ] Tenant isolation enforced on all queries (WHERE tenant_id = ?)
- [ ] No horizontal privilege escalation (user A can't access user B's data)
- [ ] Admin endpoints properly guarded

#### A02: Cryptographic Failures
- [ ] No plaintext secrets in code, config, or logs
- [ ] TLS for all external connections
- [ ] Proper token handling (no tokens in URLs or logs)

#### A03: Injection
- [ ] SQL: All queries use parameterized statements (SQLAlchemy ORM or text() with bindparams)
- [ ] No f-string SQL construction
- [ ] LLM prompt injection mitigated (input sanitization, output validation)
- [ ] No OS command injection (subprocess with shell=False)

#### A04: Insecure Design
- [ ] Rate limiting on API endpoints
- [ ] Input size limits enforced
- [ ] Error messages don't leak internal details
- [ ] Fail-closed on authorization errors

#### A05: Security Misconfiguration
- [ ] Debug mode disabled in production configs
- [ ] Default credentials changed
- [ ] Unnecessary endpoints/features disabled
- [ ] CORS properly configured

#### A06: Vulnerable Components
- [ ] Known-vulnerable dependency versions flagged
- [ ] No unnecessary dependencies

#### A07: Authentication Failures
- [ ] Session management follows best practices
- [ ] Password/token storage uses appropriate hashing
- [ ] Token expiration enforced

#### A08: Data Integrity Failures
- [ ] Avro schema validation on all Kafka events
- [ ] Input validation on all API request bodies
- [ ] File upload validation (type, size, content)

#### A09: Logging & Monitoring Failures
- [ ] Security-relevant events logged (auth failures, access denials)
- [ ] No sensitive data in logs (passwords, tokens, PII)
- [ ] Log injection prevented (structured logging with structlog)

#### A10: SSRF
- [ ] Outbound HTTP requests validate target URLs
- [ ] No user-controlled URLs in server-side requests (or properly validated)
- [ ] DNS rebinding protection where applicable

### 2.2 Project-Specific Checks

#### Multi-Tenant Isolation
- Every DB query with user data includes `tenant_id` filter
- No shared state between tenants in cache (Valkey key includes tenant_id)
- Kafka events include tenant_id for consumer filtering
- API responses don't leak other tenants' data

#### RAG/Chat Security (S8)
- User input sanitized before LLM prompt construction
- LLM output validated before presentation
- Retrieval results filtered by tenant
- No arbitrary code execution from LLM responses

#### Event Integrity
- Kafka messages validated against Avro schemas
- Malformed events sent to DLQ, not silently dropped
- Event replay doesn't cause duplicate side effects (idempotency)

#### External Data Handling
- RSS feed content treated as untrusted (HTML sanitization)
- EODHD API responses validated before storage
- No XSS vectors in stored content

---

## Phase 3 — Security Findings Report

```markdown
# Security Audit Report

**Date**: <YYYY-MM-DD>
**Scope**: <service/files/full>
**Auditor**: Claude (security-audit skill)
**Risk Level**: CRITICAL | HIGH | MEDIUM | LOW | CLEAN

## Executive Summary
<2-3 sentences on overall security posture>

## Findings

### Critical (Must fix immediately)
| ID | Category | Location | Description | Remediation |
|----|----------|----------|-------------|-------------|
| SEC-001 | A03 Injection | file:line | ... | ... |

### High (Fix before merge)
| ID | Category | Location | Description | Remediation |
|----|----------|----------|-------------|-------------|

### Medium (Fix soon)
| ID | Category | Location | Description | Remediation |
|----|----------|----------|-------------|-------------|

### Low (Track for future)
| ID | Category | Location | Description | Remediation |
|----|----------|----------|-------------|-------------|

### Informational
- <Observations that don't require action but are worth noting>

## OWASP Checklist Summary
| Category | Status | Notes |
|----------|--------|-------|
| A01 Access Control | PASS/FAIL | ... |
| A02 Crypto | PASS/FAIL | ... |
| A03 Injection | PASS/FAIL | ... |
| ... | ... | ... |

## Multi-Tenant Isolation
| Check | Status | Notes |
|-------|--------|-------|
| DB query filtering | PASS/FAIL | ... |
| Cache isolation | PASS/FAIL | ... |
| Event isolation | PASS/FAIL | ... |
| API response filtering | PASS/FAIL | ... |

## Recommendations
1. <Immediate action items>
2. <Short-term improvements>
3. <Long-term security hardening>
```

---

## Compounding Value

After each audit:
1. **New security pattern?** → Add to BUG_PATTERNS.md with Security category
2. **Recurring issue?** → Recommend adding to HIGH_RISK_PATTERNS.md
3. **Missing validation?** → Recommend specific input validation additions
4. **Missing test?** → Recommend security-focused test cases for `/test-feature`


---

## Workflow Chain — Suggest Next Steps

After completing this skill, suggest the appropriate next skill to the user:
- **If vulnerabilities found**: `/fix-bug` — fix each vulnerability with regression test
- **If architectural security issue**: `/refactor` — restructure for security
- **If all clear**: `/review` or `/qa` — proceed with standard quality gates
- **If design-level concern**: `/prd` — revisit requirements with security constraints

---

## Mandatory Compounding Step (All Skills)

Before completing this skill, check if any of these documents should be updated based on what you learned during this session:

| Document | Update When | Location |
|----------|------------|----------|
| **BUG_PATTERNS.md** | New failure pattern discovered | `docs/BUG_PATTERNS.md` |
| **STANDARDS.md** | New convention or best practice identified | `docs/STANDARDS.md` |
| **HIGH_RISK_PATTERNS.md** | New code pattern that signals risk | `.claude/review/heuristics/HIGH_RISK_PATTERNS.md` |
| **REVIEW_CHECKLIST.md** | New check that would have caught an issue | `.claude/review/checklists/REVIEW_CHECKLIST.md` |
| **Service .claude-context.md** | Service gained/changed endpoints, topics, entities, pitfalls | `services/<service>/.claude-context.md` |
| **Service docs** | API, events, schema, data model, or config changed | `docs/services/<service>.md` |
| **MASTER_PLAN.md** | System-wide architectural change | `docs/MASTER_PLAN.md` |
| **Skill definitions** | Workflow step proved insufficient or needs improvement | `.claude/skills/<skill>/SKILL.md` |
| **Agent definitions** | Agent guidance needs refinement based on real usage | `.claude/agents/<agent>.md` |
| **RULES.md** | New hard rule identified from a failure | `RULES.md` |

**This is not optional.** The compounding effect is what makes the system improve over time. Even if no updates are needed, explicitly confirm: "Compounding check: no updates needed."
