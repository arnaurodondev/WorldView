# Execution Prompt 0011 — Ingestion Pipeline v1 Foundations · Wave 01

## Context (read first)

- **Planning response**: `docs/ai-interactions/agent-responses/0011-response-20260322-ingestion-pipeline-v1-foundations.md`
- **Authoritative spec**: `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md` §1.4, §7, §15

## Assigned agent profile(s)

- `.claude/agents/data-platform-engineer.md`

## Mandatory pre-read

1. `AGENTS.md`
2. `CLAUDE.md`
3. `RULES.md`
4. `docs/ai-interactions/agent-responses/0011-response-20260322-ingestion-pipeline-v1-foundations.md` — task specs for T-F-001, T-F-002, T-F-003
5. `docs/ai-interactions/agent-responses/0014-PRD-v1-final.md` §1.4, §7.1 (Avro schema field specs), §15 (Schema Registry compatibility)
6. `infra/kafka/schemas/watchlist.item_removed.avsc` (file to rename)
7. `infra/kafka/init/create-topics.sh`
8. `infra/kafka/init/register-schemas.py`
9. `services/knowledge-graph/src/knowledge_graph/config.py`
10. `services/portfolio/` — grep for `watchlist.item_removed` before touching anything

## Objective

Complete all three §1.4 blocking repository fixes. These are mandatory prerequisites for all subsequent waves. Wave 01 must be fully committed before Wave 02 begins.

**No service implementation logic in this wave.** This wave only fixes schema files, renames event types, and corrects a config default.

## Task scope for this wave

### Parallel group — all three tasks are independent and can run concurrently

| Task | What | Files touched |
|------|------|---------------|
| **T-F-001** | Rename watchlist.item_removed → watchlist.item_deleted | `infra/kafka/schemas/` (rename + edit), `services/portfolio/` (grep + edit) |
| **T-F-002** | Create 6 missing Avro schema files + update register-schemas.py | `infra/kafka/schemas/` (6 new files), `infra/kafka/init/register-schemas.py` |
| **T-F-003** | Fix knowledge-graph DATABASE_URL default | `services/knowledge-graph/src/knowledge_graph/config.py`, `alembic.ini`, `configs/` |

Execute T-F-001 first (T-F-002 creates `portfolio.watchlist.updated.v1.avsc` which references the corrected event type vocabulary). Then T-F-002 and T-F-003 can proceed in parallel.

## Why this chunk

These are blocking fixes per PRD §1.4. Nothing in Prompts 0016 or 0017 can proceed safely without them:
- Without T-F-001: S10 silently drops watchlist delete events
- Without T-F-002: `schema-init` (boot step 4) fails; cluster cannot boot
- Without T-F-003: S7 connects to a non-existent database and fails its `/ready` check

## Implementation instructions

### T-F-001 — Rename `watchlist.item_removed` → `watchlist.item_deleted`

1. Read `infra/kafka/schemas/watchlist.item_removed.avsc`. Note all fields.
2. Create `infra/kafka/schemas/watchlist.item_deleted.avsc` with:
   - `"name": "WatchlistItemDeleted"` (was `watchlist.item_removed`)
   - `"event_type"` field default: `"watchlist.item_deleted"` (was `"watchlist.item_removed"`)
   - All other fields preserved exactly
3. Delete `infra/kafka/schemas/watchlist.item_removed.avsc`.
4. Run: `grep -r "watchlist.item_removed" services/portfolio/` — record all hits.
5. Update each hit: domain event class `event_type` string, outbox record factory, tests.
6. Run `grep -r "watchlist.item_removed" infra/` — update `register-schemas.py` if it references the old filename.
7. Run: `cd services/portfolio && make test` — all tests must pass before proceeding.

**Validation gate** (run before marking T-F-001 done):
```bash
grep -r "watchlist.item_removed" services/portfolio/ infra/kafka/schemas/
# Must return zero results
cd services/portfolio && python -m pytest tests/ -x -q
ruff check services/portfolio/src/
mypy services/portfolio/src/
```

