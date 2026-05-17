"""
Example 08 — ML Inference / Serving Logging
============================================

When your model is live, your logs must answer two different audiences:

   Engineers     → "Is the service healthy? Latency? Error rate?"
   Data Scientists → "Are inputs drifting? Are predictions still accurate?"

This example simulates an inference service and shows what to log per
prediction, while STAYING PRIVACY-AWARE:

  • Never log raw inputs (might contain PII)
  • DO log feature-vector summaries (means, hashes)
  • DO log model name + version + checksum (for traceability)
  • DO log latency, status, confidence
  • DO emit a separate "drift signal" event so the ML team can monitor it

Run:
    python examples/08_ml_inference_logging.py
"""

import hashlib
import logging
import random
import statistics
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass

import structlog


# ─────────────────────────────────────────────────────────────────────────────
# 0. structlog setup
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
# 1. Model metadata — bound to every log line
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ModelInfo:
    name: str
    version: str
    sha256: str
    training_data_hash: str

MODEL = ModelInfo(
    name="fraud-detection",
    version="v3.1.2",
    sha256="9a8f7e6d5c4b3a291", # would be `sha256sum model.pkl` in CI
    training_data_hash="b3c2a1d4",
)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Privacy-aware feature summarization
# ─────────────────────────────────────────────────────────────────────────────
def feature_vector_hash(features: list[float]) -> str:
    """Deterministic 12-char hash of a feature vector. Privacy-preserving."""
    blob = ",".join(f"{x:.4f}" for x in features).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def feature_summary(features: list[float]) -> dict:
    """Stats good enough for drift monitoring; no raw values logged."""
    return {
        "n_features": len(features),
        "fv_hash":    feature_vector_hash(features),
        "fv_mean":    round(statistics.mean(features),   4),
        "fv_stdev":   round(statistics.stdev(features),  4) if len(features) > 1 else 0,
        "fv_min":     round(min(features),               4),
        "fv_max":     round(max(features),               4),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Drift detection (toy)
# ─────────────────────────────────────────────────────────────────────────────
# In production, use Evidently AI, Arize, WhyLabs, or NannyML.
# Here we just compare the live mean to a fixed "reference" mean.
REFERENCE_MEAN = 0.50
REFERENCE_STDEV = 0.30

def maybe_emit_drift_signal(summary: dict) -> None:
    delta = abs(summary["fv_mean"] - REFERENCE_MEAN)
    if delta > 2 * REFERENCE_STDEV:
        log.warning(
            "drift_signal",
            metric="feature_mean_shift",
            live_mean=summary["fv_mean"],
            reference_mean=REFERENCE_MEAN,
            delta=round(delta, 4),
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. The actual predict() — simulates a real inference call
# ─────────────────────────────────────────────────────────────────────────────
@contextmanager
def latency_recorder(metric_name: str):
    """Measure a block's duration. The captured time is appended to the
    final log via structlog's `extra`-style kwargs in the caller."""
    t0 = time.perf_counter()
    holder = {}
    try:
        yield holder
    finally:
        holder["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)


def predict(features: list[float]) -> dict:
    request_id = f"req_{uuid.uuid4().hex[:10]}"
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        model_name=MODEL.name,
        model_version=MODEL.version,
        model_sha=MODEL.sha256,
    )

    try:
        log.info("inference_started")

        summary = feature_summary(features)
        log.info("features_received", **summary)

        with latency_recorder("inference") as rec:
            # Pretend to run the model
            time.sleep(random.uniform(0.005, 0.030))
            score = random.random()
            predicted_class = "fraud" if score > 0.7 else "legitimate"

        result = {
            "score": round(score, 4),
            "predicted_class": predicted_class,
            "confidence": round(abs(score - 0.5) * 2, 4),
        }

        log.info(
            "inference_finished",
            prediction=result["predicted_class"],
            score=result["score"],
            confidence=result["confidence"],
            **rec,                               # latency_ms
        )

        # Separately emit a drift-monitoring signal (the ML team will pick
        # this up via a dashboard / streaming aggregator).
        maybe_emit_drift_signal(summary)

        return result
    except Exception:
        log.exception("inference_failed")
        raise
    finally:
        structlog.contextvars.clear_contextvars()


# ─────────────────────────────────────────────────────────────────────────────
# 5. Drive some traffic
# ─────────────────────────────────────────────────────────────────────────────
def section(title: str) -> None:
    print("\n" + "─" * 70)
    print(title)
    print("─" * 70)


def demo_traffic() -> None:
    section("1. Normal traffic — features centered around reference mean")
    for _ in range(5):
        feats = [random.normalvariate(0.5, 0.3) for _ in range(20)]
        predict(feats)

    section("2. Drifted traffic — features shifted upward")
    for _ in range(3):
        feats = [random.normalvariate(1.5, 0.3) for _ in range(20)]
        predict(feats)
    print("\n  → Notice the `drift_signal` warning events above.")
    print("  → In prod, those would feed Grafana alerts or page the ML team.")


def takeaways() -> None:
    section("Takeaways")
    print("""
  ✅ Per-prediction log fields you should ALWAYS include:
       request_id, model_name, model_version, model_sha,
       latency_ms, prediction, confidence

  ✅ For drift monitoring (without logging raw features):
       feature-vector HASH + summary stats (mean, stdev, min, max).
       This is enough for most drift detectors.

  ✅ Emit drift as a SEPARATE structured event (level=warning), not
     embedded in regular inference logs. Otherwise it's invisible.

  ❌ NEVER log:
       - Raw input features (could be PII)
       - Full user profile data
       - Outputs containing user-provided text (toxicity / privacy risk)

  💡 Industry-standard drift / quality tools:
     • Evidently AI    — open-source drift detection
     • Arize AI        — managed observability for ML
     • WhyLabs         — privacy-first monitoring (logs stats only)
     • NannyML         — concept drift in batch settings

  💡 Where to send these logs:
     • Operational metrics  → Loki / ELK / CloudWatch (with alerts)
     • Per-prediction data  → S3 + Athena, or your drift tool's backend
""")


def main() -> None:
    print("=" * 70)
    print("LOGGING HANDBOOK — STEP 08: ML INFERENCE LOGGING")
    print("=" * 70)
    demo_traffic()
    takeaways()


if __name__ == "__main__":
    main()
