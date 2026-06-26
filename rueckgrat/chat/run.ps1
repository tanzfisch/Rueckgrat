.venv\Scripts\activate

$env:PYTHONPATH = ".."
python -c "from app.main import main; main()"