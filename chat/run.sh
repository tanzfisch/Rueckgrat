#!/bin/bash

echo "get caddy cert ..."
curl -k https://localhost/health

docker cp rueckgrat-caddy-1:/data/caddy/pki/authorities/local/root.crt ~/.ssh/caddy-root.crt

source .venv/bin/activate
PYTHONPATH=.. python -c "from app.main import main; main()"
python -c "from app.main import main; main()"