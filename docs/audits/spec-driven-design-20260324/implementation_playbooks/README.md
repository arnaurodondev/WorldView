# Implementation Playbooks

This folder contains step-by-step implementation guides for highest-priority improvements from the spec-driven audit.

Included playbooks:
- PLAYBOOK-001: Contract test baseline across event-producing services
- PLAYBOOK-002: Avro schema mirror parity gate in CI
- PLAYBOOK-003: OpenAPI lint and breaking-change diff gating
- PLAYBOOK-004: Plan/task schema formalization pilot

Execution order:
1. PLAYBOOK-001
2. PLAYBOOK-002
3. PLAYBOOK-003
4. PLAYBOOK-004

Definition of done for each playbook:
- CI checks added and green
- Documentation updated
- Evidence artifact attached in PR
- Rollback plan documented