### T-F-002 — Create 6 missing Avro schema files

Create each file in `infra/kafka/schemas/`. Use the exact field specifications from the response document §5 T-F-002. Do not invent fields — copy from the spec.

**File 1 — `portfolio.watchlist.updated.v1.avsc`**: single envelope record; `event_type` field discriminates `watchlist.item_added` vs `watchlist.item_deleted` at runtime. Include `entity_ids_affected` as an array field.

**File 2 — `graph.state.changed.v1.avsc`**: includes `primary_entity_id`, `related_entity_ids` (array), `relation_id` (nullable), `canonical_type` (nullable), `change_type`, `confidence` (nullable).

**File 3 — `intelligence.contradiction.v1.avsc`**: includes `subject_entity_id`, `relation_id`, `canonical_type`, `contradicting_claim_id`, `contradiction_strength` (float), `contradiction_type`.

**File 4 — `relation.type.proposed.v1.avsc`**: includes `proposed_type`, `semantic_mode`, `suggested_decay_class` (nullable), `example_subject_entity_id` (nullable), `example_object_entity_id` (nullable), `example_evidence_text` (nullable), `source_doc_id` (nullable).

**File 5 — `entity.dirtied.v1.avsc`**: includes `entity_id`, `dirty_reason`. This schema is for a compacted topic; the Kafka key is `entity_id` (plain string — no key schema registered).

**File 6 — `alert.delivered.v1.avsc`**: includes `alert_id`, `user_id`, `entity_id`, `alert_type`, `channel`.

All schemas must follow the event envelope standard: `event_id` (string), `event_type` (string), `schema_version` (int, default 1), `occurred_at` (string). All optional fields use Avro union `["null", "string"]` with `"default": null`.

After creating all 6 files, update `infra/kafka/init/register-schemas.py`:
- Add the FULL compatibility step for `relation.type.proposed.v1-value`:
  ```python
  # Set FULL compatibility for relation.type.proposed.v1 (both FORWARD and BACKWARD required)
  resp = requests.put(
      f"{SCHEMA_REGISTRY_URL}/config/relation.type.proposed.v1-value",
      json={"compatibility": "FULL"},
      headers={"Content-Type": "application/json"}
  )
  resp.raise_for_status()
  ```

**Validation gate**:
```bash
# Verify 6 new files exist
ls infra/kafka/schemas/*.avsc | wc -l
# Must be 16 (10 existing + 6 new; watchlist.item_removed replaced by watchlist.item_deleted)

# Validate each .avsc file is valid JSON
for f in infra/kafka/schemas/*.avsc; do python -c "import json; json.load(open('$f'))" && echo "OK: $f"; done

# Validate with fastavro
python -c "
import fastavro.schema
import pathlib
for f in pathlib.Path('infra/kafka/schemas').glob('*.avsc'):
    fastavro.schema.parse_schema(json.load(open(f)))
    print(f'VALID: {f.name}')
"

ruff check infra/kafka/init/register-schemas.py
```

### T-F-003 — Fix `knowledge-graph` DATABASE_URL default

1. Read `services/knowledge-graph/src/knowledge_graph/config.py`.
2. Change `database_url` default: `...5432/kg_db` → `...5432/intelligence_db`.
3. Add field: `alembic_enabled: bool = False`.
4. Run `grep -r "kg_db" services/knowledge-graph/` — update all occurrences (configs, alembic.ini, dev.local.env).
5. Update `configs/dev.local.env.example` (if it exists): add `KNOWLEDGE_GRAPH_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db` and `KNOWLEDGE_GRAPH_ALEMBIC_ENABLED=false`.
6. Run: `cd services/knowledge-graph && make test`.

**Validation gate**:
```bash
grep -r "kg_db" services/knowledge-graph/
# Must return zero results

cd services/knowledge-graph
python -c "from knowledge_graph.config import Settings; s = Settings(); assert 'intelligence_db' in s.database_url; assert s.alembic_enabled == False; print('Config OK')"
python -m pytest tests/ -x -q
ruff check src/
mypy src/
```

