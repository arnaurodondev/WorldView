"""Periodic background workers for the market-data (S3) service.

These are standalone, interval-driven processes (each with its own ``_main.py``
entry-point and docker-compose service) — distinct from the Kafka consumers in
``infrastructure/messaging/consumers`` which are event-driven.
"""
