#!/usr/bin/env bash
# =============================================================================
# SeaRise Europe — Compose Smoke Test
# =============================================================================
# Brings up the full local stack via docker compose and verifies every
# service reaches a healthy state within a bounded timeout. Exists to guard
# against the exact class of regression the 2026-04-13 audit uncovered:
#   - API Dockerfile missing `curl`, so the healthcheck never passes
#   - TiTiler port mapping drifted from the container's actual listen port
# Both of those would have been caught in minutes by this script.
#
# Usage (from repo root):
#   scripts/compose-smoke.sh                 # full run with teardown
#   SKIP_TEARDOWN=1 scripts/compose-smoke.sh # leave the stack running after
#
# Exit codes:
#   0  every service reached healthy and every probe responded 2xx
#   1  at least one service failed to become healthy, or a probe failed
# =============================================================================

set -euo pipefail

WAIT_TIMEOUT="${WAIT_TIMEOUT:-240}"
PROBE_TIMEOUT="${PROBE_TIMEOUT:-10}"
SKIP_TEARDOWN="${SKIP_TEARDOWN:-0}"

# Resolve repo root so the script is safe to invoke from anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

log() { printf '[compose-smoke] %s\n' "$*"; }

teardown() {
  if [[ "${SKIP_TEARDOWN}" == "1" ]]; then
    log "SKIP_TEARDOWN=1 — leaving stack running for inspection"
    return
  fi
  log "Tearing down stack"
  docker compose down --volumes --remove-orphans >/dev/null 2>&1 || true
}

dump_diagnostics() {
  log "=== docker compose ps ==="
  docker compose ps || true
  log "=== docker compose logs (tail 80 per service) ==="
  docker compose logs --tail=80 || true
}

trap 'rc=$?; if [[ $rc -ne 0 ]]; then dump_diagnostics; fi; teardown; exit $rc' EXIT

# .env.local is required by docker compose but may be absent in CI; create an
# empty one from the example if missing so the stack can start with defaults.
if [[ ! -f .env.local ]]; then
  if [[ -f .env.local.example ]]; then
    log ".env.local missing — copying .env.local.example"
    cp .env.local.example .env.local
  else
    log ".env.local and .env.local.example both missing; creating empty .env.local"
    : > .env.local
  fi
fi

log "Bringing up stack (wait timeout: ${WAIT_TIMEOUT}s)"
docker compose up -d --wait --wait-timeout "${WAIT_TIMEOUT}" --build

log "Stack healthy — running endpoint probes"

probe() {
  local name="$1" url="$2"
  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time "${PROBE_TIMEOUT}" "${url}" || true)"
  if [[ "${code}" =~ ^2[0-9][0-9]$ ]]; then
    log "  ${name}  ${url}  -> ${code}  OK"
  else
    log "  ${name}  ${url}  -> ${code}  FAIL"
    return 1
  fi
}

probe "api      " "http://localhost:8080/health"
probe "frontend " "http://localhost:3000/api/health"
probe "tiler    " "http://localhost:8000/healthz"

log "All probes passed."
