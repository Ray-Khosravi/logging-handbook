"""
Example 02 — Structured logging with python-json-logger
=======================================================

Transforms stdlib logging into JSON output without changing your application
code. This is the easiest path for existing codebases.

Plain text logs are unsearchable. JSON logs are queryable.

Run:
    python examples/02_structured_logging.py
"""

import logging
import logging.config
import sys
from datetime import datetime, timezone


def section(title: str) -> None:
    print("\n" + "─" * 70)
    print(title)
    print("─" * 70)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Demonstrate the problem with plain text
# ─────────────────────────────────────────────────────────────────────────────
def demo_plaintext_problem() -> None:
    section("1. The problem with plain-text logs")
    print("""
  Plain text:
    2026-05-15 14:23:01 INFO User 42 logged in from 10.0.0.1 (took 230ms)

  To query "average login latency for user 42", you'd write a regex like:
    ^.* INFO User (\\d+) logged in from \\S+ \\(took (\\d+)ms\\)$
                  ↑                           ↑
              user_id                     duration_ms

  This is fragile, slow, and breaks the moment someone tweaks the log format.
""")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Configure JSON output with python-json-logger
# ─────────────────────────────────────────────────────────────────────────────
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        # Human-friendly text for local development
        "text": {
            "format": "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        },
        # Machine-friendly JSON for production
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
            "rename_fields": {
                "asctime":   "ts",
                "levelname": "level",
                "name":      "logger",
                "message":   "event",
            },
            "datefmt": "%Y-%m-%dT%H:%M:%S.%fZ",
        },
    },
    "handlers": {
        "stdout_json": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "json",
            "level": "DEBUG",
        },
    },
    "loggers": {
        "__main__": {"handlers": ["stdout_json"], "level": "DEBUG", "propagate": False},
    },
    "root": {"handlers": ["stdout_json"], "level": "WARNING"},
}


# ─────────────────────────────────────────────────────────────────────────────
# 3. Demonstrate JSON output
# ─────────────────────────────────────────────────────────────────────────────
def demo_json_output(logger: logging.Logger) -> None:
    section("2. JSON output — every field is searchable")

    # The "message" becomes a flat "event" name (per our rename_fields).
    # Everything in `extra=` becomes a top-level field in the JSON output.
    logger.info(
        "user_login_succeeded",
        extra={"user_id": 42, "ip": "10.0.0.1", "duration_ms": 230},
    )

    logger.warning(
        "payment_retry_succeeded",
        extra={"user_id": 42, "attempts": 3, "amount_usd": 19.99},
    )

    logger.error(
        "charge_failed",
        extra={
            "user_id": 42,
            "amount_usd": 19.99,
            "reason": "card_declined",
            "card_last4": "4242",
        },
    )


def demo_exception_json(logger: logging.Logger) -> None:
    section("3. Exceptions in JSON — tracebacks become structured")
    try:
        # Simulate a nested operation that fails
        data = {"price": "twenty"}
        _ = float(data["price"])
    except ValueError:
        # logger.exception() captures the full stack into a JSON field
        logger.exception(
            "price_parsing_failed",
            extra={"product_id": "sku-9001", "raw_value": "twenty"},
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Side-by-side comparison
# ─────────────────────────────────────────────────────────────────────────────
def demo_comparison() -> None:
    section("4. Before vs After")
    print("""
  Before (plain text, unsearchable):
    2026-05-15 14:23:01 INFO User 42 logged in from 10.0.0.1 (230ms)

  After (JSON, queryable):
    {"ts": "2026-05-15T14:23:01.000Z", "level": "INFO",
     "logger": "myapp.auth", "event": "user_login_succeeded",
     "user_id": 42, "ip": "10.0.0.1", "duration_ms": 230}

  In Loki:   {level="INFO"} | json | duration_ms > 1000
  In Elastic: GET /logs/_search?q=event:user_login_succeeded AND user_id:42
  In CloudWatch: fields @timestamp, user_id | filter event="user_login_succeeded"
""")


def takeaways() -> None:
    section("Takeaways")
    print("""
  ✅ python-json-logger is the lowest-friction path to structured logs
     for an existing stdlib-based codebase.

  ✅ Use `extra={...}` to add fields. They appear as top-level JSON keys.

  ✅ Rename Python's awkward field names (asctime/levelname) to short,
     standard ones (ts/level) via `rename_fields`.

  ❌ Don't f-string variables into the message — keep the message a stable
     "event name" and put variables in `extra`.

     ❌ logger.info(f"User {uid} logged in from {ip}")
     ✅ logger.info("user_login", extra={"user_id": uid, "ip": ip})

  Next: example 03 shows structlog, which makes this pattern much more ergonomic.
""")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Entrypoint
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    print("=" * 70)
    print("LOGGING HANDBOOK — STEP 02: STRUCTURED LOGGING (JSON)")
    print("=" * 70)

    try:
        from pythonjsonlogger import jsonlogger  # noqa: F401
    except ImportError:
        print("\n  ⚠️  python-json-logger is not installed.")
        print("  Install with:  pip install python-json-logger")
        sys.exit(1)

    logging.config.dictConfig(LOGGING_CONFIG)
    logger = logging.getLogger(__name__)

    demo_plaintext_problem()
    demo_json_output(logger)
    demo_exception_json(logger)
    demo_comparison()
    takeaways()


if __name__ == "__main__":
    main()
