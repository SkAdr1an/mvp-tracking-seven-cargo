FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=America/Sao_Paulo
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium fonts-dejavu-core fonts-liberation tzdata curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY scripts ./scripts
COPY migrations ./migrations
RUN useradd --system --uid 10001 --create-home seven && mkdir -p /app/data && chown -R seven:seven /app
USER seven

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*"]
