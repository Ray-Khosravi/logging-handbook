"""
Example 09 — Basic LLM Call Logging
====================================

Before reaching for fancy LLM-specific tools (Langfuse, LangSmith, Phoenix),
make sure you're logging the BASICS correctly.

LLMs fail SILENTLY. A 200 OK can still:
  • Hallucinate
  • Hit a token limit and truncate
  • Cost you $5 because someone passed a 100k-token prompt
  • Return a refusal/safety block instead of an answer

Your logs are the only thing that catches this. This file shows the
minimum required fields for every LLM call, in a provider-agnostic way.

Run:
    python examples/09_llm_basic_logging.py
"""

import hashlib
import logging
import random
import time
import uuid
from contextlib import contextmanager

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
# 1. Cost tables (would be loaded from your finops config in production)
# ─────────────────────────────────────────────────────────────────────────────
COST_PER_1K_TOKENS_USD = {
    "claude-opus-4-7":          {"input": 0.015,  "output": 0.075},
    "claude-sonnet-4-6":        {"input": 0.003,  "output": 0.015},
    "claude-haiku-4-5":         {"input": 0.0008, "output": 0.004},
    "gpt-4o":                   {"input": 0.0025, "output": 0.010},
    "gpt-4o-mini":              {"input": 0.00015,"output": 0.0006},
}


