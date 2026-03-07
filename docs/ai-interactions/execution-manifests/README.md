# Execution Manifests

Execution manifests convert high-level agent responses into machine-operable tasks.

## Purpose

- make task execution deterministic
- enforce dependency order and file ownership constraints
- define test gates and evidence requirements per task

## Required files

- `0000-execution-manifest-template.yaml`: base template
- one manifest per execution run, e.g. `M-0001-shared-libs.yaml`

## Current manifests

- `M-0001-shared-libs-m1-common.yaml`
- `M-0001-shared-libs-full.yaml`
- `M-0002-portfolio-full.yaml`
- `M-0003-market-ingestion-full.yaml`
- `M-0004-market-data-full.yaml`

## How to use

1. Orchestrator creates a run-specific manifest from the template.
2. Split response tasks into one manifest task per atomic work item.
3. Assign owners and branches.
4. Move task states through: `planned -> ready -> in-progress -> review -> done`.
5. Require evidence and checklist before marking `done`.

## State ownership

- Orchestrator can set: `ready`, `blocked`, `done`, `cancelled`
- Workers can set: `in-progress`, `review`

## Conflict policy

- Only one in-progress task may hold a write lock on a file path.
- Tasks with overlapping write paths cannot run in parallel.
