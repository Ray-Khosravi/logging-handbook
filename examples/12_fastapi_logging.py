"""
Example 12 — FastAPI Logging (request middleware + correlation IDs)
====================================================================

The full production pattern for a Python web service:

  1. ASGI middleware that runs at the EDGE for every request
  2. Generate (or accept) X-Request-Id header
  3. Bind request_id + method + path to structlog contextvars
  4. Log "request_received" and "response_sent" with status + duration
  5. Every log line inside handlers automatically inherits the context

This file gives you a self-contained FastAPI app. Run it and hit it with
curl to see the structured logs flow through.

Run:
    pip install fastapi uvicorn httpx
    uvicorn examples.12_fastapi_logging:app --reload --port 8000

Then in another terminal:
    curl http://localhost:8000/orders/42
    curl -H "X-Request-Id: my-trace-001" http://localhost:8000/orders/42
    curl http://localhost:8000/error
"""

import logging
import sys
import time
import uuid

try:
    import structlog
    from fastapi import FastAPI, HTTPException, Request
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse
except ImportError:
    print("Missing deps. Install with:")
    print("  pip install fastapi uvicorn structlog httpx")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Configure structlog for the API (JSON in prod, console in dev)
# ─────────────────────────────────────────────────────────────────────────────
def configure_logging(env: str = "dev") -> None:
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
    ]
    renderer = (
        structlog.processors.JSONRenderer() if env == "prod"
        else structlog.dev.ConsoleRenderer(colors=True)
    )
    structlog.configure(
        processors=shared + [
            structlog.processors.dict_tracebacks,
            renderer,
        ] if env == "prod" else shared + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

import os
configure_logging(env=os.getenv("LOG_ENV", "dev"))
log = structlog.get_logger("api")


# ─────────────────────────────────────────────────────────────────────────────
# 2. The middleware — runs for every request
# ─────────────────────────────────────────────────────────────────────────────
class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Trust the upstream X-Request-Id (from your LB / API gateway),
        # OR generate a fresh one.
        request_id = (
            request.headers.get("X-Request-Id")
            or f"req_{uuid.uuid4().hex[:12]}"
        )

        # Bind the request-scoped context. Every log line inside this
        # request automatically inherits these fields.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            http_method=request.method,
            http_path=request.url.path,
            client_ip=request.client.host if request.client else "-",
        )

        log.info("request_received",
                 query_string=str(request.url.query) if request.url.query else None)

        t0 = time.perf_counter()
        try:
            response = await call_next(request)
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            log.info(
                "response_sent",
                status_code=response.status_code,
                duration_ms=elapsed_ms,
            )
            # Echo the request_id back so clients can correlate too.
            response.headers["X-Request-Id"] = request_id
            return response

        except Exception:
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            log.exception("request_unhandled_error", duration_ms=elapsed_ms)
            return JSONResponse(
                status_code=500,
                content={"error": "internal_server_error",
                         "request_id": request_id},
                headers={"X-Request-Id": request_id},
            )

        finally:
            structlog.contextvars.clear_contextvars()


# ─────────────────────────────────────────────────────────────────────────────
# 3. The app
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Logging Demo API")
app.add_middleware(StructuredLoggingMiddleware)


# ─── Mock data layer ─────────────────────────────────────────────────────────
ORDERS = {
    1: {"id": 1, "user_id": 7, "total": 49.99, "status": "shipped"},
    2: {"id": 2, "user_id": 7, "total": 19.50, "status": "pending"},
    42: {"id": 42, "user_id": 99, "total": 129.00, "status": "delivered"},
}


@app.get("/")
def root():
    log.info("root_endpoint_hit")
    return {"ok": True, "message": "see /orders/{id} or /error"}


@app.get("/orders/{order_id}")
def get_order(order_id: int):
    # The request_id, method, path are all already in the context.
    # Anything we add here is in addition.
    log.info("order_lookup", order_id=order_id)

    if order_id not in ORDERS:
        log.warning("order_not_found", order_id=order_id)
        raise HTTPException(status_code=404, detail="order not found")

    order = ORDERS[order_id]
    log.info("order_returned",
             order_id=order_id,
             user_id=order["user_id"],
             status=order["status"])
    return order


@app.get("/error")
def trigger_error():
    """Demonstrates that unhandled exceptions still get fully logged."""
    log.info("error_endpoint_hit")
    # Trigger an unhandled exception
    _ = 1 / 0
    return {"unreachable": True}


# ─────────────────────────────────────────────────────────────────────────────
# 4. Helpful banner when started directly
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("This file is meant to be served by uvicorn, e.g.:")
    print("  uvicorn examples.12_fastapi_logging:app --reload --port 8000")
    print()
    print("Then in another terminal:")
    print("  curl http://localhost:8000/orders/42")
    print('  curl -H "X-Request-Id: my-trace-001" http://localhost:8000/orders/42')
    print("  curl http://localhost:8000/orders/999      # 404")
    print("  curl http://localhost:8000/error           # 500")
