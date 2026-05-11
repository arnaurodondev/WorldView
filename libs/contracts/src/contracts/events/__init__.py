"""Canonical Kafka event models (typed mirrors of Avro schemas).

The ``contracts.canonical`` package historically held one-shape-per-domain
models that map to Avro schemas at ``infra/kafka/schemas/``.  As the platform
adds purely-event payloads (e.g. cross-service triggers that never persist as
their own entity), they live here under ``contracts.events.<domain>`` instead
of ``canonical/`` to keep the directory layout aligned with the event nature
of the payload.
"""
