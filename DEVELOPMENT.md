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

Project NOMAD (see the README) does not need to be listed: the hub allows its address and its library on its own.

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

## Using WebDAV

The hub can share the AI's sandbox files over WebDAV, one folder per contact, named `<name> (<id>)`. Turn it on with `HUB_WEBDAV=true` in `rueckgrat/.env` and log in with your hub user name and password. Always go through Caddy (`https://rueckgrat.hub/dav/`), never the plain hub port, or the password travels unencrypted.

While you hold a lock on any file of a contact, or the contact is paused (`PUT /contacts/{id}/files/ai_writes` with `{"paused": true}`), the AI can't write to that contact's files.

Virtual environments, caches and installed packages are not shared: `HUB_WEBDAV_EXCLUDE` in `rueckgrat/.env`, comma separated, for example `HUB_WEBDAV_EXCLUDE=.venv,venv,__pycache__,build`. Names match whole file or folder names at any depth. The installer offers `HUB_WEBDAV_EXCLUDE_DEFAULT` (`.venv,venv,__pycache__,node_modules,.mypy_cache,.pytest_cache,.ruff_cache,.tox,.nox,.gradle,.cache`) and writes the answer; without the variable (or empty) the hub uses the same list.

A good way to work in the share on Linux is davfs2 for the mount and direnv for a venv that lives outside it.

### Mount the share with davfs2

```
sudo apt install davfs2      # answer "Yes" to letting unprivileged users mount
sudo usermod -aG davfs2 $USER
mkdir -p ~/rueckgrat ~/.davfs2/certs
```

Log out and back in so the group change takes effect.

Add this line to `/etc/fstab` (replace `martin` with your user):

```
https://rueckgrat.hub/dav/  /home/martin/rueckgrat  davfs  user,noauto,rw,uid=martin,gid=martin  0  0
```

Store the login so it isn't asked every time:

```
echo 'https://rueckgrat.hub/dav/ <user> <password>' >> ~/.davfs2/secrets
chmod 600 ~/.davfs2/secrets
```

The hub uses a self-signed certificate. Copy it (or Caddy's root CA) to `~/.davfs2/certs/rueckgrat.pem` and add this line to `~/.davfs2/davfs2.conf`:

```
trust_server_cert ~/.davfs2/certs/rueckgrat.pem
```

Mount and unmount:

```
mount ~/rueckgrat
umount ~/rueckgrat
```

davfs2 caches files locally and uploads a file when it's closed, so a save can take a moment to reach the AI.

### Keep the venv outside the share with direnv

A venv only works on the machine that made it, and it's slow over WebDAV, so keep it outside the share.

Install [uv](https://docs.astral.sh/uv/) and direnv:

```
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo apt install direnv
echo 'eval "$(direnv hook bash)"' >> ~/.bashrc
source ~/.bashrc
```

Create the venv outside the share and install the project's requirements:

```
cd ~/rueckgrat/<contact>/<project>
uv venv ~/.venvs/<project>
VIRTUAL_ENV=~/.venvs/<project> uv pip install -r requirements.txt
```

Create a file `.envrc` in the project folder:

```
export VIRTUAL_ENV=~/.venvs/<project>
PATH_add "$VIRTUAL_ENV/bin"
```

Allow it once:

```
direnv allow
```

From now on the venv is active whenever you `cd` into the project folder, and `python main.py` uses it.
