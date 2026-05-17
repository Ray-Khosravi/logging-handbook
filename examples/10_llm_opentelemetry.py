"""
Example 10 — OpenTelemetry GenAI Semantic Conventions
======================================================

OpenTelemetry's GenAI semantic convention (now natively supported by
Datadog, Langfuse, LangSmith, Phoenix, OpenLLMetry, etc.) is the EMERGING
STANDARD for instrumenting LLM applications.

Instrument ONCE with these field names, and any compatible backend can
ingest your data without code changes.

This example demonstrates:
  • Creating a GenAI span with the standard `gen_ai.*` attributes
  • Recording token usage as both span attributes AND metrics
  • Toggling prompt/completion capture via OTEL_GENAI_CAPTURE_CONTENT
  • Exporting via OTLP (we use a console exporter here so you see the output)

Reference:  https://opentelemetry.io/docs/specs/semconv/gen-ai/

Run:
    python examples/10_llm_opentelemetry.py

    # In production, point at your backend:
    OTEL_EXPORTER_OTLP_ENDPOINT=https://your-collector:4318 \\
    OTEL_GENAI_CAPTURE_CONTENT=true \\
    python examples/10_llm_opentelemetry.py
"""

import os
import random
import sys
import time


def section(title: str) -> None:
    print("\n" + "─" * 70)
    print(title)
    print("─" * 70)


