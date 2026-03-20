> **STATUS: IMPLEMENTED** — Wave-01 fully implemented (2026-03-20). Tasks W-001, C-001, B-001, F-001, W-002, W-005, W-003, W-004 complete.

# Execution Prompt 0010 — portfolio-watchlist-intelligence-layer wave 01

## Context (read first)

- **Source**: Portfolio service gap analysis: `docs/ai-interactions/agent-responses/0006-response-20260319-portfolio-watchlist-gap-analysis.md`
- **Wave plan**: `docs/ai-interactions/agent-prompts/0010-exec-wave-portfolio-watchlist-intelligence-layer-plan.md`
- **Goal**: Implement all zero-dependency domain foundations for watchlists (W-001), alert preferences (C-001), entity_id linking (B-001), and pagination improvements (F-001), then build the repo ports (W-002), messaging schemas (W-005), DB infrastructure (W-003), and use cases (W-004) that depend on them. By the end of this wave, the full watchlist business logic and messaging stack are implemented and tested; only the API surface and Valkey wiring remain for wave-02.

---

## Assigned agent profile(s)

- `.claude/agents/backend-engineer.md`
- `.claude/agents/qa-test-engineer.md`

---

## Mandatory pre-read

Read **all** of these before writing a single line of code:

1. `AGENTS.md` — coding standards, naming conventions, architecture patterns
2. `CLAUDE.md` — fail-fast loop, diff discipline, no deferred fixes
3. `RULES.md` — R7 (no cross-service FKs), R8 (outbox pattern), R6 (non-breaking API additions)
4. `docs/services/portfolio.md` — full current API surface and DB schema
5. `docs/ai-interactions/agent-responses/0006-response-20260319-portfolio-watchlist-gap-analysis.md` — Section 4 (gap details) and Section 5 (task list)
6. `docs/ai-interactions/BUG_PATTERNS.md` — scan entries for async ORM, UUIDv7, Alembic, and outbox patterns
7. `services/portfolio/src/portfolio/domain/entities/portfolio.py` — reference entity pattern
8. `services/portfolio/src/portfolio/application/ports/repositories.py` — existing ABC patterns
9. `services/portfolio/src/portfolio/infrastructure/db/repositories/portfolio.py` — existing repo pattern
10. `services/portfolio/src/portfolio/infrastructure/db/unit_of_work.py` — UoW wiring pattern
11. `services/portfolio/alembic/versions/0001_initial_schema.py` — migration style reference
12. `services/portfolio/src/portfolio/messaging/topics.py` and `mapper.py` — messaging extension pattern

When handing off, explicitly list which BUG_PATTERNS entries were applied.

---

## Scope & Bounded write paths

Only touch the paths listed per task. Do not refactor surrounding code unless a BUG_PATTERN mandates it.

---

## Task scope for this wave

**Tasks: W-001, C-001, B-001, F-001, W-002, W-005, W-003, W-004**

### Parallel group A — Independent domain foundations

These four tasks have zero dependencies on each other. Run in parallel.

| Task ID | Short title | Primary paths |
|---------|-------------|---------------|
| W-001 | Watchlist domain entities + events + errors | `domain/entities/watchlist.py`, `domain/entities/watchlist_member.py`, `domain/events.py`, `domain/errors.py`, `domain/enums.py` |
| C-001 | Alert preference domain entities | `domain/entities/alert_preference.py`, `domain/enums.py`, `domain/errors.py` |
| B-001 | Add `entity_id` to InstrumentRef | `domain/entities/instrument.py`, `db/models/instrument.py`, `consumers/instrument_consumer.py`, `messaging/schemas/instrument_ref.created.avsc`, `messaging/mapper.py`, `api/schemas.py` |
| F-001 | Pagination for unbounded list endpoints | `api/schemas.py`, `api/routes/portfolio.py`, `api/routes/instrument.py`, `api/routes/transaction.py`, `application/ports/repositories.py`, `db/repositories/portfolio.py`, `db/repositories/instrument.py`, `db/repositories/transaction.py` |

### Sequential group B — Repo ports (depends on W-001)

| Task ID | Short title | Primary paths | Depends on |
|---------|-------------|---------------|------------|
| W-002 | Watchlist repo ABCs + UoW properties + FakeRepo | `application/ports/repositories.py`, `application/ports/unit_of_work.py`, `tests/unit/fakes.py` | W-001 |

