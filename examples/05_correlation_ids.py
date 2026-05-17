"""
Example 05 — Correlation IDs across services
=============================================

In a distributed system, one user click might touch:
  load balancer → API → auth service → database → cache → LLM service

If each writes 4 log lines, you have 32 unrelated log entries. Without a
correlation ID, debugging is archaeology, not engineering.

This file demonstrates THE production pattern:

  1. Generate a request_id at the system edge
  2. Bind it to contextvars (works across async tasks, threads)
  3. Inject it into every log line automatically
  4. Propagate it via HTTP headers to downstream services

We use structlog throughout — but the pattern works with any modern logger.

Run:
    python examples/05_correlation_ids.py
"""

import asyncio
import logging
import uuid
from contextvars import ContextVar

import structlog


# ─────────────────────────────────────────────────────────────────────────────
# 1. Define the contextvars that we'll thread through everything
# ─────────────────────────────────────────────────────────────────────────────
# ContextVar values are isolated per asyncio task / thread, so concurrent
# requests never see each other's IDs.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
user_id_var:    ContextVar[str] = ContextVar("user_id",    default="-")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Configure structlog to merge contextvars into every event
# ─────────────────────────────────────────────────────────────────────────────
structlog.configure(
    processors=[
        # The magic line: pulls all bound contextvars into the event dict.
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.dev.ConsoleRenderer(colors=False),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)
log = structlog.get_logger()


def section(title: str) -> None:
    print("\n" + "─" * 70)
    print(title)
    print("─" * 70)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Edge: where the request_id is born
# ─────────────────────────────────────────────────────────────────────────────
def begin_request(headers: dict) -> str:
    """Mimics what a FastAPI middleware would do at the edge.

    Either trust the upstream's X-Request-Id, or generate a fresh one.
    """
    rid = headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex[:12]}"
    request_id_var.set(rid)
    structlog.contextvars.bind_contextvars(request_id=rid)
    return rid


def end_request() -> None:
    structlog.contextvars.clear_contextvars()


# ─────────────────────────────────────────────────────────────────────────────
# 4. "Services" we'll call in sequence — none of them know about request_id
# ─────────────────────────────────────────────────────────────────────────────
async def auth_service(token: str) -> int:
    log.info("auth_check_started", token_prefix=token[:6])
    await asyncio.sleep(0.005)
    user_id = 42
    structlog.contextvars.bind_contextvars(user_id=user_id)
    log.info("auth_check_succeeded")
    return user_id


async def db_service(user_id: int) -> dict:
    log.info("db_query_started", table="users", where=f"id={user_id}")
    await asyncio.sleep(0.010)
    log.info("db_query_finished", rows=1, duration_ms=10)
    return {"id": user_id, "plan": "pro"}


async def llm_service(prompt: str) -> str:
    # The downstream service receives the request_id via an HTTP header
    # and re-binds it, so its own logs also carry the same correlation ID.
    log.info("llm_call_started", model="claude-sonnet-4-5", prompt_chars=len(prompt))
    await asyncio.sleep(0.020)
    log.info("llm_call_finished", input_tokens=42, output_tokens=128, duration_ms=20)
    return "Hello!"


# ─────────────────────────────────────────────────────────────────────────────
# 5. The handler — one request flowing through everything
# ─────────────────────────────────────────────────────────────────────────────
async def handle_request(headers: dict, body: dict) -> dict:
    rid = begin_request(headers)
    log.info("request_received", method="POST", path="/chat")

    try:
        user_id = await auth_service(body["token"])
        user    = await db_service(user_id)
        reply   = await llm_service(body["prompt"])
        log.info("response_sent", status=200, user_plan=user["plan"])
        return {"reply": reply, "request_id": rid}
    except Exception:
        log.exception("request_failed", status=500)
        raise
    finally:
        end_request()


# ─────────────────────────────────────────────────────────────────────────────
# 6. Run two concurrent requests to show contextvars are isolated
# ─────────────────────────────────────────────────────────────────────────────
async def run_concurrent_demo() -> None:
    section("1. Two concurrent requests — context stays isolated")

    requests = [
        ({"X-Request-Id": "req_alice_001"},
         {"token": "tok_alice", "prompt": "What's the weather?"}),
        ({"X-Request-Id": "req_bob_002"},
         {"token": "tok_bob",   "prompt": "Write me a haiku."}),
    ]

    await asyncio.gather(*(handle_request(h, b) for h, b in requests))

    print("\n  → Every line above carries request_id={alice|bob} automatically,")
    print("  → even though the service functions never received the ID as arg.")
    print("  → Filtering by request_id in your log store reconstructs each story.")


# ─────────────────────────────────────────────────────────────────────────────
# 7. Educational summary
# ─────────────────────────────────────────────────────────────────────────────
def takeaways() -> None:
    section("Takeaways")
    print("""
  ✅ The three rules of correlation:

     1. GENERATE the request_id at the edge (or trust X-Request-Id from
        your load balancer / API gateway).

     2. BIND it to a ContextVar (and into structlog's contextvars) so
        every log call inside that request automatically includes it.

     3. PROPAGATE it downstream via the X-Request-Id (or W3C `traceparent`)
        HTTP header so other services log under the same ID.

  ✅ Why contextvars (and not thread-locals)?
     • They work seamlessly with asyncio (each task gets its own copy)
     • They work with threading too
     • They're the modern, recommended primitive

  ✅ If you adopt OpenTelemetry, replace request_id with trace_id/span_id.
     structlog has community processors to inject these automatically.

  💡 Recommendation:
     Always include AT LEAST `request_id`. Add `user_id` when known.
     Add `trace_id`/`span_id` when running OpenTelemetry.

  Next: example 06 applies these patterns to a real data pipeline.
""")


def main() -> None:
    print("=" * 70)
    print("LOGGING HANDBOOK — STEP 05: CORRELATION IDs")
    print("=" * 70)

    asyncio.run(run_concurrent_demo())
    takeaways()


if __name__ == "__main__":
    main()
