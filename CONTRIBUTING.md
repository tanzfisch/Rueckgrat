# Contributing

By submitting a contribution to this project, you agree that:

1. You created the contribution or have the right to submit it.
2. You license your contribution under the same license as the project.
3. You grant the project maintainer the right to relicense your
   contribution under other licenses, including commercial licenses.

The author develop primarily on a private copy of this repo. Feel free to open tickets here anyway or contact directly via martinloga@protonmail.com


# First steps

1. install once manually and store your setting from `rueckgrat/config/infrastructure.json`.
2. change code
3. optional: `./install.sh -s` to rsync this tree to remote hosts from that config
4. run `./dev.sh` on each machine to restart that host's containers and follow logs
   optionally `./dev.sh -f` for wiping all volumes/db
   run `cd rueckgrat/chat && ./run.sh` to start the native chat
5. run `./stop.sh` to stop all docker services

Hint use --in-place option for the installer if you don't want your workspace be then one compiled in to the containers locally


# Chat on Android

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