# PLAN-0083 — Pydantic-Domain → Frozen-Dataclass Migration

> **PRD**: derived from `/investigate` 2026-05-07 — issue I-8 (domain-entity convention drift)
> **Status**: stub
> **Created**: 2026-05-07
> **Last revised**: 2026-05-07 (BP-405 name-verification + architecture compliance audit)
> **Owner**: TBD
> **Estimated effort**: ~1 dev-day (single wave)
> **Hard dependencies**: none (standalone refactor — no upstream plan dependencies)
> **Blocks**: none

---

## §0 Why this plan exists

The worldview domain layer convention is **frozen dataclasses with `kw_only=True`** (see `services/knowledge-graph/.../domain/entities/relation_summary.py`, PLAN-0074 §9.1). But `services/rag-chat/src/rag_chat/domain/brief.py` uses `pydantic.BaseModel` for `BriefCitation`, `BriefBullet`, `BriefSection`. Two conventions in the same domain layer increase cognitive load, break the "Pydantic in API only" boundary, and cost runtime overhead (Pydantic v2 model construction is 5–10× slower than dataclass).

This plan migrates the rag-chat brief domain entities to the worldview convention.

---

## §1 BP-405 Name Verification

The following names were mechanically verified via `grep` against the current codebase on 2026-05-07.

| Name | Type | Exists now? | Source |
|------|------|-------------|--------|
| `BriefCitation` | class in `domain/brief.py` | YES — currently `pydantic.BaseModel` | `services/rag-chat/src/rag_chat/domain/brief.py:19` |
| `BriefBullet` | class in `domain/brief.py` | YES — currently `pydantic.BaseModel` | `services/rag-chat/src/rag_chat/domain/brief.py:42` |
| `BriefSection` | class in `domain/brief.py` | YES — currently `pydantic.BaseModel` | `services/rag-chat/src/rag_chat/domain/brief.py:58` |
| `GeneratedBrief` | class | NO — DOES NOT EXIST in `domain/brief.py` or anywhere in rag-chat src. The plan must NOT include this class as a migration target. | — |
| `api/schemas.py` re-exports | `BriefCitation`, `BriefBullet`, `BriefSection` re-exported from `api/schemas.py:16,18` | YES — `from rag_chat.domain.brief import BriefBullet, BriefCitation, BriefSection` | `services/rag-chat/src/rag_chat/api/schemas.py:16` |
| `BriefingResponse` Pydantic model | class | YES — uses `BriefSection` as field type | `api/schemas.py:121` |
| `PublicBriefingResponse` Pydantic model | class | YES — uses `BriefSection` as field type | `api/schemas.py:163` |
| `generate_briefing.py` use case | file | YES — constructs `BriefCitation`, `BriefBullet`, `BriefSection` | `application/use_cases/generate_briefing.py` |
| `public_briefings.py` route | file | YES — handles `BriefSection`, `BriefBullet` | `api/routes/public_briefings.py` |
| `model_config = ConfigDict(populate_by_name=True)` | alias on `BriefCitation` | YES — `domain/brief.py:39`; must be handled in migration | `domain/brief.py:39` |
| `Field(..., max_length=400)` on `BriefCitation.snippet` | validation constraint | YES — must port to `__post_init__` | `domain/brief.py:33` |
| `Field(..., min_length=1, max_length=400)` on `BriefBullet.text` | validation constraint | YES — must port to `__post_init__` | `domain/brief.py:54` |
| `Field(..., min_length=1)` on `BriefBullet.citations` | validation constraint | YES — must port to `__post_init__` | `domain/brief.py:55` |
| `Field(..., max_length=120)` on `BriefSection.title` | validation constraint | YES — must port to `__post_init__` | `domain/brief.py:71` |
| `Field(..., min_length=0, max_length=8)` on `BriefSection.bullets` | validation constraint | YES — must port to `__post_init__` | `domain/brief.py:76` |

**Scope correction**: `GeneratedBrief` does NOT exist in the codebase. Wave A migrates only `BriefCitation`, `BriefBullet`, and `BriefSection`.

---

## 2. Scope

