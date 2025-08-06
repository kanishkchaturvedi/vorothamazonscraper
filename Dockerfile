FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Install system dependencies required for Playwright and Python builds
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    python3-dev \
    curl \
    wget \
    gnupg \
    unzip \
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
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser -m appuser

# Create necessary directories and set permissions
RUN mkdir -p /app/logs /app/crawl4ai_db /home/appuser/.crawl4ai /home/appuser/.local /home/appuser/.cache && \
    chown -R appuser:appuser /app && \
    chown -R appuser:appuser /home/appuser && \
    chmod -R 755 /home/appuser

# Install Playwright via pip (required for Docker environments)
RUN pip install --upgrade pip \
    && pip install --no-cache-dir playwright

# Install Playwright dependencies + browser (as root for system-wide install)
RUN playwright install --with-deps

# Copy project files
COPY requirements.txt .
COPY amazon_scraper.py .
COPY app.py .
COPY health_check.py .

# Install other Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

RUN rm -rf /root/.cache /root/.npm /tmp/*


# Ensure all app files are owned by appuser
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# 🛠️ Install browser as non-root (so it's in appuser's cache)
RUN playwright install chromium

# Run health check to verify permissions and paths
RUN python3 health_check.py

# Clean up root and pip cache to reduce image size
RUN rm -rf ~/.cache ~/.npm /tmp/*

# Environment variables documentation (these should be set when running the container)
ENV EVOMI_API_KEY=""
ENV GEMINI_API_KEY=""
ENV SERP_API_KEY=""
ENV PERPLEXITY_API_KEY=""

# Set Crawl4AI database path to a writable location
ENV CRAWL4AI_DB_PATH="/app/crawl4ai_db"
ENV HOME="/home/appuser"
ENV PYTHONPATH="/app"
ENV USER="appuser"

# Expose FastAPI port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run FastAPI app using Uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
