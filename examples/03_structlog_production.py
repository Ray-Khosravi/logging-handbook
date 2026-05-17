"""
Example 03 — structlog for production
=====================================

structlog is the modern answer to Python logging. It treats logs as events,
not strings. Every log call passes data through a configurable pipeline of
"processors" before being rendered to stdout.

Key features demonstrated:
  1. Different rendering for dev (pretty colored) vs prod (JSON)
  2. Context binding — attach fields once, get them on every log line
  3. Per-request contextvars — automatic context across async tasks
  4. Exception serialization — tracebacks become structured fields

Run:
    python examples/03_structlog_production.py
    LOG_ENV=prod python examples/03_structlog_production.py     # JSON output
"""

import logging
import os
import sys
import uuid

import structlog


def section(title: str) -> None:
    print("\n" + "─" * 70)
    print(title)
    print("─" * 70)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Production-ready structlog configuration
# ─────────────────────────────────────────────────────────────────────────────
def configure_structlog(env: str = "dev") -> None:
    """Configure structlog for either local development or production.

    Choose the renderer based on the environment:
      - dev   → ConsoleRenderer (colored, human-friendly)
      - prod  → JSONRenderer    (machine-parseable, line-per-event)
    """

    # Shared processors run on every log call.
    shared_processors: list = [
        # Merge any contextvars (e.g. request_id) into the event dict.
        structlog.contextvars.merge_contextvars,
        # Add the log level as a top-level field.
        structlog.processors.add_log_level,
        # ISO-8601 timestamp, UTC. Lexicographic sort == chronological sort.
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        # If you log exceptions, this turns them into a `exception` field
        # with the full traceback rendered nicely.
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
    ]

    if env == "prod":
        # Production: structured tracebacks + JSON output.
        renderer = structlog.processors.JSONRenderer()
        shared_processors.append(structlog.processors.dict_tracebacks)
    else:
        # Development: pretty colored console output.
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Demos
# ─────────────────────────────────────────────────────────────────────────────
def demo_basic(log: structlog.BoundLogger) -> None:
    section("1. Basic structured logging")
    log.info("service_started", service="api", version="1.4.2", port=8000)
    log.warning("disk_space_low", path="/var/log", available_pct=12)
    log.error(
        "external_api_failed",
        endpoint="https://api.partner.com/v1/charge",
        status_code=502,
        retries=3,
    )


def demo_bind(log: structlog.BoundLogger) -> None:
    """`.bind()` attaches context that flows into every subsequent log line."""
    section("2. Context binding with .bind()")

    request_logger = log.bind(request_id="req_abc123", user_id=42)

    request_logger.info("request_received", path="/orders", method="POST")
    request_logger.info("order_validated", order_id=1001, total_usd=149.99)
    request_logger.info("payment_processed", processor="stripe", duration_ms=210)
    request_logger.info("response_sent", status=201)

    print("\n  → Every line above carries request_id=req_abc123 and user_id=42")
    print("    automatically — no need to repeat them on each call.")


def demo_contextvars(log: structlog.BoundLogger) -> None:
    """For async/multithreaded code, contextvars are the right primitive."""
    section("3. contextvars — context that survives across function boundaries")

    structlog.contextvars.clear_contextvars()
    request_id = f"req_{uuid.uuid4().hex[:8]}"
    structlog.contextvars.bind_contextvars(request_id=request_id, user_id=99)

    # Pretend these are different functions deep in the call stack.
    _handle_validation()
    _handle_database()
    _handle_response()

    structlog.contextvars.clear_contextvars()
    print(f"\n  → Even though _handle_*() never receives request_id, every log")
    print(f"    line includes request_id={request_id} via contextvars.")


def _handle_validation() -> None:
    log = structlog.get_logger()
    log.info("validating_input", fields_checked=["email", "phone"])


def _handle_database() -> None:
    log = structlog.get_logger()
    log.info("db_query", table="users", duration_ms=4.1)


def _handle_response() -> None:
    log = structlog.get_logger()
    log.info("response_sent", status=200)


def demo_exception(log: structlog.BoundLogger) -> None:
    section("4. Exceptions — full tracebacks, structured")
    try:
        data = {"items": []}
        _ = data["items"][0]["price"]
    except (IndexError, KeyError):
        log.exception(
            "order_lookup_failed",
            order_id="ord_9001",
            shop_id="shop_42",
        )


def demo_dev_vs_prod() -> None:
    section("5. Dev vs Prod rendering")
    print("""
  Default (dev mode) — colored, pretty output:
    2026-05-15T14:23:01Z [info     ] user_login    user_id=42 ip=10.0.0.1

  Production mode (LOG_ENV=prod) — single-line JSON:
    {"event": "user_login", "user_id": 42, "ip": "10.0.0.1",
     "level": "info", "timestamp": "2026-05-15T14:23:01.123456Z"}

  Same code, different rendering — just an environment flag.
""")


def takeaways() -> None:
    section("Takeaways")
    print("""
  ✅ structlog gives you:
     • A clean event-style API:  log.info("event_name", field=value, ...)
     • Pluggable processor pipeline (timestamps, levels, redaction, ...)
     • Context binding via .bind() and contextvars
     • Native JSON support with structured tracebacks
     • Works WITH stdlib (you can route stdlib logs through structlog too)

  💡 Production tip: switch renderers via env var.
     • LOG_ENV=dev   → ConsoleRenderer (colored, human)
     • LOG_ENV=prod  → JSONRenderer    (machine-parseable)

  💡 PII / secrets: add a redaction processor BEFORE the renderer so
     fields like 'password', 'token', 'api_key' get redacted automatically.

  Next: example 04 shows Loguru, the developer-friendly alternative.
""")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Entrypoint
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    env = os.getenv("LOG_ENV", "dev")
    print("=" * 70)
    print(f"LOGGING HANDBOOK — STEP 03: STRUCTLOG  (env={env})")
    print("=" * 70)

    configure_structlog(env=env)
    log = structlog.get_logger()

    demo_basic(log)
    demo_bind(log)
    demo_contextvars(log)
    demo_exception(log)
    demo_dev_vs_prod()
    takeaways()


if __name__ == "__main__":
    main()
