"""
Example 07 — ML Training Logging with MLflow
=============================================

ML training logs to TWO places simultaneously:

  1. Application logger (structlog) — operational events: progress, errors
  2. Experiment tracker (MLflow)    — the science: params, metrics, artifacts

Why? Because the AUDIENCES are different:
  • DevOps reads structlog output to know "is training running and healthy?"
  • Data scientists read MLflow to compare runs and pick the best model.

This example trains a tiny scikit-learn model on a synthetic dataset,
logging the way you'd do it in production.

Run:
    python examples/07_ml_training_mlflow.py
    mlflow ui --backend-store-uri ./mlruns       # then open localhost:5000
"""

import logging
import os
import platform
import random
import sys
import time
import uuid
from contextlib import contextmanager

import structlog


# ─────────────────────────────────────────────────────────────────────────────
# 0. Bootstrap structlog (same prod setup as other examples)
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


@contextmanager
def step(name: str):
    log.info("step_started", step=name)
    t0 = time.perf_counter()
    try:
        yield
    finally:
        log.info("step_finished", step=name,
                 duration_ms=round((time.perf_counter() - t0) * 1000, 2))


# ─────────────────────────────────────────────────────────────────────────────
# 1. The training routine — instrumented for both structlog and MLflow
# ─────────────────────────────────────────────────────────────────────────────
def train(hyperparams: dict) -> dict:
    try:
        import mlflow
        from sklearn.datasets import make_classification
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.metrics import (accuracy_score, f1_score,
                                     precision_score, recall_score)
        from sklearn.model_selection import train_test_split
    except ImportError:
        print("\n  ⚠️  Missing deps. Run: pip install mlflow scikit-learn numpy")
        sys.exit(1)

    run_id = f"train_{uuid.uuid4().hex[:8]}"
    structlog.contextvars.bind_contextvars(
        experiment="customer_churn",
        run_id=run_id,
        git_commit=os.getenv("GIT_SHA", "9a8f7e6"),
    )

    log.info("training_started",
             hyperparams=hyperparams,
             python_version=platform.python_version())

    # ─── Set the MLflow experiment ────────────────────────────────────────
    mlflow.set_experiment("customer_churn")

    # The `with` block makes sure MLflow auto-ends the run even on exception.
    with mlflow.start_run(run_name=run_id) as mlrun:
        log.info("mlflow_run_started",
                 mlflow_run_id=mlrun.info.run_id,
                 mlflow_artifact_uri=mlrun.info.artifact_uri)

        # ─── Log hyperparameters & environment to MLflow ──────────────────
        mlflow.log_params(hyperparams)
        mlflow.log_param("python_version", platform.python_version())
        mlflow.log_param("git_commit",     os.getenv("GIT_SHA", "9a8f7e6"))

        # ─── Generate synthetic data ──────────────────────────────────────
        with step("data_prep"):
            X, y = make_classification(
                n_samples=2000, n_features=20, n_classes=2,
                weights=[0.7, 0.3], random_state=42,
            )
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42, stratify=y,
            )
            log.info("data_prepared",
                     train_rows=len(X_train), test_rows=len(X_test),
                     positive_class_pct=round(100 * y.mean(), 2))

        # ─── Train ────────────────────────────────────────────────────────
        with step("model_fit"):
            model = RandomForestClassifier(**hyperparams)
            model.fit(X_train, y_train)
            log.info("model_trained", n_estimators=model.n_estimators)

        # ─── Evaluate & log per-metric to MLflow ──────────────────────────
        with step("evaluation"):
            preds = model.predict(X_test)
            metrics = {
                "accuracy":  round(accuracy_score(y_test, preds), 4),
                "precision": round(precision_score(y_test, preds), 4),
                "recall":    round(recall_score(y_test, preds), 4),
                "f1":        round(f1_score(y_test, preds), 4),
            }
            for name, value in metrics.items():
                mlflow.log_metric(name, value)
            log.info("evaluation_finished", metrics=metrics)

        # ─── Log the model artifact ───────────────────────────────────────
        with step("model_logging"):
            mlflow.sklearn.log_model(
                sk_model=model,
                artifact_path="model",
                # `registered_model_name` would promote it into the Model
                # Registry — uncomment to enable.
                # registered_model_name="customer-churn",
            )
            log.info("model_artifact_logged")

        log.info("training_finished", status="success", metrics=metrics)

    structlog.contextvars.clear_contextvars()
    return metrics


# ─────────────────────────────────────────────────────────────────────────────
# 2. Hyperparameter sweep — log multiple runs
# ─────────────────────────────────────────────────────────────────────────────
def sweep() -> None:
    log.info("sweep_started")
    grid = [
        {"n_estimators":  50, "max_depth": 5,  "random_state": 42},
        {"n_estimators": 100, "max_depth": 8,  "random_state": 42},
        {"n_estimators": 200, "max_depth": 12, "random_state": 42},
    ]
    results = []
    for i, params in enumerate(grid, 1):
        log.info("sweep_run_dispatched", index=i, total=len(grid), params=params)
        metrics = train(params)
        results.append({"params": params, "metrics": metrics})
    best = max(results, key=lambda r: r["metrics"]["f1"])
    log.info("sweep_finished",
             total_runs=len(grid),
             best_f1=best["metrics"]["f1"],
             best_params=best["params"])


def section(title: str) -> None:
    print("\n" + "─" * 70)
    print(title)
    print("─" * 70)


def takeaways() -> None:
    section("Takeaways")
    print("""
  ✅ The "two loggers" pattern for ML training:

       structlog → operational events
         - training started/finished
         - GPU usage, OOM warnings
         - data prep errors
         - per-step duration

       MLflow → the science
         - hyperparameters
         - per-epoch / final metrics
         - artifacts (model weights, plots, confusion matrices)
         - git commit, dataset hash, environment

  ✅ Always log to MLflow:
     • Hyperparameters (mlflow.log_params)
     • Final & per-epoch metrics (mlflow.log_metric)
     • Model artifact (mlflow.{sklearn|pytorch|tf}.log_model)
     • Git commit + Python version + library versions
     • Dataset version or hash for reproducibility

  ✅ Use `mlflow.start_run() as run:` so the run auto-ends on exception.

  💡 Alternatives:
     • Weights & Biases — better UI, preferred by research teams
     • Neptune          — for huge enterprise teams
     • Comet            — managed alternative

  💡 In production CI/CD:
     - Promote the BEST run to the Model Registry
     - Tag it with the git commit and the model card link
     - Reference the registered model version in your inference service
""")


def main() -> None:
    print("=" * 70)
    print("LOGGING HANDBOOK — STEP 07: ML TRAINING WITH MLflow")
    print("=" * 70)
    sweep()
    takeaways()
    print("\n  💡 To browse your runs visually:")
    print("       mlflow ui --backend-store-uri ./mlruns")
    print("     Then open  http://localhost:5000")


if __name__ == "__main__":
    main()
