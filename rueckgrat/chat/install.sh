#!/bin/bash

set -euo pipefail

# ==================== CERTIFICATE HANDLING ====================
CERT_DEST="$HOME/.ssh/rueckgrat-caddy.cert"

if [[ -n "${1:-}" ]]; then
    CERT_SRC="$1"
    echo "🔑 Installing certificate from: $CERT_SRC"
    
    mkdir -p "$HOME/.ssh"
    cp -f "$CERT_SRC" "$CERT_DEST"
    chmod 644 "$CERT_DEST"
    echo "✅ Certificate installed to $CERT_DEST"
else
    echo "ℹ️  No certificate path provided. Skipping cert install."
    echo "   You can run: ./install.sh /path/to/root.crt"
    exit 1;
fi

# ==================== PYTHON ENVIRONMENT ====================
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt --upgrade

python -m spacy download en_core_web_sm # todo forgot what this is for


