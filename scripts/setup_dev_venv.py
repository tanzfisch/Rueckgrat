#!/usr/bin/env python3

import os
import subprocess
from pathlib import Path

ROOT = Path(".")

def create_venv(service_path):
    venv_path = service_path / ".venv"
    requirements = service_path / "requirements.txt"

    print(f"setup {service_path}")

    if not venv_path.exists():
        subprocess.run(["python3", "-m", "venv", str(venv_path)])

    pip = venv_path / "bin" / "pip"

    subprocess.run([str(pip), "install", "--upgrade", "pip"])

    if requirements.exists():
        subprocess.run([str(pip), "install", "-r", str(requirements)])

def main():
    for path in ROOT.rglob("requirements.txt"):
        create_venv(path.parent)

if __name__ == "__main__":
    main()
