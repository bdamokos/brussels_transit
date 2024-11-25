FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && rm -rf /root/.cache/pip/*

# Create cache directory and set up non-root user
RUN mkdir -p cache \
    && useradd -m appuser \
    && chown -R appuser:appuser /app

# Copy the application files (fixed duplicate copies)
COPY app/ .
COPY cache/ /app/cache/

# Expose the port the app runs on
EXPOSE 5001

USER appuser

# Command to run the application
CMD ["python", "main.py"]