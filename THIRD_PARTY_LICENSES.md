# Third-Party Licenses

Rückgrat uses many open source packages, a few container images, and it points
to AI models that you download yourself. This file lists them with their
licenses.

- Rückgrat itself is under the **GNU AGPL v3 or later** (see `LICENSE.md`).
- Every package below keeps its own license. Rückgrat's licenses do not change them.
- "Version" is the version pinned in the requirements file. If nothing is pinned,
  it shows the version installed when this list was made (marked "installed"),
  or the latest on PyPI (marked "latest") if it was not installed.
- Licenses were read from the installed package metadata, PyPI, GitHub, pub.dev
  or Hugging Face. Anything we could not confirm is listed under
  "Could not verify".
- This list was made on 2 Nov 2026. It is not legal advice.

## Hub (`rueckgrat/hub`)

Docker image based on `python:3.11-slim`. Files: `requirements.txt`, `requirements_browser.txt`, `Dockerfile`.

| Package | Version | License | Source |
|---|---|---|---|
| fastapi | 0.162.0 (installed) | MIT | https://github.com/fastapi/fastapi |
| uvicorn[standard] | 0.54.0 (installed) | BSD-3-Clause | https://github.com/encode/uvicorn |
| pytest | 9.2.0 (installed) | MIT | https://github.com/pytest-dev/pytest |
| httpx | 0.28.1 (installed) | BSD-3-Clause | https://github.com/encode/httpx |
| requests | 2.34.2 (installed) | Apache-2.0 | https://github.com/psf/requests |
| argon2-cffi | 25.1.0 (installed) | MIT | https://github.com/hynek/argon2-cffi |
| python-jose | 3.5.0 (installed) | MIT | https://github.com/mpdavis/python-jose |
| caddy-python | 0.0.54 (installed) | **not stated** | https://pypi.org/project/caddy-python/ |
| websockets | 17.4 (installed) | BSD-3-Clause | https://github.com/python-websockets/websockets |
| wsproto | 1.3.2 (installed) | MIT | https://github.com/python-hyper/wsproto |
| tqdm | 4.70.1 (installed) | MPL-2.0 AND MIT | https://github.com/tqdm/tqdm |
| scikit-learn | 1.9.1 (installed) | BSD-3-Clause | https://github.com/scikit-learn/scikit-learn |
| json-repair | 0.64.2 (installed) | MIT | https://github.com/mangiucugna/json_repair |
| bs4 / beautifulsoup4 | 0.0.2 / 4.15.0 (installed) | MIT | https://www.crummy.com/software/BeautifulSoup/ |
| tldextract | 5.4.0 (installed) | BSD-3-Clause | https://github.com/john-kurkowski/tldextract |
| torch (CPU wheel) | 2.15.0+cpu (installed) | BSD-3-Clause style, with bundled parts under Apache-2.0, BSD-2-Clause and others | https://github.com/pytorch/pytorch |
| numpy | 2.4.6 (installed) | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://github.com/numpy/numpy |
| silero-vad[onnx-cpu] | 6.2.3 (installed) | MIT | https://github.com/snakers4/silero-vad |
| ddgs | ==9.16.0 | MIT | https://github.com/deedy5/ddgs |
| sqlite-vec | ==0.1.9 | MIT OR Apache-2.0 (dual) | https://github.com/asg017/sqlite-vec |
| playwright | 1.64.1 (installed) | Apache-2.0 | https://github.com/microsoft/playwright-python |
| certifi (used directly in code, comes in through requests) | 2026.10.23 (installed) | MPL-2.0 | https://github.com/certifi/python-certifi |

Downloaded by `playwright install --with-deps --only-shell chromium` while the image builds:

| Component | Version | License | Source |
|---|---|---|---|
| Chromium headless shell | build 1248 | BSD-3-Clause, plus many bundled third-party licenses | https://www.chromium.org/ |
| ffmpeg (Playwright build) | build 1013 | LGPL (unverified, see below) | https://github.com/microsoft/playwright |
| System libraries and fonts from apt (`--with-deps`) | Debian | mixed (GPL, LGPL, MIT, font licenses) | https://www.debian.org/ |

