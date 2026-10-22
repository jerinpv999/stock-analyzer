#!/bin/sh
# Starts as root only long enough to make sure the data folder exists and is writable,
# then runs the app as your user (HOST_UID/HOST_GID) so files stay editable outside Docker.
set -e
DATA="${NSE_DATA_DIR:-/data}"
UID_="${HOST_UID:-1000}"
GID_="${HOST_GID:-1000}"
mkdir -p "$DATA" "$DATA/.home"
if [ "$(id -u)" = "0" ]; then
  # Docker creates a missing bind-mount folder as root: hand it (and anything root-owned in it) to the user
  if [ "$(stat -c %u "$DATA")" != "$UID_" ] || find "$DATA" -maxdepth 3 -uid 0 -print -quit | grep -q .; then
    echo "entrypoint: giving $DATA to uid $UID_:$GID_"
    chown -R "$UID_:$GID_" "$DATA"
  fi
  exec setpriv --reuid="$UID_" --regid="$GID_" --clear-groups "$@"
fi
exec "$@"
