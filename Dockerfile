FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates unzip && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir -U --pre "yt-dlp[default]"
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh && deno --version && yt-dlp --version && ffmpeg -version | head -n 1
WORKDIR /app
COPY worker.py /app/worker.py
RUN mkdir -p /tmp/thailam-downloader/jobs
EXPOSE 10000
CMD ["python","/app/worker.py"]
