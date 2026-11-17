#!/bin/sh
# Makes the data folder usable by the app user, then runs the API as that user.
#
# Started as root (the image default, e.g. on a PaaS with a mounted volume):
#   creates SIM_DATA_DIR, gives it to UID 10001 if it belongs to someone else
#   (a platform volume usually arrives owned by root), then drops root for good
#   with setpriv before the app starts.
# Started as 10001 (docker-compose sets `user:` and drops all capabilities):
#   only checks the folder is writable and explains how to fix it if not.
set -eu

APP_UID=10001
APP_GID=10001
data="${SIM_DATA_DIR:-/data}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$data"
    # Only when needed: chown -R on a large model cache would slow every start.
    if [ "$(stat -c %u "$data")" != "$APP_UID" ]; then
        echo "similarityly: giving $data to UID $APP_UID"
        if ! chown -R "$APP_UID:$APP_GID" "$data"; then
            echo "similarityly: cannot change the owner of $data (the container lacks the" \
                 "CHOWN capability). Make the volume writable by UID $APP_UID," \
                 "or allow CHOWN, SETUID and SETGID." >&2
            exit 1
        fi
    fi
    exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --clear-groups --no-new-privs -- "$@"
fi

probe="$data/.write-test.$$"
# touch, not `: > file`: a failed redirect on the special builtin `:` would end
# the whole shell (exit 2, no message) instead of failing this test.
if ! { mkdir -p "$data" && touch "$probe" && rm -f "$probe"; } 2>/dev/null; then
    echo "similarityly: $data is not writable by UID $(id -u). The volume mounted there" \
         "belongs to $(stat -c %u:%g "$data" 2>/dev/null || echo 'another user')." \
         "Run the container as root once (it fixes the owner and then drops root)," \
         "or make the volume writable by UID $APP_UID, e.g." \
         "chown -R $APP_UID:$APP_GID <volume path>." >&2
    exit 1
fi
exec "$@"
