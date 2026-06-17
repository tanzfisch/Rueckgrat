#!/bin/bash

set -euo pipefail

[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt --upgrade

python -m spacy download en_core_web_sm
