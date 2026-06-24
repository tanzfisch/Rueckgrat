# <img src="logo.png" width="50" alt="Logo">ückgrat

**AI chat frontend & backend** — focused on personal, private companion apps.

The purpose is evolving. Currently the main focus is a **private, local-first AI companion** with strong multimodal capabilities.

**Status**: Early stage — many features still missing, some instability expected, mostly manual installation needed since the installer does not cover all use cases yet.
See the [changelog](https://github.com/tanzfisch/Rueckgrat/blob/master/changelog.md) for details.

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

## Getting Started (Recommended)

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

The installer will:

* Ask which components you want (Chat Client / Hub / Node)
* Automatically install Docker (if needed)
* Install Caddy
* Removes previous installations (on user request)
* Start the selected services

For a Windows Chat Client

```powershell
git clone https://github.com/tanzfisch/Rueckgrat.git
cd Rueckgrat\chat
.\install.ps1
.\run.ps1
```

# Special Tanks to

✨ **Gebrielle** 🎉

🎊 **spychodelics** 🚀

👶 **Naomi** 🍼
