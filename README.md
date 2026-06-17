# <img src="logo.png" width="50" alt="Logo"> ückgrat

**AI chat frontend & backend** — focused on personal, private companion apps.

The purpose is evolving. Currently the main focus is a **private, local-first AI companion** with strong multimodal capabilities.

**Status**: Early stage — many features still missing, some instability expected.  
See the [changelog](https://github.com/tanzfisch/Rueckgrat/blob/master/changelog.md) for details.

## Features

Everything is in its early stages. Don't expect too much and mostly the quality depends on the models you run underneath

- In-chat image generation on demand 
- AI self-visualization and character-aware image generation
- Chat with any locally installed LLM
- Client-side text-to-speech using Piper
- Tools 
    - websearch searches the web when requested or needed
    - image_gen general image generation by user request or by it self
    - take_photo takes a "photo" of self, user or both based on current context

I recommend a miniumm of 24b llm (ie cognitivecomputations_Dolphin-Mistral-24B-Venice-Edition-Q6_K_L which I worked with the most) otherwise it will not be able to handle json generation correctly and consitantly.

For planned features, check the [Issues](https://github.com/tanzfisch/Rueckgrat/issues).

## Modules

### Chat
The beautiful cross-platform frontend (login, contacts, chat).

**Tip**: Quickly create a contact by copying the content of one of the templates in `chat/app/templates/` into the name field.

### Hub
Central server. Handles authentication, database, and orchestrates communication between clients and nodes. Includes **Caddy** for automatic HTTPS.

### Node
Scalable backend workers. Each node can provide services (LLM inference, image generation, etc.) to the Hub.

Currently integrated:
- **llama-server** (recommended — native performance)
- **ComfyUI** (image generation)

### common
Shared utilities across modules.

## Getting Started (Recommended)

The easiest way to install Rueckgrat is using the new **universal one-line installer**, which works on **all major Linux distributions** (Ubuntu, Debian, Fedora, Arch, openSUSE, etc.).

```bash
# From any directory
bash <(curl -fsSL https://raw.githubusercontent.com/tanzfisch/Rueckgrat/master/install.sh)
```

Or clone first and run:

```bash
git clone https://github.com/tanzfisch/Rueckgrat.git
cd Rueckgrat
./install.sh
```

The installer will:

* Ask which components you want (Chat Client / Hub / Node)
* Automatically install Docker (if needed)
* Install Caddy
* Handle previous installations
* Start the selected services

## Manual Setup (Advanced)
1. Hub only

```bash
cd rueckgrat
docker compose up --build -d hub caddy
```

2. Hub + Node on same machine

```bash
cd rueckgrat
docker compose up --build -d hub node caddy
```

3. Node only (on a separate machine)

```bash
cd rueckgrat
docker compose up --build -d node
```

For llama-server:

```bash
docker compose up --build -d llama-server
```

For ComfyUI:

```bash
cd ComfyUI && ./install.sh
```

Chat Client

```bash
cd chat
./install.sh
./run.sh
```

Chat Client (Windows)

```powershell
cd chat
.\install.ps1
.\run.ps1
```

# Development

## Tips

- For better code completion: Run python scripts/setup_dev_venv.py from the root, then open the workspace via project.code-workspace.


✨ Feedback and contributions are very welcome!