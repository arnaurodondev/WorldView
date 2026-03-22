#!/usr/bin/env python3
"""Register all Avro schemas from a directory into a Confluent Schema Registry.

Exit codes:
  0  — all schemas registered (or already exist)
  1  — one or more schemas failed to register

Environment variables (can be overridden by CLI flags):
  SCHEMA_REGISTRY_URL — Schema Registry base URL (default: http://localhost:8081)
  SCHEMA_DIR          — Directory containing .avsc files (default: /schemas)

Usage:
  # Via Docker Compose (env vars set in container):
  python3 /register-schemas.py

  # Direct invocation with flags:
  python3 register-schemas.py --schema-dir infra/kafka/schemas --registry-url http://localhost:8081
"""

import argparse
import json
import logging
import os
import sys
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


def _validate_registry_url(registry_url: str) -> str:
    parsed = urlparse(registry_url)
    if parsed.scheme not in {"http", "https"}:
        msg = f"Unsupported schema registry URL scheme: {parsed.scheme!r}"
        raise ValueError(msg)
    if not parsed.netloc:
        msg = "Schema registry URL must include host"
        raise ValueError(msg)
    return registry_url.rstrip("/")


def register_schemas(registry_url: str, schema_dir: str) -> int:
    registry_url = _validate_registry_url(registry_url)
    schema_files = sorted(f for f in os.listdir(schema_dir) if f.endswith(".avsc"))

    if not schema_files:
        logger.warning("No .avsc files found in %s", schema_dir)
        return 0

    failed = 0
    for fname in schema_files:
        subject = fname[:-5] + "-value"
        path = os.path.join(schema_dir, fname)
        with open(path) as f:
            raw = f.read()

        payload = json.dumps({"schema": raw}).encode()
        url = f"{registry_url}/subjects/{subject}/versions"
        req = Request(  # noqa: S310
            url,
            data=payload,
            headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
            method="POST",
        )
        try:
            with urlopen(req) as resp:  # noqa: S310
                body = json.load(resp)
                logger.info("Registered %s: id=%s", subject, body.get("id"))
        except HTTPError as e:
            body = json.loads(e.read())
            # 409 = schema already exists — idempotent, treat as success
            if e.code == 409 or body.get("error_code") == 409:
                logger.info("Already registered: %s", subject)
            else:
                logger.error("FAILED %s: HTTP %s %s", subject, e.code, body)
                failed += 1

    if failed:
        return failed

    # Set FULL compatibility for relation.type.proposed.v1 (both FORWARD and BACKWARD required)
    subject = "relation.type.proposed.v1-value"
    compat_url = f"{registry_url}/config/{subject}"
    compat_payload = json.dumps({"compatibility": "FULL"}).encode()
    compat_req = Request(  # noqa: S310
        compat_url,
        data=compat_payload,
        headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
        method="PUT",
    )
    try:
        with urlopen(compat_req) as resp:  # noqa: S310
            body = json.load(resp)
            logger.info("Set FULL compatibility for %s: %s", subject, body)
    except HTTPError as e:
        body = json.loads(e.read())
        logger.error("FAILED to set compatibility for %s: HTTP %s %s", subject, e.code, body)
        failed += 1

    return failed


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Register Avro schemas into Schema Registry.")
    parser.add_argument(
        "--schema-dir",
        default=os.environ.get("SCHEMA_DIR", "/schemas"),
        help="Directory containing .avsc files (default: $SCHEMA_DIR or /schemas)",
    )
    parser.add_argument(
        "--registry-url",
        default=os.environ.get("SCHEMA_REGISTRY_URL", "http://localhost:8081"),
        help="Schema Registry base URL (default: $SCHEMA_REGISTRY_URL or http://localhost:8081)",
    )
    args = parser.parse_args()

    logger.info(
        "Registering schemas from %s to %s",
        args.schema_dir,
        args.registry_url,
    )
    failed = register_schemas(args.registry_url, args.schema_dir)

    if failed:
        logger.error("Schema registration FAILED (%s error(s))", failed)
        sys.exit(1)

    logger.info("All schemas registered")


if __name__ == "__main__":
    main()
