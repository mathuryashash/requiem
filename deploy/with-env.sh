#!/bin/sh
# Load the values the bootstrap service wrote, then run the real command.
set -a
. /shared/requiem.env
set +a
exec "$@"
