#!/usr/bin/env bash
set -euo pipefail

# Helper: print usage and exit
usage() {
    echo "Usage: $0 <slug> [company name]" >&2
    exit 1
}

# Arguments
SLUG="${1:-}"
COMPANY_NAME="${2:-}"

if [[ -z "$SLUG" ]]; then
    usage
fi

# Validate slug format first
if [[ ! "$SLUG" =~ ^[a-z0-9][a-z0-9-]{1,30}$ ]]; then
    echo "Error: slug must match ^[a-z0-9][a-z0-9-]{1,30}$" >&2
    exit 2
fi

# Validate required tools (docker only needed if we will run it)
for cmd in openssl python3; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "Error: $cmd is required but not installed." >&2
        exit 1
    fi
done

# If we are going to bring up containers, ensure docker is present and compose works
if [[ "${SKIP_UP:-0}" != "1" ]]; then
    if ! command -v docker >/dev/null 2>&1; then
        echo "Error: docker is required but not installed." >&2
        exit 1
    fi
    # docker compose is a subcommand; verify it works
    if ! docker compose version >/dev/null 2>&1; then
        echo "Error: docker compose is required but not installed." >&2
        exit 1
    fi
fi

# Paths
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="${BASE_DIR}/deployments/${SLUG}"
ENV_FILE="${DEPLOY_DIR}/.env"

if [[ -e "$ENV_FILE" ]]; then
    echo "Error: deployment for '$SLUG' already exists at $ENV_FILE" >&2
    exit 1
fi

# Generate secrets
DB_PASSWORD="$(openssl rand -hex 32)"
JWT_SECRET="$(openssl rand -hex 32)"
COMPANY_ID="$(python3 -c 'import uuid, sys; sys.stdout.write(str(uuid.uuid4()))')"
ADMIN_EMAIL="admin@${SLUG}.local"
ADMIN_PASSWORD="$(openssl rand -hex 12)"

# Determine API port
START_PORT=8100
API_PORT=$START_PORT

# Gather used ports from existing .env files
used_ports=()
while IFS= read -r file; do
    if [[ -f "$file" ]]; then
        port=$(grep -E '^API_PORT=' "$file" | cut -d= -f2)
        [[ -n "$port" ]] && used_ports+=("$port")
    fi
done < <(find "${BASE_DIR}/deployments" -type f -name .env)

# Gather ports currently listening (if ss available)
if command -v ss >/dev/null 2>&1; then
    while read -r line; do
        port=$(echo "$line" | awk -F: '{print $NF}')
        used_ports+=("$port")
    done < <(ss -ltn 2>/dev/null | awk 'NR>1 {print $4}')
fi

# Increment until free
while printf '%s\n' "${used_ports[@]}" | grep -qx "$API_PORT"; do
    ((API_PORT++))
done

# Ensure COMPANY_NAME
if [[ -z "$COMPANY_NAME" ]]; then
    COMPANY_NAME="Company ${SLUG}"
fi

# Create deployment directory
mkdir -p "$DEPLOY_DIR"

# Write .env file
cat >"$ENV_FILE" <<EOF
COMPOSE_PROJECT_NAME=rl-${SLUG}
DB_PASSWORD=${DB_PASSWORD}
JWT_SECRET=${JWT_SECRET}
COMPANY_ID=${COMPANY_ID}
COMPANY_NAME=${COMPANY_NAME}
ADMIN_EMAIL=${ADMIN_EMAIL}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
API_PORT=${API_PORT}
EOF

chmod 600 "$ENV_FILE"

# Optionally skip docker compose up
if [[ "${SKIP_UP:-0}" == "1" ]]; then
    echo "Deployment file created at $ENV_FILE (docker compose up skipped)."
    exit 0
fi

# Bring up stack
cd "$BASE_DIR"
docker compose -p rl-"${SLUG}" --env-file "$ENV_FILE" up -d --build

echo "🚀 RevenueLens deployed for '${COMPANY_NAME}'"
echo "URL: http://localhost:${API_PORT}"
echo "Admin email: ${ADMIN_EMAIL}"
echo "Password is stored in ${ENV_FILE}"
