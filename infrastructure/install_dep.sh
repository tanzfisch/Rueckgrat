#!/usr/bin/env bash

set -euo pipefail

# install python env
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

echo "Setup complete."