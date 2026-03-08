"""messaging — Kafka, Avro, Outbox, and Valkey primitives for worldview.

Public API surface
------------------

Consumer:
    BaseKafkaConsumer, ConsumerConfig, FailureInfo, UnitOfWorkProtocol,
    RetryableError, FatalError (and all subclasses)

Producer:
    KafkaProducerConfig, OutboxKafkaValue, KafkaEventValueSerializer,
    OutboxEventValueSerializer, build_serializing_producer

Schema / serializer:
    AvroDictable, AvroSerializerConfig, build_avro_serializer,
    topic_event_type_subject_name_strategy

Schema registry:
    SchemaRegistryConfig, build_schema_registry_client

Serialization utilities:
    load_schema, serialize_avro, deserialize_avro, iso_datetime, decimal_to_str,
    serializer_for_schema

Outbox dispatcher:
    BaseOutboxDispatcher, DispatcherConfig, DeliveryResult, OutboxRecordProtocol,
    OutboxRepositoryProtocol, UnitOfWorkWithOutboxProtocol, run_dispatcher

Valkey:
    ValkeyClient, ValkeyConfig, create_valkey_client, create_valkey_client_from_url

Topics:
    Topic name constants (see messaging.topics)
"""

from messaging.kafka.consumer.base import (
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.consumer.errors import (
    BusinessRuleViolationError,
    ConsumerError,
    DatabaseConnectionError,
    FatalError,
    MalformedDataError,
    MissingRequiredFieldError,
    NetworkTimeoutError,
    RateLimitedError,
    RetryableError,
    SchemaVersionError,
    ServiceUnavailableError,
    StorageUnavailableError,
)
from messaging.kafka.dispatcher.base import (
    BaseOutboxDispatcher,
    DeliveryResult,
    DispatcherConfig,
    OutboxRecordProtocol,
    OutboxRepositoryProtocol,
    UnitOfWorkWithOutboxProtocol,
    run_dispatcher,
)
from messaging.kafka.producer import (
    KafkaEventValueSerializer,
    KafkaProducerConfig,
    OutboxEventValueSerializer,
    OutboxKafkaValue,
    build_serializing_producer,
)
from messaging.kafka.schema_registry import (
    SchemaRegistryConfig,
    build_schema_registry_client,
)
from messaging.kafka.serialization_utils import (
    decimal_to_str,
    deserialize_avro,
    iso_datetime,
    load_schema,
    serialize_avro,
    serializer_for_schema,
)
from messaging.kafka.serializer import (
    AvroDictable,
    AvroSerializerConfig,
    build_avro_serializer,
    topic_event_type_subject_name_strategy,
)
from messaging.valkey.client import (
    ValkeyClient,
    ValkeyConfig,
    create_valkey_client,
    create_valkey_client_from_url,
)

__all__ = [
    "AvroDictable",
    "AvroSerializerConfig",
    "BaseKafkaConsumer",
    "BaseOutboxDispatcher",
    "BusinessRuleViolationError",
    "ConsumerConfig",
    "ConsumerError",
    "DatabaseConnectionError",
    "DeliveryResult",
    "DispatcherConfig",
    "FailureInfo",
    "FatalError",
    "KafkaEventValueSerializer",
    "KafkaProducerConfig",
    "MalformedDataError",
    "MissingRequiredFieldError",
    "NetworkTimeoutError",
    "OutboxEventValueSerializer",
    "OutboxKafkaValue",
    "OutboxRecordProtocol",
    "OutboxRepositoryProtocol",
    "RateLimitedError",
    "RetryableError",
    "SchemaRegistryConfig",
    "SchemaVersionError",
    "ServiceUnavailableError",
    "StorageUnavailableError",
    "UnitOfWorkProtocol",
    "UnitOfWorkWithOutboxProtocol",
    "ValkeyClient",
    "ValkeyConfig",
    "build_avro_serializer",
    "build_schema_registry_client",
    "build_serializing_producer",
    "create_valkey_client",
    "create_valkey_client_from_url",
    "decimal_to_str",
    "deserialize_avro",
    "iso_datetime",
    "load_schema",
    "run_dispatcher",
    "serialize_avro",
    "serializer_for_schema",
    "topic_event_type_subject_name_strategy",
]
