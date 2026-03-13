"""Infrastructure smoke tests — verify all containers start and respond.

These tests require Docker to be running.  They are marked ``integration``
and ``slow`` so they can be excluded from the fast CI unit-test gate.

Run with:
    cd services/market-data && make test -- tests/integration/ -m integration -v
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]


class TestPostgresContainer:
    async def test_pg_container_starts(self, pg_container) -> None:
        """Connect to the TimescaleDB container and execute SELECT 1."""
        import asyncpg

        url = pg_container.get_connection_url()
        # asyncpg uses postgresql:// not postgresql+asyncpg://
        dsn = url.replace("postgresql+asyncpg://", "postgresql://").replace(
            "postgresql://",
            "postgresql://",
            1,
        )
        conn = await asyncpg.connect(dsn)
        result = await conn.fetchval("SELECT 1")
        await conn.close()
        assert result == 1

    async def test_migrations_run_successfully(self, _migrated_db: str) -> None:
        """Confirm that Alembic migration 002 is the head after upgrade head."""
        import asyncpg

        dsn = _migrated_db.replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(dsn)
        rows = await conn.fetch("SELECT version_num FROM alembic_version")
        await conn.close()

        version_nums = {row["version_num"] for row in rows}
        assert "002" in version_nums, f"Expected migration '002' to be head, got: {version_nums}"


class TestKafkaContainer:
    def test_kafka_container_starts(self, kafka_container) -> None:
        """Produce and consume one message to confirm Kafka is reachable."""
        from confluent_kafka import Consumer, Producer

        bootstrap_servers = kafka_container.get_bootstrap_server()
        topic = "smoke-test-topic"

        # Produce
        producer = Producer({"bootstrap.servers": bootstrap_servers})
        producer.produce(topic, key="k", value=b"smoke-test-value")
        producer.flush(timeout=10)

        # Consume
        consumer = Consumer(
            {
                "bootstrap.servers": bootstrap_servers,
                "group.id": "smoke-test-group",
                "auto.offset.reset": "earliest",
            },
        )
        consumer.subscribe([topic])
        msg = consumer.poll(timeout=10.0)
        consumer.close()

        assert msg is not None
        assert msg.error() is None
        assert msg.value() == b"smoke-test-value"


class TestMinioContainer:
    def test_minio_container_starts(self, minio_container) -> None:
        """Put and get one object to confirm MinIO is reachable."""
        import io

        client = minio_container.get_client()
        bucket = minio_container.test_bucket
        object_name = "smoke/test.txt"
        content = b"hello-minio"

        client.put_object(bucket, object_name, io.BytesIO(content), length=len(content))
        response = client.get_object(bucket, object_name)
        retrieved = response.read()

        assert retrieved == content


class TestValkeyContainer:
    async def test_valkey_container_starts(self, valkey_client) -> None:
        """Set and get one key to confirm Valkey is reachable."""
        await valkey_client.set("smoke:key", "smoke-value", ex=60)
        value = await valkey_client.get("smoke:key")
        assert value == b"smoke-value"
