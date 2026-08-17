FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates unzip git && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir -U --pre "yt-dlp[default]" "bgutil-ytdlp-pot-provider==1.3.1"
RUN mv /usr/local/bin/yt-dlp /usr/local/bin/yt-dlp-real \
    && printf '%s\n' '#!/bin/sh' 'exec /usr/local/bin/yt-dlp-real --extractor-args "youtube:player_client=mweb" "$@"' > /usr/local/bin/yt-dlp \
    && chmod +x /usr/local/bin/yt-dlp
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh && deno --version && yt-dlp --version && ffmpeg -version | head -n 1
RUN git clone --depth 1 --single-branch --branch 1.3.1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil \
    && cd /opt/bgutil/server \
    && deno install --allow-scripts=npm:canvas --frozen
WORKDIR /app
COPY worker.py /app/worker.py
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh && mkdir -p /tmp/thailam-downloader/jobs
EXPOSE 10000
CMD ["/app/start.sh"]
