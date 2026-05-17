"""
Example 01 — stdlib logging done right
======================================

Most Python tutorials show `logging.basicConfig()` and call it a day.
That's fine for scripts. In production, you need:

1. A NAMED logger per module  (not the root logger)
2. Explicit configuration       (via dictConfig, not basicConfig)
3. Multiple handlers            (console + file, or console + remote)
4. Filtered library noise       (urllib3, boto3 are too chatty by default)
5. NO print() calls anywhere

This file demonstrates each in turn.

Run:
    python examples/01_logging_basics.py
"""

import logging
import logging.config
import sys


def section(title: str) -> None:
    print("\n" + "─" * 70)
    print(title)
    print("─" * 70)


# ─────────────────────────────────────────────────────────────────────────────
# 1. The wrong way (don't do this)
# ─────────────────────────────────────────────────────────────────────────────
def demo_the_wrong_way() -> None:
    section("1. The WRONG way — print() and basicConfig()")
    print("  print('User logged in')           # ❌ no levels, no filtering")
    print("  logging.basicConfig(level=...)    # ❌ pollutes root logger globally")
    print("  logging.info('hi')                # ❌ uses root logger; loses module name")


# ─────────────────────────────────────────────────────────────────────────────
# 2. The right pattern: named loggers per module
# ─────────────────────────────────────────────────────────────────────────────
# This is the single most important pattern.  Every module does:
#
#     logger = logging.getLogger(__name__)
#
# `__name__` is the module's dotted path (e.g. "myapp.payments.charges").
# Configuration applied to a parent logger propagates to its children, so
# you can dial up DEBUG for one subsystem without affecting others.

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Configure with dictConfig (the canonical, production-ready approach)
# ─────────────────────────────────────────────────────────────────────────────
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        },
        "detailed": {
            "format": (
                "%(asctime)s [%(levelname)-8s] %(name)s "
                "%(filename)s:%(lineno)d — %(message)s"
            ),
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "default",
            "level": "INFO",
        },
    },
    "loggers": {
        # Your application — INFO and above
        "__main__": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        # Noisy libraries — bump to WARNING
        "urllib3":  {"level": "WARNING"},
        "botocore": {"level": "WARNING"},
        "boto3":    {"level": "WARNING"},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
}


# ─────────────────────────────────────────────────────────────────────────────
# 4. Demos
# ─────────────────────────────────────────────────────────────────────────────
def demo_levels() -> None:
    section("2. Log levels — pick the right one")

    # DEBUG: only visible if your logger level is DEBUG
    logger.debug("checking_cache", extra={"cache_key": "user:42"})

    # INFO: routine business event
    logger.info("user_login_succeeded user_id=42 ip=10.0.0.1")

    # WARNING: something unusual but recoverable
    logger.warning("payment_retry_succeeded user_id=42 attempts=3")

    # ERROR: an operation failed
    logger.error("charge_failed user_id=42 amount_usd=19.99 reason=card_declined")

    # CRITICAL: the application cannot continue
    logger.critical("database_unreachable cluster=primary attempts_exhausted=true")


def demo_exception_logging() -> None:
    """The #1 mistake: logging an exception WITHOUT the traceback."""
    section("3. Logging exceptions — always use logger.exception()")
    try:
        raise ValueError("invalid product_id: 'abc' is not numeric")
    except ValueError as e:
        # ❌ WRONG — loses the traceback
        # logger.error(f"got exception: {e}")

        # ✅ RIGHT — captures the full traceback automatically
        logger.exception("product_lookup_failed product_id=abc")


def demo_named_loggers() -> None:
    """Show how named loggers let you tune each subsystem independently."""
    section("4. Named loggers — independent verbosity per subsystem")

    db_logger    = logging.getLogger("myapp.db")
    api_logger   = logging.getLogger("myapp.api")
    cache_logger = logging.getLogger("myapp.cache")

    db_logger.setLevel(logging.DEBUG)         # debug DB subsystem only
    cache_logger.setLevel(logging.WARNING)    # silence the cache

    db_logger.debug("db_query sql='SELECT * FROM users WHERE id=42'")
    db_logger.info("db_pool acquired=8 max=20")
    api_logger.info("api_request method=GET path=/users/42")
    cache_logger.info("this INFO is hidden because we set WARNING")
    cache_logger.warning("cache_miss key=user:42")


def demo_extra_fields() -> None:
    """`extra=` injects fields that handlers/formatters can render."""
    section("5. Adding structured fields with `extra=`")

    logger.info(
        "user_action_completed",
        extra={"user_id": 42, "action": "checkout", "duration_ms": 120},
    )
    print("\n  Note: default text formatter doesn't render `extra` fields.")
    print("  That's why we'll switch to JSON formatting in example 02.")


# ─────────────────────────────────────────────────────────────────────────────
# 5. The single most important takeaway
# ─────────────────────────────────────────────────────────────────────────────
def takeaways() -> None:
    section("Takeaways")
    print("""
  ✅ DO:
       - Use `logger = logging.getLogger(__name__)` in every module
       - Configure once with dictConfig() at app startup
       - Use logger.exception() inside `except` blocks
       - Silence chatty libraries (urllib3, boto3, botocore)
       - In containers, send everything to stdout (12-factor)

  ❌ DON'T:
       - print() in production code
       - Use logging.basicConfig() in libraries
       - Call logger.error() with just `str(exception)` (you lose the stack)
       - Mix log levels (e.g. INFO for errors)
       - Configure logging at import time inside library modules
""")


if __name__ == "__main__":
    print("=" * 70)
    print("LOGGING HANDBOOK — STEP 01: STDLIB LOGGING DONE RIGHT")
    print("=" * 70)

    logging.config.dictConfig(LOGGING_CONFIG)

    demo_the_wrong_way()
    demo_levels()
    demo_exception_logging()
    demo_named_loggers()
    demo_extra_fields()
    takeaways()
