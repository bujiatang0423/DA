#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root/web"

# This process-local API fixture never calls real providers or a worker.
exec env DA_E2E_FIXTURES=1 npm run dev -- --host 127.0.0.1 --port 5180
