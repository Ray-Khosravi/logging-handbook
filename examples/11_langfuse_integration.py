"""
Example 11 — Langfuse Integration
=================================

Langfuse is the open-source (MIT) leader in LLM observability — 19k+ ⭐
on GitHub, framework-agnostic, self-hostable, ClickHouse-backed.

This file demonstrates:
  • A traced multi-step LLM application
  • Hierarchical spans (trace → generation → tool span)
  • Token + cost tracking
  • User & session attribution
  • Score / feedback attachment

To run this against real Langfuse:

    1. Self-host Langfuse:
         git clone https://github.com/langfuse/langfuse
         cd langfuse && docker compose up -d
         # Open http://localhost:3000

    2. Create a project, generate API keys.

    3. Set environment variables:
         export LANGFUSE_HOST=http://localhost:3000
         export LANGFUSE_PUBLIC_KEY=pk-lf-...
         export LANGFUSE_SECRET_KEY=sk-lf-...

    4. Run:
         python examples/11_langfuse_integration.py

If the env vars are missing, this example runs in DRY-RUN mode and just
prints what would have been sent.
"""

import os
import random
import sys
import time
import uuid


def section(title: str) -> None:
    print("\n" + "─" * 70)
    print(title)
    print("─" * 70)


def dry_run_demo() -> None:
    section("⚠️  DRY-RUN — Langfuse env vars not set")
    print("""
  To send real traces, set:
     LANGFUSE_HOST       (e.g. http://localhost:3000)
     LANGFUSE_PUBLIC_KEY
     LANGFUSE_SECRET_KEY

  In DRY-RUN, we describe what WOULD be sent.

  Trace tree this example would create:

    [TRACE] customer_support_query  user_id=user_42 session_id=sess_abc
      │
      ├── [SPAN] retrieve_docs                       latency=120 ms
      │     metadata: { top_k: 5, vector_store: "pinecone" }
      │
      ├── [GENERATION] claude-sonnet-4-6             latency=850 ms
      │     model: claude-sonnet-4-6
      │     input_tokens: 1245
      │     output_tokens: 312
      │     cost_usd: $0.00845
      │     temperature: 0.3
      │     metadata: { prompt_version: "v3.2.1" }
      │
      └── [SPAN] tool_call.search_orders             latency=45 ms
            args: { user_id: 42, status: "open" }
            result_count: 3

    Scores attached to the trace:
      - user_thumbs_up: 1   (positive feedback)
      - hallucination_check: 0.92  (from LLM-as-judge)

  In the Langfuse UI you'd see this as a beautiful nested timeline,
  with token & cost rolling up to the trace level.
""")


def real_run(langfuse) -> None:
    """Actually send traces to Langfuse."""
    section("1. Sending a multi-step trace to Langfuse")

    # ─── Trace (top-level container for one user interaction) ────────────
    trace = langfuse.trace(
        name="customer_support_query",
        user_id="user_42",
        session_id=f"sess_{uuid.uuid4().hex[:8]}",
        tags=["production", "billing"],
        metadata={"plan": "pro", "channel": "web"},
        input={"query": "Why was I charged twice last month?"},
    )

    # ─── Span 1: vector retrieval ────────────────────────────────────────
    retrieval = trace.span(
        name="retrieve_docs",
        metadata={"top_k": 5, "vector_store": "pinecone"},
    )
    time.sleep(0.12)
    retrieval.end(output={"docs_returned": 5, "max_score": 0.87})

    # ─── Generation: the LLM call (gets token & cost rollup) ─────────────
    generation = trace.generation(
        name="answer_with_context",
        model="claude-sonnet-4-6",
        model_parameters={"temperature": 0.3, "max_tokens": 512},
        input=[
            {"role": "system", "content": "You are a helpful support agent."},
            {"role": "user",   "content": "Why was I charged twice last month?"},
        ],
        metadata={"prompt_version": "v3.2.1"},
    )
    time.sleep(0.85)
    in_tokens, out_tokens = 1245, 312
    generation.end(
        output="It looks like you were double-charged due to a retry bug...",
        usage={
            "input":  in_tokens,
            "output": out_tokens,
            "total":  in_tokens + out_tokens,
            "unit":   "TOKENS",
        },
    )

    # ─── Tool call as a child span ───────────────────────────────────────
    tool_span = trace.span(
        name="tool.search_orders",
        input={"user_id": 42, "status": "open"},
    )
    time.sleep(0.045)
    tool_span.end(output={"result_count": 3})

    # ─── Attach scores: user feedback + LLM-as-judge ─────────────────────
    trace.score(
        name="user_thumbs_up",
        value=1,
        comment="User clicked the 👍 button",
    )
    trace.score(
        name="hallucination_check",
        value=0.92,
        comment="LLM-as-judge said the answer is grounded.",
    )

    trace.update(output={"resolved": True})

    # ─── Flush before exit ───────────────────────────────────────────────
    langfuse.flush()

    print(f"  ✓ Trace sent. Open Langfuse UI to inspect:")
    print(f"    {os.getenv('LANGFUSE_HOST')}/traces")


def takeaways() -> None:
    section("Takeaways")
    print("""
  ✅ Why use Langfuse (or LangSmith / Phoenix) instead of raw OTel?

     • Built-in UI for browsing LLM traces (timelines, token rollups, cost)
     • Prompt management & versioning (compare prompt v3.2 vs v3.3)
     • LLM-as-judge evaluations attached to traces
     • Dataset management for offline eval
     • User feedback (thumbs up/down) attached to traces

  ✅ When to pick Langfuse:
     • You want SELF-HOSTING (MIT license)
     • You're FRAMEWORK-AGNOSTIC (not all-in on LangChain)
     • You want data sovereignty (full self-host with ClickHouse)

  ✅ When to pick LangSmith instead:
     • You're DEEP in the LangChain / LangGraph ecosystem
     • You want native managed SaaS with zero ops
     • You're OK with vendor lock-in to LangChain Inc.

  ✅ When to pick Arize Phoenix:
     • You want strong RAG evaluation tooling
     • You're already on Arize for model monitoring

  ✅ When to pick OpenLLMetry + your existing observability stack:
     • You don't want a separate LLM-specific tool
     • You want vendor-neutral OpenTelemetry through and through

  💡 You can use MULTIPLE: many teams pair a gateway tool (Helicone or
     Portkey) for cost tracking with an evaluation tool (Phoenix or
     TruLens) for quality.

  💡 The data captured here also flows nicely into your structlog logs
     via the Langfuse span's `trace_id` — bind it as a context var, and
     you can pivot from a Loki log query straight to the Langfuse UI.
""")


def main() -> None:
    print("=" * 70)
    print("LOGGING HANDBOOK — STEP 11: LANGFUSE LLM OBSERVABILITY")
    print("=" * 70)

    have_creds = all(os.getenv(k) for k in (
        "LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY",
    ))

    if not have_creds:
        dry_run_demo()
        takeaways()
        return

    try:
        from langfuse import Langfuse
    except ImportError:
        print("\n  ⚠️  langfuse not installed — running in dry-run mode.")
        print("  pip install langfuse\n")
        dry_run_demo()
        takeaways()
        return

    langfuse = Langfuse(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        host=os.environ["LANGFUSE_HOST"],
    )
    real_run(langfuse)
    takeaways()


if __name__ == "__main__":
    main()
