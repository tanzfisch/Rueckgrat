# speech_task.py
import subprocess
from pathlib import Path
import sys
import uuid
import os
import re
import argparse
import tempfile
import platform

from common import Logger
logger = Logger(__name__).get_logger()


def cleanup_for_speech(text):
    text = text.replace("*", "")
    text = re.sub(r"\*[^*]+\*|\([^)]*\)|\[[^\]]+\]", "", text)
    text = re.sub(r'https?://\S+|www\.\S+', '', text).strip()
    return re.sub(r'\[IMAGE:[^\]]*\]', '', text).strip()


def run_speech(text, model):
    output_file = os.path.join(
        tempfile.gettempdir(),
        f"chat_speech_{uuid.uuid4()}.wav"
    )

    try:
        logger.debug(f"generate speech: {output_file}")
        subprocess.run(["piper", "--model", model, "--output_file", output_file, text],
                       check=True, capture_output=True)

        if not os.path.exists(output_file):
            logger.error("failed to generate speech file")
            return

        logger.debug(f"playback speech")
        if platform.system() == "Windows":
            import winsound
            winsound.PlaySound(output_file, winsound.SND_FILENAME)
        else:
            subprocess.run(["aplay", output_file], check=False)
    except Exception as e:
        logger.error(f"Speech error: {e}", file=sys.stderr)
    finally:
        logger.debug(f"delete speech")
        Path(output_file).unlink(missing_ok=True)


def parse_args():
    parser = argparse.ArgumentParser(description="Example argument parser")

    parser.add_argument(
        "--text",
        type=str,
        required=True,
        help="Text input"
    )

    parser.add_argument(
        "--model",
        type=str,
        default="en_US-hfc_male-medium.onnx",
        help="the model used to process speech"
    )

    return parser.parse_args()


if __name__ == "__main__":
    if platform.system() != "Windows":
        os.setpgrp()

    args = parse_args()

    text = args.text
    model = args.model

    clean_text = cleanup_for_speech(text)
    run_speech(clean_text, model)
