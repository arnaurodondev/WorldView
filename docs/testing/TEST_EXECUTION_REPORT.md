# Test Execution Report

Generated at: 2026-03-25T11:41:11Z
Run ID: 20260325T113403Z
Run artifacts: docs/testing/test-runs/20260325T113403Z
Run duration (sec): 428

## Environment
- git branch: feat/unstructured-data-ingestion-pipeline
- git sha: 853f9d31798591acc6a47f2b8fb89e8d0d05f538
- python: Python 3.11.14
- docker: Docker version 29.1.3, build f52814d
- docker compose: Docker Compose version v5.0.0-desktop.1
- retain logs: on-failure
- integration mode: sequential

## Summary
- Test suites passed: 19
- Test suites failed: 2
- Test suites skipped: 27
- Total collected tests: 1054
- Total failed tests: 20

## Infra Status
- Status: passed
- compose ps: docs/testing/test-runs/20260325T113403Z/infra/compose.ps.txt
- compose config: docs/testing/test-runs/20260325T113403Z/infra/compose.config.yaml
- compose all logs: docs/testing/test-runs/20260325T113403Z/infra/compose.all.log
- service logs dir: docs/testing/test-runs/20260325T113403Z/infra/services
- inspect dir: docs/testing/test-runs/20260325T113403Z/infra/inspect

