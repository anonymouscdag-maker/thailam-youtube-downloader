#!/bin/sh
set -eu

# Render mounts Secret Files read-only under /etc/secrets.
# yt-dlp may update its cookie jar, so copy it to writable /tmp first.
if [ -f /etc/secrets/youtube-cookies.txt ]; then
  cp /etc/secrets/youtube-cookies.txt /tmp/youtube-cookies.txt
  chmod 600 /tmp/youtube-cookies.txt
fi

# PO token runs in script mode inside each yt-dlp call.
# Keep Render with a single public listening port: the downloader worker on $PORT (default 10000).
exec python /app/worker.py