### Parallel group C — Messaging schemas + DB infrastructure (parallel with each other; both depend on W-002)

| Task ID | Short title | Primary paths | Depends on |
|---------|-------------|---------------|------------|
| W-005 | Watchlist Avro schemas + messaging wiring | `messaging/schemas/watchlist.item_added.avsc`, `messaging/schemas/watchlist.item_removed.avsc`, `messaging/topics.py`, `messaging/mapper.py`, `messaging/serialization.py`, `infra/kafka/schemas/`, `infra/kafka/init/create-topics.sh` | W-001 |
| W-003 | Watchlist DB migration, ORM models, SQL repositories | `db/models/watchlist.py`, `db/models/watchlist_member.py`, `db/repositories/watchlist.py`, `db/repositories/watchlist_member.py`, `db/unit_of_work.py`, `alembic/versions/0002_add_watchlists.py` | W-002 |

### Sequential group D — Use cases (depends on W-002 for repo ports and fakes)

| Task ID | Short title | Primary paths | Depends on |
|---------|-------------|---------------|------------|
| W-004 | All 6 watchlist use cases | `application/use_cases/watchlist.py` | W-002 |

---

## Implementation instructions

---

### W-001 — Watchlist domain entities, events, and errors

**Why:** The watchlist feature is entirely absent from the domain layer. No file, class, enum, event, or error exists for watchlists.

**How:**

1. **`domain/enums.py`** — Add `WatchlistStatus(StrEnum)` with values `ACTIVE = "active"` and `DELETED = "deleted"`.

2. **`domain/entities/watchlist.py`** — Create `Watchlist` frozen dataclass:
   ```python
   @dataclass(frozen=True)
   class Watchlist:
       id: UUID
       tenant_id: UUID
       user_id: UUID
       name: str
       status: WatchlistStatus
       created_at: datetime

       def is_active(self) -> bool:
           return self.status == WatchlistStatus.ACTIVE
   ```
   Use `new_id()` from `libs/common` for `id` when constructing new instances.

3. **`domain/entities/watchlist_member.py`** — Create `WatchlistMember` frozen dataclass:
   ```python
   @dataclass(frozen=True)
   class WatchlistMember:
       id: UUID
       watchlist_id: UUID
       entity_id: UUID   # KG canonical entity — no cross-service FK (R7)
       entity_type: str  # e.g. "company"
       added_at: datetime
   ```

4. **`domain/events.py`** — Add two new event classes inheriting from `DomainEvent`:
   - `WatchlistItemAdded` with fields: `watchlist_id: UUID`, `user_id: UUID`, `entity_id: UUID`, `entity_type: str`
   - `WatchlistItemRemoved` with same fields

5. **`domain/errors.py`** — Add:
   - `WatchlistNotFoundError(DomainError)`
   - `WatchlistAlreadyExistsError(DomainError)` (duplicate name per user)
   - `WatchlistMemberNotFoundError(DomainError)`
   - `WatchlistMemberAlreadyExistsError(DomainError)`

**Tests (mandatory, full coverage):**
- `tests/unit/test_domain_watchlist.py`:
  - `test_watchlist_is_active_returns_true_for_active_status`
  - `test_watchlist_is_active_returns_false_for_deleted_status`
  - `test_watchlist_member_stores_entity_id_without_fk`
  - `test_watchlist_item_added_event_fields`
  - `test_watchlist_item_removed_event_fields`
  - `test_watchlist_error_hierarchy` — assert all 4 errors subclass `DomainError`

**Documentation:** `docs/services/portfolio.md` — update after W-006 when API is complete. No doc update needed yet for domain-only changes.

---

### C-001 — Alert preference domain entities

**Why:** Alert preferences are entirely absent from the domain layer.

**How:**

1. **`domain/enums.py`** — Add `AlertType(StrEnum)` with values: `SIGNAL = "signal"`, `CONTRADICTION = "contradiction"`, `CONFIDENCE_DROP = "confidence_drop"`, `NEW_EVENT = "new_event"`.

