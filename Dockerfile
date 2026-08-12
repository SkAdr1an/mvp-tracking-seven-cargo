FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=America/Sao_Paulo
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium fonts-dejavu-core fonts-liberation tzdata curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-production.txt ./
RUN pip install --no-cache-dir -r requirements-production.txt
COPY app ./app
COPY scripts ./scripts
COPY migrations ./migrations
RUN useradd --system --uid 10001 --create-home seven && mkdir -p /app/data && chown -R seven:seven /app
USER seven

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/health', headers={'X-Forwarded-Proto':'https'}), timeout=3)" || exit 1

# Access logs are disabled because public portal tokens are part of request paths.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*", "--no-access-log"]
