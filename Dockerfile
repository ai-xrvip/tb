FROM python:3.11.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# Create non-root user
RUN groupadd -r botuser && useradd -r -g botuser botuser && mkdir -p /app/data && chown botuser:botuser /app/data

COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . .

# Use non-root user
USER botuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" || exit 1

EXPOSE 8000

CMD ["python", "main.py"]
