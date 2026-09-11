if (-not (Test-Path .venv)) {
    python -m venv .venv
}

.venv\Scripts\activate

pip install -r requirements.txt --upgrade
