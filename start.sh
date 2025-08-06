#!/bin/bash

# Install Playwright's browser (without --with-deps)
python -m playwright install chromium

# Start the server
exec uvicorn app:app --host=0.0.0.0 --port=$PORT
