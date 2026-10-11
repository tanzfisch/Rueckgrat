import subprocess
from pathlib import Path
import uuid
import os
import re
import argparse
import tempfile
import platform
import shlex

from app.utils import Hub
from app.common import get_logger
logger = get_logger()


def cleanup_for_speech(text):
    text = text.replace("*", "")
    text = re.sub(r"\*[^*]+\*|\([^)]*\)|\[[^\]]+\]", "", text)
    text = re.sub(r'https?://\S+|www\.\S+', '', text).strip()
    return re.sub(r'\[IMAGE:[^\]]*\]', '', text).strip()


def play(wav_file: str):
    logger.debug("playback speech")
    if platform.system() == "Windows":
        import winsound
        winsound.PlaySound(wav_file, winsound.SND_FILENAME)
    else:
        command_aplay = ["aplay", wav_file]
        logger.debug(f"run: {shlex.join(command_aplay)}")
        subprocess.run(command_aplay, check=False)


def run_speech(text, voice):
    wav = Hub.tts(text, voice)
    if not wav:
        logger.error("failed to get speech from hub")
        return

    output_file = os.path.join(tempfile.gettempdir(), f"chat_speech_{uuid.uuid4()}.wav")
    try:
        Path(output_file).write_bytes(wav)
        play(output_file)
    except Exception as e:
        logger.error(f"failed to playback speech: {e}")
    finally:
        logger.debug("delete speech")
        Path(output_file).unlink(missing_ok=True)


def parse_args():
    parser = argparse.ArgumentParser(description="fetch speech from the hub and play it")

    parser.add_argument("--text", type=str, required=True, help="Text input")
    parser.add_argument("--voice", type=str, default="", help="reference voice id, empty = default voice")
    parser.add_argument("--hub-url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--cert", required=True)

    return parser.parse_args()


if __name__ == "__main__":
    if platform.system() != "Windows":
        os.setpgrp()

    args = parse_args()

    # this runs in its own process, so set up the Hub connection data here
    Hub.url = args.hub_url
    Hub.access_token = args.token
    Hub.server_cert = args.cert or False

    run_speech(cleanup_for_speech(args.text), args.voice)
