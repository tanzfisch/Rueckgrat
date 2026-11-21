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

The hub can share the AI's sandbox files over WebDAV, one folder per contact, named `<name> (<id>)`. Turn it on with `HUB_FILE_SHARE=webdav` in `rueckgrat/.env` and log in with your hub user name and password. Always go through Caddy (`https://rueckgrat.hub/dav/`), never the plain hub port, or the password travels unencrypted.

The AI can write a contact's files while you have them open, over WebDAV or SMB. Nothing holds it back, so know when it's working on them.

Virtual environments, caches and installed packages are not shared: `HUB_FILE_SHARE_EXCLUDE` in `rueckgrat/.env`, comma separated, for example `HUB_FILE_SHARE_EXCLUDE=.venv,venv,__pycache__,build`. It applies to SMB too. Names match whole file or folder names at any depth. The installer offers `HUB_FILE_SHARE_EXCLUDE_DEFAULT` (`.venv,venv,__pycache__,node_modules,.mypy_cache,.pytest_cache,.ruff_cache,.tox,.nox,.gradle,.cache`) and writes the answer; without the variable (or empty) the hub uses the same list.

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

The app's settings (tab Network, below the hub connection, only with a file share) list the folders' addresses: `GET /file_share` gives `FileShare.connect` (`SandboxDav` / `SandboxSmb`: title, notes, the user's contacts with a folder, each name and address; `null` without a file share). The addresses use the host the app reached the hub with (the request's `Host`), SMB's the hub's `HUB_SMB_PORT` (compose passes it to the hub too). SMB leaves out the contacts without a share yet and adds a note when the user has no SMB login yet. The mount commands stay here: davfs2 above, mount.cifs below.

## Using SMB

With `HUB_FILE_SHARE=smb` the `smb` service (`rueckgrat/smb`, Samba, compose profile `smb`) shares each contact's files as an SMB share named `<name> (<id>)`. Only the contact's user can open it and sees it in the list. Start it with the hub:

```
cd rueckgrat
docker compose --profile smb up -d --build hub smb
```

How it fits together:

- The hub writes the users and shares into the volume `hub_smb` (`/hub/smb` in the hub, `/state` in the smb service): `passwd` (one unix user `rg<user id>` per hub user, uid 20000 + id), `smbpasswd` (their NT hashes), `users.map` (the hub user name each logs in with) and `shares.conf` (the shares, included by `smb.conf`). It refreshes them every 15 s and right after a login. The smb service reloads its config when `shares.conf` changes. No restarts.
- SMB logins check an NT hash (MD4 of the password), and the hub keeps only the argon2 hash. So the hub takes the NT hash when the password is typed: signup, login, password change. It's dropped when the hub password changes another way, for example through hub management, until the user logs in again. Empty passwords get no SMB login.
- The shares are the contacts' docker volumes, read straight from docker's volumes folder. The installer writes it as `HUB_SMB_VOLUMES` (`docker info`'s root plus `/volumes`, default `/var/lib/docker/volumes`). Samba works in them as the sandbox user (uid 1000), so what you create belongs to the AI's sandbox user too. A share exists once the contact's volume does, which is after the AI first used its files.
- Excluded names are `veto files`: hidden, can't be opened or created, and a folder holding only those can still be deleted.
- SMB3 only, signing required, encryption when the client supports it. No guests. Clients from private addresses only (`hosts allow`), published on IPv4 at `HUB_SMB_PORT` (default 445; the container listens on 445 either way). Set it in `rueckgrat/.env` when something on the host already uses 445.

Mount on Linux with a credentials file:

```
sudo apt install cifs-utils
printf 'username=<user>\npassword=<password>\n' > ~/.smb-rueckgrat && chmod 600 ~/.smb-rueckgrat
sudo mkdir -p /mnt/lena
sudo mount -t cifs "//rueckgrat.hub/Lena (3)" /mnt/lena -o credentials=$HOME/.smb-rueckgrat,uid=$(id -u),gid=$(id -g),vers=3.1.1
```

or in `/etc/fstab` (`\040` is a space):

```
//rueckgrat.hub/Lena\040(3)  /mnt/lena  cifs  credentials=/home/martin/.smb-rueckgrat,uid=martin,gid=martin,vers=3.1.1,noauto,user  0  0
```

With `HUB_SMB_PORT` other than 445, add `port=<n>` to the mount options (both lines above), use `smb://rueckgrat.hub:<n>/...` for gio and macOS and `smbclient -p <n>`. Windows only connects to 445.

Without root: `gio mount "smb://rueckgrat.hub/Lena (3)"`. It's mounted under `/run/user/$(id -u)/gvfs/`. `smbclient -L //rueckgrat.hub -U <user>` lists your shares. macOS: Finder, Go, Connect to Server, `smb://rueckgrat.hub`. Windows: `\\rueckgrat.hub` in Explorer, or `net use L: "\\rueckgrat.hub\Lena (3)" /user:<user>`.

### Keep the venv outside the share with direnv

A venv only works on the machine that made it, and it's slow over the network, so keep it outside the share.

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
