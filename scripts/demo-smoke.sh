#!/usr/bin/env bash
set -euo pipefail

# Build the Docker image locally
docker build -t revenuelens:ci .

# Register cleanup trap BEFORE bringing up services
cleanup() {
  rc=$?
  if (( rc != 0 )); then
    echo "=== Demo logs (last 200 lines) ==="
    docker compose -f docker-compose.demo.yml -p rl-demo logs --tail 200
  fi
  echo "Tearing down demo..."
  docker compose -f docker-compose.demo.yml -p rl-demo down -v
  exit $rc
}
trap cleanup EXIT

# Bring up the demo stack
RL_IMAGE=revenuelens:ci docker compose -f docker-compose.demo.yml -p rl-demo up -d

# Wait for health endpoint
MAX_WAIT=300
INTERVAL=5
elapsed=0
while true; do
  if curl -s -o /dev/null -w "%{http_code}" http://localhost:${DEMO_PORT:-8765}/health | grep -q "^200$"; then
    echo "Health check passed."
    break
  fi
  elapsed=$((elapsed+INTERVAL))
  if (( elapsed > MAX_WAIT )); then
    echo "Health endpoint never became ready."
    exit 1
  fi
  sleep $INTERVAL
done

# Login (expect 303 redirect, do not follow)
COOKIE_JAR=$(mktemp)
code=$(curl -s -o /dev/null -w '%{http_code}' -c "$COOKIE_JAR" -X POST \
  -d 'email=demo@revenuelens.local' -d 'password=revenuelens-demo' \
  http://localhost:${DEMO_PORT:-8765}/login)
if [[ "$code" != "303" ]]; then
  echo "Login request returned $code, expected 303."
  exit 1
fi
# Verify login succeeded (cookie named rl_token)
if ! grep -q rl_token "$COOKIE_JAR"; then
  echo "Login cookie rl_token not set."
  exit 1
fi

# Home page contains expected text
HOME_CONTENT=$(curl -s -b "$COOKIE_JAR" http://localhost:${DEMO_PORT:-8765}/)
grep -q "leaking this month" <<<"$HOME_CONTENT" || {
  echo "Home page does not contain expected leak phrase."
  exit 1
}

# /reports endpoint must return 200 and contain "CSV"
REPORT_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" http://localhost:${DEMO_PORT:-8765}/reports)
if [[ "$REPORT_STATUS" != "200" ]]; then
  echo "/reports returned $REPORT_STATUS, expected 200."
  exit 1
fi
grep -q "CSV" <<<"$(curl -s -b "$COOKIE_JAR" http://localhost:${DEMO_PORT:-8765}/reports)" || {
  echo "/reports endpoint does not contain expected CSV text."
  exit 1
}

# /docs endpoint with query must return 200 and contain "NMB_MAX_699"
DOCS_URL="http://localhost:${DEMO_PORT:-8765}/docs?request=document+plan+NMB_MAX_699&level=analyst"
DOCS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" "$DOCS_URL")
if [[ "$DOCS_STATUS" != "200" ]]; then
  echo "/docs returned $DOCS_STATUS, expected 200."
  exit 1
fi
grep -q "NMB_MAX_699" <<<"$(curl -s -b "$COOKIE_JAR" "$DOCS_URL")" || {
  echo "/docs endpoint does not contain expected NMB_MAX_699 text."
  exit 1
}

# Summary check
curl -s -b "$COOKIE_JAR" http://localhost:${DEMO_PORT:-8765}/api/summary | python3 -c '
import json, sys
d = json.load(sys.stdin)
assert d.get("count", 0) > 0, f"count not >0: {d.get("count")}"
print("findings:", d["count"])
'

# Answer key: planted issues must all be detected
curl -s -b "$COOKIE_JAR" http://localhost:${DEMO_PORT:-8765}/api/answer-key | python3 -c '
import json, sys
d = json.load(sys.stdin)
print("seed:", d["seed"], "planted:", d["planted"], "detected:", d["detected"], "precision:", d["precision"], "recall:", d["recall"])
assert d["planted"] > 0, "no planted issues"
assert d["recall"] == 1.0, d["per_check"]
'
for page in fixes audit planted; do
  st=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" http://localhost:${DEMO_PORT:-8765}/$page)
  [[ "$st" == "200" ]] || { echo "/$page returned $st"; exit 1; }
done
curl -s -b "$COOKIE_JAR" http://localhost:${DEMO_PORT:-8765}/api/fixes | python3 -c '
import json, sys
d = json.load(sys.stdin)
items = d.get("fixes", d) if isinstance(d, dict) else d
assert len(items) > 0, "no sample fixes"
print("sample fixes:", len(items))
'
# Empty password must give a friendly 422 page, not raw JSON
body=$(curl -s -X POST -d 'email=demo@revenuelens.local' -d 'password=' http://localhost:${DEMO_PORT:-8765}/login)
grep -q "Enter your email and password" <<<"$body" || { echo "login 422 not friendly"; exit 1; }

# Self-registration: create a viewer account, then log in by username
U="smoke_$RANDOM"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST -d "username=$U" -d 'password=smoke-pass-1' -d 'confirm_password=smoke-pass-1' http://localhost:${DEMO_PORT:-8765}/register)
[[ "$code" == "303" ]] || { echo "register returned $code"; exit 1; }
body=$(curl -s -X POST -d "username=${U^^}" -d 'password=smoke-pass-1' -d 'confirm_password=smoke-pass-1' http://localhost:${DEMO_PORT:-8765}/register)
grep -q "That username is already taken" <<<"$body" || { echo "duplicate username not rejected"; exit 1; }
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST -d "email=$U" -d 'password=smoke-pass-1' http://localhost:${DEMO_PORT:-8765}/login)
[[ "$code" == "303" ]] || { echo "username login returned $code"; exit 1; }
echo "registration OK ($U)"

echo "DEMO OK"
