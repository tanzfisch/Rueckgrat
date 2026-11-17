# <img src="rueckgrat/chat/assets/icons/logo.png" width="50" alt="Logo">ückgrat

**AI tools running private and local.**

**Status**: Early stage. Do not use in production.

- many features still missing and instability is expected
- Author has no clue about security, auth, certs, or Caddy. Help welcome.
- See the [changelog](https://github.com/tanzfisch/Rueckgrat/blob/master/changelog.md) for more details.

# Features

Rückgrat is a backend (hub and nodes) plus a user-facing companion chat client. Quality of the experience depends on the models you run which is limited by the hardware you have available.

- Tools available to the AI
    - **bash** — run bash commands in a sandbox
    - **calculate** — calculate given expression
    - **run_code** — write a small program and run it in a fresh sandbox container (Python, JavaScript, C++, Java, Go)
    - **convert** — conversion between numerous units
    - **current_time** — current time for given location
    - **date_calc** — date calculations
    - **fetch_url** — fetch content for given URL
    - **find_tools** — helps the AI to find tools it needs
    - **generate_image** — generate an image on request or on its own
    - **show_map** — show a place on an OpenStreetMap map in the chat, tapping it opens the maps app
    - **poll** — ask the user a question with options to pick from in the chat
    - **price_finder** — looks for the best price of something and then shows you a ranked result in the chat
    - **remember** — keep a short fact about the user, per contact
    - **search_memory** — find saved facts by meaning (384-dimension vectors, sqlite-vec on the hub)
    - **spawn_job** — hand a bigger task to a background agent job that reports back when it is done
    - **task** — do something at a set time, once or repeating (reminders, alarms, wake-up calls, daily news or a price check); also list, change and cancel these tasks
    - **take_photo** — generate a photo of self, user, or both from current context
    - **text_to_speech** — speak a short text or text files (e.g. the chapters of an audiobook) with the contact's voice into one audio file, downloadable by the user in chat (long ones as Ogg Opus)
    - **weather** — weather forcast for given location
    - **websearch** — search the web when requested or needed
    - **wikipedia** — search wikipedia when requested or needed
    - **write_file** — write text or code files, downloadable by the user in chat
    - **share_file** — attach files or folders already in the sandbox to the answer, downloadable by the user in chat

    Some tools are only offered while the matching service is available: **generate_image** and **take_photo** need an image node, **text_to_speech** a TTS node, **remember** and **search_memory** a text-embeddings node, and **websearch**, **fetch_url**, **wikipedia**, **weather**, **price_finder** and **show_map** need internet.

- agent jobs running in the background
    - a controller plans the job in steps and delegates each step to up multiple sub agents working in parallel, each with its own role (e.g. researcher, analyst, writer)
    - results of every step get reported back to the controller, a failed sub agent is retried once with a revised task
    - messages from the user during the job can change the remaining plan
    - the controller merges all results into the final answer, progress is shown in the chat
    - agents work on projects in their own sandbox file system and can generate images

- persistent companion
    - opt-in per contact, the contact gets a life of its own between conversations and may write first
    - every night it plans its day on a private calendar: events of its own life, news scans, an evening reflection and check-ins with the user, only what fits its character
    - each planned entry runs as an agent job with the usual tools (e.g. websearch for the news) and may send the user a message, sometimes with a photo
    - the evening reflection carries open threads into the next day's planning

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

## Frontend Tools

### Chat
- running on Linux and Android
- chat with a locally installed LLM
- several conversations per contact
- in-chat image generation based on use prompt
- self image generation. Like taking a picture of self based on current context.
- maps, polls and price rankings shown in the chat
- source links under answers that used the web
- code highlighting, copy button on code blocks and blockquotes
- files from the AI: one file as itself, several files of one answer as a single zip
- preview text files in the chat with syntax highlighting, without downloading them
- file browser for the files of a conversation
- speak into the chat with the mic (needs an STT node)
- spoken answers start playing while the text is still streaming
- progress of background agent jobs in the chat, with a cancel button
- contacts, character templates, character-creation wizard, settings
- choose a voice for a contact (predefined or your own recording, needs a TTS node)
- view and delete a contact's memories
- opt-in companion per contact, from the contact profile
- assiting a conversation with someone in an other language (using your own llm for translation)
- transcribe: record a transcript, bookmark moments, edit the text, export as markdown, get a summary or a cleaned-up copy (recording needs an STT node)
- image generation tool and a gallery of your images (needs an image node)
- tasks and alarms (list, change or cancel them); alarms can ring in the app
- notifications when a reply or image is ready
- dark or light theme and text size
- Enter sends a message (or Ctrl+Enter when that is off)
- a banner when the hub is unreachable or a configured service is down

Some screenhots of the app ...

<img src="docs/screenshots/contact_list.png" width="200" alt="contact list"> <img src="docs/screenshots/chat_image.png" width="200" alt="image gen in chat"> <img src="docs/screenshots/chat_foto.png" width="200" alt="self image in chat"> <img src="docs/screenshots/translate.png" width="200" alt="code in chat">

generated promo video ...

[![Rueckgrat promo](https://img.youtube.com/vi/uEq7prKKw6c/0.jpg)](https://www.youtube.com/shorts/uEq7prKKw6c)

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
docker exec -it rueckgrat_hub python -m app.hub_management invite create --email [e-mail]
docker exec -it rueckgrat_hub python -m app.hub_management invite list
docker exec -it rueckgrat_hub python -m app.hub_management user create [user_name]
docker exec -it rueckgrat_hub python -m app.hub_management user list
docker exec -it rueckgrat_hub python -m app.hub_management companion status [contact_id]
docker exec -it rueckgrat_hub python -m app.hub_management maintenance status
docker exec -it rueckgrat_hub python -m app.hub_management stats
```

**Note: The invite token is printed only once, copy it immediately.**

To let the AI read websites on your home network or on the hub machine, see [Local web pages](DEVELOPMENT.md#local-web-pages).

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

# Development

If you like to contribute please check out [DEVELOPMENT.md](DEVELOPMENT.md).

# FAQ

| Issue/Question | Answer |
| --- | --- |
| The chat bot seems to fail doing anything right | Use at least a 24B LLM (e.g. `cognitivecomputations_Dolphin-Mistral-24B-Venice-Edition-Q6_K_L`). Smaller models often fail to generate valid JSON tool calls. |
| What does Rückgrat mean? | Rückgrat (or the alternative spelling Rueckgrat) is German for spine. Idea was to create a framework that is the base for a bunch of tools. Plus it looks cool as a logo. |
| Can I use Rückgrat for commercial projects? | No. |
| A model is missing | Install it with the [registry manager](#registry-manager), e.g. `docker exec -it rueckgrat_node python -m app.registry_manager install [model_name]`. |

# Special thanks to

✨ **Gebrielle** 🎉

🎊 **spychodelics** 🚀

👶 **Naomi** 🍼