## Constraints

- Do NOT implement any service application logic (no adapters, no consumers, no use cases).
- Do NOT modify any files outside the listed `write_paths` for each task.
- Do NOT change existing Avro schema files other than the watchlist rename.
- Do NOT rename `watchlist.item_added.avsc` — only the removed/deleted one changes.
- The 6 new Avro schema files must have all fields with defaults for optional fields (forward compatibility).

**write_paths**:
```
infra/kafka/schemas/watchlist.item_deleted.avsc          # T-F-001 (created)
infra/kafka/schemas/portfolio.watchlist.updated.v1.avsc  # T-F-002
infra/kafka/schemas/graph.state.changed.v1.avsc          # T-F-002
infra/kafka/schemas/intelligence.contradiction.v1.avsc   # T-F-002
infra/kafka/schemas/relation.type.proposed.v1.avsc       # T-F-002
infra/kafka/schemas/entity.dirtied.v1.avsc               # T-F-002
infra/kafka/schemas/alert.delivered.v1.avsc              # T-F-002
infra/kafka/init/register-schemas.py                     # T-F-002
services/portfolio/src/portfolio/domain/events.py        # T-F-001
services/portfolio/src/portfolio/infrastructure/messaging/  # T-F-001 (grep-dependent)
services/portfolio/tests/                                # T-F-001 (grep-dependent)
services/knowledge-graph/src/knowledge_graph/config.py   # T-F-003
services/knowledge-graph/alembic.ini                     # T-F-003
services/knowledge-graph/configs/                        # T-F-003
```

## Required tests

```bash
# T-F-001
cd services/portfolio && python -m pytest tests/ -x -q
ruff check services/portfolio/src/
mypy services/portfolio/src/

# T-F-002 — schema validation
python -c "
import json, pathlib, fastavro.schema
schemas = list(pathlib.Path('infra/kafka/schemas').glob('*.avsc'))
print(f'Total schemas: {len(schemas)}')
for f in schemas:
    fastavro.schema.parse_schema(json.load(open(f)))
    print(f'VALID: {f.name}')
"

# T-F-003
cd services/knowledge-graph && python -m pytest tests/ -x -q
ruff check src/
mypy src/

# Full contract validation (run last)
./scripts/gen-contracts.sh
```

**Pass criteria**:
- `gen-contracts.sh` exits 0
- Portfolio tests: 100% pass
- Knowledge-graph tests: 100% pass
- All 16 `.avsc` files parse as valid Avro schemas
- `grep -r "watchlist.item_removed" services/ infra/kafka/schemas/` returns no results
- `grep -r "kg_db" services/knowledge-graph/` returns no results

## Incremental quality gates (mandatory)

Run these gates **immediately after each task** — do not batch. Fix all failures before moving to the next task.

**After T-F-001**:
```bash
grep -r "watchlist.item_removed" services/portfolio/ infra/
# MUST return zero results — if any, fix before continuing
cd services/portfolio && python -m pytest tests/ -x -q && ruff check src/ && mypy src/
```

**After T-F-002**:
```bash
python -c "import json,pathlib,fastavro.schema; [fastavro.schema.parse_schema(json.load(open(f))) for f in pathlib.Path('infra/kafka/schemas').glob('*.avsc')]"; echo "All schemas valid"
ruff check infra/kafka/init/register-schemas.py
```

**After T-F-003**:
```bash
grep -r "kg_db" services/knowledge-graph/
# MUST return zero results
cd services/knowledge-graph && python -m pytest tests/ -x -q && ruff check src/ && mypy src/
```

**No Deferred Fixes**: Do not carry ruff/mypy/test failures from T-F-001 into T-F-002. Fix immediately before continuing.

## Documentation requirements

All documentation must meet the **Documentation quality standard** (8 criteria from `docs/ai-interactions/agent-prompts/0000-exec-wave-generation-template.md`).

