# <img src="rueckgrat/chat/assets/icons/logo.png" width="50" alt="Logo">ückgrat

**AI tools running private and local.**

**Status**: Early stage. Do not use in production.

- many features still missing and instability is expected
- Author has no clue about security, auth, certs, or Caddy. Help welcome.
- See the [changelog](https://github.com/tanzfisch/Rueckgrat/blob/master/changelog.md) for more details.

# Features

Rückgrat is a backend (hub and nodes) plus a user-facing companion chat client. Quality of the experience depends on the models you run which is limited by the hardware you have available.

## Backend

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
    - text embeddings using fastembed
    - tool detection using Laya where possible
- GPU: NVIDIA and AMD. Intel GPUs are not supported/tested.
- AI tools
    - **websearch** — search the web when requested or needed
    - **wikipedia** — search wikipedia when requested or needed
    - **generate_image** — generate an image on request or on its own
    - **take_photo** — generate a photo of self, user, or both from current context
    - **remember** — keep a short fact about the user, per contact
    - **search_memory** — find saved facts by meaning (384-dimension vectors, sqlite-vec on the hub)
    - **calculate** — calculate given expression
    - **convert** — conversion between numerous units
    - **current_time** — current time for given location
    - **date_calc** — date calculations
    - **fetch_url** — fetch content for given URL
    - **weather** — weather forcast for given location

## Frontend Tools

### Chat
- running on Linux and Android
- chat with a locally installed LLM
- in-chat image generation based on use prompt
- self image generation. Like taking a picture of self based on current context.
- code highlighting
- contacts, character templates, character-creation wizard, settings
- assiting a conversation with someone in an other language (using your own llm for translation)
- persistent companion (opt-in per contact): plans its own day and may write first

Some screenhots of the app ...

<img src="docs/screenshots/contact_list.png" width="200" alt="contact list"> <img src="docs/screenshots/chat_image.png" width="200" alt="image gen in chat"> <img src="docs/screenshots/chat_foto.png" width="200" alt="self image in chat"> <img src="docs/screenshots/translate.png" width="200" alt="code in chat">

# Getting started

## Linux

```bash
wget https://raw.githubusercontent.com/tanzfisch/Rueckgrat/master/install.sh
chmod +x install.sh
./install.sh
```

The installer supports multi-host deploy, component selection (native chat, hub, node, llama-server, ImageGen, TTS, STT, text embeddings), an optional Cloudflare tunnel and an optional Android APK of the chat client.

Run chat natively:

```bash
cd rueckgrat/chat
./run.sh
```

Alternatively clone first and then install:

```bash
git clone https://github.com/tanzfisch/Rueckgrat.git
cd Rueckgrat
./install.sh
```

Reinstall from a saved config, skipping the setup questions:

```bash
./install.sh -c rueckgrat/config/config_example.json -y
```

### Running multiple hosts

**What every machine needs**

- `ssh` and `rsync` installed
- the same user name on every machine, and that user is allowed to use sudo
- your ssh key, so the installer can log in from the machine you install from

The user should also be in the `docker` group, so it can run the containers. If docker was not installed already the installer adds it after it installs Docker automatically.

**Recommended: a separate user for Rueckgrat**

The easiest way is a separate user just for Rueckgrat, with your ssh key and sudo without a password. Then the installer never asks for a password. `create_rueckgrat_user.sh` sets this up on all your machines in one go. It asks for your sudo password once per machine:

```bash
./create_rueckgrat_user.sh rueckgrat localhost 192.168.2.10 192.168.2.11
./install.sh -u rueckgrat
```

`-u` tells the installer which user to log in as on every machine. Without it, it uses the user you are logged in as. Rueckgrat is then installed in that user's home folder (`~/Rueckgrat-install`).

Keep in mind that sudo without a password means anyone who gets your ssh key can do anything on those machines. Protect your key with a passphrase.

## Android

Make sure to run the installer at least once before so it can generate the caddy certificate the client needs.
Either select build apk in the installer or alternatively you can manually build the apk with:

```bash
./install.sh --apk
adb install -r dist/rueckgrat-chat[version].apk
```

## Windows

(currently not actively tested)

Native client only:

```powershell
git clone https://github.com/tanzfisch/Rueckgrat.git
cd Rueckgrat\rueckgrat\chat
.\install.ps1
.\run.ps1
```

# Development

If you like to contribute please check out [CONTRIBUTING.md](CONTRIBUTING.md) on how to contribute.

# Models

Edit `rueckgrat/node/data/registry.json` to add models to the registry

Manage installs with the registry manager.

Launch any node container then run the following to control it's registry

```bash
docker exec -it rueckgrat_node python -m app.registry_manager --help
docker exec -it rueckgrat_node python -m app.registry_manager list -v
docker exec -it rueckgrat_node python -m app.registry_manager list -v -t llm
docker exec -it rueckgrat_node python -m app.registry_manager install [model_name]
docker exec -it rueckgrat_node python -m app.registry_manager nodes
```

Models default location is `/var/lib/Rueckgrat/models` on the host.

# Hub management

Invites and users are managed with the hub management tool. Run the hub container, then use it inside the hub container as follows

```bash
docker exec -it rueckgrat_hub python -m app.hub_management --help
docker exec -it rueckgrat_hub python -m app.hub_management invite create
docker exec -it rueckgrat_hub python -m app.hub_management invite create --email [e-mail]
docker exec -it rueckgrat_hub python -m app.hub_management user create [user_name]
docker exec -it rueckgrat_hub python -m app.hub_management user list
docker exec -it rueckgrat_hub python -m app.hub_management invite list
docker exec -it rueckgrat_hub python -m app.hub_management companion list
docker exec -it rueckgrat_hub python -m app.hub_management companion status [contact_id]
```

**Note: The invite token is printed only once, copy it immediately.**

## Local web pages

By default the AI can only open public websites. It cannot open pages in your home network or on the hub machine itself.

If you want the AI to read your own local websites or services, list them in `rueckgrat/.env` on the hub machine and rebuild the hub. Separate entries with commas. You can list a single address, a whole network, or a machine name:

```bash
HUB_FETCH_ALLOW=192.168.2.0/24,nas.local,127.0.0.1
```

Write `private` to allow your whole home network. This does not include the hub machine itself (`127.0.0.1`), which you have to list on its own.

You can also set this in the installer config as `"fetch_allow"` in the hub section, so it is kept when you reinstall.

# Hardware requirements

There is no minimum requirements but for a good experience about 40 GB of VRAM in total is a comfortable minimum.
To be able to run the stack with useful models. It can sit in one machine or be spread over several cards or machines.

Following an example setup that worked fine for the dev

| Component | HW specs | VRAM usage |
| --- | --- | --- |
| LLM (Dolphin Venice Edition Q4) | AMD RX 7900 XTX 24GB | ~22 GB |
| Image generation (DreamShaperXL_Turbo_V2-SFW) | AMD RX 9060 XT 16GB | ~12-13 GB |
| TTS (Chatterbox) | NVIDIA RTX 3080 10GB | ~4-5 GB |
| Text embeddings (bge-small-en-v1.5) | CPU | 0 GB |

See [config_example.json](rueckgrat/config/config_example.json) for the dev setup.

# FAQ

| Issue/Question | Answer |
| --- | --- |
| The chat bot seems to fail doing anything right | Use at least a 24B LLM (e.g. `cognitivecomputations_Dolphin-Mistral-24B-Venice-Edition-Q6_K_L`). Smaller models often fail to generate valid JSON tool calls. |
| What does Rückgrat mean? | Rückgrat (or the alternative spelling Rueckgrat) is German for spine. Idea was to create a framework that is the base for a bunch of tools. Plus it looks cool as a logo. |
| Can I use Rückgrat for commercial projects? | Yes. Check out for commercial licensing here `COMMERCIAL_LICENSE.md`. |
| A model is missing | Install it with the [registry manager](#registry-manager), e.g. `docker exec -it rueckgrat_node python -m app.registry_manager install [model_name]`. |

# Special thanks to

✨ **Gebrielle** 🎉

🎊 **spychodelics** 🚀

👶 **Naomi** 🍼
