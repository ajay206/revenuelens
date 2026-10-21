#!/usr/bin/env bash
set -euo pipefail

# Cleanup function to bring down deployments and show logs on failure
cleanup() {
    local exit_code=$?
    for slug in acme beta; do
        env_file="deployments/${slug}/.env"
        if [[ -f "$env_file" ]]; then
            # Show recent logs if something failed
            if (( exit_code != 0 )); then
                echo "=== Logs for ${slug} (last 100 lines) ==="
                docker compose -p "rl-${slug}" --env-file "$env_file" logs --no-color --tail 100 || true
                echo "=== End logs for ${slug} ==="
            fi
            # Bring the stack down, ignore errors (include legacy-sim profile)
            docker compose -p "rl-${slug}" --env-file "$env_file" --profile legacy-sim down -v || true
        fi
    done
    exit $exit_code
}
trap cleanup EXIT

# Deploy two companies
scripts/new-company.sh acme "Acme Corp"
scripts/new-company.sh beta "Beta Ltd"

# Helper to read a value from a .env file
read_env() {
    local file=$1
    local key=$2
    grep -E "^${key}=" "$file" | cut -d= -f2-
}

# Iterate over both deployments
for slug in acme beta; do
    env_file="deployments/${slug}/.env"

    API_PORT=$(read_env "$env_file" "API_PORT")
    ADMIN_EMAIL=$(read_env "$env_file" "ADMIN_EMAIL")
    ADMIN_PASSWORD=$(read_env "$env_file" "ADMIN_PASSWORD")

    # Wait for health endpoint
    timeout=120
    elapsed=0
    interval=2
    while true; do
        if curl -fsS "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; then
            echo "✅ ${slug} API is healthy"
            break
        fi
        if (( elapsed >= timeout )); then
            echo "❌ ${slug} API did not become healthy within ${timeout}s"
            exit 1
        fi
        sleep $interval
        ((elapsed+=interval))
    done

    # ------------------------------------------------------------
    # Optional legacy billing simulator for Acme
    # ------------------------------------------------------------
    if [[ "$slug" == "acme" ]]; then
        echo "🚀 Loading legacy billing simulator for acme..."
        docker compose -p rl-acme --env-file deployments/acme/.env --profile legacy-sim run --rm legacy-sim
        if [[ $? -ne 0 ]]; then
            echo "❌ Legacy simulator failed to load for acme"
            exit 1
        fi
        echo "✅ Legacy simulator loaded for acme"

        # Assert row count in legacy-db
        ROW_COUNT=$(docker compose -p rl-acme --env-file deployments/acme/.env --profile legacy-sim exec -T legacy-db psql -U nimbus -d nimbus -tAc "select count(*) from nimbus.cust_mstr")
        if [[ "$ROW_COUNT" != "500" ]]; then
            echo "❌ Expected 500 rows in nimbus.cust_mstr, got ${ROW_COUNT}"
            exit 1
        fi
        echo "✅ Legacy DB contains expected 500 rows"
    fi

    # Login and obtain token
    token=$(curl -fsS -X POST "http://127.0.0.1:${API_PORT}/auth/login" \
        -H "Content-Type: application/json" \
        -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"}" |
        jq -r '.access_token')
    if [[ -z "$token" || "$token" == "null" ]]; then
        echo "❌ Failed to obtain token for ${slug}"
        exit 1
    fi

    # Verify /me works with own token
    http_code=$(curl -s -o /dev/null -w '%{http_code}' \
        -H "Authorization: Bearer ${token}" \
        "http://127.0.0.1:${API_PORT}/me")
    if [[ "$http_code" != "200" ]]; then
        echo "❌ /me returned $http_code for ${slug}"
        exit 1
    fi
    echo "✅ Auth works for ${slug}"

    if [[ "$slug" == "acme" ]]; then
        jar=$(mktemp)
        code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${API_PORT}/")
        [[ "$code" == "303" ]] || { echo "❌ Dashboard without login returned $code"; exit 1; }
        curl -fsS -c "$jar" -o /dev/null --data-urlencode "email=${ADMIN_EMAIL}" \
            --data-urlencode "password=${ADMIN_PASSWORD}" "http://127.0.0.1:${API_PORT}/login"
        page=$(curl -fsS -b "$jar" "http://127.0.0.1:${API_PORT}/")
        grep -q "leaking this month" <<<"$page" || { echo "❌ Dashboard did not render"; exit 1; }
        curl -fsS -b "$jar" "http://127.0.0.1:${API_PORT}/leaks/0" | grep -q "Sources" \
            || { echo "❌ Story page did not render"; exit 1; }
        echo "✅ Dashboard loads for acme"
    fi

    # Store token for later cross‑company checks
    if [[ "$slug" == "acme" ]]; then
        ACME_TOKEN=$token
        ACME_PORT=$API_PORT
    else
        BETA_TOKEN=$token
        BETA_PORT=$API_PORT
    fi
done

# Cross‑company isolation checks
# acme token on beta
code=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer ${ACME_TOKEN}" \
    "http://127.0.0.1:${BETA_PORT}/me")
if [[ "$code" != "401" ]]; then
    echo "❌ Expected 401 when using acme token on beta, got $code"
    exit 1
fi
echo "✅ Acme token rejected by Beta as expected"

# beta token on acme
code=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer ${BETA_TOKEN}" \
    "http://127.0.0.1:${ACME_PORT}/me")
if [[ "$code" != "401" ]]; then
    echo "❌ Expected 401 when using beta token on acme, got $code"
    exit 1
fi
echo "✅ Beta token rejected by Acme as expected"

# Network isolation checks
# Get container IDs
ACME_API_ID=$(docker compose -p "rl-acme" --env-file "deployments/acme/.env" ps -q api)
BETA_DB_ID=$(docker compose -p "rl-beta" --env-file "deployments/beta/.env" ps -q db)

# Get Beta DB IP
BETA_DB_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$BETA_DB_ID")

# 1. Acme API must NOT be able to reach Beta DB
if docker exec "$ACME_API_ID" python -c "import socket, sys; \
    socket.create_connection(('${BETA_DB_IP}', 5432), timeout=3)" 2>/dev/null; then
    echo "❌ Acme API can connect to Beta DB – network isolation broken"
    exit 1
fi
echo "✅ Acme API cannot connect to Beta DB (expected)"

# 2. From Acme API, hostname 'db' should resolve to its own DB, not Beta's
RESOLVED_IP=$(docker exec "$ACME_API_ID" getent hosts db | awk '{print $1}')
if [[ "$RESOLVED_IP" == "$BETA_DB_IP" ]]; then
    echo "❌ Hostname 'db' in Acme resolves to Beta DB IP"
    exit 1
fi
echo "✅ Hostname 'db' in Acme resolves to its own DB (expected)"

# 3. Positive control: Acme API can connect to its own DB
if ! docker exec "$ACME_API_ID" python -c "import socket, sys; \
    socket.create_connection(('db', 5432), timeout=3)" 2>/dev/null; then
    echo "❌ Acme API cannot connect to its own DB"
    exit 1
fi
echo "✅ Acme API can connect to its own DB (positive control)"

echo "🎉 All end‑to‑end checks passed"
