import subprocess
from pathlib import Path
import uuid
import os
import re
import argparse
import tempfile
import platform
import shlex

from app.utils import Paths, Hub
from app.common import get_logger
logger = get_logger()


def cleanup_for_speech(text):
    text = text.replace("*", "")
    text = re.sub(r"\*[^*]+\*|\([^)]*\)|\[[^\]]+\]", "", text)
    text = re.sub(r'https?://\S+|www\.\S+', '', text).strip()
    return re.sub(r'\[IMAGE:[^\]]*\]', '', text).strip()


def ensure_model(model: str) -> Path:
    voices_base_path = Paths.get_voices_path()
    model_dir = Path(voices_base_path) / model
    model_file = model_dir / f"{model}.onnx"
    model_json = model_dir / f"{model}.onnx.json"

    if not model_file.exists() or not model_json.exists():
        logger.debug(f"downloading voice {model}")

        # fake Hub initialisation
        Hub.url = args.hub_url
        Hub.access_token = args.token
        Hub.server_cert = args.cert or False

        Hub.get_model(model, model_dir)

    if not model_file.exists():
        raise FileNotFoundError(f"failed to retrieve voice file for {model}")

    return model_file


def run_speech(text, model):
    model_file = ensure_model(model)

    output_file = os.path.join(
        tempfile.gettempdir(),
        f"chat_speech_{uuid.uuid4()}.wav",
    )

    try:
        command_piper = [".venv/bin/piper", "--model", str(model_file), "--output_file", output_file, text]
        logger.debug(f"run: {shlex.join(command_piper)}")
        subprocess.run(command_piper, check=True, capture_output=True)

        if not os.path.exists(output_file):
            logger.error("failed to generate speech file")
            return

        logger.debug("playback speech")
        if platform.system() == "Windows":
            import winsound
            winsound.PlaySound(output_file, winsound.SND_FILENAME)
        else:
            command_aplay = ["aplay", output_file]
            logger.debug(f"run: {shlex.join(command_aplay)}")
            subprocess.run(command_aplay, check=False)
    except Exception as e:
        logger.error(f"failed to generate and playback speech: {e}")
    finally:
        logger.debug("delete speech")
        Path(output_file).unlink(missing_ok=True)


def parse_args():
    parser = argparse.ArgumentParser(description="Example argument parser")

    parser.add_argument("--text", type=str, required=True, help="Text input")
    parser.add_argument("--model", type=str, default="en_US-hfc_male-medium.onnx", help="the model used to process speech")
    parser.add_argument("--hub-url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--cert", required=True)

    return parser.parse_args()


if __name__ == "__main__":
    if platform.system() != "Windows":
        os.setpgrp()

    args = parse_args()

    text = args.text
    model = args.model

    clean_text = cleanup_for_speech(text)
    run_speech(clean_text, model)
