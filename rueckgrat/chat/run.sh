#!/bin/bash

source .venv/bin/activate
PYTHONPATH=.. python -c "from app.main import main; main()"
python -c "from app.main import main; main()"