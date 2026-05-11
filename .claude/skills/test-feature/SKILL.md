---
name: test-feature
description: "Design and implement comprehensive tests for a feature or module. Analyzes code to identify test scenarios (happy path, edge cases, error paths, integration), writes tests, and validates coverage. Use to ensure thorough test coverage for new or existing features."
user-invocable: true
argument-hint: "[feature name, service, module path, or specific function to test]"
effort: medium
paths:
  - "**/domain/**/*.py"
  - "**/application/**/*.py"
  - "**/application/use_cases/**/*.py"
---

# Test Feature — Comprehensive Test Design & Implementation

You are a **Senior QA/Test Engineer** responsible for designing and implementing thorough test coverage. You don't just write tests that pass — you write tests that catch bugs, including the ones that haven't been written yet.

## Input

Test target: `$ARGUMENTS`

---

## Phase 1 — Test Target Analysis

### 1.1 Identify the Code Under Test
- Read the target source code thoroughly
- Map all public functions, methods, and classes
- Identify the architectural layer (domain, application, infrastructure, API)
- Note dependencies (what does this code call/use?)
- Note callers (what calls this code?)

### 1.2 Load Context
- Read `services/<service>/.claude-context.md` (if exists)
- Read `docs/services/<service>.md` for expected behavior
- Read existing tests in the service's `tests/` directory
- Read `docs/BUG_PATTERNS.md` for relevant patterns
- Read `docs/workflows/testing-strategy.md` for test conventions

### 1.3 Understand Existing Coverage
- Run existing tests to see what passes: `python -m pytest <service>/tests -m "unit" -v --tb=short`
- Identify which functions/paths already have tests
- Identify gaps: untested functions, untested branches, untested error paths

---

## Phase 2 — Test Case Design

### 2.1 Test Categories
For each public function/method, design tests across these categories:

#### Happy Path Tests
- Normal input → expected output
- Multiple valid input variations
- Boundary values that should succeed (e.g., min/max valid lengths)

#### Edge Case Tests
- Empty input (empty string, empty list, None)
- Single element collections
- Boundary values (0, -1, MAX_INT, empty UUID)
- Unicode / special characters in strings
- Very large inputs (stress test)
- Concurrent access (if applicable)

#### Error Path Tests
- Invalid input types
- Out-of-range values
- Missing required fields
- Malformed data
- Null/None where not expected
- Duplicate data (idempotency testing)

#### State Transition Tests (if stateful)
- Valid state transitions
- Invalid state transitions (should fail gracefully)
- Race conditions between state changes

#### Integration Scenarios (if applicable)
- DB interactions: create, read, update, delete
- Kafka: produce message, consume message, handle duplicate
- External API: success response, error response, timeout
- Cache: hit, miss, invalidation

### 2.2 Test Matrix
Produce a test matrix before writing any code:

```markdown
| Function/Method | Test Case | Type | Priority | Marker |
|----------------|-----------|------|----------|--------|
| create_entity() | valid input → entity created | happy | HIGH | unit |
| create_entity() | duplicate ID → raises error | error | HIGH | unit |
| create_entity() | empty name → validation error | edge | MEDIUM | unit |
| get_by_id() | existing ID → returns entity | happy | HIGH | unit |
| get_by_id() | non-existent ID → None | edge | HIGH | unit |
| process_event() | valid event → state updated | happy | HIGH | integration |
| process_event() | duplicate event → idempotent | edge | HIGH | integration |
```

Present this matrix to the user for review before proceeding.

---

## Phase 3 — Test Implementation

### 3.1 Test Structure
Follow the existing test conventions in the codebase:

```python
"""Tests for <module>.<function>."""
import pytest
from <service>.domain.entities.<entity> import Entity
from <service>.domain.errors import DomainError

class TestFunctionName:
    """Tests for function_name."""

    @pytest.mark.unit
    def test_happy_path_description(self):
        """Should <expected behavior> when <condition>."""
        # Arrange
        ...
        # Act
        result = function_name(input)
        # Assert
        assert result == expected

    @pytest.mark.unit
    def test_edge_case_description(self):
        """Should <expected behavior> when <edge condition>."""
        ...

    @pytest.mark.unit
    def test_error_path_description(self):
        """Should raise <Error> when <condition>."""
        with pytest.raises(ExpectedError):
            function_name(bad_input)
```

