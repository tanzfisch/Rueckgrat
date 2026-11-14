#!/bin/sh
# runs tune.py in the hub image with the current code, from anywhere. LAYA_DECIDE=host:port picks the laya node
HUB="$(cd "$(dirname "$0")/.." && pwd)"
exec docker run --rm --network host -e PYTHONDONTWRITEBYTECODE=1 -e LAYA_DECIDE \
  -v "$HUB/app:/hub/app" -v "$HUB/../chat/app/common:/hub/app/common:ro" -v "$HUB/laya_tune:/hub/laya_tune" \
  -w /hub --entrypoint python rueckgrat-hub -m laya_tune.tune
