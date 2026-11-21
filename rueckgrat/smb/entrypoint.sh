#!/bin/sh
# #225 smbd in the foreground once the hub wrote its shares, its config reloaded when the hub changes them
set -eu
SHARES=/state/shares.conf

until [ -f "$SHARES" ]; do sleep 2; done
smbd --foreground --no-process-group --debug-stdout &
smbd=$!
trap 'kill -TERM "$smbd" 2>/dev/null' TERM INT

seen=$(cksum "$SHARES")
while kill -0 "$smbd" 2>/dev/null; do
    sleep 3 &
    wait $! || true
    now=$(cksum "$SHARES" 2>/dev/null || true)
    if [ -n "$now" ] && [ "$now" != "$seen" ]; then
        seen=$now
        smbcontrol smbd reload-config || true
    fi
done
wait "$smbd"
