#!/usr/bin/env bash
# Run the browser tests (tests/browser) with the browser in a container and the tests on this machine.
# Needs Docker. Extra arguments go to pytest, e.g. `scripts/browser-tests.sh -k accounts`;
# `FINODE_BROWSER=webkit scripts/browser-tests.sh` runs them in WebKit, which is closest to iOS Safari.
set -euo pipefail

# Keep this in step with the playwright version pinned in pyproject.toml.
VERSION="1.55.0"
IMAGE="mcr.microsoft.com/playwright/python:v${VERSION}-noble"
PORT="${BROWSER_PORT:-3333}"
NAME="finode-browser-$$"

cd "$(dirname "$0")/.."

# The browser server listens on localhost only: it must never be reachable from outside.
docker run -d --rm --name "$NAME" --network host --ipc=host "$IMAGE" \
  sh -c "pip install -q playwright==${VERSION} && python -m playwright run-server --host 127.0.0.1 --port ${PORT}" >/dev/null
trap 'docker stop "$NAME" >/dev/null 2>&1 || true' EXIT

for _ in $(seq 1 90); do
  if (echo > "/dev/tcp/127.0.0.1/${PORT}") 2>/dev/null; then break; fi
  sleep 1
done

FINODE_BROWSER_WS="ws://127.0.0.1:${PORT}/" uv run pytest tests/browser "$@"
