"""
Example 04 — Loguru: zero-config logging that just works
=========================================================

Loguru takes the opposite philosophy from structlog:

  structlog → explicit processor pipeline, production-grade control
  Loguru    → one import, sensible defaults, beautiful output

For scripts, prototypes, and small services, Loguru is hard to beat.
For large codebases with strict observability requirements, structlog wins.

This file shows:
  1. The "zero config" setup
  2. Switching to JSON for production with one flag
  3. Context binding via .bind() and .contextualize()
  4. File rotation, retention, and compression (built-in!)
  5. Intercepting stdlib logs so libraries flow through Loguru

Run:
    python examples/04_loguru_quickstart.py
"""

import os
import sys
from contextlib import contextmanager


def section(title: str) -> None:
    print("\n" + "─" * 70)
    print(title)
    print("─" * 70)


def main() -> None:
    print("=" * 70)
    print("LOGGING HANDBOOK — STEP 04: LOGURU")
    print("=" * 70)

    try:
        from loguru import logger
    except ImportError:
        print("\n  ⚠️  loguru not installed. `pip install loguru`")
        sys.exit(1)

    # ─────────────────────────────────────────────────────────────────────
    # 1. Zero-config — Loguru works out of the box
    # ─────────────────────────────────────────────────────────────────────
    section("1. Zero-config — just import and log")
    logger.info("service started")
    logger.success("payment processed!")           # Loguru has SUCCESS level
    logger.warning("disk usage at 85%")
    logger.error("payment gateway timeout")

    # ─────────────────────────────────────────────────────────────────────
    # 2. Reconfigure for production (JSON output)
    # ─────────────────────────────────────────────────────────────────────
    section("2. Switching to JSON for production")
    logger.remove()                                # drop default handler
    logger.add(sys.stdout, serialize=True, level="INFO")

    logger.info("user_login_succeeded", user_id=42, ip="10.0.0.1")
    logger.warning("payment_retried", user_id=42, attempts=3)

    print("\n  → `serialize=True` switches to JSON output.")
    print("  → Every log line is now one queryable JSON object.")

    # ─────────────────────────────────────────────────────────────────────
    # 3. Context binding — .bind() and .contextualize()
    # ─────────────────────────────────────────────────────────────────────
    section("3. Context binding")

    # Reset to colored output for readability
    logger.remove()
    logger.add(sys.stdout,
               format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | "
                      "<cyan>{extra}</cyan> | {message}",
               level="INFO", colorize=True)

    # .bind() creates a logger with permanently bound fields
    request_logger = logger.bind(request_id="req_abc", user_id=42)
    request_logger.info("request received")
    request_logger.info("order created")
    request_logger.info("response sent")

    # .contextualize() is a context manager — fields auto-clear on exit
    with logger.contextualize(request_id="req_xyz", user_id=99):
        logger.info("processing request")
        logger.info("response 200 OK")

    logger.info("outside the contextualize block — context is gone")

    # ─────────────────────────────────────────────────────────────────────
    # 4. Built-in file rotation, retention, compression
    # ─────────────────────────────────────────────────────────────────────
    section("4. File rotation, retention, compression — one line each")
    print("""
  Loguru's killer feature: production-grade file handlers in one call.

      from loguru import logger

      logger.add(
          "logs/app_{time}.log",
          rotation="100 MB",       # rotate at 100 MB OR ...
          rotation="00:00",        # ... rotate at midnight
          retention="30 days",     # keep only last 30 days
          compression="gz",        # gzip rotated files
          level="INFO",
          serialize=True,          # JSON
      )

  No more wiring up RotatingFileHandler + TimedRotatingFileHandler manually.

  ⚠️  Reminder: in CONTAINERS, do not log to files.
     Log to stdout and let the platform handle rotation/retention.
""")

    # ─────────────────────────────────────────────────────────────────────
    # 5. InterceptHandler — route stdlib logging through Loguru
    # ─────────────────────────────────────────────────────────────────────
    section("5. Capturing stdlib logging through Loguru")
    print("""
  Most libraries (boto3, requests, sqlalchemy) use stdlib `logging`.
  By default, those logs DON'T go through Loguru — they bypass it.

  Solution: install an InterceptHandler that redirects everything.

      import logging
      from loguru import logger

      class InterceptHandler(logging.Handler):
          def emit(self, record):
              try:
                  level = logger.level(record.levelname).name
              except ValueError:
                  level = record.levelno
              frame, depth = logging.currentframe(), 2
              while frame and frame.f_code.co_filename == logging.__file__:
                  frame = frame.f_back
                  depth += 1
              logger.opt(depth=depth, exception=record.exc_info).log(
                  level, record.getMessage()
              )

      logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

  Now every stdlib log call (from any library) gets Loguru's formatting,
  destinations, rotation, and JSON serialization.
""")

    # ─────────────────────────────────────────────────────────────────────
    # 6. Exceptions — Loguru's killer feature
    # ─────────────────────────────────────────────────────────────────────
    section("6. Exceptions with `diagnose=True` — variable values in tracebacks")
    print("""
  Loguru's traceback includes the VALUE of each variable at every frame.

      from loguru import logger

      @logger.catch
      def divide(a, b):
          return a / b

      divide(10, 0)

  Standard Python traceback gives you:
      ZeroDivisionError: division by zero

  Loguru with `diagnose=True` (default) gives you:
      File "...", line 5, in divide
          return a / b
                 │   └ 0   ← actual value at runtime
                 └ 10
      ZeroDivisionError: division by zero

  → 10x faster debugging. Disable in production if logs contain sensitive
    data, since variable VALUES end up in the log.
""")

    # ─────────────────────────────────────────────────────────────────────
    # 7. Takeaways
    # ─────────────────────────────────────────────────────────────────────
    section("Takeaways")
    print("""
  ✅ Pick Loguru when:
     • You're prototyping or writing a script
     • You value developer ergonomics over fine-grained control
     • You need file rotation/retention without the boilerplate

  ✅ Pick structlog when:
     • You're building a long-lived production service
     • You need an explicit processor pipeline (PII redaction, filtering)
     • You're integrating with OpenTelemetry (Loguru lacks official OTel
       integration; structlog has community processors for it)

  Both libraries can emit JSON. Both support context binding. They differ
  in philosophy, not capability.

  Next: example 05 shows correlation IDs via contextvars — the missing
  piece for tracing one request across many services.
""")


if __name__ == "__main__":
    main()
