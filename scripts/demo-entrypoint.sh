#!/usr/bin/env bash
set -euo pipefail

# Wait for PostgreSQL to become ready
MAX_TRIES=60
SLEEP=2
tries=0
while ! python -c "import psycopg; psycopg.connect('${DATABASE_URL}')" 2>/dev/null; do
  tries=$((tries+1))
  if (( tries >= MAX_TRIES )); then
    echo "PostgreSQL did not become ready after ${MAX_TRIES} attempts."
    exit 1
  fi
  echo "Waiting for PostgreSQL... (${tries}/${MAX_TRIES})"
  sleep $SLEEP
done

# Run migrations and seed the demo admin user
python -m app.migrate
python -m app.seed

# Pick the demo seed: reuse the stored one on restart, else DEMO_SEED, else random
export LEGACY_DATABASE_URL="${LEGACY_DATABASE_URL:-$DATABASE_URL}"
SEED=$(python -m app.demo_pipeline seed)
echo "Demo seed: ${SEED} (set DEMO_SEED=${SEED} to reproduce this exact data set)"

# Load randomized synthetic Nimbus data (with planted leaks) into the legacy DB
python -m legacy_sim load --database-url "$LEGACY_DATABASE_URL" --seed "$SEED" --randomize

# Choose LLM implementation
if [[ -z "${GROQ_API_KEY:-}" && -z "${OPENROUTER_API_KEY:-}" && -z "${GEMINI_API_KEY:-}" ]]; then
  export RL_LLM=fake
  echo "No LLM API key provided – using fake LLM implementation."
fi

# Detect leaks, explain them, draft sample fixes/audit/report entries and grade against the answer key
python -m app.demo_pipeline run --seed "$SEED" --ground-truth-out /tmp/ground_truth.json \
  || echo "Demo pipeline failed, continuing."

# Show demo URL and credentials
DEMO_URL="http://localhost:${DEMO_PORT:-8765}"
cat <<EOF

============================================================
Demo is running at: $DEMO_URL
Login with:
  Email:    ${ADMIN_EMAIL}
  Password: ${ADMIN_PASSWORD}
These credentials are for the synthetic demo only.
============================================================

EOF

# Start the FastAPI server
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
