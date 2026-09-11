# <img src="logo.png" width="50" alt="Logo">ückgrat

AI chat frontend & backend. The purpose is evolving. Currently the main focus is a **private, local-first AI companion**.

**Status**: Early stage. Do not use in production.
 * many features still missing
 * instability expected
 * Author has no clue about auth, cert and caddy. Could use some help here to get this right.
 * See the [changelog](https://github.com/tanzfisch/Rueckgrat/blob/master/changelog.md) for more details.

## Features

Everything is in its early stages. Don't expect too much and mostly the quality depends on the models you run underneath

- all python based
- full Linux support
- only native chat client on Windows supported
- in-chat image generation
- Chat with locally installed LLM
- Client-side text-to-speech using Piper (subject to change)
- speech to text using silero_vad and faster_whisper
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

Install Rueckgrat on Linux using the following commands

```bash
wget https://raw.githubusercontent.com/tanzfisch/Rueckgrat/master/install.sh
chmod +x install.sh
./install.sh
```

The installer supports multi-host deployment, component selection (Chat native/Docker, Hub, Node, llama-server), clean builds, and all major distros. It will install and run all selected options except the native chat client.

*Note:* The installer requires you to have sudo access on all machines you want to install with using the same username. 

To launch the native client manually:

```bash
cd rueckgrat/chat
./run.sh
```

##### Alternative methods of installation:

First clone and then run install

```bash
git clone https://github.com/tanzfisch/Rueckgrat.git
cd Rueckgrat
./install.sh
```

Alternatively it can be started using a config file like so. This file can be created ussing the installer it self. Just follow the instructions until the point where it recaps your install instructions. The config file then can be found at rueckgrat/config/infrastructure.json

```bash
./install -c rueckgrat/config/config_example.json -y
```

### Windows

Currently only installing the client by script is supported for Windows.

```powershell
git clone https://github.com/tanzfisch/Rueckgrat.git
cd Rueckgrat\chat
.\install.ps1
.\run.ps1
```

# Development

For local development this is the recommended workflow.

* Install once as described above (note that this creates a config file `infrastructure.json`).
* make changes to code
* optionally run `./install.sh -s` to sync the local changes to all remote machines based on `infrastructure.json`
* run `./dev.sh` on each machine to launch all docker containers based on the configuration in `infrastructure.json`

# Models

In oder to use other models then offered by Rückgrat edit the registry at rueckgrat/node/data/registry.json.
Follow the existing entries as example.

In order to manually install and manage models use the registry manager

# Registry manager

Currently the only way to run the registry manager is from a shell inside of a running container.

`docker compose run --entrypoint /bin/bash --rm node`

**list models**
python -m app.registry_manager list -v

**install models**
python -m app.registry_manager install [modelname as shown by list]

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