2. **`domain/entities/alert_preference.py`** — Create two frozen dataclasses:
   ```python
   @dataclass(frozen=True)
   class AlertPreference:
       id: UUID
       tenant_id: UUID
       user_id: UUID
       alert_type: AlertType
       enabled: bool
       updated_at: datetime

   @dataclass(frozen=True)
   class EntitySuppression:
       id: UUID
       tenant_id: UUID
       user_id: UUID
       entity_id: UUID
       suppressed_at: datetime
   ```

3. **`domain/errors.py`** — Add `AlertPreferenceNotFoundError(DomainError)`.

**Tests (mandatory):**
- `tests/unit/test_domain_alert_preference.py`:
  - `test_alert_preference_creation`
  - `test_entity_suppression_creation`
  - `test_alert_type_enum_values`
  - `test_alert_preference_error_hierarchy`

**Documentation:** `docs/services/portfolio.md` — update after C-003 when API is complete.

---

### B-001 — Add `entity_id` to InstrumentRef

**Why:** `InstrumentRef` has no `entity_id` field. Without it, holdings cannot be joined to watchlist members (which track by `entity_id`), blocking the "portfolio vs watchlist overlap" intelligence feature.

**How:**

1. **`domain/entities/instrument.py`** — Add `entity_id: UUID | None = None` to `InstrumentRef` dataclass. Use `None` default so the field is optional (most instruments won't have a KG entity yet).

2. **`infrastructure/db/models/instrument.py`** — Add nullable column:
   ```python
   entity_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
   ```

3. **`alembic/versions/0003_add_entity_id_to_instruments.py`** — Create new migration:
   ```python
   op.add_column("instruments", sa.Column("entity_id", sa.UUID(), nullable=True))
   op.create_index("ix_instruments_entity_id", "instruments", ["entity_id"], unique=False,
                   postgresql_where=sa.text("entity_id IS NOT NULL"))
   ```
   This is additive and fully backward-compatible.

4. **`consumers/instrument_consumer.py`** — In the handler, parse `entity_id` from the event payload (if present in the Avro record). Pass to `InstrumentRef` constructor.

5. **`messaging/schemas/instrument_ref.created.avsc`** — Add field with null default (backward-compatible schema evolution):
   ```json
   {"name": "entity_id", "type": ["null", "string"], "default": null}
   ```

6. **`messaging/mapper.py`** — In `instrument_ref_created_to_dict`, add `"entity_id": str(instrument.entity_id) if instrument.entity_id else None`.

7. **`api/schemas.py`** — Add `entity_id: UUID | None = None` to `InstrumentResponse`.

**Tests (mandatory):**
- `tests/unit/test_domain_entities.py` — update to assert `InstrumentRef` accepts `entity_id=None` and a valid UUID.
- `tests/contract/test_instrument_ref_created_contract.py` — update: assert the Avro schema includes `entity_id` with null default; round-trip encode/decode with `entity_id=None` and with a UUID value.
- `tests/integration/test_instrument_api.py` — update: assert `GET /api/v1/instruments/{id}` response includes `entity_id` field (may be null).

**Documentation:** `docs/services/portfolio.md` — update InstrumentRef entity description and API response schema table to include `entity_id`.

---

### F-001 — Pagination for unbounded list endpoints

**Why:** `GET /api/v1/portfolios`, `GET /api/v1/instruments`, and `GET /api/v1/transactions` return unbounded lists. With thousands of instruments or transactions, these will cause OOM and gateway timeouts.

**How:**

1. **`api/schemas.py`** — Add generic paginated response wrapper:
   ```python
   from typing import Generic, TypeVar
   T = TypeVar("T")

   class PaginatedResponse(BaseModel, Generic[T]):
       items: list[T]
       total: int
       limit: int
       offset: int
   ```

2. **`application/ports/repositories.py`** — For `PortfolioRepository`, `InstrumentRepository`, `TransactionRepository`, update the `list` / `list_all` method signatures to accept `limit: int = 100, offset: int = 0` and return a tuple `(items, total)` or equivalent.

3. **`infrastructure/db/repositories/portfolio.py`**, `instrument.py`, `transaction.py` — Implement `LIMIT :limit OFFSET :offset` in SQL queries. Add a `COUNT(*)` sub-query or window function to get `total`.

4. **`api/routes/portfolio.py`** — Add `limit: int = Query(default=100, le=500, ge=1)` and `offset: int = Query(default=0, ge=0)` to the list endpoint. Return `PaginatedResponse[PortfolioResponse]`.

5. **`api/routes/instrument.py`** and `api/routes/transaction.py`** — Same changes.

**Tests (mandatory):**
- `tests/integration/test_portfolio_api.py` — add: insert 3 portfolios, call list with `limit=2&offset=0`, assert `items` has 2 and `total` is 3; call with `offset=2`, assert `items` has 1.
- Same pattern for instruments and transactions.
- Assert backward compatibility: existing callers passing no params get `limit=100, offset=0` defaults.

**Documentation:** `docs/services/portfolio.md` — update each list endpoint entry to show `limit` and `offset` query params and the `PaginatedResponse` shape.

---

### W-002 — Watchlist repo ABCs, UoW properties, and fake implementations

**Why:** Use cases need abstract repository interfaces before they can be written. The `FakeUnitOfWork` in tests needs fake implementations so use case unit tests (W-004) can run without a DB.

**How:**

1. **`application/ports/repositories.py`** — Add two abstract classes:

   `WatchlistRepository(ABC)`:
   - `async def get(self, id: UUID, tenant_id: UUID) -> Watchlist | None`
   - `async def list_by_user(self, user_id: UUID, tenant_id: UUID) -> list[Watchlist]`
   - `async def save(self, watchlist: Watchlist) -> None`
   - `async def delete(self, id: UUID) -> None`

   `WatchlistMemberRepository(ABC)`:
   - `async def get(self, watchlist_id: UUID, entity_id: UUID) -> WatchlistMember | None`
   - `async def list_by_watchlist(self, watchlist_id: UUID) -> list[WatchlistMember]`
   - `async def list_by_entity(self, entity_id: UUID) -> list[WatchlistMember]`
   - `async def save(self, member: WatchlistMember) -> None`
   - `async def delete(self, watchlist_id: UUID, entity_id: UUID) -> None`

2. **`application/ports/unit_of_work.py`** — Add abstract properties `watchlists: WatchlistRepository` and `watchlist_members: WatchlistMemberRepository`.

3. **`tests/unit/fakes.py`** — Add `FakeWatchlistRepository` and `FakeWatchlistMemberRepository` (in-memory dict-based implementations). Wire them into `FakeUnitOfWork`.

**Tests:** No dedicated test file for fakes — they are tested implicitly in W-004.

---

### W-005 — Watchlist Avro schemas and messaging wiring

**Why:** The outbox dispatcher needs schema registry entries and mapper functions for `WatchlistItemAdded` and `WatchlistItemRemoved` events before use cases can publish them.

**How:**

1. **`messaging/schemas/watchlist.item_added.avsc`** — Create:
   ```json
   {
     "type": "record",
     "name": "watchlist.item_added",
     "namespace": "portfolio.events",
     "fields": [
       {"name": "event_id", "type": "string"},
       {"name": "event_type", "type": "string", "default": "watchlist.item_added"},
       {"name": "aggregate_type", "type": "string", "default": "watchlist"},
       {"name": "aggregate_id", "type": "string"},
       {"name": "tenant_id", "type": "string"},
       {"name": "occurred_at", "type": "string"},
       {"name": "schema_version", "type": "int", "default": 1},
       {"name": "correlation_id", "type": ["null", "string"], "default": null},
       {"name": "causation_id", "type": ["null", "string"], "default": null},
       {"name": "watchlist_id", "type": "string", "default": ""},
       {"name": "user_id", "type": "string", "default": ""},
       {"name": "entity_id", "type": "string", "default": ""},
       {"name": "entity_type", "type": "string", "default": "company"}
     ]
   }
   ```

2. **`messaging/schemas/watchlist.item_removed.avsc`** — Same envelope + domain fields as above.

3. **`infra/kafka/schemas/watchlist.item_added.avsc`** and `watchlist.item_removed.avsc` — Copy identical content (global schema registry registration).

4. **`messaging/topics.py`** — Add constant `WATCHLIST_UPDATED_V1 = "portfolio.watchlist.updated.v1"` and add entries to `EVENT_TOPIC_MAP`: `"watchlist.item_added": WATCHLIST_UPDATED_V1`, `"watchlist.item_removed": WATCHLIST_UPDATED_V1`.

5. **`messaging/mapper.py`** — Add `watchlist_item_added_to_dict(event: WatchlistItemAdded) -> dict` and `watchlist_item_removed_to_dict(event: WatchlistItemRemoved) -> dict` functions matching the Avro field names exactly.

6. **`messaging/serialization.py`** — Add both event types to `_AVSC_MAP` referencing the new `.avsc` file paths.

7. **`infra/kafka/init/create-topics.sh`** — Add `portfolio.watchlist.updated.v1:3:1`.

**Tests (mandatory):**
- `tests/contract/test_watchlist_item_added_contract.py` — Avro round-trip: encode a `WatchlistItemAdded` event dict → Avro bytes → decode back → assert all fields match.
- `tests/contract/test_watchlist_item_removed_contract.py` — Same for `WatchlistItemRemoved`.

**Documentation:** No portfolio.md update yet — updated in W-006 when the full feature is documented.

---

### W-003 — Watchlist DB migration, ORM models, and SQL repositories

**Why:** Watchlist business logic needs storage. `alembic check` currently produces a diff because `WatchlistModel` and `WatchlistMemberModel` do not exist.

**How:**

1. **`infrastructure/db/models/watchlist.py`**:
   ```python
   class WatchlistModel(Base):
       __tablename__ = "watchlists"
       id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
       tenant_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
       user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
       name: Mapped[str] = mapped_column(Text, nullable=False)
       status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
       created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
   ```
   Table-level: `UniqueConstraint("user_id", "name", name="uq_watchlists_user_name")`, indexes on `user_id` and `tenant_id`.

2. **`infrastructure/db/models/watchlist_member.py`**:
   ```python
   class WatchlistMemberModel(Base):
       __tablename__ = "watchlist_members"
       id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
       watchlist_id: Mapped[UUID] = mapped_column(ForeignKey("watchlists.id"), nullable=False)
       entity_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
       entity_type: Mapped[str] = mapped_column(String(50), nullable=False, default="company")
       added_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, server_default=func.now())
   ```
   Table-level: `UniqueConstraint("watchlist_id", "entity_id", name="uq_watchlist_members_watchlist_entity")`, indexes on `entity_id` and `watchlist_id`.

3. **`alembic/versions/0002_add_watchlists.py`** — Migration covering both tables + all indexes + outbox performance index from Gap E4:
   ```sql
   CREATE INDEX ix_outbox_events_status_lease_expires
   ON outbox_events (status, lease_expires NULLS FIRST)
   WHERE status IN ('pending', 'processing');
   ```
   Run `alembic check` after — must produce no diff.

4. **`infrastructure/db/repositories/watchlist.py`** — Implement `SqlAlchemyWatchlistRepository(WatchlistRepository)` following the existing repository pattern (see `portfolio.py`). Implement `get`, `list_by_user`, `save`, `delete`.

5. **`infrastructure/db/repositories/watchlist_member.py`** — Implement `SqlAlchemyWatchlistMemberRepository(WatchlistMemberRepository)`. For `list_by_entity`, use a JOIN on `watchlists` to filter by `status = 'active'` so only active watchlists' members are returned.

6. **`infrastructure/db/unit_of_work.py`** — Wire new repos in `__aenter__` and add concrete properties.

7. **`infrastructure/db/models/__init__.py`** — Register both new models so Alembic picks them up.

**Tests (mandatory):**
- `tests/integration/test_watchlist_api.py` — placeholder for wave-02; add a minimal integration test that runs `alembic upgrade head` and confirms both tables exist.

**Documentation:** Updated in W-006.

---

### W-004 — All 6 watchlist use cases

**Why:** The application layer has no use cases for watchlist management. Without them, the API cannot be built.

**How (implement in `application/use_cases/watchlist.py`):**

1. `CreateWatchlistUseCase`:
   - Validate user exists (call `uow.users.get(user_id, tenant_id)`, raise `UserNotFoundError` if absent).
   - Check name uniqueness: call `uow.watchlists.list_by_user(user_id, tenant_id)` and ensure no active watchlist has the same name (raise `WatchlistAlreadyExistsError`).
   - Create `Watchlist(id=new_id(), ..., status=WatchlistStatus.ACTIVE)`.
   - `uow.watchlists.save(watchlist)`.
   - Write `WatchlistCreated` outbox event to `portfolio.events.v1` topic. (Use existing outbox pattern from `create_portfolio.py`.)
   - Commit.

2. `GetWatchlistUseCase`:
   - Fetch `uow.watchlists.get(watchlist_id, tenant_id)` → raise `WatchlistNotFoundError` if absent.
   - Assert `watchlist.user_id == owner_id` (raise `PermissionDeniedError` or equivalent if not owner).
   - Return watchlist.

3. `ListWatchlistsUseCase`:
   - `uow.watchlists.list_by_user(owner_id, tenant_id)`.

4. `DeleteWatchlistUseCase`:
   - Fetch and ownership-check (same as Get).
   - Soft-delete: replace watchlist with `status=WatchlistStatus.DELETED`, call `uow.watchlists.save(updated_watchlist)`.
   - Write `WatchlistDeleted` outbox event.

5. `AddWatchlistMemberUseCase`:
   - Fetch and ownership-check watchlist.
   - Assert watchlist is active (raise `WatchlistNotFoundError` if deleted).
   - Check duplicate: `uow.watchlist_members.get(watchlist_id, entity_id)` — raise `WatchlistMemberAlreadyExistsError` if found.
   - Create and save `WatchlistMember`.
   - Write `WatchlistItemAdded` outbox event to `portfolio.watchlist.updated.v1` topic (R8 compliance: same DB transaction).
   - **Cache invalidation**: call `await cache.invalidate_entity(entity_id)` — `cache` is a `WatchlistCachePort` injected as a use case parameter. For wave-01, the concrete implementation is injected as a `NoOpWatchlistCache` (stub that does nothing); wave-02 replaces it with `ValkeyWatchlistCache`.

6. `RemoveWatchlistMemberUseCase`:
   - Fetch watchlist (ownership check).
   - Fetch member (`uow.watchlist_members.get(watchlist_id, entity_id)`) — raise `WatchlistMemberNotFoundError` if absent.
   - Delete member.
   - Write `WatchlistItemRemoved` outbox event.
   - Call `await cache.invalidate_entity(entity_id)`.

**Cache port (add to `application/ports/cache.py`, new file):**
```python
class WatchlistCachePort(ABC):
    @abstractmethod
    async def get_user_ids(self, entity_id: UUID) -> list[UUID]: ...
    @abstractmethod
    async def invalidate_entity(self, entity_id: UUID) -> None: ...
    @abstractmethod
    async def set_user_ids(self, entity_id: UUID, user_ids: list[UUID], ttl: int) -> None: ...

class NoOpWatchlistCache(WatchlistCachePort):
    async def get_user_ids(self, entity_id: UUID) -> list[UUID]: return []
    async def invalidate_entity(self, entity_id: UUID) -> None: pass
    async def set_user_ids(self, entity_id: UUID, user_ids: list[UUID], ttl: int) -> None: pass
```

**Tests (mandatory — full coverage):**
- `tests/unit/test_use_cases_watchlist.py`:
  - `test_create_watchlist_success`
  - `test_create_watchlist_duplicate_name_raises`
  - `test_create_watchlist_user_not_found_raises`
  - `test_get_watchlist_not_found_raises`
  - `test_get_watchlist_wrong_owner_raises`
  - `test_list_watchlists_returns_user_watchlists`
  - `test_delete_watchlist_soft_deletes`
  - `test_add_member_success_writes_outbox_event`
  - `test_add_member_duplicate_raises`
  - `test_add_member_calls_cache_invalidation`
  - `test_remove_member_success_writes_outbox_event`
  - `test_remove_member_not_found_raises`
  - `test_remove_member_calls_cache_invalidation`

Use `FakeUnitOfWork` (with `FakeWatchlistRepository` and `FakeWatchlistMemberRepository` from W-002) and `NoOpWatchlistCache`.

---

## Task-scoped fail-fast gate (mandatory)

After **each** task:

1. Run `ruff check` on changed files.
2. Run `mypy` on changed packages.
3. Run targeted unit/contract/integration tests for that task.

Fix any failure before starting the next task. No deferred fixes.

---

## Regression guardrails

Before marking wave-01 done:

1. `make test` passes in `services/portfolio` — all existing 253+ tests still pass.
2. `alembic check` exits 0 after migration 0002 and 0003 are applied.
3. Contract tests for `watchlist.item_added` and `watchlist.item_removed` pass.
4. All 13+ new unit tests for use cases (W-004) pass.
5. No `datetime.now()` without `tz=` in any modified file.
6. No cross-service FK in migration 0002 (watchlist_members.entity_id must be a plain UUID column, not an FK).

---

## Documentation updates (mandatory)

| Document | Required changes |
|----------|------------------|
| `docs/services/portfolio.md` | Update entity_id field on InstrumentRef (B-001); update list endpoints with pagination params and PaginatedResponse shape (F-001). Watchlist and alert-pref sections updated in wave-02 when API is complete. |

---

## Done criteria (wave-01 complete when all pass)

- [ ] `Watchlist`, `WatchlistMember` domain entities exist and all unit tests pass.
- [ ] `WatchlistItemAdded`, `WatchlistItemRemoved` events exist and contract tests pass.
- [ ] All 4 watchlist domain errors exist and inherit from `DomainError`.
- [ ] `AlertType`, `AlertPreference`, `EntitySuppression` exist and unit tests pass.
- [ ] `InstrumentRef.entity_id` field exists; Avro schema updated (null default); contract test updated and passes.
- [ ] Migration `0003_add_entity_id_to_instruments.py` applied; `alembic check` exits 0.
- [ ] Pagination (`limit`/`offset`) on all 3 list endpoints; integration tests verify `total` and item counts.
- [ ] `WatchlistRepository` and `WatchlistMemberRepository` ABCs defined; `FakeRepo` implementations exist in `tests/unit/fakes.py`.
- [ ] `WatchlistCachePort` and `NoOpWatchlistCache` defined in `application/ports/cache.py`.
- [ ] Avro schemas for watchlist events exist (both `services/portfolio/messaging/schemas/` and `infra/kafka/schemas/`).
- [ ] Contract tests for both watchlist Avro schemas pass.
- [ ] `portfolio.watchlist.updated.v1` added to `create-topics.sh`.
- [ ] Migration `0002_add_watchlists.py` creates both tables + all indexes + outbox index; `alembic check` exits 0.
- [ ] All 13+ watchlist use case unit tests pass.
- [ ] `make test` passes — no regressions in existing 253+ tests.
- [ ] Ruff and mypy clean on all modified files.

---

## Handoff evidence required

1. Task IDs completed + changed files per task.
2. `alembic check` output (exit code 0).
3. Unit test output: pass count for new tests in `test_domain_watchlist.py`, `test_domain_alert_preference.py`, `test_use_cases_watchlist.py`.
4. Contract test output: `test_watchlist_item_added_contract.py` and `test_watchlist_item_removed_contract.py` pass.
5. Integration test output confirming pagination works.
6. BUG_PATTERNS entries applied (list IDs).
7. **Documentation quality checklist:**

| Criterion | Status | Notes |
|-----------|--------|-------|
| Accuracy — entity_id field and pagination in portfolio.md match implementation | ✓ / N/A | |
| Avro schemas valid (round-trip tested) | ✓ | |
| No cross-service FK in migrations | ✓ | |
| No datetime.now() without tz= | ✓ | |
| Existing test suite (253+) still passes | ✓ | |

8. Proposed commit message.

---

## Proposed commit message (template)

```
feat(portfolio): watchlist domain, messaging, DB layer, use cases; entity_id + pagination

- Add Watchlist and WatchlistMember domain entities, events (WatchlistItemAdded/Removed),
  4 domain errors, WatchlistStatus enum.
- Add AlertPreference, EntitySuppression domain entities and AlertType enum.
- Add entity_id (nullable UUID) to InstrumentRef; update Avro schema, consumer, mapper.
- Add PaginatedResponse[T] + limit/offset to portfolio, instrument, transaction list endpoints.
- Add WatchlistRepository/WatchlistMemberRepository ABCs; FakeRepo implementations.
- Add WatchlistCachePort with NoOpWatchlistCache stub.
- Add watchlist.item_added and watchlist.item_removed Avro schemas; wire into topics/mapper/serialization.
- Add migrations 0002 (watchlists + members tables + outbox index) and 0003 (entity_id col).
- Implement all 6 watchlist use cases with outbox pattern and cache invalidation hook.

Validated: alembic check clean; 253+ existing tests pass; new unit/contract tests pass.
```
