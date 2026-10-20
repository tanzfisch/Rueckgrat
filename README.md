# <img src="logo.png" width="50" alt="Logo">ückgrat

**AI tools running private and local.**

**Status**: Early stage. Do not use in production.

- many features still missing
- instability expected
- Author has no clue about security, auth, certs, or Caddy. Help welcome.
- See the [changelog](https://github.com/tanzfisch/Rueckgrat/blob/master/changelog.md) for more details.

## Features

Rückgrat is a backend (hub and nodes) plus a user-facing companion chat client. Quality of the experience depends on the models you run which is limited by the hardware you have available.

### Backend

- runs on Linux only
    - Debian ✅
    - Ubuntu (not tested)
    - Fedora (not tested)
    - Arch (not tested)
    - openSUSE (not tested)
- multi-host: one **hub** (control + DB + STT) and one or more **nodes** (workers)
- Caddy for HTTPS (subject to change)
- nodes
    - llama.cpp
    - image generation via Diffusers / SDXL
    - STT using Silero VAD + faster-whisper
    - TTS using Chatterbox
- GPU: NVIDIA and AMD. Intel GPUs are not supported/tested.
- AI tools
    - **websearch** — search the web when requested or needed
    - **generate_image** — generate an image on request or on its own
    - **take_photo** — generate a photo of self, user, or both from current context

### Chat client

- running on Linux, Android (iOS and Windows not tested)
- chat with a locally installed LLM
- in-chat image generation based on use prompt
- self image generation. Like taking a picture of self based on current context.
- code highlighting
- contacts, character templates, character-creation wizard, settings

## Screenshots

Some screenhots of the chat app because people like to see images even if crap.

<img src="docs/screenshots/contact_list.png" width="200" alt="contact list"> <img src="docs/screenshots/chat_code.png" width="200" alt="code in chat"> <img src="docs/screenshots/chat_image.png" width="200" alt="image gen in chat"> <img src="docs/screenshots/chat_foto.png" width="200" alt="self image in chat">

## Hardware requirements

About 40 GB of VRAM in total is a comfortable target for running the stack with useful models. It can sit in one machine or be spread over several cards or machines.

| Component | VRAM |
| --- | --- |
| LLM (default model: Dolphin Venice Edition) | ~22 GB |
| Image generation | ~12 GB |
| Text to speech | ~3-4 GB |
| **Total** | **~37-38 GB, rounded up to 40 GB** |

Some models also run with less VRAM if they can offload into system RAM, but expect them to be slower.

For reference, the dev setup runs on three machines: hub and LLM on an AMD RX 7900 XTX (24 GB, ROCm), TTS on an NVIDIA RTX 3080 (10 GB, CUDA) and image generation on an AMD RX 9060 XT (16 GB, ROCm).

## Getting started

### Linux

```bash
wget https://raw.githubusercontent.com/tanzfisch/Rueckgrat/master/install.sh
chmod +x install.sh
./install.sh
```

The installer supports multi-host deploy, component selection (native chat, hub, node, llama-server, ImageGen, TTS, STT), an optional Cloudflare tunnel and an optional Android APK of the chat client.

**Note: Every machine needs sudo with the same username, plus `ssh` and `rsync`; target hosts must also run an SSH server:**

#### What the installer does

1. Asks the setup questions and saves them to `rueckgrat/config/infrastructure.json`.
2. Deploys the chosen components to each host.
3. Optionally sets up the Cloudflare tunnel and builds the Android APK.

Run chat:

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

Reinstall from a saved config, without the setup questions:

```bash
./install.sh -c rueckgrat/config/config_example.json -y
```

#### Android APK

The setup question "Would you like to build an Android APK for the chat client? (y/N)" is saved as `chat_apk` in the config (default `false`; configs without the key count as `false`):

```json
{
  "hosts": [ ... ],
  "cloudflare": { "enabled": false },
  "users": [],
  "chat_apk": true
}
```

To only build the APK, without installing anything or asking questions, use `-a` / `--apk` (it ignores `chat_apk`):

```bash
./install.sh -a
adb install -r dist/rueckgrat-chat.apk
```

The APK lands in `dist/rueckgrat-chat.apk` and is unsigned. On first use `flet` downloads Flutter, a JDK and the Android SDK (several GB). The app trusts the hub through the Caddy certificate, so run a normal install first, which creates it.

For all options run `./install.sh -h`.

### Windows

Native client only:

```powershell
git clone https://github.com/tanzfisch/Rueckgrat.git
cd Rueckgrat\rueckgrat\chat
.\install.ps1
.\run.ps1
```

## Development

1. install once manually with your settings
2. change code
3. optional: `./install.sh -s` to rsync this tree to remote hosts from that config
4. run `./dev.sh` on each machine to restart that host's containers and follow logs
   run `cd rueckgrat/chat && ./run.sh` to start the native chat
5. run `./stop.sh` to stop all docker services

### Chat on Android

Build the APK by hand instead of with the installer ([Android APK](#android-apk)):

```bash
cd rueckgrat/chat
source .venv/bin/activate
flet clean && flutter pub get && flet build apk
```

This may install flutter SDK, android SDK if not there already

On your phone enable Developer options → USB debugging
Check if it is available with `adb devices`

Install on android phone, open the app on the phone and follow its logs

```bash
adb uninstall com.flet.chat && adb install build/apk/*.apk && adb logcat -s flet.python
```

## Models

Edit `rueckgrat/node/data/registry.json` to add models. Copy an existing entry for reference.

Manage installs with the registry manager.

### Registry manager

Launch any node container then run the following to control it's registry

```bash
docker exec -it rueckgrat_node python -m app.registry_manager list -v
docker exec -it rueckgrat_node python -m app.registry_manager list -v -t llm
docker exec -it rueckgrat_node python -m app.registry_manager install [model_name]
docker exec -it rueckgrat_node python -m app.registry_manager nodes
docker exec -it rueckgrat_node python -m app.registry_manager --help
```

Models live under `/var/lib/Rueckgrat/models` on the host.

## Hub management

Invites (and users) are managed with the hub management tool. Run the hub container, then use it inside the hub container as follows

```bash
docker exec -it rueckgrat_hub python -m app.hub_management invite create
docker exec -it rueckgrat_hub python -m app.hub_management invite create --email [e-mail]
docker exec -it rueckgrat_hub python -m app.hub_management user create [user_name]
docker exec -it rueckgrat_hub python -m app.hub_management user list
docker exec -it rueckgrat_hub python -m app.hub_management invite list
docker exec -it rueckgrat_hub python -m app.hub_management --help
```

**Note: The token is printed only once, copy it immediately.**

## Troubleshoot & FAQ

### Logs for hub, node, caddy, llama-server

`docker logs -f CONTAINER`

Container names: `rueckgrat_hub`, `rueckgrat_node`, `rueckgrat_caddy`, `rueckgrat_llama_server`.

### Native chat logs

Stdout only (`./run.sh` also writes `logs/chat.log` if that path exists).

### FAQ

| Issue/Question | Answer |
| --- | --- |
| The chat bot seems to fail doing anything right | Use at least a 24B LLM (e.g. `cognitivecomputations_Dolphin-Mistral-24B-Venice-Edition-Q6_K_L`). Smaller models often fail to generate valid JSON tool calls. |
| What does Rückgrat mean? | Rückgrat (or the alternative spelling Rueckgrat) is German for spine. Idea was to create a framework that is the base for a bunch of tools. Plus it looks cool as a logo. |
| Can I use Rückgrat for commercial projects? | Yes. Check out for commercial licensing here `COMMERCIAL_LICENSE.md`. |
| A model is missing | Install it with the [registry manager](#registry-manager), e.g. `docker exec -it rueckgrat_node python -m app.registry_manager install [model_name]`. |

## Special thanks to

✨ **Gebrielle** 🎉

🎊 **spychodelics** 🚀

👶 **Naomi** 🍼
