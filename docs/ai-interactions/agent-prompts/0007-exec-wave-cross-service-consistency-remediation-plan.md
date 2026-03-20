# Execution Wave Plan 0007 — cross-service-consistency-remediation

## Source Inputs
- Planning prompt: docs/ai-interactions/agent-planning/0007-cross-service-documentat.md
- Planning response: docs/ai-interactions/agent-responses/0007-response-20260319-cross-service-consistency-audit.md

## Task Extraction
- Canonical task source for this scope: divergence IDs in Section 3 of the response.
- Discovered task IDs:
  - D-001, D-002, D-003, D-004, D-005, D-006, D-007, D-008, D-009
  - D-010, D-011, D-012, D-013, D-014, D-015, D-016, D-017, D-018
- Duplicate IDs detected: none
- Coverage mode: full
- Tasks discovered: 18
- Max tasks per wave: 20
- Theoretical minimum waves (W_min): 1
- Actual waves: 2 (W_min + 1)
- Justification for extra wave: unresolved architecture/contract decisions and safety-critical contract fixes must land before large S4-S8 implementation/doc-truth alignment.

## Generated Wave Files
- docs/ai-interactions/agent-prompts/0007-exec-cross-service-consistency-remediation-wave-01.md
- docs/ai-interactions/agent-prompts/0007-exec-cross-service-consistency-remediation-wave-02.md

## Wave Assignment Summary
- Wave 01:
  - D-001, D-002, D-003, D-004, D-011, D-012, D-013, D-014, D-015, D-016, D-018
- Wave 02:
  - D-005, D-006, D-007, D-008, D-009, D-010, D-017

## Dependency Rationale
- Wave 01 resolves gateway contract mismatches, core architecture/config decisions, and global stale docs that would otherwise force churn in later waves.
- Wave 02 performs S4-S8 truth-alignment and test-gap closure after wave-01 decisions define target behavior.

## Coverage Check
- assigned/discovered: 18/18
- exact-set match: passed
- unassigned tasks: none

## Coverage Ledger

| task_id | assigned_wave | status | dependency_note |
|---|---:|---|---|
| D-001 | 01 | scheduled | Base doc corrections before broad remediation |
| D-002 | 01 | scheduled | Quick doc fix; independent |
| D-003 | 01 | scheduled | Needed before S2 runbook/workflow alignment |
| D-004 | 01 | scheduled | Needed before S8 scope decisions are documented |
| D-005 | 02 | scheduled | Depends on S4 strategy decided in wave 01 |
| D-006 | 02 | scheduled | Depends on S5 strategy decided in wave 01 |
| D-007 | 02 | scheduled | Depends on S6 strategy decided in wave 01 |
| D-008 | 02 | scheduled | Depends on S7 strategy decided in wave 01 |
| D-009 | 02 | scheduled | Depends on S8 strategy decided in wave 01 |
| D-010 | 02 | scheduled | Follows S4-S8 implementation/doc strategy |
| D-011 | 01 | scheduled | Critical gateway contract decision/fix |
| D-012 | 01 | scheduled | Critical S9-S3 caller/callee compatibility |
| D-013 | 01 | scheduled | Env/config baseline for gateway work |
| D-014 | 01 | scheduled | Master DB naming canonicalization before downstream updates |
| D-015 | 01 | scheduled | Architecture decision blocker for S8 work |
| D-016 | 01 | scheduled | Infra compose scope clarification before workflow updates |
| D-017 | 02 | scheduled | Test alignment after behavior/doc truth-alignment |
| D-018 | 01 | scheduled | Global ID policy decision before related docs/code edits |
