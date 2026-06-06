# speech_task.py
import subprocess
from pathlib import Path
import sys
import uuid
import os
import re
import argparse


def cleanup_for_speech(text):
    text = text.replace("*", "")
    text = re.sub(r"\*[^*]+\*|\([^)]*\)|\[[^\]]+\]", "", text)
    text = re.sub(r'https?://\S+|www\.\S+', '', text).strip()
    return re.sub(r'\[IMAGE:[^\]]*\]', '', text).strip()

def run_speech(text, model):
    output_file = f"/tmp/chat_speech_{uuid.uuid4()}.wav"

    try:
        subprocess.run(["piper", "--model", model, "--output_file", output_file, text],
                       check=True, capture_output=True)
        subprocess.run(["aplay", output_file], check=False)
    except Exception as e:
        print(f"Speech error: {e}", file=sys.stderr)
    finally:
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
    os.setpgrp()

    args = parse_args()

    text = args.text
    model = args.model

    clean_text = cleanup_for_speech(text)
    run_speech(clean_text, model)  
    
      