## Node (`rueckgrat/node`)

Docker image based on `python:3.11-slim`. Optional parts are installed only if that feature is turned on.
Files: `requirements_base.txt`, `requirements_decision.txt`, `requirements_embedding.txt`,
`requirements_image_gen.txt`, `requirements_stt.txt`, `requirements_tts.txt`, `Dockerfile`.

| Package | Version | License | Source | Used for |
|---|---|---|---|---|
| fastapi | 0.162.0 (installed) | MIT | https://github.com/fastapi/fastapi | base |
| uvicorn | 0.54.0 (installed) | BSD-3-Clause | https://github.com/encode/uvicorn | base |
| pytest | 9.2.0 (installed) | MIT | https://github.com/pytest-dev/pytest | base |
| httpx | 0.28.1 (installed) | BSD-3-Clause | https://github.com/encode/httpx | base |
| tqdm | 4.70.1 (installed) | MPL-2.0 AND MIT | https://github.com/tqdm/tqdm | base |
| requests | 2.34.2 (installed) | Apache-2.0 | https://github.com/psf/requests | base |
| websocket-client | 1.9.2 (installed) | Apache-2.0 | https://github.com/websocket-client/websocket-client | base |
| Pillow | 13.0.0 (installed) | MIT-CMU | https://github.com/python-pillow/Pillow | base |
| json-repair | 0.64.2 (installed) | MIT | https://github.com/mangiucugna/json_repair | base |
| websockets | 17.4 (installed) | BSD-3-Clause | https://github.com/python-websockets/websockets | base |
| torch, torchvision, torchaudio (PyTorch wheel index, CPU/CUDA/ROCm/XPU) | not pinned (latest: 2.15.0 / 0.29.2 / 2.11.1) | BSD-3-Clause style (torch also bundles Apache-2.0 and other parts); torchvision BSD; torchaudio BSD | https://github.com/pytorch | image gen, TTS, decision |
| laya | ==0.4.15 | Apache-2.0 | https://huggingface.co/convaiinnovations/laya | decision (tool detection) |
| fastembed | ==0.9.1 | Apache-2.0 | https://github.com/qdrant/fastembed | embedding |
| diffusers | not pinned (latest 0.42.1) | Apache-2.0 | https://github.com/huggingface/diffusers | image gen, TTS |
| transformers | not pinned (latest 5.22.1) | Apache-2.0 | https://github.com/huggingface/transformers | image gen, TTS |
| accelerate | not pinned (latest 1.15.0) | Apache-2.0 | https://github.com/huggingface/accelerate | image gen |
| compel | not pinned (latest 2.5.1) | MIT | https://github.com/damian0815/compel | image gen |
| peft | not pinned (latest 0.21.2) | Apache-2.0 | https://github.com/huggingface/peft | image gen |
| insightface | ==0.7.3 | MIT (code only, see Notable) | https://github.com/deepinsight/insightface | image gen (face reference) |
| onnxruntime | 1.31.1 (installed) | MIT | https://github.com/microsoft/onnxruntime | image gen |
| opencv-python-headless | not pinned (latest 5.0.0.93) | Apache-2.0 | https://github.com/opencv/opencv-python | image gen |
| Cython | not pinned (latest 3.3.1) | Apache-2.0 | https://github.com/cython/cython | image gen (build only) |
| faster-whisper | 1.2.1 (installed) | MIT | https://github.com/SYSTRAN/faster-whisper | STT |
| ctranslate2 (comes with faster-whisper, imported directly) | 4.8.4 (installed) | MIT | https://github.com/OpenNMT/CTranslate2 | STT |
| numpy | 2.4.6 (installed, STT); <2.0.0 for TTS | BSD-3-Clause and others (see Hub) | https://github.com/numpy/numpy | STT, TTS |
| chatterbox-tts | not pinned (latest 0.1.7), installed with `--no-deps` | MIT | https://github.com/resemble-ai/chatterbox | TTS |
| librosa | not pinned (latest 1.0.0) | ISC | https://github.com/librosa/librosa | TTS |
| s3tokenizer | not pinned (latest 0.3.0) | Apache-2.0 | https://github.com/xingchensong/S3Tokenizer | TTS |
| resemble-perth | not pinned (latest 1.0.1) | MIT | https://github.com/resemble-ai/Perth | TTS |
| conformer | not pinned (latest 0.3.2) | MIT | https://github.com/lucidrains/conformer | TTS |
| safetensors | not pinned (latest 0.8.0) | Apache-2.0 | https://github.com/huggingface/safetensors | TTS |
| pyloudnorm | not pinned (latest 0.2.0) | MIT | https://github.com/csteinmetz1/pyloudnorm | TTS |
| omegaconf | not pinned (latest 2.4.0) | BSD-3-Clause | https://github.com/omry/omegaconf | TTS |
| soundfile | not pinned (latest 0.14.0) | BSD-3-Clause | https://github.com/bastibe/python-soundfile | TTS |
| langid | not pinned (latest 1.1.6) | BSD-style (see LICENSE file) | https://github.com/saffsd/langid.py | TTS |

