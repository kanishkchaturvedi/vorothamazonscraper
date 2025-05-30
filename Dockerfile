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

# Install Playwright via pip (required for Docker environments)
RUN pip install --upgrade pip \
    && pip install --no-cache-dir playwright

# Install Playwright dependencies + browser
RUN playwright install --with-deps chromium

# Copy project files
COPY requirements.txt .
COPY amazon_scraper.py .
COPY app.py .

# Install other Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose FastAPI port
EXPOSE 8000

# Run FastAPI app using Uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