| Wave | Title | Layer | Effort |
|------|-------|-------|--------|
| A | Convert `BriefCitation`, `BriefBullet`, `BriefSection` (3 classes, NOT 4 — `GeneratedBrief` does not exist) from `pydantic.BaseModel` to `@dataclass(frozen=True, kw_only=True)`; add `from_dict` / `to_dict` class/instance methods; port all `Field(...)` constraints to `__post_init__`; handle `populate_by_name` alias; update all callers (use cases, routes, API schemas); run full rag-chat test suite before and after | `domain/` + `application/` + `api/` | 1 dev-day |

## 3. Hard Constraints

- **Exact decorator**: use `@dataclass(frozen=True, kw_only=True)` — both flags are required. `frozen=True` enforces immutability (prevents mutation after construction). `kw_only=True` allows required fields in subclasses without MRO ordering issues (standard worldview convention).
- **`from_dict` / `to_dict` methods**: each migrated class MUST have:
  - `@classmethod def from_dict(cls, data: dict) -> Self` — constructs the dataclass from a plain dict (used by API layer to convert from JSON/Pydantic response body).
  - `def to_dict(self) -> dict` — converts to a JSON-serializable dict (used by API layer to serialize to Pydantic response models and by Valkey/DB storage).
  These methods follow the canonical pattern in `libs/contracts/` frozen dataclasses.
- **API layer serialization path**: `api/schemas.py` imports `BriefCitation`, `BriefBullet`, `BriefSection` directly and re-exports them (line 16–18). After migration, `BriefingResponse` and `PublicBriefingResponse` (Pydantic `BaseModel` — these stay Pydantic) must serialize domain frozen dataclasses to JSON. Two valid patterns:
  1. `BriefSection.to_dict()` called in the response model's `model_validator` or in the route handler before constructing the Pydantic response.
  2. Pydantic `model_config = ConfigDict(arbitrary_types_allowed=True)` on `BriefingResponse` + custom `__get_pydantic_core_schema__` on the dataclass. **Pattern 1 is strongly preferred** (simpler, no metaclass magic).
  The chosen pattern MUST be documented with a `# WHY` comment in `api/schemas.py`.
- **`populate_by_name` alias migration**: `BriefCitation` has `model_config = ConfigDict(populate_by_name=True)` to accept the legacy `source_id` alias. In the frozen dataclass, this becomes: constructor parameter is `document_id`; `from_dict` accepts both `document_id` and `source_id` keys (checks for `source_id` as fallback). The `to_dict` always emits `document_id` (no legacy key emitted).
- **Validation parity in `__post_init__`**: all `Field(...)` constraints port to explicit guards:
  ```python
  def __post_init__(self) -> None:
      if len(self.snippet) > 400:
          raise ValueError(f"snippet too long: {len(self.snippet)} > 400")
      # etc.
  ```
  The constraints are listed in §1 above. Every constraint gets a corresponding unit test.
- **No `pydantic` import in `domain/brief.py` after migration**: the final file must NOT contain `from pydantic import ...`. A lint rule or import guard can verify this.
- **Behaviour preserving**: run `python -m pytest services/rag-chat/tests/ -v` BEFORE editing any file (record passing count) and AGAIN after the final commit. Both runs must show the same passing tests. Any new failures are regressions and must be fixed before merging (R33).
- **Full test suite, not just touched files (R33)**: run `python -m pytest services/rag-chat/tests/ -v` — not just `tests/unit/domain/` — because `generate_briefing.py`, `public_briefings.py`, and `api/schemas.py` all import these classes and their tests will catch serialization regressions.
- **No Alembic migration required**: these are application-layer value objects, not ORM models. No DB schema changes.
- **UUIDs**: `common.ids.new_uuid7()` for any UUIDs created by callers (R10). No `uuid.uuid4()`.
- **Timestamps**: `common.time.utc_now()` (R11). No naive datetimes.
- **structlog only**: if any logging is added, use `structlog.get_logger()`. No stdlib `logging`.

## 4. Out of scope

- `GeneratedBrief` — does not exist; nothing to migrate.
- Other Pydantic-in-domain instances (would need a repo-wide audit first; capture as a follow-up if more are found).

---

*Stub generated 2026-05-07. BP-405 audit 2026-05-07.*