**Files to update in this wave**:
- `docs/MASTER_PLAN.md §6.2` — update Kafka topic table:
  - Change `watchlist.item_removed` → `watchlist.item_deleted` in any mention
  - Add 5 new topics (graph.state.changed.v1, intelligence.contradiction.v1, relation.type.proposed.v1, entity.dirtied.v1, alert.delivered.v1) to the topic table
- `infra/kafka/schemas/README.md` (if exists) — list new schemas with their producers/consumers

**N/A criteria for this wave**:
- Diagrams: N/A — no new control flow or data flow introduced (schema file changes only)
- Realistic code examples: N/A — no new public API surface
- Abstract methods documented: N/A — no abstract classes
- Lib docs updated: N/A — `libs/contracts` not modified in this wave; explicit `docs/libs/contracts.md` update deferred to T-F-013 (Wave 05)
- Service docs: N/A — no service behavior change (stub fixes only for knowledge-graph)

## Required handoff evidence

The executing agent must provide:

1. **Changed files list** (exact paths)
2. **Validation ledger**:
   | Command | Scope | Exit code | Result |
   |---------|-------|-----------|--------|
   | `grep -r "watchlist.item_removed" services/ infra/kafka/schemas/` | All | 1 (no matches) | ✓ |
   | `cd services/portfolio && python -m pytest tests/ -x -q` | S1 Portfolio | 0 | ✓ |
   | `ruff check services/portfolio/src/` | S1 | 0 | ✓ |
   | `mypy services/portfolio/src/` | S1 | 0 | ✓ |
   | `fastavro schema validation` (all 16 schemas) | infra/kafka/schemas | 0 | ✓ |
   | `grep -r "kg_db" services/knowledge-graph/` | S7 | 1 (no matches) | ✓ |
   | `cd services/knowledge-graph && python -m pytest tests/ -x -q` | S7 | 0 | ✓ |
   | `./scripts/gen-contracts.sh` | All | 0 | ✓ |

3. **Documentation quality checklist**:
   | Criterion | Status | Notes |
   |-----------|--------|-------|
   | Accuracy verified | ✓ | Schema fields match PRD §7.1 exactly |
   | Diagrams for non-trivial flows | N/A | No new flows introduced |
   | Realistic code examples | N/A | No new public API |
   | Abstract methods documented | N/A | No abstract classes |
   | Common pitfalls section | N/A | No new lib or service |
   | Lib docs updated | N/A | No lib surface change |
   | Service docs reflect final state | ✓ | MASTER_PLAN §6.2 updated |
   | No orphan documentation | ✓ | |

4. **Commit message proposal**:
   ```
   fix: §1.4 blocking pre-implementation repository corrections

   Rename watchlist.item_removed → watchlist.item_deleted per PRD §1.5 rule 5;
   create 6 missing Avro schema files required by schema-init boot step; fix
   knowledge-graph DATABASE_URL default from kg_db to intelligence_db.
   ```

## Definition of done

- [ ] `watchlist.item_deleted.avsc` exists; `watchlist.item_removed.avsc` deleted
- [ ] Zero occurrences of `watchlist.item_removed` in `services/portfolio/` and `infra/kafka/schemas/`
- [ ] All 6 new Avro schema files present and valid (fastavro parses without error)
- [ ] `register-schemas.py` sets FULL compatibility for `relation.type.proposed.v1-value`
- [ ] `knowledge-graph/config.py` references `intelligence_db` in database_url default
- [ ] Zero occurrences of `kg_db` in `services/knowledge-graph/`
- [ ] `alembic_enabled: bool = False` field present in `knowledge-graph` Settings
- [ ] Portfolio tests pass; knowledge-graph tests pass
- [ ] `ruff check` passes on all modified files
- [ ] `mypy` passes on all modified files
- [ ] `./scripts/gen-contracts.sh` exits 0
- [ ] `docs/MASTER_PLAN.md §6.2` updated with corrected event type and 5 new topics
- [ ] Documentation quality checklist completed (all 8 criteria ✓ or explicitly N/A)
- [ ] Incremental quality gates passed for each task (no deferred failures)
- [ ] Commit message proposal provided
