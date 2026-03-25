# Review Knowledge Base

Historical patterns, known bugs, and domain knowledge used during code review.

## Primary Reference

The canonical bug pattern catalog is at:
**`docs/ai-interactions/BUG_PATTERNS.md`**

This file contains all known bug patterns (BP-001 through BP-XXX) with:
- Category, severity, symptoms
- Root cause analysis
- Example code (bad vs good)
- Fix approach
- Prevention guidance
- Regression test references

## How to Use

During code review (via `/review` skill):
1. Read `BUG_PATTERNS.md` at the start of every review
2. For each changed function, check: "Could this change introduce or be affected by any known pattern?"
3. If a new pattern is discovered during review, recommend adding it to the catalog

## Pattern Categories

| Category | Common Patterns | Examples |
|----------|----------------|---------|
| Serialization | Outbox format, Avro compatibility | BP-001 |
| Configuration | Env loading order, defaults | BP-002 |
| Testing | Fixture scope, async setup | BP-003 |
| Database | Migration targets, ORM gotchas | BP-004, BP-005 |
| Async | Concurrency, event loops | BP-006+ |

## Distributed System Patterns

For distributed system-specific review concerns, reference:
- Outbox pattern (libs/messaging)
- Claim-check pattern (libs/storage)
- Idempotent consumer pattern
- Event-driven eventual consistency

## Compounding

The knowledge base grows over time:
- Every `/fix-bug` invocation may add a new BP-XXX entry
- Every `/investigate` may recommend new patterns
- Every `/review` that finds a new pattern should recommend cataloging it
