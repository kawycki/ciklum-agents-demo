#!/usr/bin/env bash
# Start the whole stack locally: Temporal dev server + worker + API.
# Ctrl-C tears everything down.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo ">> starting Temporal dev server (localhost:7233, UI on :8233)"
# --db-filename persists workflow history to disk so it survives a server restart.
temporal server start-dev --db-filename ./temporal.db --log-level error >temporal.log 2>&1 &
pids+=($!)

echo ">> waiting for Temporal to accept connections"
for _ in $(seq 1 60); do
  if temporal operator namespace list >/dev/null 2>&1; then break; fi
  sleep 0.5
done

echo ">> starting worker"
uv run python -m app.worker >worker.log 2>&1 &
pids+=($!)

echo ">> starting API on http://localhost:8000"
uv run uvicorn app.api:app --host 0.0.0.0 --port 8000 >api.log 2>&1 &
pids+=($!)

echo ">> stack up. logs: temporal.log worker.log api.log  (Ctrl-C to stop)"
wait
