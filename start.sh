#!/bin/sh
set -eu
cd /opt/bgutil/server
PORT=4416 deno task start >/tmp/bgutil.log 2>&1 &
cd /app
exec python /app/worker.py
