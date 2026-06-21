FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    npm \
    chromium \
    fonts-dejavu \
    libsm6 \
    libxext6 \
    libgl1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

ENV PUPPETEER_SKIP_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install the Revideo compositor runtime used by semantic lecture exports.
WORKDIR /revideo
COPY revideo/package*.json ./
RUN npm ci --omit=dev

# Copy application code
WORKDIR /app
COPY app/ /app/
COPY revideo/ /revideo/
COPY entrypoint.sh /entrypoint.sh

# Scripts are mounted as a read-only volume at runtime via docker-compose.yml
# (Dockerfile build context cannot access parent directories)

# Create storage directories
RUN chmod +x /entrypoint.sh \
    && mkdir -p /data/videos /data/uploads /data/uploads/staging/native-imports/manifests /data/uploads/orphaned-imports /data/temp /data/logs /data/config /data/backups /data/proxies /data/models

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
