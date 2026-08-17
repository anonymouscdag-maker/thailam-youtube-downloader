FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates unzip git && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir -U --pre "yt-dlp[default]" "bgutil-ytdlp-pot-provider==1.3.1"
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh
RUN git clone --depth 1 --single-branch --branch 1.3.1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil \
    && cd /opt/bgutil/server \
    && deno install --allow-scripts=npm:canvas --frozen
RUN mv /usr/local/bin/yt-dlp /usr/local/bin/yt-dlp-real \
    && printf '%s\n' \
      '#!/bin/sh' \
      'if [ -f /tmp/youtube-cookies.txt ]; then' \
      '  exec /usr/local/bin/yt-dlp-real --cookies /tmp/youtube-cookies.txt --extractor-args "youtube:player_client=default,mweb" --extractor-args "youtubepot-bgutilscript:server_home=/opt/bgutil/server" "$@"' \
      'else' \
      '  exec /usr/local/bin/yt-dlp-real --extractor-args "youtube:player_client=mweb" --extractor-args "youtubepot-bgutilscript:server_home=/opt/bgutil/server" "$@"' \
      'fi' \
      > /usr/local/bin/yt-dlp \
    && chmod +x /usr/local/bin/yt-dlp \
    && deno --version \
    && yt-dlp --version \
    && ffmpeg -version | head -n 1
WORKDIR /app
COPY worker.py /app/worker.py
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh && mkdir -p /tmp/thailam-downloader/jobs
EXPOSE 10000
CMD ["/app/start.sh"]
