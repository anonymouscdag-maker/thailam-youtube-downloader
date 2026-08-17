#!/bin/sh
set -eu

# PO token runs in script mode inside each yt-dlp call.
# Keep Render with a single public listening port: the downloader worker on $PORT (default 10000).
exec python /app/worker.py
