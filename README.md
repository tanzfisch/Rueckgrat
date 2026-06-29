# <img src="logo.png" width="50" alt="Logo">ückgrat

**AI chat frontend & backend** — focused on personal, private companion apps.

The purpose is evolving. Currently the main focus is a **private, local-first AI companion**.

**Status**: Early stage. Do not use in production. 
 * many features still missing
 * instability expected
 * Author has no clue about auth, cert and caddy. Could use some help here to get this right.
 * See the [changelog](https://github.com/tanzfisch/Rueckgrat/blob/master/changelog.md) for more details.

## Features

Everything is in its early stages. Don't expect too much and mostly the quality depends on the models you run underneath

- all python based
- full Linux support (Chat client only for Windows)
- In-chat image generation on demand
- AI self-visualization and character-aware image generation
- Chat with any locally installed LLM
- Client-side text-to-speech using Piper (subject to change)
- code highlighting
- Tools 
    - websearch searches the web when requested or needed
    - image_gen general image generation by user request or by it self
    - take_photo takes a "photo" of self, user or both based on current context
 
Currently supported os are:
* Debian ✅
* Ubuntu (not tested)
* Fedora (not tested)
* Arch (not tested)
* openSUSE (not tested)
* Windows ✅ (client only)

I recommend a miniumm of 24b llm (ie cognitivecomputations_Dolphin-Mistral-24B-Venice-Edition-Q6_K_L which I worked with the most) otherwise it will not be able to handle json generation correctly and consitantly.

For planned features, check the [Issues](https://github.com/tanzfisch/Rueckgrat/issues).

## 🚀 Getting Started

### Linux

The easiest way to install Rueckgrat on Linux is using the one-line installer

```bash
curl -fsSL https://raw.githubusercontent.com/tanzfisch/Rueckgrat/master/install.sh | bash
```

Or clone first and run:

```bash
git clone https://github.com/tanzfisch/Rueckgrat.git
cd Rueckgrat
./install.sh
```

The installer supports multi-host deployment, component selection (Chat native/Docker, Hub, Node, llama-server), clean builds, and all major distros via Docker/Caddy.

Alternatively it can be started using a config file like so.

```bash
./install -c infrastructure.json -y
```

No need to write a config manually when running ./install.sh it will create one and store it at rueckgrat/config/infrastructure.json

### Windows

Currently only installing the client by script is supported for Windows.

```powershell
git clone https://github.com/tanzfisch/Rueckgrat.git
cd Rueckgrat\chat
.\install.ps1
.\run.ps1
```

# Development

For local development it is ideal to shortcut the installer and go straight for instlling one host directly. This allows for an in code installation so when looking at error logs the path points to the code and not an installed copy.

```bash
./install.sh --host-config '{ "addr": "192.168.2.39", "node": { "port": 7346, "services": [ { "type":"text_to_text", "name": "llama-server", "port": 8080, "model": "cognitivecomputations_Dolphin-Mistral-24B-Venice-Edition-Q6_K_L" } ] }, "hub": { "port": 14223 }, "chat": {}, "chat_docker": { "pert": "3001" } }'
```

# Troubleshoot & FAQ

### How can I see the logs?
For hub, node, caddy and llama-server:
`docker logs -f [container]`

### Can't see the Chat logs when running inside Docker
Look in `logs/chat.log` and `logs/autostart.log`.

### Where are the logs for Chat running native?
No log file. Chat writes directly to stdout.

# Special Tanks to

✨ **Gebrielle** 🎉

🎊 **spychodelics** 🚀

👶 **Naomi** 🍼
3001