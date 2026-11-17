# Development

The author develops primarily on a private copy of this repo. Feel free to open tickets here anyway or contact directly via martinloga@protonmail.com

## First steps

1. install once manually and store your setting from `rueckgrat/config/infrastructure.json`.
2. change code
3. optional: `./install.sh -s` to rsync this tree to remote hosts from that config
4. run `./dev.sh` on each machine to restart that host's containers and follow logs
   optionally `./dev.sh -f` for wiping all volumes/db
   run `cd rueckgrat/chat && ./run.sh` to start the native chat
5. run `./stop.sh` to stop all docker services

Hint use --in-place option for the installer if you don't want your workspace be then one compiled in to the containers locally

## Communication

Chat talks to the hub over HTTPS and websockets. The hub talks to the nodes over HTTP and websockets on your network. Clients can reach the hub on the LAN through Caddy, or from the internet through an optional Cloudflare tunnel. See [docs/communication.md](docs/communication.md) for the components, ports, authentication and the typical message and audio flows.

## Test Prompts Library

Since it is cumbersome to reinvent prompts for testing all the time. Please find some test prompts here [docs/test_prompts.md](docs/test_prompts.md).

## Local web pages

By default the AI can only open public websites. It cannot open pages in your home network or on the hub machine itself.

If you want the AI to read your own local websites or services, list them in `rueckgrat/.env` on the hub machine and rebuild the hub. Separate entries with commas. You can list a single address, a whole network, or a machine name:

```bash
HUB_FETCH_ALLOW=192.168.2.0/24,nas.local,127.0.0.1
```

Write `private` to allow your whole home network. This does not include the hub machine itself (`127.0.0.1`), which you have to list on its own.

You can also set this in the installer config as `"fetch_allow"` in the hub section, so it is kept when you reinstall.

## Chat on Android

Build the APK by hand instead of with the installer

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

## Laya tuning

Add tune data to rueckgrat/hub/laya_tune/dataset.jsonl then run:

```bash
cd rueckgrat/hub
./laya_tune/tune.sh
```

## better logging

Install doozle-agent on remote machines

```
docker run -d --name dozzle-agent \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -p 7007:7007 \
  amir20/dozzle:latest agent
```

Install doozle on your machine refering to the remote machines. For Example:

```
docker run -d --name dozzle \
  -p 8088:8080 \
  -e DOZZLE_REMOTE_AGENT=192.168.2.158:7007,192.168.2.239:7007 \
  amir20/dozzle:latest
```

Then open with http://localhost:8088/ in browser