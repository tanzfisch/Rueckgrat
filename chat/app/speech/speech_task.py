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

def run_speech_piper(text, model):
    output_file = f"/tmp/chat_speech_{uuid.uuid4()}.wav"

    try:
        subprocess.run(["piper", "--model", model, "--output_file", output_file, text],
                       check=True, capture_output=True)
        subprocess.run(["aplay", output_file], check=False)
    except Exception as e:
        print(f"Speech error: {e}", file=sys.stderr)
    finally:
        Path(output_file).unlink(missing_ok=True)

def run_speech_kokoro(text, voice):
    from pykokoro import KokoroPipeline, PipelineConfig
    from pykokoro.generation_config import GenerationConfig
    import soundfile as sf

    output_file = f"/tmp/chat_speech_{uuid.uuid4()}.wav"

    config = PipelineConfig(
        voice=voice,
        generation=GenerationConfig(lang="en-us", speed=1.0),
    )    

    pipe = KokoroPipeline(config)
    res = pipe.run(text)
    audio = res.audio
    sample_rate = 24000

    sf.write(output_file, audio, sample_rate)    

    try:    
        subprocess.run(["aplay", output_file], check=False)
    except Exception as e:
        print(f"Speech error: {e}", file=sys.stderr)
    finally:
        Path(output_file).unlink(missing_ok=True)    

def parse_args():
    parser = argparse.ArgumentParser(description="Example argument parser")

    parser.add_argument(
        "--interface",
        type=str,
        default="piper",
        help="Interface to use"
    )

    parser.add_argument(
        "--text",
        type=str,
        required=True,
        help="Text input"
    )

    parser.add_argument(
        "--voice",
        type=str,
        default="af_bella",
        help="Voice type"
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

    interface = args.interface
    text = args.text
    voice = args.voice
    model = args.model

    clean_text = cleanup_for_speech(text)

    if interface == "piper":
        run_speech_piper(clean_text, model)  
    elif interface == "kokoro":
        run_speech_kokoro(clean_text, voice)  
    else:
        print("Error: unknown interface")
    
      