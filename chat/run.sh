#!/bin/bash

curl -k https://localhost

#docker cp rueckgrat-rueckgrat_caddy-1:/data/caddy/pki/authorities/local/root.crt ~/.ssh/caddy-root.crt
docker cp rueckgrat_rueckgrat_caddy_1:/data/caddy/pki/authorities/local/root.crt ~/.ssh/caddy-root.crt

source .venv/bin/activate
PYTHONPATH=.. python -c "from app.main import main; main()"
# python -c "from app.main import main; main()"