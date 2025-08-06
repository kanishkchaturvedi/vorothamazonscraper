#!/bin/bash

# Install system dependencies (Playwright requires these)
apt-get update && apt-get install -y \
  libatk1.0-0 \
  libatk-bridge2.0-0 \
  libxkbcommon0 \
  libatspi2.0-0 \
  libxcomposite1 \
  libxdamage1 \
  libxfixes3 \
  libxrandr2 \
  libgbm1 \
  libasound2

# Install Playwright browser binaries
python -m playwright install chromium

# Start your app
exec uvicorn app:app --host=0.0.0.0 --port="${PORT}"
