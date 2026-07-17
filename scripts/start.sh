#!/usr/bin/env bash

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_PORT="${DA_API_PORT:-8000}"
WEB_PORT="${DA_WEB_PORT:-5173}"
LOG_DIR="$ROOT_DIR/data/logs"
RUN_DIR="$ROOT_DIR/data/run"
API_LOG="$LOG_DIR/backend.log"
WEB_LOG="$LOG_DIR/frontend.log"
WORKER_LOG="$LOG_DIR/worker.log"
API_PID_FILE="$RUN_DIR/backend.pid"
WEB_PID_FILE="$RUN_DIR/frontend.pid"
WORKER_PID_FILE="$RUN_DIR/worker.pid"

log() {
    printf '[DA] %s\n' "$*"
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || {
        printf '[DA] missing required command: %s\n' "$1" >&2
        exit 1
    }
}

port_pids() {
    lsof -nP -t -iTCP:"$1" -sTCP:LISTEN 2>/dev/null || true
}

stop_pid() {
    local pid="$1"
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        for _ in 1 2 3 4 5; do
            kill -0 "$pid" 2>/dev/null || return 0
            sleep 1
        done
        kill -KILL "$pid" 2>/dev/null || true
    fi
}

clear_port() {
    local port="$1"
    local pids
    pids="$(port_pids "$port")"
    if [[ -z "$pids" ]]; then
        return 0
    fi
    while read -r pid; do
        [[ -n "$pid" ]] || continue
        log "stopping PID $pid on port $port"
        stop_pid "$pid"
    done <<< "$pids"
    if [[ -n "$(port_pids "$port")" ]]; then
        printf '[DA] port %s is still occupied\n' "$port" >&2
        return 1
    fi
}

read_pid() {
    local file="$1"
    [[ -f "$file" ]] && tr -d '[:space:]' < "$file" || true
}

stop_recorded() {
    local name="$1" file="$2"
    local pid
    pid="$(read_pid "$file")"
    if [[ -n "$pid" ]]; then
        log "stopping $name PID $pid"
        stop_pid "$pid"
    fi
    rm -f "$file"
}

start_backend() {
    clear_port "$API_PORT"
    log "starting backend on port $API_PORT"
    (
        cd "$ROOT_DIR"
        exec python -m backend.app.main
    ) >>"$API_LOG" 2>&1 &
    echo $! > "$API_PID_FILE"
}

start_frontend() {
    clear_port "$WEB_PORT"
    log "starting frontend on port $WEB_PORT"
    (
        cd "$ROOT_DIR/web"
        exec npm run dev -- --host 127.0.0.1 --port "$WEB_PORT"
    ) >>"$WEB_LOG" 2>&1 &
    echo $! > "$WEB_PID_FILE"
}

start_worker() {
    log "starting worker"
    (
        cd "$ROOT_DIR"
        exec python -m backend.app.worker_main
    ) >>"$WORKER_LOG" 2>&1 &
    echo $! > "$WORKER_PID_FILE"
}

status() {
    local api_pid web_pid worker_pid
    api_pid="$(read_pid "$API_PID_FILE")"
    web_pid="$(read_pid "$WEB_PID_FILE")"
    worker_pid="$(read_pid "$WORKER_PID_FILE")"
    printf 'backend: pid=%s port=%s %s\n' "${api_pid:--}" "$API_PORT" \
        "$( [[ -n "$api_pid" ]] && kill -0 "$api_pid" 2>/dev/null && echo running || echo stopped )"
    printf 'frontend: pid=%s port=%s %s\n' "${web_pid:--}" "$WEB_PORT" \
        "$( [[ -n "$web_pid" ]] && kill -0 "$web_pid" 2>/dev/null && echo running || echo stopped )"
    printf 'worker: pid=%s %s\n' "${worker_pid:--}" \
        "$( [[ -n "$worker_pid" ]] && kill -0 "$worker_pid" 2>/dev/null && echo running || echo stopped )"
}

start() {
    require_command lsof
    require_command python
    require_command npm
    mkdir -p "$LOG_DIR" "$RUN_DIR"
    start_backend
    start_frontend
    start_worker
    sleep 2
    if [[ -n "$(port_pids "$API_PORT")" && -n "$(port_pids "$WEB_PORT")" \
        && -n "$(read_pid "$WORKER_PID_FILE")" ]] \
        && kill -0 "$(read_pid "$WORKER_PID_FILE")" 2>/dev/null; then
        log "backend, frontend, and worker started"
        status
    else
        printf '[DA] startup failed; inspect %s and %s\n' "$API_LOG" "$WEB_LOG" >&2
        return 1
    fi
}

stop() {
    require_command lsof
    stop_recorded backend "$API_PID_FILE"
    stop_recorded frontend "$WEB_PID_FILE"
    stop_recorded worker "$WORKER_PID_FILE"
    clear_port "$API_PORT"
    clear_port "$WEB_PORT"
    log "services stopped"
}

case "${1:-start}" in
    start) start ;;
    stop) stop ;;
    restart) stop; start ;;
    status) status ;;
    *)
        printf 'usage: %s [start|stop|restart|status]\n' "$0" >&2
        exit 2
        ;;
esac
