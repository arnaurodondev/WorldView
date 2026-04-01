"""Avro schema placeholder for the Knowledge Graph service.

S7 uses pre-serialized payloads written by upstream services (S6, S1, S2).
Outbox events are stored as raw bytes in outbox_events.payload_avro.
No locally-owned Avro schemas are needed for the dispatcher.
"""
