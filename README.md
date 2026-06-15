# <img src="logo.png" width="50" alt="Logo">ückgrat

ai chat frontend &amp; backend

The purpose is evolving. Currently the focus is on personal, private companion app. 

Status: it's in the early stages. Lots of features still missing, unstable and non trivial to install.
For more details check the [change log](https://github.com/tanzfisch/Rueckgrat/blob/master/changelog.md).

# Features

* in chat image genration on demand without context to the conversation. Just write something like "Can you please draw me a picture of an ape riding a horse"
* in chat image generation by AI showing it self in action or user and AI in action (currently barely any continuity of character)
* chatting with which ever llm is installed
* text to speach on client side using piper
* inventory system that tracks the clothing and items on characters (experimental)

For future features check [issues](https://github.com/tanzfisch/Rueckgrat/issues).

# modules

## Chat

The chat frontend. Loging, create a contact, chat.
Tip: for quickly creating a contact copy paste the content of one of the tamplates in chat/app/templates in to the name field of the form

## Hub

This is the server the client communicates to. I contains the database and controls the communication of the system.

## Node

There can be a number of nodes. Each node offers a service (inference, image generation etc.) the Hub can use.

Services currently integrated
* llama.cpp as service (docker container is too slow)
* ComfyUI as service

## common

Some utility code shared across modules

# getting started

First decide which machine will be running hub, node or chat or if it is all running on one machine.

## hub setup

In order to only run the hub on a machine execute:

```
cd rueckgrat
docker compose up --build hub caddy
```

This will build/launch the hub and caddy which is a proxy to handle https access to the hub.

If you also want to run a node on that same machine go with.

```
docker compose up --build hub node caddy
```

## node setup

to run llama.cpp server on a node run 
```
cd rueckgrat
docker compose up --build llama-server
```

ro tun ComfyUI on your node execute:
```
ComfyUI/install.sh
```

## chat client setup

to run the chat from linux
```
cd chat
./install.sh
./run.sh
```

to run the chat from windows
```
cd chat
.\install.ps1
.\run.ps1
```

# Development

## Tips

* For better code completion run from root workspace scripts/setup_dev_venv.py and then open workspace from file project.code-workspace
