FROM python:3.12-slim

# Системные зависимости для Playwright (Chromium) и общие утилиты
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libglib2.0-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libxshmfence1 \
    xdg-utils \
    cron \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем зависимости и устанавливаем
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium \
    && playwright install-deps chromium

# Копируем исходный код приложения
COPY main.py .
COPY gmail_auth.py .
COPY digest_reader.py .
COPY article_scraper.py .
COPY openai_gpts.py .
COPY gdrive_reader.py .
COPY google_sheets_writer.py .

# Директория для токенов и credentials (монтируется как volume)
RUN mkdir -p /app/secrets

# Скрипт-точка входа
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_HEADLESS=true

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "main.py"]