def estimate_cost_usd(model: str, in_tokens: int, out_tokens: int) -> float:
    rates = COST_PER_1K_TOKENS_USD.get(model, {"input": 0, "output": 0})
    return round(
        (in_tokens  * rates["input"]  / 1000)
      + (out_tokens * rates["output"] / 1000),
        6,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Privacy: hash the prompt instead of storing it
# ─────────────────────────────────────────────────────────────────────────────
def prompt_fingerprint(text: str) -> str:
    """A short, stable hash of the prompt — safe to log in production."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def safe_truncate(text: str, max_chars: int = 200) -> str:
    """Sometimes you DO want a sample of the prompt for debugging.
    Truncate aggressively and never log full text in production."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"…[truncated {len(text) - max_chars} chars]"


# ─────────────────────────────────────────────────────────────────────────────
# 3. The instrumented LLM call (provider-agnostic stub)
# ─────────────────────────────────────────────────────────────────────────────
def call_llm(
    provider: str,
    model: str,
    prompt: str,
    *,
    temperature: float = 0.7,
    max_tokens: int = 512,
    log_content: bool = False,        # gated via env in production
) -> dict:
    """Make an LLM call and log the right fields."""
    call_id = f"llm_{uuid.uuid4().hex[:10]}"
    structlog.contextvars.bind_contextvars(
        llm_call_id=call_id,
        provider=provider,
        model=model,
    )

    log.info(
        "llm_call_started",
        prompt_fingerprint=prompt_fingerprint(prompt),
        prompt_chars=len(prompt),
        temperature=temperature,
        max_tokens=max_tokens,
        # Only log content under an explicit flag (think PII / secrets)
        **({"prompt_sample": safe_truncate(prompt)} if log_content else {}),
    )

    t0 = time.perf_counter()
    try:
        # ─── Mock the actual API call ─────────────────────────────────────
        time.sleep(random.uniform(0.05, 0.25))
        input_tokens  = max(1, len(prompt) // 4)        # ~4 chars per token
        output_tokens = random.randint(50, 300)
        finish_reason = random.choice(
            ["stop", "stop", "stop", "length", "tool_calls"]
        )
        completion = "[mock LLM response of length " f"{output_tokens}]"

        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        cost = estimate_cost_usd(model, input_tokens, output_tokens)

        # ─── THE log line that lets you debug at 2 AM ────────────────────
        log.info(
            "llm_call_succeeded",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_usd=cost,
            finish_reason=finish_reason,
            latency_ms=latency_ms,
            **({"completion_sample": safe_truncate(completion)}
               if log_content else {}),
        )

        # ─── Special warnings ────────────────────────────────────────────
        if finish_reason == "length":
            log.warning(
                "llm_response_truncated",
                hint="The model hit its max_tokens limit before finishing.",
            )
        if cost > 0.10:
            log.warning("llm_call_expensive", cost_usd=cost)

        return {
            "completion": completion,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "finish_reason": finish_reason,
            "cost_usd": cost,
            "latency_ms": latency_ms,
        }

    except Exception:
        log.exception(
            "llm_call_failed",
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        )
        raise
    finally:
        structlog.contextvars.clear_contextvars()


# ─────────────────────────────────────────────────────────────────────────────
# 4. Demos
# ─────────────────────────────────────────────────────────────────────────────
def section(title: str) -> None:
    print("\n" + "─" * 70)
    print(title)
    print("─" * 70)


def demo_normal_calls() -> None:
    section("1. Normal calls — what you should see in steady-state")
    prompts = [
        ("anthropic", "claude-sonnet-4-6", "What is the capital of France?"),
        ("openai",    "gpt-4o-mini",       "Summarize: " + "lorem ipsum " * 50),
        ("anthropic", "claude-haiku-4-5",  "Write a haiku about logging."),
    ]
    for provider, model, prompt in prompts:
        call_llm(provider, model, prompt)


def demo_pitfalls() -> None:
    section("2. Pitfalls — events you want to ALARM on")
    # Force a "length" finish_reason by tweaking the seed
    random.seed(7)
    call_llm("openai", "gpt-4o", "Write a 10000-word essay about cats")

    # Force an expensive call
    expensive_prompt = " ".join(["analyze this"] * 50_000)
    call_llm("anthropic", "claude-opus-4-7", expensive_prompt)


def demo_minimum_fields() -> None:
    section("3. The minimum field set — per OpenTelemetry GenAI conventions")
    print("""
  Every LLM call should log these fields (mapped to OTel GenAI names):

     provider          (gen_ai.system)            → anthropic / openai / vertex_ai
     model             (gen_ai.request.model)     → claude-sonnet-4-6 / gpt-4o
     input_tokens      (gen_ai.usage.input_tokens)
     output_tokens     (gen_ai.usage.output_tokens)
     finish_reason     (gen_ai.response.finish_reason) → stop / length / tool_calls
     temperature       (gen_ai.request.temperature)
     latency_ms        (custom — duration of the call)
     cost_usd          (custom — your finops signal)

  Optionally (gated by env flag, e.g. OTEL_GENAI_CAPTURE_CONTENT=true):
     prompt_sample     (gen_ai.prompt)
     completion_sample (gen_ai.completion)

  Example 10 wires these into actual OpenTelemetry spans.
  Example 11 sends them to Langfuse for visual tracing.
""")


def takeaways() -> None:
    section("Takeaways")
    print("""
  ✅ Treat every LLM call like an API call AND a billing event.
     Log tokens (in/out), latency, finish_reason, AND estimated cost.

  ✅ Hash prompts by default. Log full content only under an explicit
     env flag (think PII, prompt-injection vectors, customer data).

  ✅ Special-case these events:
     • finish_reason == "length"  → truncated; user got incomplete answer
     • cost > some threshold      → finops alert
     • latency > p99              → user-visible slowness
     • tool_calls finish_reason   → log which tool & args (for agent debug)

  ❌ Don't roll your own dashboards from these logs alone. Plug the data
     into a real LLM observability platform (see example 11).

  💡 In 2026, the de-facto standard is OpenTelemetry's GenAI semantic
     conventions. Use those field names so you can swap backends without
     rewriting instrumentation.
""")


def main() -> None:
    print("=" * 70)
    print("LOGGING HANDBOOK — STEP 09: BASIC LLM CALL LOGGING")
    print("=" * 70)
    demo_normal_calls()
    demo_pitfalls()
    demo_minimum_fields()
    takeaways()


if __name__ == "__main__":
    main()
