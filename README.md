# <img src="logo.png" width="50" alt="Logo">ückgrat

**AI tools running private and local.**

**Status**: Early stage. Do not use in production.
 * many features still missing
 * instability expected
 * Author has no clue about security, auth, certs, or Caddy. Help welcome.
 * See the [changelog](https://github.com/tanzfisch/Rueckgrat/blob/master/changelog.md) for more details.

AGPL-3.0. Commercial licensing: see `COMMERCIAL_LICENSE.md`.

## Features

Rückgrat is a hub/node backend plus a user-facing companion chat client. Quality depends on the models you run.

### Backend

- Linux only
    * Debian ✅
    * Ubuntu (not tested)
    * Fedora (not tested)
    * Arch (not tested)
    * openSUSE (not tested)
- full conrol over which hardware is used
- no third-party AI APIs used
- multi-host: one **hub** (control + DB + STT) and one or more **nodes** (workers)
- Caddy for HTTPS
- **llama.cpp** server in Docker (`text_to_text`)
- image generation via Diffusers / SDXL (`text_to_image`)
- STT on the hub: Silero VAD + faster-whisper
- GPU: NVIDIA and AMD. Intel GPUs are not supported/tested.
- AI tools
    - **websearch** — search the web when requested or needed
    - **generate_image** — generate an image on request or on its own
    - **take_photo** — generate a photo of self, user, or both from current context

Use at least a 24B LLM (e.g. `cognitivecomputations_Dolphin-Mistral-24B-Venice-Edition-Q6_K_L`). Smaller models fail JSON/tool calls often.

### Chat Client

- native Linux and Windows
- optional Docker chat (known issues: no audio, autostart unreliable)
- chat with a locally installed LLM
- in-chat image generation
- client-side TTS via Piper
- code highlighting
- contacts, character templates, character-creation wizard, settings

## Planned

- rewrite the client for mobile, then drop Docker chat
- character consistency in images
- Flux support
- some more productivity oriented frontend
- agents

## Getting Started

### Linux

```bash
wget https://raw.githubusercontent.com/tanzfisch/Rueckgrat/master/install.sh
chmod +x install.sh
./install.sh
```

The installer supports multi-host deploy, component selection (chat native/Docker, hub, node, llama-server, ImageGen), clean/fresh builds (`-f`), and the distros listed above. Selected Docker services are started; the native chat client is not.

Requires sudo on every target host, same username.

Native chat:

```bash
cd rueckgrat/chat
./run.sh
```

#### Alternatives

Clone, then install:

```bash
git clone https://github.com/tanzfisch/Rueckgrat.git
cd Rueckgrat
./install.sh
```

Config-driven install. Walk the installer until it recaps the plan; the written file is `rueckgrat/config/infrastructure.json`. Example:

```bash
./install.sh -c rueckgrat/config/config_example.json -y
```

Useful flags: `-y` non-interactive, `-c FILE` config, `-s` rsync-only sync, `-f` clean rebuild, `--key` / `--cert` Caddy files, `-h` help.

### Windows

Native client only:

```powershell
git clone https://github.com/tanzfisch/Rueckgrat.git
cd Rueckgrat\rueckgrat\chat
.\install.ps1
.\run.ps1
```

## Development

1. install once (creates `rueckgrat/config/infrastructure.json`)
2. change code
3. optional: `./install.sh -s` to rsync this tree to remote hosts from that config
4. run `./dev.sh` on each machine to restart that host's containers and follow logs
5. run `./stop.sh` to stop all docker services

## Models

Edit `rueckgrat/node/data/registry.json` to add models. Copy an existing entry for reference.

Manage installs with the registry manager.

## Registry manager

Needs to run inside a node container:

```bash
cd rueckgrat
docker compose run --entrypoint /bin/bash --rm node
```

```bash
python -m app.registry_manager list -v
python -m app.registry_manager list -v -t llm    # llm | image | tts | stt
python -m app.registry_manager install MODELNAME
python -m app.registry_manager nodes
```

Models live under `/var/lib/Rueckgrat/models` on the host.

## Troubleshoot & FAQ

### Logs for hub, node, caddy, llama-server

`docker logs -f CONTAINER`

Container names: `rueckgrat_hub`, `rueckgrat_node`, `rueckgrat_caddy`, `rueckgrat_llama_server`, `rueckgrat_chat`.

### Chat logs in Docker

`logs/chat.log` and `logs/autostart.log`.

### Native chat logs

Stdout only (`./run.sh` also writes `logs/chat.log` if that path exists).

## Special thanks to

✨ **Gebrielle** 🎉

🎊 **spychodelics** 🚀

👶 **Naomi** 🍼