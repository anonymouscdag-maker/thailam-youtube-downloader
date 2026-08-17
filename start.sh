#!/bin/sh
set -eu

# Start BgUtils PO-token provider exactly as documented for Deno.
cd /opt/bgutil/server/node_modules
deno run --allow-env --allow-net --allow-ffi=. --allow-read=. ../src/main.ts --port 4416 >/tmp/bgutil.log 2>&1 &

# Do not report the downloader as ready until the PO-token provider is actually reachable.
i=0
while [ "$i" -lt 30 ]; do
  if curl -sS --max-time 1 http://127.0.0.1:4416/ >/dev/null 2>&1; then
    break
  fi
  i=$((i+1))
  sleep 1
done

if ! curl -sS --max-time 1 http://127.0.0.1:4416/ >/dev/null 2>&1; then
  echo "PO-token provider failed to start" >&2
  cat /tmp/bgutil.log >&2 || true
  exit 1
fi

cd /app
exec python /app/worker.py