System packages: `build-essential` (GCC and friends, GPL) is added to the node image when image generation is turned on, because insightface is compiled from source.

## Chat client (`rueckgrat/chat`)

Python app built with Flet. Desktop uses `requirements_desktop.txt`, Android uses `pyproject.toml`
(and `requirements.txt` for the plain install). Versions are from `rueckgrat/chat/.venv`.

| Package | Version | License | Source | Used in |
|---|---|---|---|---|
| flet (with flet-desktop, flet-web, flet-cli from `flet[all]`) | ==1.0.4 | Apache-2.0 | https://github.com/flet-dev/flet | desktop, Android |
| flet-audio | ==1.0.4 (local patched copy in `extensions/flet_audio`) | Apache-2.0 | https://github.com/flet-dev/flet | desktop, Android |
| flet-audio-recorder | ==1.0.4 (local patched copy in `extensions/flet_audio_recorder`) | Apache-2.0 | https://github.com/flet-dev/flet | desktop, Android |
| pathvalidate | 3.3.1 (installed) | MIT | https://github.com/thombashi/pathvalidate | desktop, Android |
| websockets | 17.2 (installed) | BSD-3-Clause | https://github.com/python-websockets/websockets | desktop, Android |
| markdown | 3.11 (installed) | BSD-3-Clause | https://github.com/Python-Markdown/markdown | desktop, Android |
| pygments | 2.21.0 (installed) | BSD-2-Clause | https://github.com/pygments/pygments | desktop, Android |
| bleach | 6.4.0 (installed) | Apache-2.0 | https://github.com/mozilla/bleach | desktop, Android |
| requests | ==2.32.3 | Apache-2.0 | https://github.com/psf/requests | desktop, Android |
| urllib3 | ==2.2.3 | MIT | https://github.com/urllib3/urllib3 | desktop, Android |
| charset-normalizer | ==3.3.2 | MIT | https://github.com/jawah/charset_normalizer | desktop, Android |
| json-repair | 0.64.0 (installed) | MIT | https://github.com/mangiucugna/json_repair | desktop, Android |
| click | 8.5.0 (installed) | BSD-3-Clause | https://github.com/pallets/click | desktop, Android |
| tqdm | 4.70.1 (installed) | MPL-2.0 AND MIT | https://github.com/tqdm/tqdm | desktop, Android |
| pydantic | 2.14.0 (installed) | MIT | https://github.com/pydantic/pydantic | desktop, Android |
| certifi (used directly in code, comes in through requests) | 2026.7.22 (installed) | MPL-2.0 | https://github.com/certifi/python-certifi | desktop, Android |
| onnxruntime | 1.31.0 (installed) | MIT | https://github.com/microsoft/onnxruntime | desktop |
| sounddevice | 0.5.6 (installed) | MIT | https://github.com/spatialaudio/python-sounddevice | desktop |
| soundfile | 0.14.0 (installed) | BSD-3-Clause | https://github.com/bastibe/python-soundfile | desktop |
| pip-system-certs | 5.3 (installed) | BSD-3-Clause | https://gitlab.com/alelec/pip-system-certs | desktop |
| truststore | 0.10.4 (installed) | MIT | https://github.com/sethmlarson/truststore | desktop |

