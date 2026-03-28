#!/bin/bash

caddy trust

source .venv/bin/activate
python -c "from app.main import main; main()"