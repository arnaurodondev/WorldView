"""startup_assert — boot-time guard against insecure platform misconfiguration.

This module is intentionally tiny: it contains a single helper,
``assert_app_env_or_die``, which every backend service calls from inside its
FastAPI ``lifespan`` before the app accepts a single request.

Why this exists (PLAN-0093 Wave A-1, audit finding F-LOG-JWT-001 / F-LOG-005):
    The settings flag ``internal_jwt_skip_verification`` defaults to ``False``
    in production code, but if an operator (or a forgotten ``.env``) sets it
    to ``True`` AND forgets to set ``APP_ENV``, the per-service pydantic
    validator only emits a CRITICAL log line — it does NOT abort startup.
    Combined with PRD-0025's JWT-based tenant isolation, that means a single
    misconfigured container can silently accept unsigned JWTs in production.

    This helper closes that gap by *refusing to start* whenever the two
    failure conditions co-occur:

        ``internal_jwt_skip_verification=True`` AND ``APP_ENV`` is unset.

    Both conditions individually are recoverable: skip_verification with an
    explicit dev/test APP_ENV is fine; an unset APP_ENV with full JWT
    verification is fine.  Only the combination is dangerous.

Architecture notes:
    * R12 — uses ``structlog`` (via ``observability.logging.get_logger``) for
      the security event; never stdlib ``logging``.
    * R25 — pure library; no infrastructure imports (no DB, no Kafka, no
      Valkey, no service-specific config classes).  Callers pass the two
      runtime values they already have on hand.
    * The structured log event name ``startup_security_check_failed`` is the
      stable hook for log-based alerting (Loki / Sentry / Grafana).
"""

from __future__ import annotations

import os

from observability.logging import get_logger

# Module-level logger so the security event is correctly attributed to this
# helper rather than the caller.  Alert rules can match on this logger name
# directly: ``logger == "observability.startup_assert"``.
_log = get_logger(__name__)


def assert_app_env_or_die(
    *,
    service_name: str,
    internal_jwt_skip_verification: bool,
    app_env_var: str = "APP_ENV",
) -> None:
    """Refuse to start when JWT verification is disabled with no APP_ENV set.

    Call this from every FastAPI service's ``lifespan`` BEFORE the app accepts
    requests (i.e. before ``yield``).  The signature is intentionally
    keyword-only so callers can never accidentally swap the two args.

    Parameters
    ----------
    service_name
        The logical service name (e.g. ``"rag-chat"``).  Bound to the security
        log event for filtering and alert routing.
    internal_jwt_skip_verification
        The current value of the service's ``internal_jwt_skip_verification``
        setting.  Pull this from the already-validated pydantic settings
        object — do NOT re-read it from the environment here, because the
        settings layer may have applied parsing/coercion (e.g. ``"false"``
        → ``False``).
    app_env_var
        The environment variable name to check.  Overridable purely for unit
        testing; production callers should keep the default ``"APP_ENV"``.

    Raises
    ------
    RuntimeError
        When ``internal_jwt_skip_verification=True`` AND the ``APP_ENV``
        environment variable is unset or empty (after whitespace strip).
        The raise happens *after* the CRITICAL log line is emitted, so
        operators get both the structured event and the stderr traceback.
    """
    # Read APP_ENV fresh from os.environ rather than from a settings object so
    # callers from any service can use this helper without a common config
    # contract (R25 — library helper, no service-specific knowledge).
    #
    # ``.strip()`` collapses whitespace-only values ("   ", "\t") to "" — those
    # are functionally the same as unset for our purposes and the original
    # rag-chat F-S005 guard already used this normalisation.
    raw_env = os.environ.get(app_env_var, "")
    app_env = raw_env.strip()

    # The dangerous condition: JWT verification is bypassed AND we cannot
    # confirm we are running in a dev/test environment.  An unset APP_ENV is
    # the canonical "production by accident" signal — Kubernetes manifests
    # almost always set it explicitly, so an empty value at this point
    # implies either a forgotten env block or a manual ``docker run`` that
    # bypassed the platform's compose definitions.
    if internal_jwt_skip_verification and app_env == "":
        # Emit a structured CRITICAL log first so the failure is captured by
        # the platform log pipeline even if the process dies before stdout is
        # flushed by the traceback writer.
        _log.critical(
            "startup_security_check_failed",
            service=service_name,
            check="app_env_unset_with_skip_verification",
            internal_jwt_skip_verification=True,
            app_env_var=app_env_var,
            app_env_value=raw_env,
            remediation=(
                "Set APP_ENV to one of {development, dev, test, ci, local} "
                "for safe environments, or set internal_jwt_skip_verification=False."
            ),
        )
        # Raise AFTER the log so operators always get the structured event.
        # RuntimeError (not ValueError) so the FastAPI lifespan error handler
        # surfaces it as a startup failure rather than a validation issue.
        raise RuntimeError(
            "BLOCKING SECURITY: APP_ENV unset and JWT verification disabled — "
            f"refusing to start service {service_name!r}. "
            "Set APP_ENV explicitly (development/dev/test/ci/local) or "
            "disable internal_jwt_skip_verification."
        )
