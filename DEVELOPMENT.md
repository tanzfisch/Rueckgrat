# Develop Rückgrat

1. install once (creates `rueckgrat/config/infrastructure.json`)
2. change code
3. optional: `./install.sh -s` to rsync this tree to remote hosts from that config
4. run `./dev.sh` on each machine to restart that host's containers and follow logs
   run `cd rueckgrat/chat && ./run.sh` to start the native chat
5. run `./stop.sh` to stop all docker services

## Chat

To develop and run the chat app 

**Run it natively**

```
cd rueckgrat/chat
./run.py
```

**build it for android**

```
cd rueckgrat/chat
source .venv/bin/activate
flet clean && flutter pub get && flet build apk
```

This may install flutter SDK, android SDK if not there already

On your phone enable Developer options → USB debugging
Check if it is available with `adb devices`

Install on android phone and open logging

```
adb uninstall com.flet.chat
adb install build/apk/*.apk
adb logcat -s flet.python
```

Open app on the phone

and see logs like this

```
adb logcat -s flet.python
```




