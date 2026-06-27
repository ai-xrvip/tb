# AI Girlfriend Telegram Bot
FROM python:3.11-slim

WORKDIR /app

# ── System deps ──
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# ── Python deps ──
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# ── App code ──
COPY . .

# ── Persistent data volume ──
RUN mkdir -p /data

# ── Railway port ──
EXPOSE 8080

# ── Health check (reads PORT env var) ──
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import os,urllib.request; port=os.environ.get('PORT','8080'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health')"

# ── Run ──
CMD ["python", "bot.py"]