def main() -> None:
    print("=" * 70)
    print("LOGGING HANDBOOK — STEP 10: OpenTelemetry GenAI Conventions")
    print("=" * 70)

    try:
        from opentelemetry import trace, metrics
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (BatchSpanProcessor,
                                                    ConsoleSpanExporter)
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import (ConsoleMetricExporter,
                                                      PeriodicExportingMetricReader)
        from opentelemetry.sdk.resources import Resource
    except ImportError:
        print("\n  ⚠️  Missing deps. Run:")
        print("     pip install opentelemetry-api opentelemetry-sdk")
        sys.exit(1)

    # ─────────────────────────────────────────────────────────────────────
    # 1. Bootstrap OpenTelemetry — tracer + meter
    # ─────────────────────────────────────────────────────────────────────
    resource = Resource.create({
        "service.name":              "llm-chat-service",
        "service.version":           "1.4.2",
        "deployment.environment":    os.getenv("DEPLOY_ENV", "dev"),
    })

    # Trace pipeline
    tp = TracerProvider(resource=resource)
    tp.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(tp)
    tracer = trace.get_tracer("llm-chat-service")

    # Metric pipeline (token/cost counters)
    mp = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                ConsoleMetricExporter(),
                export_interval_millis=10_000,
            )
        ],
    )
    metrics.set_meter_provider(mp)
    meter = metrics.get_meter("llm-chat-service")

    # Define the standard GenAI metrics. These names follow the
    # OpenTelemetry GenAI semantic-convention spec.
    token_counter = meter.create_counter(
        name="gen_ai.client.token.usage",
        description="Tokens consumed by GenAI requests",
        unit="{token}",
    )
    operation_duration = meter.create_histogram(
        name="gen_ai.client.operation.duration",
        description="LLM operation duration",
        unit="s",
    )

    CAPTURE_CONTENT = (
        os.getenv("OTEL_GENAI_CAPTURE_CONTENT", "false").lower() == "true"
    )

    # ─────────────────────────────────────────────────────────────────────
    # 2. Define a chat() function that wraps the call in a GenAI span
    # ─────────────────────────────────────────────────────────────────────
    def chat(user_message: str, model: str = "gpt-4o") -> str:
        # The span name itself follows the convention: gen_ai.{operation}.
        with tracer.start_as_current_span("chat") as span:
            # ─── Standard GenAI attributes ────────────────────────────────
            span.set_attribute("gen_ai.system",              "openai")
            span.set_attribute("gen_ai.operation.name",      "chat")
            span.set_attribute("gen_ai.request.model",       model)
            span.set_attribute("gen_ai.request.temperature", 0.7)
            span.set_attribute("gen_ai.request.max_tokens",  512)

            # Optionally capture the prompt content
            if CAPTURE_CONTENT:
                span.add_event(
                    "gen_ai.content.prompt",
                    attributes={"gen_ai.prompt": user_message},
                )

            t0 = time.perf_counter()
            try:
                # ─── Mock the API call ────────────────────────────────────
                time.sleep(random.uniform(0.05, 0.20))
                in_tokens  = max(1, len(user_message) // 4)
                out_tokens = random.randint(50, 300)
                finish     = random.choice(["stop", "stop", "stop", "length"])
                completion = f"[mock completion of {out_tokens} tokens]"

                # ─── Standard GenAI response attributes ──────────────────
                span.set_attribute("gen_ai.usage.input_tokens",  in_tokens)
                span.set_attribute("gen_ai.usage.output_tokens", out_tokens)
                span.set_attribute("gen_ai.response.finish_reasons", [finish])
                # gen_ai.response.id is also recommended when available
                span.set_attribute("gen_ai.response.id", f"resp_{random.randint(1, 10**9)}")

                # ─── Record METRICS in addition to span attributes ───────
                # The convention recommends BOTH: spans for tracing,
                # metrics for dashboards.
                token_counter.add(in_tokens, {
                    "gen_ai.system": "openai",
                    "gen_ai.request.model": model,
                    "gen_ai.token.type": "input",
                })
                token_counter.add(out_tokens, {
                    "gen_ai.system": "openai",
                    "gen_ai.request.model": model,
                    "gen_ai.token.type": "output",
                })
                operation_duration.record(
                    time.perf_counter() - t0,
                    {"gen_ai.system": "openai", "gen_ai.request.model": model},
                )

                # Capture completion content (opt-in)
                if CAPTURE_CONTENT:
                    span.add_event(
                        "gen_ai.content.completion",
                        attributes={"gen_ai.completion": completion},
                    )

                return completion

            except Exception as exc:
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
                span.record_exception(exc)
                raise

    # ─────────────────────────────────────────────────────────────────────
    # 3. Run a few calls and let the exporter print them
    # ─────────────────────────────────────────────────────────────────────
    section(f"1. Running calls (OTEL_GENAI_CAPTURE_CONTENT={CAPTURE_CONTENT})")
    chat("What is the capital of France?")
    chat("Summarize: " + ("lorem ipsum " * 80))
    chat("Write a haiku about logging.")

    # Flush before the script exits
    tp.shutdown()
    mp.shutdown()

    # ─────────────────────────────────────────────────────────────────────
    # 4. Why this matters
    # ─────────────────────────────────────────────────────────────────────
    section("2. Why the convention matters")
    print("""
  Standardized attribute names mean any backend can ingest your data:

     • Datadog LLM Observability     ✓ (natively supports OTel GenAI v1.37)
     • Langfuse                      ✓ (OTLP endpoint)
     • LangSmith                     ✓ (OTel-compatible)
     • Phoenix (Arize)               ✓ (built on OTel)
     • OpenLLMetry / Traceloop       ✓ (defines this convention)
     • New Relic / Splunk / Honeycomb ✓ (any OTel-compatible APM)

  → Instrument once, swap backends with an environment variable.

  Useful env vars:
     OTEL_SERVICE_NAME              = "llm-chat-service"
     OTEL_RESOURCE_ATTRIBUTES       = "deployment.environment=prod"
     OTEL_EXPORTER_OTLP_ENDPOINT    = "https://your-collector:4318"
     OTEL_EXPORTER_OTLP_PROTOCOL    = "http/protobuf"  | "grpc"
     OTEL_GENAI_CAPTURE_CONTENT     = "false"          # never capture in prod by default
""")

    section("Takeaways")
    print("""
  ✅ Use the OTel GenAI convention for ALL your LLM instrumentation.
     The field names are documented at:
     https://opentelemetry.io/docs/specs/semconv/gen-ai/

  ✅ Always record BOTH spans (for tracing) AND metrics (for dashboards).
     - Spans answer "what happened in this one request?"
     - Metrics answer "how is the whole system behaving?"

  ✅ Gate prompt/completion capture behind an env flag — they may contain
     PII or secrets. Default OFF in production.

  ✅ For agent workflows, each tool call & retrieval step gets its OWN
     child span. The convention covers these too (gen_ai.tool.* attrs).

  Next: example 11 shows Langfuse — a higher-level, LLM-specific tool
  that you can layer on top of (or instead of) raw OpenTelemetry.
""")


if __name__ == "__main__":
    main()