Rückgrat's own Flet extensions `flet-foreground-service` and `flet-notifications` are part of
this project (AGPL) and not third-party.

### Android app (Flutter / Dart parts inside the APK)

`flet build apk` packs these into the app. Versions are from `build/flutter/pubspec.lock`.

| Package | Version | License | Source |
|---|---|---|---|
| flet (Dart) | 1.0.4 | Apache-2.0 | https://pub.dev/packages/flet |
| serious_python (runs Python on the phone) | 5.0.0 | Apache-2.0 | https://pub.dev/packages/serious_python |
| CPython (bundled by serious_python) | 3.14.7 | PSF-2.0 | https://www.python.org/ |
| audioplayers (used by flet_audio) | 6.8.1 | MIT | https://pub.dev/packages/audioplayers |
| record (used by flet_audio_recorder) | 7.1.2 | BSD-3-Clause style | https://pub.dev/packages/record |
| flutter_foreground_task (used by flet_foreground_service) | 11.0.3 | MIT | https://pub.dev/packages/flutter_foreground_task |
| flutter_math_fork (comes with flet) | 0.7.4 | Apache-2.0 | https://pub.dev/packages/flutter_math_fork |
| KaTeX fonts (inside flutter_math_fork) | - | MIT | https://github.com/KaTeX/KaTeX |
| msgpack_dart | 1.0.1 | MIT | https://pub.dev/packages/msgpack_dart |
| package_info_plus | 9.0.1 | BSD-3-Clause | https://pub.dev/packages/package_info_plus |
| path | 1.9.1 | BSD-3-Clause | https://pub.dev/packages/path |
| path_provider | 2.1.6 | BSD-3-Clause | https://pub.dev/packages/path_provider |
| window_manager | 0.5.2 | MIT | https://pub.dev/packages/window_manager |
| cupertino_icons | 1.0.9 | MIT | https://pub.dev/packages/cupertino_icons |
| Flutter SDK and Material icons font | - | BSD-3-Clause / Apache-2.0 | https://github.com/flutter/flutter |

## Containers and installer tools

| Component | Version | License | Source | Where |
|---|---|---|---|---|
| python:3.11-slim (base image) | Python 3.11.18 on Debian | PSF-2.0 for Python; Debian packages mixed (GPL, LGPL, MIT, ...) | https://hub.docker.com/_/python | hub, node |
| caddy (base image) | latest (v2.11.7 running) | Apache-2.0 | https://github.com/caddyserver/caddy | caddy |
| cloudflare/cloudflared | latest | Apache-2.0 | https://github.com/cloudflare/cloudflared | tunnel |
| ghcr.io/ggml-org/llama.cpp:server-* | not pinned (0.8.0-dev running) | MIT | https://github.com/ggml-org/llama.cpp | LLM server |
| Docker (via get.docker.com) | - | Apache-2.0 | https://github.com/moby/moby | install.sh |
| NVIDIA Container Toolkit | - | Apache-2.0 | https://github.com/NVIDIA/nvidia-container-toolkit | install.sh (NVIDIA only) |
| git, curl, rsync, jq, alsa-utils, portaudio, python3 venv | distro packages | mixed (GPL-2.0, MIT/curl, GPL-3.0, MIT, LGPL, MIT, PSF-2.0) | your Linux distribution | install.sh, on the host only |

## Models

Models are **not shipped** with Rückgrat. `rueckgrat/node/data/registry.json` only points to
where they can be downloaded. Each model has its own license, often with extra rules on how
it may be used. The license below is what the model page on Hugging Face says.

## Voice samples (`characters/voices`)

These audio clips **are** in the repo. Details per file are in `characters/voices/voices.json`.

| Source | Files | License |
|---|---|---|
| LibriVox recordings (archive.org) | 14 | Public domain (CC0 1.0, CC Public Domain Dedication or CC PDM 1.0) |
| EARS dataset (Richter et al., Interspeech 2024), https://github.com/facebookresearch/ears_dataset | 19 | **CC BY-NC 4.0** (non-commercial, attribution required) |
| Own recording (Martin Loga) | 1 | own recording, no license stated |