## Suite Results
- architecture: passed (layer=architecture, type=pytest, collected=29, duration=1s)
- libs: passed (layer=libs, type=script, collected=0, duration=28s) - summarized by scripts/test-libs.sh
- alert:unit: skipped (layer=unit, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no unit tests
- api-gateway:unit: failed (layer=unit, type=pytest, collected=0, duration=0s, failure_type=script_failure) - pytest exited with code 4
- content-ingestion:unit: passed (layer=unit, type=pytest, collected=24, duration=1s)
- content-store:unit: passed (layer=unit, type=pytest, collected=2, duration=1s)
- intelligence-migrations:unit: skipped (layer=unit, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no tests dir
- knowledge-graph:unit: passed (layer=unit, type=pytest, collected=2, duration=0s)
- market-data:unit: passed (layer=unit, type=pytest, collected=248, duration=6s)
- market-ingestion:unit: passed (layer=unit, type=pytest, collected=311, duration=1s)
- nlp-pipeline:unit: passed (layer=unit, type=pytest, collected=2, duration=0s)
- portfolio:unit: passed (layer=unit, type=pytest, collected=248, duration=1s)
- rag-chat:unit: passed (layer=unit, type=pytest, collected=2, duration=0s)
- alert:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- api-gateway:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- content-ingestion:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- content-store:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- intelligence-migrations:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract dir
- knowledge-graph:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- market-data:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- market-ingestion:contract: passed (layer=contract, type=pytest, collected=3, duration=1s)
- nlp-pipeline:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- portfolio:contract: passed (layer=contract, type=pytest, collected=14, duration=1s)
- rag-chat:contract: skipped (layer=contract, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no contract tests
- compose:up: passed (layer=infra, type=compose_startup, collected=0, duration=102s)
- compose:readiness: passed (layer=infra, type=readiness, collected=0, duration=2s)
- alert:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- alert:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- api-gateway:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- api-gateway:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- content-ingestion:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- content-ingestion:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- content-store:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- content-store:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- intelligence-migrations:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- intelligence-migrations:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- knowledge-graph:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- knowledge-graph:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- market-data:integration: passed (layer=integration, type=pytest, collected=66, duration=22s)
- market-data:e2e: failed (layer=e2e, type=pytest, collected=24, duration=7s, failure_type=assertion) - pytest exited with code 1
- market-ingestion:integration: passed (layer=integration, type=pytest, collected=10, duration=1s)
- market-ingestion:e2e: passed (layer=e2e, type=pytest, collected=16, duration=27s)
- nlp-pipeline:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- nlp-pipeline:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests
- portfolio:integration: passed (layer=integration, type=pytest, collected=43, duration=6s)
- portfolio:e2e: passed (layer=e2e, type=pytest, collected=10, duration=1s)
- rag-chat:integration: skipped (layer=integration, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no integration tests
- rag-chat:e2e: skipped (layer=e2e, type=pytest, collected=0, duration=0s, failure_type=no_tests) - no e2e tests

## Failed Tests (Reason + Traceback Excerpt)
### 1. <suite-level failure>
- suite: api-gateway:unit
- kind: script_failure
- reason: pytest exited with code 4
- log: docs/testing/test-runs/20260325T113403Z/suites/api-gateway_unit.log

### 2. tests.e2e.test_api_e2e::test_instruments_list_contains_seeded
- suite: market-data:e2e
- kind: error
- reason: failed on setup with "sqlalchemy.exc.IntegrityError: (sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value violates unique constraint "securities_figi_key"
DETAIL:  Key (figi)=(BBG000B9XRY4) already exists.
[SQL: INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12), $10::VARCHAR(12), $11::VARCHAR(255), $12::VARCHAR(100), $13::VARCHAR(100), $14::VARCHAR(3), $15::VARCHAR(3)) ON CONFLICT (id) DO UPDATE SET figi = $1::VARCHAR(12), isin = $2::VARCHAR(12), name = $3::VARCHAR(255), sector = $4::VARCHAR(100), industry = $5::VARCHAR(100), country = $6::VARCHAR(3), currency = $7::VARCHAR(3) RETURNING securities.id, securities.figi, securities.isin, securities.name, securities.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at]
[parameters: ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None, '019d24ca-a3ea-7d73-bbea-a82aa1acd59f', 'BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None)]
(Background on this error at: https://sqlalche.me/e/20/gkpj)"
- log: docs/testing/test-runs/20260325T113403Z/suites/market-data_e2e.log
```text
self = <sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_cursor object at 0x11059f760>
operation = 'INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12),...ies.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at'
parameters = ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, ...)
    async def _prepare_and_execute(self, operation, parameters):
        adapt_connection = self._adapt_connection
        async with adapt_connection._execute_mutex:
            if not adapt_connection._started:
                await adapt_connection._start_transaction()
            if parameters is None:
                parameters = ()
            try:
                prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof
                )
                if attributes:
                    self.description = [
                        (
                            attr.name,
                            attr.type.oid,
                            None,
                            None,
                            None,
                            None,
                            None,
                        )
```

### 3. tests.e2e.test_api_e2e::test_instrument_lookup_by_symbol
- suite: market-data:e2e
- kind: error
- reason: failed on setup with "sqlalchemy.exc.IntegrityError: (sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value violates unique constraint "securities_figi_key"
DETAIL:  Key (figi)=(BBG000B9XRY4) already exists.
[SQL: INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12), $10::VARCHAR(12), $11::VARCHAR(255), $12::VARCHAR(100), $13::VARCHAR(100), $14::VARCHAR(3), $15::VARCHAR(3)) ON CONFLICT (id) DO UPDATE SET figi = $1::VARCHAR(12), isin = $2::VARCHAR(12), name = $3::VARCHAR(255), sector = $4::VARCHAR(100), industry = $5::VARCHAR(100), country = $6::VARCHAR(3), currency = $7::VARCHAR(3) RETURNING securities.id, securities.figi, securities.isin, securities.name, securities.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at]
[parameters: ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None, '019d24ca-a559-78ee-b465-06bf26811160', 'BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None)]
(Background on this error at: https://sqlalche.me/e/20/gkpj)"
- log: docs/testing/test-runs/20260325T113403Z/suites/market-data_e2e.log
```text
self = <sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_cursor object at 0x110735f00>
operation = 'INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12),...ies.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at'
parameters = ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, ...)
    async def _prepare_and_execute(self, operation, parameters):
        adapt_connection = self._adapt_connection
        async with adapt_connection._execute_mutex:
            if not adapt_connection._started:
                await adapt_connection._start_transaction()
            if parameters is None:
                parameters = ()
            try:
                prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof
                )
                if attributes:
                    self.description = [
                        (
                            attr.name,
                            attr.type.oid,
                            None,
                            None,
                            None,
                            None,
                            None,
                        )
```

### 4. tests.e2e.test_api_e2e::test_instrument_lookup_by_id
- suite: market-data:e2e
- kind: error
- reason: failed on setup with "sqlalchemy.exc.IntegrityError: (sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value violates unique constraint "securities_figi_key"
DETAIL:  Key (figi)=(BBG000B9XRY4) already exists.
[SQL: INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12), $10::VARCHAR(12), $11::VARCHAR(255), $12::VARCHAR(100), $13::VARCHAR(100), $14::VARCHAR(3), $15::VARCHAR(3)) ON CONFLICT (id) DO UPDATE SET figi = $1::VARCHAR(12), isin = $2::VARCHAR(12), name = $3::VARCHAR(255), sector = $4::VARCHAR(100), industry = $5::VARCHAR(100), country = $6::VARCHAR(3), currency = $7::VARCHAR(3) RETURNING securities.id, securities.figi, securities.isin, securities.name, securities.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at]
[parameters: ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None, '019d24ca-a693-7e7f-9982-682deb56cf5e', 'BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None)]
(Background on this error at: https://sqlalche.me/e/20/gkpj)"
- log: docs/testing/test-runs/20260325T113403Z/suites/market-data_e2e.log
```text
self = <sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_cursor object at 0x1112e2440>
operation = 'INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12),...ies.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at'
parameters = ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, ...)
    async def _prepare_and_execute(self, operation, parameters):
        adapt_connection = self._adapt_connection
        async with adapt_connection._execute_mutex:
            if not adapt_connection._started:
                await adapt_connection._start_transaction()
            if parameters is None:
                parameters = ()
            try:
                prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof
                )
                if attributes:
                    self.description = [
                        (
                            attr.name,
                            attr.type.oid,
                            None,
                            None,
                            None,
                            None,
                            None,
                        )
```

### 5. tests.e2e.test_api_e2e::test_ohlcv_returns_seeded_bars
- suite: market-data:e2e
- kind: error
- reason: failed on setup with "sqlalchemy.exc.IntegrityError: (sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value violates unique constraint "securities_figi_key"
DETAIL:  Key (figi)=(BBG000B9XRY4) already exists.
[SQL: INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12), $10::VARCHAR(12), $11::VARCHAR(255), $12::VARCHAR(100), $13::VARCHAR(100), $14::VARCHAR(3), $15::VARCHAR(3)) ON CONFLICT (id) DO UPDATE SET figi = $1::VARCHAR(12), isin = $2::VARCHAR(12), name = $3::VARCHAR(255), sector = $4::VARCHAR(100), industry = $5::VARCHAR(100), country = $6::VARCHAR(3), currency = $7::VARCHAR(3) RETURNING securities.id, securities.figi, securities.isin, securities.name, securities.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at]
[parameters: ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None, '019d24ca-a80d-74f1-8159-440fdc796be2', 'BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None)]
(Background on this error at: https://sqlalche.me/e/20/gkpj)"
- log: docs/testing/test-runs/20260325T113403Z/suites/market-data_e2e.log
```text
self = <sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_cursor object at 0x110686020>
operation = 'INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12),...ies.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at'
parameters = ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, ...)
    async def _prepare_and_execute(self, operation, parameters):
        adapt_connection = self._adapt_connection
        async with adapt_connection._execute_mutex:
            if not adapt_connection._started:
                await adapt_connection._start_transaction()
            if parameters is None:
                parameters = ()
            try:
                prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof
                )
                if attributes:
                    self.description = [
                        (
                            attr.name,
                            attr.type.oid,
                            None,
                            None,
                            None,
                            None,
                            None,
                        )
```

### 6. tests.e2e.test_api_e2e::test_ohlcv_reversed_range_returns_422
- suite: market-data:e2e
- kind: error
- reason: failed on setup with "sqlalchemy.exc.IntegrityError: (sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value violates unique constraint "securities_figi_key"
DETAIL:  Key (figi)=(BBG000B9XRY4) already exists.
[SQL: INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12), $10::VARCHAR(12), $11::VARCHAR(255), $12::VARCHAR(100), $13::VARCHAR(100), $14::VARCHAR(3), $15::VARCHAR(3)) ON CONFLICT (id) DO UPDATE SET figi = $1::VARCHAR(12), isin = $2::VARCHAR(12), name = $3::VARCHAR(255), sector = $4::VARCHAR(100), industry = $5::VARCHAR(100), country = $6::VARCHAR(3), currency = $7::VARCHAR(3) RETURNING securities.id, securities.figi, securities.isin, securities.name, securities.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at]
[parameters: ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None, '019d24ca-a957-7350-bc39-f0611d076441', 'BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None)]
(Background on this error at: https://sqlalche.me/e/20/gkpj)"
- log: docs/testing/test-runs/20260325T113403Z/suites/market-data_e2e.log
```text
self = <sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_cursor object at 0x1109e1120>
operation = 'INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12),...ies.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at'
parameters = ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, ...)
    async def _prepare_and_execute(self, operation, parameters):
        adapt_connection = self._adapt_connection
        async with adapt_connection._execute_mutex:
            if not adapt_connection._started:
                await adapt_connection._start_transaction()
            if parameters is None:
                parameters = ()
            try:
                prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof
                )
                if attributes:
                    self.description = [
                        (
                            attr.name,
                            attr.type.oid,
                            None,
                            None,
                            None,
                            None,
                            None,
                        )
```

### 7. tests.e2e.test_api_e2e::test_ohlcv_empty_range_returns_empty_list
- suite: market-data:e2e
- kind: error
- reason: failed on setup with "sqlalchemy.exc.IntegrityError: (sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value violates unique constraint "securities_figi_key"
DETAIL:  Key (figi)=(BBG000B9XRY4) already exists.
[SQL: INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12), $10::VARCHAR(12), $11::VARCHAR(255), $12::VARCHAR(100), $13::VARCHAR(100), $14::VARCHAR(3), $15::VARCHAR(3)) ON CONFLICT (id) DO UPDATE SET figi = $1::VARCHAR(12), isin = $2::VARCHAR(12), name = $3::VARCHAR(255), sector = $4::VARCHAR(100), industry = $5::VARCHAR(100), country = $6::VARCHAR(3), currency = $7::VARCHAR(3) RETURNING securities.id, securities.figi, securities.isin, securities.name, securities.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at]
[parameters: ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None, '019d24ca-aa81-7234-9a70-f3225cb47d4b', 'BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None)]
(Background on this error at: https://sqlalche.me/e/20/gkpj)"
- log: docs/testing/test-runs/20260325T113403Z/suites/market-data_e2e.log
```text
self = <sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_cursor object at 0x1112de2c0>
operation = 'INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12),...ies.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at'
parameters = ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, ...)
    async def _prepare_and_execute(self, operation, parameters):
        adapt_connection = self._adapt_connection
        async with adapt_connection._execute_mutex:
            if not adapt_connection._started:
                await adapt_connection._start_transaction()
            if parameters is None:
                parameters = ()
            try:
                prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof
                )
                if attributes:
                    self.description = [
                        (
                            attr.name,
                            attr.type.oid,
                            None,
                            None,
                            None,
                            None,
                            None,
                        )
```

### 8. tests.e2e.test_api_e2e::test_ohlcv_available_timeframes
- suite: market-data:e2e
- kind: error
- reason: failed on setup with "sqlalchemy.exc.IntegrityError: (sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value violates unique constraint "securities_figi_key"
DETAIL:  Key (figi)=(BBG000B9XRY4) already exists.
[SQL: INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12), $10::VARCHAR(12), $11::VARCHAR(255), $12::VARCHAR(100), $13::VARCHAR(100), $14::VARCHAR(3), $15::VARCHAR(3)) ON CONFLICT (id) DO UPDATE SET figi = $1::VARCHAR(12), isin = $2::VARCHAR(12), name = $3::VARCHAR(255), sector = $4::VARCHAR(100), industry = $5::VARCHAR(100), country = $6::VARCHAR(3), currency = $7::VARCHAR(3) RETURNING securities.id, securities.figi, securities.isin, securities.name, securities.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at]
[parameters: ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None, '019d24ca-abf3-7072-a24f-47a853118ee0', 'BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None)]
(Background on this error at: https://sqlalche.me/e/20/gkpj)"
- log: docs/testing/test-runs/20260325T113403Z/suites/market-data_e2e.log
```text
self = <sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_cursor object at 0x110946680>
operation = 'INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12),...ies.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at'
parameters = ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, ...)
    async def _prepare_and_execute(self, operation, parameters):
        adapt_connection = self._adapt_connection
        async with adapt_connection._execute_mutex:
            if not adapt_connection._started:
                await adapt_connection._start_transaction()
            if parameters is None:
                parameters = ()
            try:
                prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof
                )
                if attributes:
                    self.description = [
                        (
                            attr.name,
                            attr.type.oid,
                            None,
                            None,
                            None,
                            None,
                            None,
                        )
```

### 9. tests.e2e.test_api_e2e::test_ohlcv_date_range_endpoint
- suite: market-data:e2e
- kind: error
- reason: failed on setup with "sqlalchemy.exc.IntegrityError: (sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value violates unique constraint "securities_figi_key"
DETAIL:  Key (figi)=(BBG000B9XRY4) already exists.
[SQL: INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12), $10::VARCHAR(12), $11::VARCHAR(255), $12::VARCHAR(100), $13::VARCHAR(100), $14::VARCHAR(3), $15::VARCHAR(3)) ON CONFLICT (id) DO UPDATE SET figi = $1::VARCHAR(12), isin = $2::VARCHAR(12), name = $3::VARCHAR(255), sector = $4::VARCHAR(100), industry = $5::VARCHAR(100), country = $6::VARCHAR(3), currency = $7::VARCHAR(3) RETURNING securities.id, securities.figi, securities.isin, securities.name, securities.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at]
[parameters: ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None, '019d24ca-ad2e-7f8f-8557-07c099ed4427', 'BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None)]
(Background on this error at: https://sqlalche.me/e/20/gkpj)"
- log: docs/testing/test-runs/20260325T113403Z/suites/market-data_e2e.log
```text
self = <sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_cursor object at 0x110c4a080>
operation = 'INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12),...ies.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at'
parameters = ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, ...)
    async def _prepare_and_execute(self, operation, parameters):
        adapt_connection = self._adapt_connection
        async with adapt_connection._execute_mutex:
            if not adapt_connection._started:
                await adapt_connection._start_transaction()
            if parameters is None:
                parameters = ()
            try:
                prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof
                )
                if attributes:
                    self.description = [
                        (
                            attr.name,
                            attr.type.oid,
                            None,
                            None,
                            None,
                            None,
                            None,
                        )
```

### 10. tests.e2e.test_api_e2e::test_ohlcv_bulk_multiple_instruments
- suite: market-data:e2e
- kind: error
- reason: failed on setup with "sqlalchemy.exc.IntegrityError: (sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value violates unique constraint "securities_figi_key"
DETAIL:  Key (figi)=(BBG000B9XRY4) already exists.
[SQL: INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12), $10::VARCHAR(12), $11::VARCHAR(255), $12::VARCHAR(100), $13::VARCHAR(100), $14::VARCHAR(3), $15::VARCHAR(3)) ON CONFLICT (id) DO UPDATE SET figi = $1::VARCHAR(12), isin = $2::VARCHAR(12), name = $3::VARCHAR(255), sector = $4::VARCHAR(100), industry = $5::VARCHAR(100), country = $6::VARCHAR(3), currency = $7::VARCHAR(3) RETURNING securities.id, securities.figi, securities.isin, securities.name, securities.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at]
[parameters: ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None, '019d24ca-ae85-7003-8aaa-4e89bb2a2a18', 'BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None)]
(Background on this error at: https://sqlalche.me/e/20/gkpj)"
- log: docs/testing/test-runs/20260325T113403Z/suites/market-data_e2e.log
```text
self = <sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_cursor object at 0x11121eec0>
operation = 'INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12),...ies.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at'
parameters = ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, ...)
    async def _prepare_and_execute(self, operation, parameters):
        adapt_connection = self._adapt_connection
        async with adapt_connection._execute_mutex:
            if not adapt_connection._started:
                await adapt_connection._start_transaction()
            if parameters is None:
                parameters = ()
            try:
                prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof
                )
                if attributes:
                    self.description = [
                        (
                            attr.name,
                            attr.type.oid,
                            None,
                            None,
                            None,
                            None,
                            None,
                        )
```

### 11. tests.e2e.test_api_e2e::test_quote_cache_aside_first_call_hits_db
- suite: market-data:e2e
- kind: error
- reason: failed on setup with "sqlalchemy.exc.IntegrityError: (sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value violates unique constraint "securities_figi_key"
DETAIL:  Key (figi)=(BBG000B9XRY4) already exists.
[SQL: INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12), $10::VARCHAR(12), $11::VARCHAR(255), $12::VARCHAR(100), $13::VARCHAR(100), $14::VARCHAR(3), $15::VARCHAR(3)) ON CONFLICT (id) DO UPDATE SET figi = $1::VARCHAR(12), isin = $2::VARCHAR(12), name = $3::VARCHAR(255), sector = $4::VARCHAR(100), industry = $5::VARCHAR(100), country = $6::VARCHAR(3), currency = $7::VARCHAR(3) RETURNING securities.id, securities.figi, securities.isin, securities.name, securities.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at]
[parameters: ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None, '019d24ca-aff5-7316-b90e-7ea5291b298f', 'BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None)]
(Background on this error at: https://sqlalche.me/e/20/gkpj)"
- log: docs/testing/test-runs/20260325T113403Z/suites/market-data_e2e.log
```text
self = <sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_cursor object at 0x110c82860>
operation = 'INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12),...ies.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at'
parameters = ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, ...)
    async def _prepare_and_execute(self, operation, parameters):
        adapt_connection = self._adapt_connection
        async with adapt_connection._execute_mutex:
            if not adapt_connection._started:
                await adapt_connection._start_transaction()
            if parameters is None:
                parameters = ()
            try:
                prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof
                )
                if attributes:
                    self.description = [
                        (
                            attr.name,
                            attr.type.oid,
                            None,
                            None,
                            None,
                            None,
                            None,
                        )
```

### 12. tests.e2e.test_api_e2e::test_quote_second_call_served_from_cache
- suite: market-data:e2e
- kind: error
- reason: failed on setup with "sqlalchemy.exc.IntegrityError: (sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value violates unique constraint "securities_figi_key"
DETAIL:  Key (figi)=(BBG000B9XRY4) already exists.
[SQL: INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12), $10::VARCHAR(12), $11::VARCHAR(255), $12::VARCHAR(100), $13::VARCHAR(100), $14::VARCHAR(3), $15::VARCHAR(3)) ON CONFLICT (id) DO UPDATE SET figi = $1::VARCHAR(12), isin = $2::VARCHAR(12), name = $3::VARCHAR(255), sector = $4::VARCHAR(100), industry = $5::VARCHAR(100), country = $6::VARCHAR(3), currency = $7::VARCHAR(3) RETURNING securities.id, securities.figi, securities.isin, securities.name, securities.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at]
[parameters: ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None, '019d24ca-b13f-78e0-9f35-8e5a1bf4312d', 'BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None)]
(Background on this error at: https://sqlalche.me/e/20/gkpj)"
- log: docs/testing/test-runs/20260325T113403Z/suites/market-data_e2e.log
```text
self = <sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_cursor object at 0x110e076a0>
operation = 'INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12),...ies.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at'
parameters = ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, ...)
    async def _prepare_and_execute(self, operation, parameters):
        adapt_connection = self._adapt_connection
        async with adapt_connection._execute_mutex:
            if not adapt_connection._started:
                await adapt_connection._start_transaction()
            if parameters is None:
                parameters = ()
            try:
                prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof
                )
                if attributes:
                    self.description = [
                        (
                            attr.name,
                            attr.type.oid,
                            None,
                            None,
                            None,
                            None,
                            None,
                        )
```

### 13. tests.e2e.test_api_e2e::test_batch_quotes_post
- suite: market-data:e2e
- kind: error
- reason: failed on setup with "sqlalchemy.exc.IntegrityError: (sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value violates unique constraint "securities_figi_key"
DETAIL:  Key (figi)=(BBG000B9XRY4) already exists.
[SQL: INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12), $10::VARCHAR(12), $11::VARCHAR(255), $12::VARCHAR(100), $13::VARCHAR(100), $14::VARCHAR(3), $15::VARCHAR(3)) ON CONFLICT (id) DO UPDATE SET figi = $1::VARCHAR(12), isin = $2::VARCHAR(12), name = $3::VARCHAR(255), sector = $4::VARCHAR(100), industry = $5::VARCHAR(100), country = $6::VARCHAR(3), currency = $7::VARCHAR(3) RETURNING securities.id, securities.figi, securities.isin, securities.name, securities.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at]
[parameters: ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None, '019d24ca-b2e9-7a74-918f-c459896155f2', 'BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None)]
(Background on this error at: https://sqlalche.me/e/20/gkpj)"
- log: docs/testing/test-runs/20260325T113403Z/suites/market-data_e2e.log
```text
self = <sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_cursor object at 0x1109108e0>
operation = 'INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12),...ies.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at'
parameters = ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, ...)
    async def _prepare_and_execute(self, operation, parameters):
        adapt_connection = self._adapt_connection
        async with adapt_connection._execute_mutex:
            if not adapt_connection._started:
                await adapt_connection._start_transaction()
            if parameters is None:
                parameters = ()
            try:
                prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof
                )
                if attributes:
                    self.description = [
                        (
                            attr.name,
                            attr.type.oid,
                            None,
                            None,
                            None,
                            None,
                            None,
                        )
```

### 14. tests.e2e.test_api_e2e::test_batch_quotes_get_latest
- suite: market-data:e2e
- kind: error
- reason: failed on setup with "sqlalchemy.exc.IntegrityError: (sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value violates unique constraint "securities_figi_key"
DETAIL:  Key (figi)=(BBG000B9XRY4) already exists.
[SQL: INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12), $10::VARCHAR(12), $11::VARCHAR(255), $12::VARCHAR(100), $13::VARCHAR(100), $14::VARCHAR(3), $15::VARCHAR(3)) ON CONFLICT (id) DO UPDATE SET figi = $1::VARCHAR(12), isin = $2::VARCHAR(12), name = $3::VARCHAR(255), sector = $4::VARCHAR(100), industry = $5::VARCHAR(100), country = $6::VARCHAR(3), currency = $7::VARCHAR(3) RETURNING securities.id, securities.figi, securities.isin, securities.name, securities.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at]
[parameters: ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None, '019d24ca-b41b-7927-80c9-d975eab51b90', 'BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None)]
(Background on this error at: https://sqlalche.me/e/20/gkpj)"
- log: docs/testing/test-runs/20260325T113403Z/suites/market-data_e2e.log
```text
self = <sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_cursor object at 0x110c37340>
operation = 'INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12),...ies.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at'
parameters = ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, ...)
    async def _prepare_and_execute(self, operation, parameters):
        adapt_connection = self._adapt_connection
        async with adapt_connection._execute_mutex:
            if not adapt_connection._started:
                await adapt_connection._start_transaction()
            if parameters is None:
                parameters = ()
            try:
                prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof
                )
                if attributes:
                    self.description = [
                        (
                            attr.name,
                            attr.type.oid,
                            None,
                            None,
                            None,
                            None,
                            None,
                        )
```

### 15. tests.e2e.test_api_e2e::test_securities_list_contains_seeded
- suite: market-data:e2e
- kind: error
- reason: failed on setup with "sqlalchemy.exc.IntegrityError: (sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value violates unique constraint "securities_figi_key"
DETAIL:  Key (figi)=(BBG000B9XRY4) already exists.
[SQL: INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12), $10::VARCHAR(12), $11::VARCHAR(255), $12::VARCHAR(100), $13::VARCHAR(100), $14::VARCHAR(3), $15::VARCHAR(3)) ON CONFLICT (id) DO UPDATE SET figi = $1::VARCHAR(12), isin = $2::VARCHAR(12), name = $3::VARCHAR(255), sector = $4::VARCHAR(100), industry = $5::VARCHAR(100), country = $6::VARCHAR(3), currency = $7::VARCHAR(3) RETURNING securities.id, securities.figi, securities.isin, securities.name, securities.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at]
[parameters: ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None, '019d24ca-b56a-721f-834c-bc3fc75a0279', 'BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None)]
(Background on this error at: https://sqlalche.me/e/20/gkpj)"
- log: docs/testing/test-runs/20260325T113403Z/suites/market-data_e2e.log
```text
self = <sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_cursor object at 0x110c72f80>
operation = 'INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12),...ies.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at'
parameters = ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, ...)
    async def _prepare_and_execute(self, operation, parameters):
        adapt_connection = self._adapt_connection
        async with adapt_connection._execute_mutex:
            if not adapt_connection._started:
                await adapt_connection._start_transaction()
            if parameters is None:
                parameters = ()
            try:
                prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof
                )
                if attributes:
                    self.description = [
                        (
                            attr.name,
                            attr.type.oid,
                            None,
                            None,
                            None,
                            None,
                            None,
                        )
```

### 16. tests.e2e.test_api_e2e::test_security_detail_by_id
- suite: market-data:e2e
- kind: error
- reason: failed on setup with "sqlalchemy.exc.IntegrityError: (sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value violates unique constraint "securities_figi_key"
DETAIL:  Key (figi)=(BBG000B9XRY4) already exists.
[SQL: INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12), $10::VARCHAR(12), $11::VARCHAR(255), $12::VARCHAR(100), $13::VARCHAR(100), $14::VARCHAR(3), $15::VARCHAR(3)) ON CONFLICT (id) DO UPDATE SET figi = $1::VARCHAR(12), isin = $2::VARCHAR(12), name = $3::VARCHAR(255), sector = $4::VARCHAR(100), industry = $5::VARCHAR(100), country = $6::VARCHAR(3), currency = $7::VARCHAR(3) RETURNING securities.id, securities.figi, securities.isin, securities.name, securities.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at]
[parameters: ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None, '019d24ca-b6b4-74d9-b6dd-cacc9ec6b97d', 'BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None)]
(Background on this error at: https://sqlalche.me/e/20/gkpj)"
- log: docs/testing/test-runs/20260325T113403Z/suites/market-data_e2e.log
```text
self = <sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_cursor object at 0x110d95ea0>
operation = 'INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12),...ies.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at'
parameters = ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, ...)
    async def _prepare_and_execute(self, operation, parameters):
        adapt_connection = self._adapt_connection
        async with adapt_connection._execute_mutex:
            if not adapt_connection._started:
                await adapt_connection._start_transaction()
            if parameters is None:
                parameters = ()
            try:
                prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof
                )
                if attributes:
                    self.description = [
                        (
                            attr.name,
                            attr.type.oid,
                            None,
                            None,
                            None,
                            None,
                            None,
                        )
```

### 17. tests.e2e.test_pipeline_e2e::test_ohlcv_priority_resolution_visible_via_api
- suite: market-data:e2e
- kind: error
- reason: failed on setup with "sqlalchemy.exc.IntegrityError: (sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value violates unique constraint "securities_figi_key"
DETAIL:  Key (figi)=(BBG000B9XRY4) already exists.
[SQL: INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12), $10::VARCHAR(12), $11::VARCHAR(255), $12::VARCHAR(100), $13::VARCHAR(100), $14::VARCHAR(3), $15::VARCHAR(3)) ON CONFLICT (id) DO UPDATE SET figi = $1::VARCHAR(12), isin = $2::VARCHAR(12), name = $3::VARCHAR(255), sector = $4::VARCHAR(100), industry = $5::VARCHAR(100), country = $6::VARCHAR(3), currency = $7::VARCHAR(3) RETURNING securities.id, securities.figi, securities.isin, securities.name, securities.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at]
[parameters: ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None, '019d24ca-b7fc-7a60-ade3-a076a1a34629', 'BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None)]
(Background on this error at: https://sqlalche.me/e/20/gkpj)"
- log: docs/testing/test-runs/20260325T113403Z/suites/market-data_e2e.log
```text
self = <sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_cursor object at 0x110d69cc0>
operation = 'INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12),...ies.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at'
parameters = ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, ...)
    async def _prepare_and_execute(self, operation, parameters):
        adapt_connection = self._adapt_connection
        async with adapt_connection._execute_mutex:
            if not adapt_connection._started:
                await adapt_connection._start_transaction()
            if parameters is None:
                parameters = ()
            try:
                prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof
                )
                if attributes:
                    self.description = [
                        (
                            attr.name,
                            attr.type.oid,
                            None,
                            None,
                            None,
                            None,
                            None,
                        )
```

### 18. tests.e2e.test_pipeline_e2e::test_quote_update_reflected_via_api
- suite: market-data:e2e
- kind: error
- reason: failed on setup with "sqlalchemy.exc.IntegrityError: (sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value violates unique constraint "securities_figi_key"
DETAIL:  Key (figi)=(BBG000B9XRY4) already exists.
[SQL: INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12), $10::VARCHAR(12), $11::VARCHAR(255), $12::VARCHAR(100), $13::VARCHAR(100), $14::VARCHAR(3), $15::VARCHAR(3)) ON CONFLICT (id) DO UPDATE SET figi = $1::VARCHAR(12), isin = $2::VARCHAR(12), name = $3::VARCHAR(255), sector = $4::VARCHAR(100), industry = $5::VARCHAR(100), country = $6::VARCHAR(3), currency = $7::VARCHAR(3) RETURNING securities.id, securities.figi, securities.isin, securities.name, securities.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at]
[parameters: ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None, '019d24ca-b947-7e82-9a07-19b94f18cc1e', 'BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None)]
(Background on this error at: https://sqlalche.me/e/20/gkpj)"
- log: docs/testing/test-runs/20260325T113403Z/suites/market-data_e2e.log
```text
self = <sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_cursor object at 0x1115e6d40>
operation = 'INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12),...ies.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at'
parameters = ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, ...)
    async def _prepare_and_execute(self, operation, parameters):
        adapt_connection = self._adapt_connection
        async with adapt_connection._execute_mutex:
            if not adapt_connection._started:
                await adapt_connection._start_transaction()
            if parameters is None:
                parameters = ()
            try:
                prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof
                )
                if attributes:
                    self.description = [
                        (
                            attr.name,
                            attr.type.oid,
                            None,
                            None,
                            None,
                            None,
                            None,
                        )
```

### 19. tests.e2e.test_pipeline_e2e::test_instrument_flags_promoted_by_data_ingest
- suite: market-data:e2e
- kind: error
- reason: failed on setup with "sqlalchemy.exc.IntegrityError: (sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value violates unique constraint "securities_figi_key"
DETAIL:  Key (figi)=(BBG000B9XRY4) already exists.
[SQL: INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12), $10::VARCHAR(12), $11::VARCHAR(255), $12::VARCHAR(100), $13::VARCHAR(100), $14::VARCHAR(3), $15::VARCHAR(3)) ON CONFLICT (id) DO UPDATE SET figi = $1::VARCHAR(12), isin = $2::VARCHAR(12), name = $3::VARCHAR(255), sector = $4::VARCHAR(100), industry = $5::VARCHAR(100), country = $6::VARCHAR(3), currency = $7::VARCHAR(3) RETURNING securities.id, securities.figi, securities.isin, securities.name, securities.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at]
[parameters: ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None, '019d24ca-baa3-79e1-8700-9dd484812dad', 'BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None)]
(Background on this error at: https://sqlalche.me/e/20/gkpj)"
- log: docs/testing/test-runs/20260325T113403Z/suites/market-data_e2e.log
```text
self = <sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_cursor object at 0x1115d10c0>
operation = 'INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12),...ies.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at'
parameters = ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, ...)
    async def _prepare_and_execute(self, operation, parameters):
        adapt_connection = self._adapt_connection
        async with adapt_connection._execute_mutex:
            if not adapt_connection._started:
                await adapt_connection._start_transaction()
            if parameters is None:
                parameters = ()
            try:
                prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof
                )
                if attributes:
                    self.description = [
                        (
                            attr.name,
                            attr.type.oid,
                            None,
                            None,
                            None,
                            None,
                            None,
                        )
```

### 20. tests.e2e.test_pipeline_e2e::test_fundamentals_income_statement_accessible
- suite: market-data:e2e
- kind: error
- reason: failed on setup with "sqlalchemy.exc.IntegrityError: (sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value violates unique constraint "securities_figi_key"
DETAIL:  Key (figi)=(BBG000B9XRY4) already exists.
[SQL: INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12), $10::VARCHAR(12), $11::VARCHAR(255), $12::VARCHAR(100), $13::VARCHAR(100), $14::VARCHAR(3), $15::VARCHAR(3)) ON CONFLICT (id) DO UPDATE SET figi = $1::VARCHAR(12), isin = $2::VARCHAR(12), name = $3::VARCHAR(255), sector = $4::VARCHAR(100), industry = $5::VARCHAR(100), country = $6::VARCHAR(3), currency = $7::VARCHAR(3) RETURNING securities.id, securities.figi, securities.isin, securities.name, securities.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at]
[parameters: ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None, '019d24ca-bbe5-7770-a74f-d03f44f72150', 'BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, None)]
(Background on this error at: https://sqlalche.me/e/20/gkpj)"
- log: docs/testing/test-runs/20260325T113403Z/suites/market-data_e2e.log
```text
self = <sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_cursor object at 0x1108dd5a0>
operation = 'INSERT INTO securities (id, figi, isin, name, sector, industry, country, currency) VALUES ($8::UUID, $9::VARCHAR(12),...ies.sector, securities.industry, securities.country, securities.currency, securities.created_at, securities.updated_at'
parameters = ('BBG000B9XRY4', 'US0378331005', 'E2E Apple Inc.', None, None, None, ...)
    async def _prepare_and_execute(self, operation, parameters):
        adapt_connection = self._adapt_connection
        async with adapt_connection._execute_mutex:
            if not adapt_connection._started:
                await adapt_connection._start_transaction()
            if parameters is None:
                parameters = ()
            try:
                prepared_stmt, attributes = await adapt_connection._prepare(
                    operation, self._invalidate_schema_cache_asof
                )
                if attributes:
                    self.description = [
                        (
                            attr.name,
                            attr.type.oid,
                            None,
                            None,
                            None,
                            None,
                            None,
                        )
```