### 3.2 Test Quality Rules

**DO**:
- Use descriptive test names: `test_create_portfolio_returns_entity_with_uuid7_id`
- One assertion concept per test (multiple asserts on same object is fine)
- Use `pytest.mark.unit`, `pytest.mark.integration`, `pytest.mark.e2e` markers
- Use fixtures for common setup (but keep them close to usage)
- Test behavior, not implementation (don't test private methods)
- Use `pytest.raises` for expected exceptions
- Use `pytest.mark.parametrize` for data-driven tests
- Verify side effects (was the event published? was the DB updated?)

**DON'T**:
- Don't mock everything — mock at boundaries (ports), not within layers
- Don't write tests that pass regardless of implementation
- Don't test framework behavior (FastAPI routing, SQLAlchemy ORM)
- Don't use `time.sleep` in tests — use proper async patterns
- Don't share mutable state between tests

### 3.3 Mock Strategy
- **Domain layer tests**: No mocks needed (pure functions/entities)
- **Application layer tests**: Mock port interfaces (repositories, message publishers)
- **Infrastructure layer tests**: Mock external services (DB, Kafka, S3) OR use testcontainers for integration
- **API layer tests**: Use FastAPI TestClient with mocked use cases

### 3.4 Integration Test Patterns
For tests that need infrastructure:
```python
@pytest.mark.integration
async def test_repository_persists_entity(db_session):
    """Should persist entity to database and retrieve it."""
    repo = PostgresEntityRepository(db_session)
    entity = Entity.create(name="test")

    await repo.save(entity)
    retrieved = await repo.get_by_id(entity.id)

    assert retrieved is not None
    assert retrieved.id == entity.id
    assert retrieved.name == "test"
```

---

## Phase 4 — Validation

### 4.1 Run All Tests
```bash
# Run new tests in isolation
python -m pytest <new_test_files> -v

# Run all tests for the service
python -m pytest <service>/tests -m "unit" -v

# Run integration tests if applicable
python -m pytest <service>/tests -m "integration" -v
```

### 4.2 Verify Test Quality
For each test, verify:
- [ ] Test fails when the code under test is broken (change the implementation and verify the test catches it)
- [ ] Test name clearly describes what is being tested
- [ ] Test is deterministic (no flaky behavior)
- [ ] Test runs in < 1 second (for unit tests)

### 4.3 Lint Tests
```bash
ruff check <test_files>
```

---

## Phase 5 — Coverage Report & File Output

### 5.1 Determine Report File Path

**MANDATORY**: Every `/test-feature` invocation MUST write its report to a file. Never rely on terminal output as the only record.

```
docs/audits/YYYY-MM-DD-test-<slug>-report.md
```

Where `<slug>` is a kebab-case abbreviation of the test target (e.g., `nlp-pipeline-price-impact`, `scripts-local-k8s`, `content-ingestion-unit`).

Create the directory if needed: `docs/audits/`

### 5.2 Per-Issue Deep Investigation

For every gap, failure, or problem discovered during testing, write a full investigation block in the report file. Do NOT summarise — investigate fully.

Each issue block must contain:

```markdown
## Issue I-NNN: <title>

### Summary
<2-3 sentence description of what is wrong and where>

### Severity
<BLOCKING | CRITICAL | MAJOR | MINOR | NIT>
**Rationale**: <why this severity was assigned>

### Root Cause Analysis
<Deep investigation — answer ALL of the following:>
- **What**: The exact code/config/data that is wrong (with file:line references)
- **Why**: The chain of events that causes this — what decisions or omissions led here
- **When**: Under what conditions the issue manifests (always? intermittently? under load?)
- **Where**: Exact location in the architecture (domain? application? infrastructure? config?)
- **History**: Was this recently introduced? Is it a known class of bug (BP-XXX)?

### Evidence
```
<paste actual failing test output, error messages, or code excerpt>
```
- **File**: `path/to/file.py:line_number`
- **Related BP**: BP-XXX (if applicable)

### Impact
- **Immediate**: <what breaks or is incorrect right now>
- **Blast radius**: <other services, tests, or systems that could be affected>
- **Data risk**: <any data corruption, data loss, or incorrect data risk>
- **User impact**: <visible to end user? how?>

### Solution Options

#### Option A: <short descriptive title>
**Description**: <clear explanation of what this solution does and how it addresses the root cause>
**Changes required**:
- [ ] `path/to/file.py` — <what changes and why>
- [ ] `path/to/test.py` — <what test changes are needed>
- [ ] `docs/...` — <what documentation must be updated>
- [ ] `infra/...` — <any infrastructure changes>
**Benefits (long-term)**:
- <architectural benefit>
- <maintainability benefit>
- <correctness/safety benefit>
**Drawbacks (long-term)**:
- <technical debt or complexity introduced>
- <performance or scalability concern>
- <migration cost or breaking change risk>
**Effort**: Low | Medium | High
**Risk**: Low | Medium | High
**Complexity**: <lines changed, services touched, test changes required>

#### Option B: <short descriptive title>
*(Use same structure as Option A)*

#### Option C: <short descriptive title (if applicable)>
*(Use same structure as Option A)*

### Recommended Option
**Option X** — <1 sentence rationale comparing it to alternatives, citing the most important trade-off>

### Verification Steps
After applying the fix:
- [ ] <specific test or command to run to confirm the issue is resolved>
- [ ] <regression check — ensure nothing else broke>

---
```

### 5.3 Write Report File

Write the complete report to the file path determined in §5.1. The report structure:

```markdown
# Test Feature Report: <target>

**Date**: YYYY-MM-DD HH:MM UTC
**Skill**: test-feature
**Target**: <exact target description from input>
**Branch**: <git branch>
**Test Run**: `<exact pytest command that was run>`
**Verdict**: PASS | PASS_WITH_GAPS | FAIL

---

## Executive Summary
<3-5 sentences: what was tested, what was found, most important issues, overall assessment>

## Test Execution Results
| Test File | Tests Run | Passed | Failed | Skipped | Status |
|-----------|-----------|--------|--------|---------|--------|
| ... | N | N | N | N | PASS/FAIL |

## Coverage Matrix
| Function/Method | Happy | Edge | Error | Integration | Status |
|----------------|-------|------|-------|-------------|--------|
| func_a() | 2/2 | 3/3 | 2/2 | 1/1 | COVERED |
| func_b() | 1/1 | 1/2 | 0/1 | N/A | GAPS |

## Issues Found

*(One full investigation block per issue — see §5.2 format)*

## Bug Pattern Guards Added
| Pattern | Test | Coverage |
|---------|------|---------|
| BP-XXX | test_name | guards against X |

## Recommendations
- <priority-ordered list of next steps>
```

After writing the file, output its path to the terminal: `Report written to: docs/audits/YYYY-MM-DD-test-<slug>-report.md`

---

## Compounding Value

After writing tests, check:
1. **Discovered a testable invariant?** → Add to service's `.claude-context.md`
2. **Found a common test pattern?** → Suggest adding a shared fixture to `conftest.py`
3. **Found untestable code?** → Suggest refactoring for testability (separate concern)
4. **Found a bug while testing?** → Route to `/fix-bug`


---

## Workflow Chain — Suggest Next Steps

After completing this skill, suggest the appropriate next skill to the user:
- **If tests reveal bugs**: `/fix-bug` — diagnose and fix the discovered issues
- **If coverage is now complete**: `/review` — review the test code itself
- **If ready for full validation**: `/qa` — run the full multi-agent QA pass

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
