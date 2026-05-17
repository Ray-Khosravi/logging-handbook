"""
Example 06 — Data Pipeline Logging
==================================

A realistic data pipeline that demonstrates what to log at each step:

  Extract  → Transform → Validate → Load

We simulate a small pipeline processing a CSV-like dataset, with:
  • Pipeline-level metadata (run_id, git_commit, params)
  • Per-step duration and row counts
  • Data quality checks (with structured PASS/FAIL events)
  • Schema-drift detection
  • Final pipeline summary

The pattern is library- and framework-agnostic — it works whether you use
Airflow, Prefect, Dagster, or a plain Python script.

Run:
    python examples/06_data_pipeline_logging.py
"""

import logging
import random
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field

import structlog

# ─────────────────────────────────────────────────────────────────────────────
# 0. Bootstrap structlog (we reuse the production setup from example 03)
# ─────────────────────────────────────────────────────────────────────────────
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.dev.ConsoleRenderer(colors=True),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.PrintLoggerFactory(),
)
log = structlog.get_logger()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Per-step timer — emits start, end, and duration as structured events
# ─────────────────────────────────────────────────────────────────────────────
@contextmanager
def step(name: str):
    log.info("step_started", step=name)
    t0 = time.perf_counter()
    try:
        yield
    except Exception:
        log.exception("step_failed", step=name)
        raise
    finally:
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        log.info("step_finished", step=name, duration_ms=elapsed_ms)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Data quality checks — every check emits a result event
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class QualityResult:
    name: str
    passed: bool
    details: dict = field(default_factory=dict)


def check_row_count(rows: list, minimum: int) -> QualityResult:
    return QualityResult(
        "row_count_above_minimum",
        passed=len(rows) >= minimum,
        details={"rows": len(rows), "minimum": minimum},
    )


def check_no_nulls(rows: list, column: str) -> QualityResult:
    nulls = sum(1 for r in rows if r.get(column) is None)
    return QualityResult(
        f"no_nulls_in_{column}",
        passed=nulls == 0,
        details={"nulls": nulls, "rows": len(rows)},
    )


def check_id_uniqueness(rows: list, id_col: str = "id") -> QualityResult:
    ids = [r[id_col] for r in rows]
    return QualityResult(
        "ids_are_unique",
        passed=len(ids) == len(set(ids)),
        details={"rows": len(rows), "unique_ids": len(set(ids))},
    )


def run_quality_checks(rows: list) -> bool:
    """Run all checks and log each result. Returns True only if all pass."""
    checks = [
        check_row_count(rows, minimum=50),
        check_no_nulls(rows, "email"),
        check_id_uniqueness(rows, "id"),
    ]
    all_passed = True
    for c in checks:
        if c.passed:
            log.info("dq_check_passed", check=c.name, **c.details)
        else:
            log.error("dq_check_failed", check=c.name, **c.details)
            all_passed = False
    return all_passed


# ─────────────────────────────────────────────────────────────────────────────
# 3. Schema-drift detection
# ─────────────────────────────────────────────────────────────────────────────
def detect_schema_drift(rows: list, expected: set) -> set | None:
    """Return the missing/unexpected columns, or None if schema matches."""
    if not rows:
        return None
    actual = set(rows[0].keys())
    if actual != expected:
        diff = expected.symmetric_difference(actual)
        log.warning(
            "schema_drift_detected",
            expected=sorted(expected),
            actual=sorted(actual),
            diff=sorted(diff),
        )
        return diff
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 4. Mock pipeline steps
# ─────────────────────────────────────────────────────────────────────────────
def extract() -> list:
    with step("extract"):
        rows = [
            {"id": i, "email": f"user{i}@example.com", "amount": round(random.uniform(5, 500), 2)}
            for i in range(1, 101)
        ]
        # Sprinkle in a few problems to make logs interesting
        rows[7]["email"]  = None                # null email
        rows[12]["id"]    = rows[11]["id"]      # duplicate ID
        log.info("data_extracted", source="api/v2/orders", rows=len(rows))
        return rows


def transform(rows: list) -> list:
    with step("transform"):
        before = len(rows)
        # Drop rows with null email
        cleaned = [r for r in rows if r["email"] is not None]
        dropped = before - len(cleaned)
        if dropped:
            log.warning("rows_dropped", reason="null_email", dropped=dropped)
        # Add a derived column
        for r in cleaned:
            r["amount_eur"] = round(r["amount"] * 0.92, 2)
        log.info(
            "transform_applied",
            rows_in=before, rows_out=len(cleaned),
            derived_columns=["amount_eur"],
        )
        return cleaned


def validate(rows: list) -> bool:
    with step("validate"):
        expected_schema = {"id", "email", "amount", "amount_eur"}
        detect_schema_drift(rows, expected_schema)
        return run_quality_checks(rows)


def load(rows: list) -> int:
    with step("load"):
        # Simulate writing to a warehouse
        time.sleep(0.05)
        log.info(
            "rows_written",
            destination="warehouse.public.orders",
            rows=len(rows),
            partition="2026-05-15",
        )
        return len(rows)


# ─────────────────────────────────────────────────────────────────────────────
# 5. The pipeline runner — top-level metadata + summary
# ─────────────────────────────────────────────────────────────────────────────
def run_pipeline() -> None:
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    structlog.contextvars.bind_contextvars(
        pipeline="daily_orders_etl",
        run_id=run_id,
        git_commit="9a8f7e6",            # would come from $GIT_SHA in CI
        environment="dev",
    )

    log.info("pipeline_started",
             params={"date": "2026-05-15", "warehouse": "snowflake"})
    t0 = time.perf_counter()

    try:
        raw   = extract()
        clean = transform(raw)
        ok    = validate(clean)

        if not ok:
            # Fail closed: do not load if quality checks failed
            log.critical("pipeline_aborted", reason="quality_checks_failed")
            return

        rows_written = load(clean)
        log.info(
            "pipeline_finished",
            status="success",
            rows_written=rows_written,
            duration_ms=round((time.perf_counter() - t0) * 1000, 2),
        )
    except Exception:
        log.exception("pipeline_failed", status="error")
        raise
    finally:
        structlog.contextvars.clear_contextvars()


def takeaways() -> None:
    print("\n" + "─" * 70)
    print("Takeaways")
    print("─" * 70)
    print("""
  ✅ Bind RUN-LEVEL fields once (pipeline name, run_id, git_commit, env).
     Every downstream log automatically inherits them.

  ✅ Wrap each step in a context manager that emits start/end/duration.

  ✅ Each data-quality check is its OWN structured event with PASS/FAIL +
     details. Don't summarize 10 checks into one log line.

  ✅ Schema drift gets WARNING (not ERROR) — your job continues, but
     someone needs to know upstream changed.

  ✅ End with a `pipeline_finished` summary event including final row count
     and total duration. This is your SLO signal.

  ❌ NEVER log entire dataframes / row contents — log COUNTS and STATS.
  ❌ NEVER log raw PII (emails, phone numbers). Hash, mask, or omit.

  Real-world tools that use this pattern under the hood:
     • Great Expectations — data quality framework
     • dbt artifacts.json — emits structured events for every model run
     • Airflow / Prefect / Dagster — task-level logs follow this shape
""")


def main() -> None:
    print("=" * 70)
    print("LOGGING HANDBOOK — STEP 06: DATA PIPELINE LOGGING")
    print("=" * 70)
    run_pipeline()
    takeaways()


if __name__ == "__main__":
    main()
