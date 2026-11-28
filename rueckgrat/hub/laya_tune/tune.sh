#!/bin/sh
# runs tune.py in the hub image with the current code, from anywhere. LAYA_DECIDE=host:port picks the laya node
# progress goes to stderr, live: python -u, PYTHONUNBUFFERED=1, and docker -t when stdout is a terminal.
# stdout and stderr are not redirected.
HUB="$(cd "$(dirname "$0")/.." && pwd)"
TTY=
[ -t 1 ] && TTY=-t
exec docker run --rm $TTY --network host \
  -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONUNBUFFERED=1 -e LAYA_DECIDE -e LLM_CHAT -e IMAGE_NODE -e TTS_NODE \
  -v "$HUB/app:/hub/app" -v "$HUB/../chat/app/common:/hub/app/common:ro" -v "$HUB/../config:/hub/config:ro" -v "$HUB/laya_tune:/hub/laya_tune" \
  -w /hub --entrypoint python rueckgrat-hub -u -m laya_tune.tune "$@"
