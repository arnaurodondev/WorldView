# .agents — Multi-Stage PR Investigation Framework

> **Purpose**: A structured reasoning system for AI-assisted code review.
> Pattern matching alone is insufficient. This framework forces structured
> investigation, failure simulation, and invariant verification.

---

## Directory Structure

```
.agents/
├── README.md                          ← this file
│
├── investigation/                     ← structured reasoning methods
│   ├── PR_INVESTIGATION_PROTOCOL.md   ← central reasoning engine (start here)
│   ├── FAILURE_MODE_ANALYSIS.md       ← failure enumeration procedure
│   └── INVARIANT_ANALYSIS.md          ← invariant identification and verification
│
├── knowledge/                         ← historical bugs and conventions
│   ├── BUG_PATTERNS.md                ← links to docs/ai-interactions/BUG_PATTERNS.md
│   ├── DISTRIBUTED_SYSTEM_PATTERNS.md ← distributed execution failure patterns
│   └── STORAGE_ATOMICITY_PATTERNS.md  ← partial write and atomicity patterns
│
├── roles/                             ← specialized analysis agents
│   ├── senior_pr_reviewer.md          ← top-level review coordinator
│   ├── failure_mode_investigator.md   ← failure simulation specialist
│   ├── distributed_systems_reviewer.md← Spark / cluster correctness
│   └── data_pipeline_reviewer.md      ← data pipeline and ML pipeline reviewer
│
├── checklists/                        ← quick sanity checks
│   ├── REVIEW_CHECKLIST.md            ← universal pre-report checklist
│   ├── SPARK_PIPELINE_CHECKLIST.md    ← Spark-specific checks
│   └── STORAGE_IO_CHECKLIST.md        ← storage and I/O checks
│
└── heuristics/                        ← failure generation techniques
    ├── HIGH_RISK_PATTERNS.md          ← code patterns that signal high risk
    └── EDGE_CASE_GENERATION.md        ← systematic edge case generation
```

---

## Layer Reference

| Layer | Purpose |
|-------|---------|
| `knowledge/` | Historical bugs and conventions — what has failed before |
| `investigation/` | Structured reasoning methods — how to reason about new code |
| `roles/` | Specialized analysis agents — who performs which analysis |
| `checklists/` | Quick sanity checks — did we forget anything obvious |
| `heuristics/` | Failure generation techniques — how to generate new failure hypotheses |

---

## Agent Pipeline (in order)

When reviewing a PR, agents must execute in this sequence:

```
1. PR_INVESTIGATION_PROTOCOL      ← map change surface, identify side effects
2. FAILURE_MODE_ANALYSIS          ← enumerate failure modes per function
3. BUG_PATTERN_CHECK              ← cross-check known historical patterns
4. DISTRIBUTED_SYSTEM_REVIEW      ← evaluate distributed/cluster correctness
5. EDGE_CASE_SIMULATION           ← test hypothetical inputs
6. FINAL_REPORT                   ← report realistic failures only
```

---

## Why This Architecture

Most PR review agents fail because they only do pattern matching.

This system forces:

- **Structured reasoning** — every function is decomposed into steps
- **Failure simulation** — every step is evaluated for failure state
- **Invariant verification** — conditions that must always hold are tested
- **Edge case generation** — systematic hypothetical inputs are evaluated

This is how elite engineers review critical systems at Stripe, Google, and Databricks.

---

## Entry Point

Start with: [investigation/PR_INVESTIGATION_PROTOCOL.md](investigation/PR_INVESTIGATION_PROTOCOL.md)
