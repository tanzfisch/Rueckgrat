#!/bin/bash

if systemctl is-active --quiet Rueckgrat_backend.service; then
    sudo systemctl stop Rueckgrat_backend.service
fi

source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 14223