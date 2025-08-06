# ────────────────────────────────
# 🧱 Stage 1: Build with everything
# ────────────────────────────────
FROM python:3.13-slim-bookworm as build

WORKDIR /app

# Install build tools & runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    python3-dev \
    curl \
    wget \
    unzip \
    gnupg \
    fonts-liberation \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxrandr2 \
    libasound2 \
    libgbm1 \
    libgtk-3-0 \
    ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Python dependencies + Playwright + Chromium
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir playwright
RUN playwright install --with-deps chromium

# Copy source files
COPY . .

# Optional: run build-time scripts like health_check.py
RUN python3 health_check.py || echo "Health check skipped"

# ────────────────────────────────
# 🪶 Stage 2: Slim final runtime
# ────────────────────────────────
FROM python:3.13-slim-bookworm

WORKDIR /app

# Copy just what we need from the build stage
COPY --from=build /app /app
COPY --from=build /root/.cache/ms-playwright /root/.cache/ms-playwright

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install ONLY required shared libraries (no build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxrandr2 \
    libasound2 \
    libgbm1 \
    libgtk-3-0 \
    ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Create appuser
RUN groupadd -r appuser && useradd -r -g appuser -m appuser && \
    chown -R appuser:appuser /app

USER appuser

# Install Playwright browser as non-root user (so it's in the right cache location)
RUN playwright install chromium

# Env vars
ENV CRAWL4AI_DB_PATH="/app/crawl4ai_db"
ENV HOME="/home/appuser"
ENV PYTHONPATH="/app"
ENV USER="appuser"
ENV EVOMI_API_KEY=""
ENV GEMINI_API_KEY=""
ENV SERP_API_KEY=""
ENV PERPLEXITY_API_KEY=""

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# Run your app
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
