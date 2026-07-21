#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"

export DA_E2E_LOCAL=1
export DA_ENVIRONMENT=test
export DA_PROVIDER_MODE=fake
export DA_BIND_PORT="${DA_E2E_API_PORT:-18000}"
export DA_E2E_WEB_PORT="${DA_E2E_WEB_PORT:-15180}"
export DA_DATABASE_URL="${DA_E2E_DATABASE_URL:-postgresql+psycopg://da:da@127.0.0.1:5432/da_test}"
export DA_PIT_APPROVAL_SECRET="${DA_E2E_PIT_APPROVAL_SECRET:-local-e2e-pit-approval-secret-0001}"

cd "$root"
python -m alembic upgrade head
python -m backend.app.e2e_main &
api_pid=$!

cleanup() {
  kill "$api_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 100); do
  if curl --fail --silent "http://127.0.0.1:${DA_BIND_PORT}/api/v1/health/live" >/dev/null; then
    break
  fi
  if ! kill -0 "$api_pid" 2>/dev/null; then
    exit 1
  fi
  sleep 0.1
done

if ! curl --fail --silent "http://127.0.0.1:${DA_BIND_PORT}/api/v1/health/live" >/dev/null; then
  exit 1
fi

cd "$root/web"
npm run dev -- --host 127.0.0.1 --port "${DA_E2E_WEB_PORT}"
