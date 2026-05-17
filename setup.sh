#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Logging Handbook — one-command setup
# ─────────────────────────────────────────────────────────────────────────────
# Creates a virtual environment, installs all dependencies, and prints
# instructions for running the examples and the local log stack.
#
# Usage:
#     ./setup.sh
#
# Requirements: Python 3.10+ and (optional) Docker for the Loki/Grafana stack
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# Pretty output helpers
BOLD="\033[1m"; RESET="\033[0m"; GREEN="\033[32m"; YELLOW="\033[33m"; BLUE="\033[34m"

step() { printf "\n${BOLD}${BLUE}▶ %s${RESET}\n" "$*"; }
ok()   { printf "${GREEN}✓ %s${RESET}\n" "$*"; }
warn() { printf "${YELLOW}⚠ %s${RESET}\n" "$*"; }

# ─── 1. Check Python version ─────────────────────────────────────────────
step "Checking Python version"
PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "Python 3.10+ is required but '$PY' was not found." >&2
    exit 1
fi
PY_VER=$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
ok "Found Python $PY_VER"

# ─── 2. Create venv ──────────────────────────────────────────────────────
step "Creating virtual environment (./.venv)"
if [ ! -d ".venv" ]; then
    "$PY" -m venv .venv
    ok "Created .venv"
else
    ok ".venv already exists"
fi

# Activate
# shellcheck source=/dev/null
source .venv/bin/activate
ok "Activated .venv"

# ─── 3. Install dependencies ─────────────────────────────────────────────
step "Installing dependencies from requirements.txt"
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
ok "Dependencies installed"

# ─── 4. Optional Docker check ────────────────────────────────────────────
step "Checking for Docker (optional, for the local log stack)"
if command -v docker >/dev/null 2>&1; then
    ok "Docker found — you can run the local Loki + Grafana stack"
    DOCKER_AVAILABLE=1
else
    warn "Docker not found — that's fine. Examples still work without it."
    DOCKER_AVAILABLE=0
fi

# ─── 5. Print quickstart instructions ────────────────────────────────────
cat <<EOF

${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}
${BOLD}  🚀  Setup complete — what to try next${RESET}
${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}

  Activate the venv in any new shell:
      ${BLUE}source .venv/bin/activate${RESET}

  Run the examples (each is self-contained):

      ${BLUE}python examples/01_logging_basics.py${RESET}        # stdlib done right
      ${BLUE}python examples/02_structured_logging.py${RESET}    # JSON output
      ${BLUE}python examples/03_structlog_production.py${RESET}  # production setup
      ${BLUE}python examples/04_loguru_quickstart.py${RESET}     # loguru alternative
      ${BLUE}python examples/05_correlation_ids.py${RESET}       # request IDs
      ${BLUE}python examples/06_data_pipeline_logging.py${RESET} # data pipelines
      ${BLUE}python examples/07_ml_training_mlflow.py${RESET}    # ML training
      ${BLUE}python examples/08_ml_inference_logging.py${RESET}  # ML inference
      ${BLUE}python examples/09_llm_basic_logging.py${RESET}     # LLM calls
      ${BLUE}python examples/10_llm_opentelemetry.py${RESET}     # OTel GenAI
      ${BLUE}python examples/11_langfuse_integration.py${RESET}  # Langfuse

  Run the FastAPI demo (in two terminals):

      Terminal 1:  ${BLUE}uvicorn examples.12_fastapi_logging:app --reload --port 8000${RESET}
      Terminal 2:  ${BLUE}curl http://localhost:8000/orders/42${RESET}

EOF

if [ "$DOCKER_AVAILABLE" -eq 1 ]; then
cat <<EOF
  Spin up the local Loki + Grafana stack:

      ${BLUE}docker compose up -d${RESET}
      Open Grafana:  ${BLUE}http://localhost:3000${RESET}  (admin / admin)

  To send your example logs into Loki:

      mkdir -p logs
      python examples/03_structlog_production.py 2>&1 | tee logs/app.log
      # Now query in Grafana → Explore: {service="logging-handbook"}

EOF
fi

cat <<EOF
  Read the full guide:  ${BLUE}README.md${RESET}

${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}
EOF
