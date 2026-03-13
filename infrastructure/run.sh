#!/bin/bash

if systemctl is-active --quiet Rueckgrat_infrastructure.service; then
    sudo systemctl stop Rueckgrat_infrastructure.service
fi

source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 7346